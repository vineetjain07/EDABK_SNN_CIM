#!/usr/bin/env python3
"""
PyTorch Dataset wrapper for preprocessed DVS128 feature vectors.

Wraps the .npz files produced by dvs128_preprocess.py into a Dataset
that the training loop can pass to DataLoader.

Usage:
    from training.dvs128_dataset import DVS128Dataset, make_loaders
    train_loader, test_loader, clip_val = make_loaders()
    train_loader_aug, _, _ = make_loaders(augment=True)
    # Hardware-matched scale (default):
    train_loader_hw, _, _ = make_loaders(input_scale=256)
    # Raw uint16 (legacy):
    train_loader_raw, _, _ = make_loaders(input_scale=None)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture"))
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture" / "utils"))
from snn_hw_utils import load_nvm_parameter

_nvm = load_nvm_parameter()


class DVS128Dataset(Dataset):
    """
    Minimal Dataset wrapping the (N, NUM_AXON_LAYER_0) uint16 feature arrays.

    Parameters
    ----------
    features    : (N, NUM_AXON_LAYER_0) uint16 — values in [0, 32767]
    labels      : (N,) int64 — class indices 0–11
    augment     : if True, apply training augmentations in __getitem__:
                  - spatial jitter ±1 bin (256-axon temporal2 only)
                  - Gaussian noise σ=0.05, clamped [0, input_scale]
                  - time-window dropout p=0.1 (256-axon temporal2 only)
    input_scale : int or None.
                  - int  → quantise to [0, input_scale] matching hardware
                           accumulator range.  256 prevents 16-bit saturation
                           (64 connections × 256 = 16384 < POS_SAT 32767).
                  - None → raw uint16 as float32 (legacy, causes saturation).
    """

    def __init__(self, features: np.ndarray, labels: np.ndarray,
                 augment: bool = False, input_scale: int | None = 256):
        expected = _nvm.NUM_AXON_LAYER_0
        assert features.shape[1] == expected, (
            f"Expected {expected} axons (nvm_parameter.NUM_AXON_LAYER_0), "
            f"got {features.shape[1]}"
        )
        assert len(features) == len(labels)

        self.input_scale = input_scale
        if input_scale is not None:
            scaled = np.minimum(
                np.round(features.astype(np.float64) / 32767.0 * input_scale),
                input_scale,
            ).astype(np.float32)
            self.features = torch.from_numpy(scaled)
        else:
            self.features = torch.from_numpy(features.astype(np.float32))
        self.labels  = torch.from_numpy(labels.astype(np.int64))
        self.augment = augment

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int):
        x = self.features[idx]
        y = self.labels[idx]

        if self.augment:
            x = x.clone()
            n = x.shape[0]
            clamp_max = float(self.input_scale) if self.input_scale is not None else 32767.0

            if n == 256:
                # Spatial jitter ±1 bin: shared roll across all 4 8×8 blocks
                # so window1/window2 and ON/OFF structure is preserved.
                dy = int(torch.randint(-1, 2, ()))
                dx = int(torch.randint(-1, 2, ()))
                x = torch.roll(x.view(4, 8, 8), shifts=(dy, dx), dims=(1, 2)).reshape(n)

            # Gaussian noise — always applied; small magnitude keeps values valid
            noise_std = 0.05 * clamp_max
            x = (x + noise_std * torch.randn_like(x)).clamp(0.0, clamp_max)

            if n == 256 and torch.rand(()).item() < 0.1:
                # Zero out one full time-window: teaches survival under partial loss
                if torch.rand(()).item() < 0.5:
                    x = x.clone(); x[:128] = 0.0
                else:
                    x = x.clone(); x[128:] = 0.0

        return x, y


def make_loaders(
    data_dir:    Path | str  = "data",
    batch_size:  int         = 32,
    num_workers: int         = 0,
    augment:     bool        = False,
    input_scale: int | None  = 256,
) -> tuple[DataLoader, DataLoader, float]:
    """
    Load both splits from .npz files and return DataLoaders.

    Args:
        data_dir    : directory containing dvs128_train.npz / dvs128_test.npz
        batch_size  : mini-batch size for training
        num_workers : DataLoader workers (0 = main process, safe default)
        augment     : if True, apply augmentation on the training split only
        input_scale : passed to DVS128Dataset; 256 (default) matches hardware
                      accumulator range.  None → raw uint16.

    Returns:
        train_loader : shuffled DataLoader (augmented if augment=True)
        test_loader  : unshuffled DataLoader (never augmented)
        clip_val     : raw clip_val from npz (informational; not used for scaling)
    """
    data_dir  = Path(data_dir)
    train_npz = np.load(data_dir / "dvs128_train.npz")
    test_npz  = np.load(data_dir / "dvs128_test.npz")

    train_ds = DVS128Dataset(train_npz["features"], train_npz["labels"],
                             augment=augment, input_scale=input_scale)
    test_ds  = DVS128Dataset(test_npz["features"],  test_npz["labels"],
                             augment=False,  input_scale=input_scale)
    clip_val = float(train_npz["clip_val"])

    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=True,
        num_workers=num_workers, pin_memory=torch.cuda.is_available(),
    )
    test_loader = DataLoader(
        test_ds, batch_size=batch_size, shuffle=False,
        num_workers=num_workers, pin_memory=torch.cuda.is_available(),
    )

    scale_tag = f"scale={input_scale}" if input_scale is not None else "raw uint16"
    aug_tag   = " [augmented]" if augment else ""
    print(f"Train: {len(train_ds)} samples → {len(train_loader)} batches "
          f"(bs={batch_size}, {scale_tag}){aug_tag}")
    print(f"Test : {len(test_ds)} samples  → {len(test_loader)} batches ({scale_tag})")
    print(f"clip_val: {clip_val:.1f}")

    return train_loader, test_loader, clip_val


if __name__ == "__main__":
    train_loader, test_loader, clip_val = make_loaders()
    x, y = next(iter(train_loader))
    print(f"\nBatch x: {x.shape}  dtype={x.dtype}  range=[{x.min():.3f}, {x.max():.3f}]")
    print(f"Batch y: {y.shape}  classes={y.unique().tolist()}")
