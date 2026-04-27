#!/usr/bin/env python3
"""
Phase 5: Stimuli Export → stimuli.txt (for RTL testbench verification)

Translates preprocessed DVS128 test-set feature vectors into the 32-bit
binary words that the RTL testbench expects, and writes the ground-truth
labels for pass/fail comparison.

Hardware packing format
-----------------------
Each gesture is encoded as NUM_STIMULI_WORD (= NUM_AXON_LAYER_0 // 2) lines.
Each line packs two consecutive axon values into one 32-bit word:

    word[i] = (axon[2i] << 16) | axon[2i+1]

Axon sign convention (hardware MAC):
    axon_col = axon_index % 32
    sign     = axon_col % 2          # odd columns are negated in hardware
    input    = sign ? -val : +val

This script does NOT apply the negation here — that is done inside the
hardware MAC unit.  The raw uint16 values are packed without sign change,
matching how stimuli.txt is consumed by the RTL.

Usage
-----
    # Export 100 samples (default) from preprocessed test set
    python export_stimuli.py

    # Export custom number with explicit paths
    python export_stimuli.py \\
        --data-file data_t4/dvs128_test.npz \\
        --out-dir mem \\
        --num-samples 50

Output (relative to --out-dir)
-------------------------------
    stimuli/stimuli.txt     — N × NUM_STIMULI_WORD 32-bit binary lines
    testbench/tb_correct.txt — N ground-truth 8-bit binary labels
    (prints reminder to set SUM_OF_PICS = N in nvm_parameter.py)
"""

import argparse
import sys
from pathlib import Path

import numpy as np

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture"))
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture" / "utils"))
from snn_hw_utils import load_nvm_parameter

# ---------------------------------------------------------------------------
# Load hardware constants from nvm_parameter.py (single source of truth)
# ---------------------------------------------------------------------------
_nvm = load_nvm_parameter()

NUM_AXON_LAYER_0 = _nvm.NUM_AXON_LAYER_0   # 256 — axon words per gesture feature
NUM_STIMULI_WORD = _nvm.NUM_STIMULI_WORD    # 128 — 32-bit words per gesture (= NUM_AXON // 2)


# ---------------------------------------------------------------------------
# Core export functions
# ---------------------------------------------------------------------------

def export_stimuli(feature_vectors: np.ndarray, filepath: Path) -> None:
    """
    Write the RTL stimuli file.

    Each gesture is converted to NUM_STIMULI_WORD 32-bit binary lines by
    packing pairs of uint16 axon values.

    Args:
        feature_vectors : (N, NUM_AXON_LAYER_0) uint16
        filepath        : output path for stimuli.txt
    """
    n_samples, n_axons = feature_vectors.shape
    if n_axons != NUM_AXON_LAYER_0:
        raise ValueError(
            f"Expected {NUM_AXON_LAYER_0} axons (nvm_parameter.NUM_AXON_LAYER_0), "
            f"got {n_axons}. Re-run dvs128_preprocess.py with the correct encoding."
        )

    with open(filepath, "w") as fh:
        for gesture in feature_vectors:
            for w in range(NUM_STIMULI_WORD):
                # Pack two consecutive 16-bit axon values into one 32-bit word.
                # even axon → upper 16 bits; odd axon → lower 16 bits.
                even_axon = int(gesture[w * 2])     & 0xFFFF
                odd_axon  = int(gesture[w * 2 + 1]) & 0xFFFF
                word = (even_axon << 16) | odd_axon
                fh.write(f"{word:032b}\n")


def export_labels(labels: np.ndarray, filepath: Path) -> None:
    """
    Write ground-truth labels as 8-bit binary integers (one per line).

    Args:
        labels   : (N,) integer class indices
        filepath : output path for tb_correct.txt
    """
    with open(filepath, "w") as fh:
        for label in labels:
            fh.write(f"{int(label):08b}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DVS128 Stimuli Export — Phase 5 (RTL testbench inputs)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-file", type=Path, default=Path("data/dvs128_test.npz"),
        help="Path to preprocessed test-set .npz (default: data/dvs128_test.npz)",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("mem"),
        help="Root output directory (default: mem)",
    )
    parser.add_argument(
        "--num-samples", type=int, default=100,
        help="Number of samples to export for RTL simulation (default: 100)",
    )
    parser.add_argument(
        "--input-scale", type=int, default=256,
        help="Quantise raw uint16 features to [0, INPUT_SCALE] before export "
             "(default: 256 — matches training and prevents 16-bit accumulator "
             "saturation).  Pass 0 to export raw uint16 (legacy).",
    )
    args = parser.parse_args()

    stimuli_dir   = args.out_dir / "stimuli"
    testbench_dir = args.out_dir / "testbench"
    stimuli_dir.mkdir(parents=True, exist_ok=True)
    testbench_dir.mkdir(parents=True, exist_ok=True)

    if not args.data_file.exists():
        sys.exit(f"ERROR: Dataset not found: {args.data_file}\n"
                 f"Run dvs128_preprocess.py first.")

    print(f"Loading data from {args.data_file} ...")
    dataset    = np.load(args.data_file)
    feats_all  = dataset["features"]   # (N, NUM_AXON_LAYER_0) uint16
    labels_all = dataset["labels"]     # (N,) int64
    encoding   = str(dataset.get("encoding", "unknown"))

    n_export       = min(args.num_samples, len(feats_all))
    feats_subset   = feats_all[:n_export]
    labels_subset  = labels_all[:n_export]

    # Apply input scaling (matches dvs128_dataset.py input_scale=256)
    if args.input_scale > 0:
        feats_subset = np.minimum(
            np.round(feats_subset.astype(np.float64) / 32767.0 * args.input_scale),
            args.input_scale,
        ).astype(np.uint16)
        scale_tag = f"[0, {args.input_scale}]"
    else:
        scale_tag = "raw uint16 [0, 32767]"

    print(f"  Encoding    : {encoding}")
    print(f"  Axons       : {feats_all.shape[1]}  (nvm_parameter.NUM_AXON_LAYER_0={NUM_AXON_LAYER_0})")
    print(f"  Stimuli words/gesture : {NUM_STIMULI_WORD}")
    print(f"  Samples     : {len(feats_all)} available → exporting {n_export}")
    print(f"  Input scale : {scale_tag}")

    stim_file  = stimuli_dir  / "stimuli.txt"
    label_file = testbench_dir / "tb_correct.txt"

    print(f"\nExporting {n_export} samples ...")
    export_stimuli(feats_subset, stim_file)
    print(f"  Stimuli written to : {stim_file}")

    export_labels(labels_subset, label_file)
    print(f"  Labels  written to : {label_file}")

    print(f"\nRemember to update verilog/tb/nvm_parameter.py:")
    print(f"  SUM_OF_PICS = {n_export}")
    print(f"\nExpected words per sample : {NUM_STIMULI_WORD}")
    print(f"Expected total lines      : {n_export * NUM_STIMULI_WORD}")


if __name__ == "__main__":
    main()
