#!/usr/bin/env python3
"""
Phase 1: DVS128 Preprocessing -> 256 Axons (16-bit integers)

This script processes the DVS128 gesture dataset into feature vectors 
compatible with the SNN hardware core. It performs event binning, pooling, 
and normalization.

Default Encoding (temporal2):
  - 2 equal-time windows per sample.
  - 8x8 spatial grid with 2 polarities (ON/OFF).
  - Total Axons: 2 * 8 * 8 * 2 = 256.
    axons   0– 63 : window1 ON   (8×8, row-major)
    axons  64–127 : window1 OFF
    axons 128–191 : window2 ON
    axons 192–255 : window2 OFF

Default encoding: temporal2 (2 equal-time windows × 8×8 grid × 2 polarities = 256 axons)
Encoding 2: static           (single window × 7×17 grid × 2 polarities = 238 axons)
Encoding 3: temporal4_merged (4 windows × 8×8 grid × merged polarity = 256 axons)
Encoding 4: spatial_focus      (2 windows × 11×11 grid × merged polarity = 242 axons, padded to 256)

Normalization:
  - Clips raw event counts at the 99th percentile of the training set.
  - Scales values to the [0, 32767] range (uint16) to prevent signed 
    overflow in the hardware accumulator during inference.


Output
------
  data/dvs128_train.npz  — features (N_train, 256) uint16, labels, clip_val, encoding
  data/dvs128_test.npz   — features (N_test,  256) uint16, labels, clip_val, encoding

Usage
-----
  # First run: downloads dataset (~1.5 GB) then preprocesses
  python dvs128_preprocess.py

  # Use legacy 238-axon static encoding
  python dvs128_preprocess.py --encoding static

  # Custom paths
  python dvs128_preprocess.py --data-root /mnt/ssd/dvs --out-dir data

  # Print stats on already-processed files (no reprocessing)
  python dvs128_preprocess.py --stats-only

  # Skip download — data already in place manually
  python dvs128_preprocess.py --no-download

Manual download (if auto-download fails)
-----------------------------------------
  tonic 1.x expects pre-processed .npy files served from figshare.
  If the figshare URL is down, download the tarballs manually:

    Train: https://figshare.com/ndownloader/files/38022171
    Test:  https://figshare.com/ndownloader/files/38020584

  Then place them at:
    data/dvs128/ibmGestureTrain.tar.gz
    data/dvs128/ibmGestureTest.tar.gz

  Extract both:
    tar -xzf data/dvs128/ibmGestureTrain.tar.gz -C data/dvs128/
    tar -xzf data/dvs128/ibmGestureTest.tar.gz  -C data/dvs128/

  Then run with --no-download:
    python dvs128_preprocess.py --no-download
"""

from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Hardware constants
# ---------------------------------------------------------------------------
SENSOR_H   = 128          # DVS128 sensor height
SENSOR_W   = 128          # DVS128 sensor width
MAX_UINT15 = 32767        # 15-bit positive range — avoids signed overflow in hardware MAC

# temporal2 encoding (default): 2 time windows × 8×8 grid × 2 polarities = 256 axons
POOL_H     = 8
POOL_W     = 8
N_WINDOWS  = 2
N_AXONS    = POOL_H * POOL_W * 2 * N_WINDOWS   # 256

# static encoding (legacy): 7×17 grid × 2 polarities = 238 axons
_STATIC_POOL_H = 7
_STATIC_POOL_W = 17
_N_AXONS_STATIC = _STATIC_POOL_H * _STATIC_POOL_W * 2   # 238


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _sum_pool_2d(arr: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """
    Sum-pool a 2-D (H, W) float array to (out_h, out_w).

    Uses proportional bin boundaries (same as PyTorch adaptive_avg_pool2d but
    sums instead of averages).
    """
    H, W = arr.shape
    pooled = np.zeros((out_h, out_w), dtype=np.float64)
    for i in range(out_h):
        h0 = round(i       * H / out_h)
        h1 = round((i + 1) * H / out_h)
        for j in range(out_w):
            w0 = round(j       * W / out_w)
            w1 = round((j + 1) * W / out_w)
            pooled[i, j] = arr[h0:h1, w0:w1].sum()
    return pooled


def events_to_features(events: np.ndarray, encoding: str = "temporal2") -> np.ndarray:
    """
    Convert one structured event array → feature vector.

    Parameters
    ----------
    events   : structured numpy array with fields 't','x','y','p'
    encoding : "temporal2" (default, 256 axons), "static" (legacy, 238 axons),
               "temporal4_merged" (256 axons), or "spatial_focus" (242->256 axons)

    Returns
    -------
    float64 vector of length N_AXONS (256) or _N_AXONS_STATIC (238).
    """
    if encoding == "static":
        return _events_to_features_static(events)
    if encoding == "temporal4_merged":
        return _events_to_features_temporal4_merged(events)
    if encoding == "spatial_focus":
        return _events_to_features_spatial_focus(events)

    # temporal2: split at t_mid, pool each half to POOL_H×POOL_W
    t = events['t']
    t_mid = (t.min() + t.max()) / 2.0
    mask1 = t <= t_mid

    hist1 = np.zeros((2, SENSOR_H, SENSOR_W), dtype=np.float64)
    hist2 = np.zeros((2, SENSOR_H, SENSOR_W), dtype=np.float64)

    ev1 = events[mask1]
    if len(ev1):
        np.add.at(hist1,
                  (ev1['p'].astype(np.intp), ev1['y'].astype(np.intp), ev1['x'].astype(np.intp)),
                  1.0)
    ev2 = events[~mask1]
    if len(ev2):
        np.add.at(hist2,
                  (ev2['p'].astype(np.intp), ev2['y'].astype(np.intp), ev2['x'].astype(np.intp)),
                  1.0)

    on1  = _sum_pool_2d(hist1[1], POOL_H, POOL_W)   # p=1 → ON
    off1 = _sum_pool_2d(hist1[0], POOL_H, POOL_W)   # p=0 → OFF
    on2  = _sum_pool_2d(hist2[1], POOL_H, POOL_W)
    off2 = _sum_pool_2d(hist2[0], POOL_H, POOL_W)

    # layout: [w1_ON, w1_OFF, w2_ON, w2_OFF] each 8×8 = 64 elements
    return np.concatenate([on1.ravel(), off1.ravel(), on2.ravel(), off2.ravel()])  # (256,)



def _events_to_features_temporal4_merged(events: np.ndarray) -> np.ndarray:
    """4 time windows, merged polarity, 8x8 grid -> 256 axons."""
    t = events['t']
    t_start, t_end = t.min(), t.max()
    t_range = max(t_end - t_start, 1)
    
    # 4 equal-time windows
    boundaries = [t_start + t_range * i / 4.0 for i in range(5)]
    windows = []
    
    for i in range(4):
        mask = (t >= boundaries[i]) & (t < boundaries[i+1])
        if i == 3: # include end boundary for last window
            mask = (t >= boundaries[i]) & (t <= boundaries[i+1])
            
        hist = np.zeros((SENSOR_H, SENSOR_W), dtype=np.float64)
        ev = events[mask]
        if len(ev):
            np.add.at(hist, (ev['y'].astype(np.intp), ev['x'].astype(np.intp)), 1.0)
            
        pooled = _sum_pool_2d(hist, 8, 8)
        windows.append(pooled.ravel())
        
    return np.concatenate(windows) # (256,)


def _events_to_features_spatial_focus(events: np.ndarray) -> np.ndarray:
    """2 time windows, merged polarity, 11x11 grid -> 242 axons, padded to 256."""
    t = events['t']
    t_mid = (t.min() + t.max()) / 2.0
    
    windows = []
    for mask in [t <= t_mid, t > t_mid]:
        hist = np.zeros((SENSOR_H, SENSOR_W), dtype=np.float64)
        ev = events[mask]
        if len(ev):
            np.add.at(hist, (ev['y'].astype(np.intp), ev['x'].astype(np.intp)), 1.0)
            
        pooled = _sum_pool_2d(hist, 11, 11)
        windows.append(pooled.ravel())
        
    vec = np.concatenate(windows) # (242,)
    # Pad with 14 zeros to maintain 256-axon hardware compatibility
    return np.pad(vec, (0, 14), mode='constant')


def _events_to_features_static(events: np.ndarray) -> np.ndarray:
    """Legacy static encoding → (238,) float64."""
    hist = np.zeros((2, SENSOR_H, SENSOR_W), dtype=np.float64)
    np.add.at(
        hist,
        (events['p'].astype(np.intp),
         events['y'].astype(np.intp),
         events['x'].astype(np.intp)),
        1.0,
    )
    on_pooled  = _sum_pool_2d(hist[1], _STATIC_POOL_H, _STATIC_POOL_W)
    off_pooled = _sum_pool_2d(hist[0], _STATIC_POOL_H, _STATIC_POOL_W)
    return np.concatenate([on_pooled.ravel(), off_pooled.ravel()])   # (238,)


def _normalise(
    features_raw: np.ndarray,
    clip_val: Optional[float] = None,
) -> Tuple[np.ndarray, float]:
    """
    Global clip-and-scale normalisation.

    Parameters
    ----------
    features_raw : (N, W) float64  — raw event counts
    clip_val     : if None, computed as 99th percentile of features_raw.

    Returns
    -------
    features_uint16 : (N, W) uint16  — values in [0, MAX_UINT15]
    clip_val        : scalar used for clipping
    """
    if clip_val is None:
        clip_val = float(np.percentile(features_raw, 99))

    clipped = np.clip(features_raw, 0.0, clip_val)
    scaled  = np.round(clipped / clip_val * MAX_UINT15).astype(np.uint16)
    return scaled, clip_val


# ---------------------------------------------------------------------------
# Download helpers (robust fallback for tonic's urllib downloader)
# ---------------------------------------------------------------------------

_URLS = {
    "train": "https://figshare.com/ndownloader/files/38022171",
    "test":  "https://figshare.com/ndownloader/files/38020584",
}
_FOLDERS = {
    "train": "ibmGestureTrain",
    "test":  "ibmGestureTest",
}

_TONIC_SUBDIR = "DVSGesture"


def _tonic_root(root: Path) -> Path:
    return root / _TONIC_SUBDIR


def _npy_files_present(root: Path, split: str) -> bool:
    folder = _tonic_root(root) / _FOLDERS[split]
    if not folder.is_dir():
        return False
    return sum(1 for _ in folder.glob("**/*.npy")) >= 100


def _ensure_sentinel(root: Path, split: str) -> None:
    sentinel = _tonic_root(root) / f"{_FOLDERS[split]}.tar.gz"
    if not sentinel.exists():
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()


def _download_split(root: Path, split: str) -> None:
    try:
        import requests
    except ImportError:
        sys.exit(
            "ERROR: 'requests' is not installed — needed for fallback download.\n"
            "Install it with:  pip install requests\n"
            "Or download manually (see script docstring).\n"
        )

    folder      = _FOLDERS[split]
    url         = _URLS[split]
    tonic_data  = _tonic_root(root)
    tarball     = tonic_data / f"{folder}.tar.gz"

    tonic_data.mkdir(parents=True, exist_ok=True)

    print(f"  Downloading {tarball.name} via requests ...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; dvs128_preprocess/1.0)"}
    try:
        with requests.get(url, stream=True, allow_redirects=True,
                          headers=headers, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(tarball, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = 100.0 * downloaded / total
                        mb  = downloaded / 1e6
                        print(f"\r  {mb:6.1f} / {total/1e6:.1f} MB  ({pct:.1f}%)",
                              end="", flush=True)
        print()
    except requests.RequestException as exc:
        sys.exit(
            f"\nERROR: Download failed: {exc}\n\n"
            "Please download manually:\n"
            f"  Train: {_URLS['train']}\n"
            f"  Test:  {_URLS['test']}\n\n"
            f"Place both tarballs in:  {tonic_data}/\n"
            "Extract:\n"
            f"  tar -xzf {tonic_data}/ibmGestureTrain.tar.gz -C {tonic_data}/\n"
            f"  tar -xzf {tonic_data}/ibmGestureTest.tar.gz  -C {tonic_data}/\n\n"
            "Then re-run with:  python dvs128_preprocess.py --no-download\n"
        )

    print(f"  Extracting {tarball.name} ...")
    with tarfile.open(tarball) as tf:
        tf.extractall(tonic_data)
    print(f"  Extracted → {tonic_data / folder}/")


def _ensure_data(root: Path, split: str, no_download: bool) -> None:
    if _npy_files_present(root, split):
        _ensure_sentinel(root, split)
        return

    if no_download:
        folder = _tonic_root(root) / _FOLDERS[split]
        sys.exit(
            f"ERROR: --no-download set but {folder} has no .npy files.\n\n"
            "Extract the tarballs to tonic's expected location:\n"
            f"  mkdir -p {_tonic_root(root)}\n"
            f"  tar -xzf ibmGestureTrain.tar.gz -C {_tonic_root(root)}/\n"
            f"  tar -xzf ibmGestureTest.tar.gz  -C {_tonic_root(root)}/\n\n"
            "Then re-run with:  python dvs128_preprocess.py --no-download\n"
        )

    try:
        import tonic
        print(f"  Trying tonic built-in downloader ...")
        tonic.datasets.DVSGesture(save_to=str(root), train=(split == "train"))
        if _npy_files_present(root, split):
            _ensure_sentinel(root, split)
            return
    except Exception:
        pass

    print(f"  Tonic downloader failed — using requests fallback ...")
    _download_split(root, split)


# ---------------------------------------------------------------------------
# Split-level processing
# ---------------------------------------------------------------------------

def preprocess_split(
    root: Path,
    train: bool,
    clip_val: Optional[float] = None,
    no_download: bool = False,
    encoding: str = "temporal2",
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Process one DVSGesture split.

    Parameters
    ----------
    root        : directory where tonic downloads / finds the dataset
    train       : True → training split, False → test split
    clip_val    : None → computed from training split; pass training value for test
    no_download : skip all download attempts
    encoding    : "temporal2" (256 axons, default) or "static" (238 axons, legacy)

    Returns
    -------
    features : (N, n_axons) uint16
    labels   : (N,) int64
    clip_val : scalar used for normalisation
    """
    try:
        import tonic
    except ImportError:
        sys.exit(
            "ERROR: 'tonic' is not installed.\n"
            "Install it with:  pip install tonic\n"
        )

    n_axons = 256 if encoding != "static" else _N_AXONS_STATIC
    split_name = "train" if train else "test"
    print(f"\n[{split_name}] Loading DVSGesture from '{root}' (encoding={encoding}) ...")

    _ensure_data(root, split_name, no_download)

    dataset = tonic.datasets.DVSGesture(save_to=str(root), train=train)
    n = len(dataset)
    print(f"[{split_name}] {n} samples found.")

    features_raw = np.empty((n, n_axons), dtype=np.float64)
    labels       = np.empty(n, dtype=np.int64)

    for idx, (events, label) in enumerate(dataset):
        if idx % 100 == 0:
            print(f"  [{split_name}] {idx:4d}/{n} ...", flush=True)
        features_raw[idx] = events_to_features(events, encoding=encoding)
        labels[idx]       = int(label)

    print(f"  [{split_name}] done.  Raw feature range: "
          f"[{features_raw.min():.0f}, {features_raw.max():.0f}]")

    features, clip_val = _normalise(features_raw, clip_val)

    if train:
        print(f"  [{split_name}] 99th-percentile clip_val = {clip_val:.1f}")
    else:
        print(f"  [{split_name}] using training clip_val  = {clip_val:.1f}")

    return features, labels, clip_val


# ---------------------------------------------------------------------------
# Statistics / verification
# ---------------------------------------------------------------------------

def print_stats(features: np.ndarray, labels: np.ndarray, split_name: str,
                encoding: str = "temporal2") -> None:
    """Print verification stats; window-balance check for temporal2."""
    n_axons = features.shape[1]

    print(f"\n{'='*55}")
    print(f" {split_name.upper()} SPLIT STATS  (encoding={encoding})")
    print(f"{'='*55}")
    print(f"  Shape  : {features.shape}    (expected (N, {n_axons}))")
    print(f"  dtype  : {features.dtype}    (expected uint16)")
    print(f"  Range  : [{int(features.min())}, {int(features.max())}]"
          f"   (expected [0, 32767])")

    if n_axons == 256:
        if encoding == "temporal2":
            w1_mean = features[:, :128].mean()
            w2_mean = features[:, 128:].mean()
            denom   = max(w1_mean, w2_mean)
            balance = (min(w1_mean, w2_mean) / denom) if denom > 0 else 0.0
            print(f"  W1 mean: {w1_mean:.1f}   W2 mean: {w2_mean:.1f}")
            print(f"  W1/W2 balance: {balance:.3f}   (>0.4 expected; low → timestamp bug)")
            on_mean  = (features[:, :64].mean() + features[:, 128:192].mean()) / 2
            off_mean = (features[:, 64:128].mean() + features[:, 192:256].mean()) / 2
            denom2   = max(on_mean, off_mean)
            bal2     = (min(on_mean, off_mean) / denom2) if denom2 > 0 else 0.0
            print(f"  ON mean: {on_mean:.1f}   OFF mean: {off_mean:.1f}")
            print(f"  ON/OFF balance: {bal2:.3f}")
        elif encoding == "temporal4_merged":
            means = [features[:, i*64:(i+1)*64].mean() for i in range(4)]
            print(f"  Window means: {[round(m, 1) for m in means]}")
            balance = min(means) / max(means) if max(means) > 0 else 0.0
            print(f"  Temporal balance: {balance:.3f}")
        elif encoding == "spatial_focus":
            w1_mean = features[:, :121].mean()
            w2_mean = features[:, 121:242].mean()
            pad_mean = features[:, 242:].mean()
            print(f"  W1 mean: {w1_mean:.1f}   W2 mean: {w2_mean:.1f}  Pad mean: {pad_mean:.2f}")
    else:
        # static encoding: original ON/OFF balance
        half     = n_axons // 2
        on_mean  = features[:, :half].mean()
        off_mean = features[:, half:].mean()
        denom    = max(on_mean, off_mean)
        balance  = (min(on_mean, off_mean) / denom) if denom > 0 else 0.0
        print(f"  ON  mean : {on_mean:.1f}")
        print(f"  OFF mean : {off_mean:.1f}")
        print(f"  ON/OFF balance : {balance:.3f}   (1.0 = perfect; >0.5 expected)")

    print(f"  Classes  : {sorted(np.unique(labels).tolist())}")
    print()
    for cls in sorted(np.unique(labels).tolist()):
        count = int((labels == cls).sum())
        print(f"    class {cls:2d} : {count:4d} samples")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DVS128 → uint16 feature vectors (Phase 1 preprocessing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-root", type=Path, default=Path("data/dvs128"),
        help="Directory for tonic to download/find DVSGesture (default: data/dvs128)",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("data"),
        help="Output directory for .npz files (default: data)",
    )
    parser.add_argument(
        "--encoding", choices=["temporal2", "static", "temporal4_merged", "spatial_focus"], default="temporal2",
        help="temporal2 (default): 2-window 8×8 = 256 axons; "
             "static (legacy): single-window 7×17 = 238 axons; "
             "temporal4_merged: 4-window 8×8 (no polarity) = 256 axons; "
             "spatial_focus: 2-window 11×11 (no polarity) = 242 (padded to 256) axons",
    )
    parser.add_argument(
        "--stats-only", action="store_true",
        help="Print stats on already-processed .npz files (no reprocessing)",
    )
    parser.add_argument(
        "--no-download", action="store_true",
        help="Skip all download attempts. Fails if .npy files are not already extracted.",
    )
    args = parser.parse_args()

    if args.stats_only:
        for split in ("train", "test"):
            path = args.out_dir / f"dvs128_{split}.npz"
            if not path.exists():
                print(f"ERROR: {path} not found. Run without --stats-only first.")
                sys.exit(1)
            data = np.load(path)
            enc  = str(data.get("encoding", "unknown"))
            print_stats(data["features"], data["labels"], split, encoding=enc)
            print(f"  clip_val : {float(data['clip_val']):.1f}")
            print(f"  encoding : {enc}")
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)

    train_feats, train_labels, clip_val = preprocess_split(
        args.data_root, train=True, clip_val=None,
        no_download=args.no_download, encoding=args.encoding,
    )
    print_stats(train_feats, train_labels, "train", encoding=args.encoding)

    train_path = args.out_dir / "dvs128_train.npz"
    np.savez(train_path, features=train_feats, labels=train_labels,
             clip_val=clip_val, encoding=args.encoding)
    print(f"Saved: {train_path}")

    test_feats, test_labels, _ = preprocess_split(
        args.data_root, train=False, clip_val=clip_val,
        no_download=args.no_download, encoding=args.encoding,
    )
    print_stats(test_feats, test_labels, "test", encoding=args.encoding)

    test_path = args.out_dir / "dvs128_test.npz"
    np.savez(test_path, features=test_feats, labels=test_labels,
             clip_val=clip_val, encoding=args.encoding)
    print(f"Saved: {test_path}")

    n_axons = 256 if args.encoding != "static" else 238
    print(f"\nPhase 1 complete.")
    print(f"  encoding : {args.encoding}  ({n_axons} axons)")
    print(f"  clip_val : {clip_val:.1f}  (stored in both .npz files)")
    print(f"  Next     : python train_dvs128.py --data-dir data --epochs 80")


if __name__ == "__main__":
    main()
