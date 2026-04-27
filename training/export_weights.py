#!/usr/bin/env python3
"""
Phase 4: Weight Export -> connection_XXX.txt

Exports trained binary weights from an SNNNetwork checkpoint to the formatted
files expected by the RTL testbench.  All dimensions and file numbering are
derived automatically from the model's LayerConfig topology and nvm_parameter.py
— no values are hardcoded.

Hardware file format
--------------------
Each connection file represents one 64-neuron crossbar tile (one LIFCore).
Format: NUM_AXON (256) lines × NUM_NEURON (64) chars.

    Line N  → bit connectivity for axon N.
    Char 0  → neuron 63 (hardware-expected MSB-first order).
    Char 63 → neuron 0.

Input padding: Each crossbar is physically 256 axons × 64 neurons, regardless
of how many axons a layer actually connects.  Rows beyond the layer's real
n_in are padded with zeros (disconnected axons).

Output trimming: The last layer (voting layer) uses only NUM_VOTES active
neurons out of NUM_NEURON × n_cores.  The unused columns are zeroed to
prevent phantom spikes in the hardware simulation.

File numbering convention
-------------------------
    L0 cores  : connection_000 … connection_{L0_cores-1}
    L1 cores  : connection_{L0_cores} … connection_{L0_cores+L1_cores-1}
    ...
    Last layer: connection_{offset}_part{1..n_cores}

Usage
-----
    # Export weights from best checkpoint (run from project root)
    python training/export_weights.py --checkpoint training/checkpoints/best.pt

    # Custom output directory
    python training/export_weights.py \\
        --checkpoint training/checkpoints/best.pt \\
        --out-dir    mem/connection
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

# Allow imports from training/ and verilog/tb/ when run from project root
sys.path.insert(0, str(Path(__file__).parent))
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture"))
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture" / "utils"))
from snn_model import build_model, get_binary_weights, get_hardware_params, HARDWARE_LAYERS
from snn_hw_utils import load_nvm_parameter

# ---------------------------------------------------------------------------
# Load hardware constants from nvm_parameter.py (single source of truth)
# ---------------------------------------------------------------------------
_nvm = load_nvm_parameter()

NUM_AXON   = _nvm.NUM_AXON    # 256 — physical rows per crossbar tile
NUM_NEURON = _nvm.NUM_NEURON  # 64  — physical columns per crossbar tile
NUM_VOTES  = _nvm.NUM_VOTES   # active neurons in last layer (= classes × votes_per_class)


# ---------------------------------------------------------------------------
# Core export function
# ---------------------------------------------------------------------------

def export_connection_file(W: np.ndarray, filepath: Path) -> None:
    """
    Write one crossbar connection file.

    W is logically (n_in, n_out) but is physically padded/trimmed to
    (NUM_AXON=256, NUM_NEURON=64) before writing.

    Args:
        W        : (n_in, n_out) uint8 {0,1} — binarised weight slice
        filepath : output path (e.g. connection_000.txt)
    """
    # Allocate full physical tile (256 × 64), zeros = disconnected
    tile = np.zeros((NUM_AXON, NUM_NEURON), dtype=np.uint8)
    rows = min(W.shape[0], NUM_AXON)
    cols = min(W.shape[1], NUM_NEURON)
    tile[:rows, :cols] = W[:rows, :cols]

    with open(filepath, "w") as fh:
        for axon_row in range(NUM_AXON):
            # Hardware expects MSB-first: column 63 first, then 62 … 0
            row_bits = tile[axon_row, :][::-1]
            fh.write("".join(map(str, row_bits)) + "\n")


# ---------------------------------------------------------------------------
# Public API: export all layers from a trained model
# ---------------------------------------------------------------------------

def export_all_weights(model, out_dir: Path) -> None:
    """
    Export all binary weights from a trained SNNNetwork to connection_XXX.txt.

    Replaces the private _export_weights_to_dir() that was duplicated in
    validate_reference_model.py.  All callers should use this function so
    the padding/trimming/numbering logic stays in one place.

    Layout: connection_000.txt ... connection_{total_cores-1:03d}.txt
    Last layer output columns beyond active_per_core are zeroed.

    Args:
        model   : trained SNNNetwork instance
        out_dir : directory to write connection_XXX.txt files into
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bins       = get_binary_weights(model)
    n_layers   = len(model.layer_configs)
    file_index = 0

    for layer_idx in range(n_layers):
        layer_key       = f"l{layer_idx}"
        cores_list      = bins[layer_key]
        is_last         = (layer_idx == n_layers - 1)
        n_cores         = len(cores_list)
        active_per_core = (NUM_VOTES // n_cores) if is_last else NUM_NEURON

        for W_core in cores_list:
            if is_last and active_per_core < NUM_NEURON:
                W_export = W_core.copy()
                W_export[:, active_per_core:] = 0
            else:
                W_export = W_core
            export_connection_file(W_export, out_dir / f"connection_{file_index:03d}.txt")
            file_index += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DVS128 Weight Export — Phase 4 (RTL connection files)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--checkpoint", type=Path, required=True,
        help="Trained model .pt checkpoint (e.g. training/checkpoints/best.pt)",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("mem/connection"),
        help="Directory to save connection_XXX.txt files "
             "(default: mem/connection)",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if not args.checkpoint.exists():
        sys.exit(f"ERROR: Checkpoint not found: {args.checkpoint}")

    # ── Load model ────────────────────────────────────────────────────────────
    print(f"Loading checkpoint: {args.checkpoint}")
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    model = build_model(layers=HARDWARE_LAYERS).to("cpu")
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    # ── Extract binary weights ─────────────────────────────────────────────────
    # get_binary_weights returns { 'l0': [W_core0, ...], 'l1': [...], ... }
    # Each W_coreK has shape (n_in, NEURONS_PER_CORE) uint8.
    bins = get_binary_weights(model)

    n_layers   = len(model.layer_configs)
    file_index = 0   # global running file counter across all layers

    print(f"\nExporting {n_layers}-layer model to {args.out_dir} ...")
    print(f"  NUM_AXON   = {NUM_AXON}   (physical rows per tile)")
    print(f"  NUM_NEURON = {NUM_NEURON} (physical cols per tile)")
    print(f"  NUM_VOTES  = {NUM_VOTES}  (active output neurons)")

    for layer_idx in range(n_layers):
        layer_key  = f"l{layer_idx}"
        cfg        = model.layer_configs[layer_idx]
        cores_list = bins[layer_key]           # list of (n_in, 64) uint8 arrays
        is_last    = (layer_idx == n_layers - 1)
        label      = cfg.label or f"L{layer_idx}"
        n_cores    = len(cores_list)

        # Active neurons per core in the last (voting) layer
        active_per_core = (NUM_VOTES // n_cores) if is_last else NUM_NEURON

        for core_idx, W_core in enumerate(cores_list):
            # Trim unused output columns for the last layer
            if is_last and active_per_core < NUM_NEURON:
                W_export = W_core.copy()
                W_export[:, active_per_core:] = 0
            else:
                W_export = W_core

            filename = args.out_dir / f"connection_{file_index:03d}.txt"

            export_connection_file(W_export, filename)
            print(f"  {label} core {core_idx}  "
                  f"(n_in={W_core.shape[0]}, n_out={active_per_core}) "
                  f"→ {filename.name}")

            file_index += 1

    # ── Hardware parameters ────────────────────────────────────────────────────
    hw = get_hardware_params(model)
    print(f"\nHardware export parameters (write back to nvm_parameter.py):")
    print(f"  NEURON_THRESHOLD  = {int(round(hw['threshold']))}  "
          f"(trained: {hw['threshold']:.4f})")
    print(f"  NEURON_LEAK_SHIFT = {hw['leak_shift']}  "
          f"(trained beta: {hw['beta']:.5f})")
    if hw["threshold_spread"] > 0.01 or hw["beta_spread"] > 0.001:
        print(f"\n  WARNING: Cross-core parameter spread detected.")
        print(f"    threshold spread: {hw['threshold_spread']:.4f}")
        print(f"    beta      spread: {hw['beta_spread']:.5f}")
        print("    This may cause a slight HW/SW accuracy gap. Consider using")
        print("    --multi-threshold during training to force integer alignment.")

    print("\nDone.")


if __name__ == "__main__":
    main()
