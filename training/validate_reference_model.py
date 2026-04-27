#!/usr/bin/env python3
"""
Phase 6: Validation via Hardware Reference Model

Loads a trained PyTorch checkpoint, exports weights + stimuli to a temp directory,
then runs inference through the Python reference model (snn_reference_model.py)
to measure bit-accurate hardware accuracy without RTL simulation.

"Bit-accurate" means the Python reference model applies the exact same fixed-point
arithmetic as the RTL: integer accumulation, arithmetic-right-shift leak, integer
threshold comparison, and interleaved i%12 voting. It is not a floating-point
approximation. If reference-model accuracy matches software (PyTorch) accuracy,
the trained weights are compatible with the hardware data path. If it diverges,
there is a HW/SW contract violation (wrong voting scheme, scale mismatch, etc.)
that will also appear in RTL simulation — catch it here first before running the
slower cocotb tests.

Usage
-----
    # From project root
    python validate_reference_model.py \\
        --checkpoint checkpoints/best.pt \\
        --data-file  data/dvs128_test.npz \\
        --num-samples 200
"""

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch

# ── Allow imports from training/ when run from project root ──────────────────
sys.path.insert(0, str(Path(__file__).parent))
from snn_model import build_model, HARDWARE_LAYERS
from export_weights import export_all_weights
from export_stimuli import export_stimuli, export_labels

# ── Reference model — functional API ─────────────────────────────────────────
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture"))
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture" / "utils"))
import snn_reference_model as _ref_mod
from snn_reference_model import (
    load_connection_files,
    load_stimuli_file,
    run_full_network,
    classify,
    NUM_AXON,
    NUM_NEURON,
    _ACTIVE_PER_L2_CORE,
)
from snn_hw_utils import interleaved_logits




# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Load checkpoint + test data, run Python reference model, print HW/SW accuracy."""
    parser = argparse.ArgumentParser(
        description="DVS128 Hardware Reference Accuracy — Phase 6",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--checkpoint", type=Path, required=True,
        help="Trained model .pt checkpoint (e.g. checkpoints/best.pt)",
    )
    parser.add_argument(
        "--data-file", type=Path, default=Path("data/dvs128_test.npz"),
        help="Preprocessed test-set .npz (default: data/dvs128_test.npz)",
    )
    parser.add_argument(
        "--num-samples", type=int, default=200,
        help="Number of test samples to evaluate (default: 200)",
    )
    # ── Hardware-faithfulness knobs ──────────────────────────────────────────
    parser.add_argument(
        "--stimuli-scale", type=int, default=256,
        help="Scale raw uint16 features to [0, stimuli-scale] before hardware "
             "inference (default: 256).  Prevents 16-bit accumulator saturation.",
    )
    parser.add_argument(
        "--hw-threshold", type=int, default=None,
        help="Override NEURON_THRESHOLD for this run.  "
             "If omitted, uses round(mean_trained_th * stimuli_scale / 32767), "
             "with a floor of 1.",
    )
    args = parser.parse_args()

    if not args.checkpoint.exists():
        sys.exit(f"ERROR: checkpoint not found: {args.checkpoint}")
    if not args.data_file.exists():
        sys.exit(f"ERROR: data file not found: {args.data_file}")

    # ── Load model ────────────────────────────────────────────────────────────
    print(f"Loading checkpoint: {args.checkpoint}")
    ckpt  = torch.load(args.checkpoint, map_location="cpu")
    model = build_model(layers=HARDWARE_LAYERS).to("cpu")
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    # ── Decide hardware threshold ─────────────────────────────────────────────
    # Hardware constraint: one global integer threshold shared by all cores.
    # The trained model learns per-core thresholds; we round their mean.
    all_cores   = [c for cores in model._layers for c in cores]
    mean_th     = sum(c.lif.threshold.item() for c in all_cores) / len(all_cores)
    per_layer   = {
        f"L{i}": [round(c.lif.threshold.item(), 3) for c in cores]
        for i, cores in enumerate(model._layers)
    }
    _auto_th     = max(1, round(mean_th))
    hw_threshold = args.hw_threshold if args.hw_threshold is not None else _auto_th

    print(f"\nTrained threshold summary:")
    for lname, ths in per_layer.items():
        print(f"  {lname}  min={min(ths):.3f}  max={max(ths):.3f}  mean={sum(ths)/len(ths):.3f}")
    print(f"  All-core mean: {mean_th:.3f}  → hw_threshold = {hw_threshold}")
    if max(c.lif.threshold.item() for c in all_cores) - \
       min(c.lif.threshold.item() for c in all_cores) > 0.5:
        print("  WARNING: large threshold spread (>0.5) — a single hardware threshold "
              "will under-fire some cores and over-fire others.  "
              "Consider retraining with learn_threshold=False or constrained spread.")

    # ── Load dataset ──────────────────────────────────────────────────────────
    print(f"\nLoading data: {args.data_file}")
    dataset    = np.load(args.data_file)
    n_export   = min(args.num_samples, len(dataset["features"]))
    feats_raw  = dataset["features"][:n_export]       # uint16  [0, 32767]
    labels     = dataset["labels"][:n_export]
    print(f"  Samples: {len(dataset['features'])} available → evaluating {n_export}")

    # ── Prepare L0 stimuli ──────────────────────────────────────────────────
    # Scale inputs to [0, stimuli_scale] to avoid 16-bit accumulator saturation.
    # Raw uint16 [0,32767] with 64 connections saturates after ~9 injections.
    feats_hw = np.minimum(
        np.round(feats_raw.astype(np.float64) / 32767.0 * args.stimuli_scale),
        args.stimuli_scale,
    ).astype(np.uint16)
    print(f"  stimuli_scale={args.stimuli_scale}  "
          f"input range [0, {int(feats_hw.max())}]  NEURON_THRESHOLD = {hw_threshold}")

    # Temporarily patch the reference model's threshold constant so picture_done
    # uses the correct value for this validation run.
    original_threshold = _ref_mod.NEURON_THRESHOLD
    _ref_mod.NEURON_THRESHOLD = hw_threshold

    try:
        # ── Export to temp dir and run reference model ─────────────────────────
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path  = Path(tmp)
            conn_dir  = tmp_path / "connection"
            conn_dir.mkdir()
            stim_file = tmp_path / "stimuli.txt"

            print("\nExporting weights to temp directory ...")
            export_all_weights(model, conn_dir)

            print("Exporting stimuli ...")
            export_stimuli(feats_hw, stim_file)

            print(f"Running reference model on {n_export} gestures ...")
            conn_matrices = load_connection_files(conn_dir)
            stimuli_words = load_stimuli_file(stim_file)

            spike_l2 = run_full_network(conn_matrices, stimuli_words, num_pics=n_export)

        preds_interleaved = classify(spike_l2)        # hardware-native i%12 vote

    finally:
        _ref_mod.NEURON_THRESHOLD = original_threshold

    # ── Software accuracy (same interleaved voting for fair comparison) ───────
    from dvs128_dataset import DVS128Dataset
    from snn_model import N_CLASSES
    _ds      = DVS128Dataset(feats_raw, labels, augment=False,
                             input_scale=args.stimuli_scale)
    with torch.no_grad():
        _out = model(_ds.features)
    sw_preds = interleaved_logits(_out, N_CLASSES).argmax(dim=1).tolist()
    n_sw     = sum(p == int(l) for p, l in zip(sw_preds, labels))

    # ── Bit-level comparison (L2 spikes) ─────────────────────────────────────
    hw_spikes = np.array(spike_l2)
    sw_spikes = _out.cpu().numpy()
    bit_diff  = np.abs(hw_spikes - sw_spikes).sum()

    # ── Accuracy report ───────────────────────────────────────────────────────
    avg_l2 = sum(sum(r) for r in spike_l2) / n_export
    n_int  = sum(p == int(l) for p, l in zip(preds_interleaved, labels))

    print(f"\n{'='*60}")
    print(f" Hardware Reference Accuracy  ({n_export} samples)")
    print(f"{'='*60}")
    print(f"  Avg L2 active spikes   : {avg_l2:.1f} / {len(spike_l2[0])}")
    print(f"  SW (interleaved vote)  : {n_sw}/{n_export} = {100.*n_sw/n_export:.2f}%")
    print(f"  HW (interleaved vote)  : {n_int}/{n_export} = {100.*n_int/n_export:.2f}%  ← primary")
    print(f"  HW/SW gap (interleaved): {100.*(n_sw-n_int)/n_export:+.2f} pp")
    print(f"  L2 Bit-level Match     : {100.0 * (1.0 - bit_diff / (n_export * 240)):.4f}% "
          f"({int(bit_diff)} bits different)")
    print(f"{'='*60}")
    print(f"\nAll three (SW training, HW reference, RTL) use interleaved i%12 voting.")


if __name__ == "__main__":
    main()
