#!/usr/bin/env python3
"""
Phase 3: DVS128 SNN Training
Binary-weight SNN on ReRAM crossbar — hardware-faithful training loop.

Training strategy
-----------------
The axon_sign encoding (odd axons negated) and binary {0,1} weights together
zero-centre the LIF potential:
With high thresholds (e.g. 10), P(fire) ≈ 3% → dead neuron cascade, zero grads.
With lower thresholds (e.g. 3), P(fire) ≈ 30% → healthy gradient flow.
The initial threshold is set via --init-threshold (default: nvm_parameter.NEURON_THRESHOLD).

The surrogate slope must satisfy  slope × threshold < 4  early in training so
the gradient is non-zero at potential=0.  We start at slope=0.6 and anneal to
10.0 over four training phases.

Loss:  majority_vote_cross_entropy
     + asymmetric spike-rate regularisation     (λ_reg; off in Phase 4)

  - Vote:      reshape (B, N_OUTPUT) → (B, N_CLASSES, VOTES_PER_CLS),
               sum votes → (B, N_CLASSES) logits, CE loss
  - Spike reg: penalise rates below target (10×) or above target (1×) to keep
               all layers near 25-30% throughout training.

4-Phase schedule in mutiphase flow
----------------
Phase 1  Epochs  1-10   slope 0.6→0.6  lr 1e-3   λ_reg 0.10  Establish spike rates
Phase 2  Epochs 11-30   slope 0.6→3.0  lr 5e-4   λ_reg 0.05  Adapt to binary weights
Phase 3  Epochs 31-60   slope 3.0→10.0 lr 1e-4↘  λ_reg 0.01  Maximise accuracy
Phase 4  Epochs 61-80   slope 10.0     lr 5e-5↘  λ_reg 0.00  Fine-tune
                                                              Freezes: thresholds (all layers)
                                                                       last-layer BinaryLinear weights

Usage
-----
  python train_dvs128.py --data-dir data --epochs 80

    # Smoke test (no real data required):
    python train_dvs128.py --dry-run

    # Resume from a checkpoint:
    python train_dvs128.py --resume checkpoints/best.pt

Dependencies: torch, snntorch, numpy (all in venv)
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from snntorch import surrogate

sys.path.insert(0, str(Path(__file__).parent))
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture"))
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture" / "utils"))
from snn_model import (
    SNNNetwork, build_model, override_lif_params,
    forward_with_internals, get_hardware_params,
    HARDWARE_LAYERS, DEEP_LAYERS, DEFAULT_N_INPUTS, DEFAULT_THRESHOLD,
    N_CLASSES,   # sourced from nvm_parameter.NUM_CLASS
)
from dvs128_dataset import make_loaders, DVS128Dataset
from snn_hw_utils import interleaved_logits


# ─────────────────────────────────────────────────────────────────────────────
# 1. Constants
# ─────────────────────────────────────────────────────────────────────────────

# Output shape — derived from hardware layer config (nvm_parameter.py source of truth)
N_OUTPUT:      int   = HARDWARE_LAYERS[-1].total_output   # 240
# N_CLASSES imported from snn_model (= nvm_parameter.NUM_CLASS = 12)
VOTES_PER_CLS: int   = N_OUTPUT // N_CLASSES               # 20

# Hardware LIF parameter bounds (enforced after every optimizer step)
THRESHOLD_MIN: float = 1.0      # NEURON_THRESHOLD >= 1
THRESHOLD_MAX: float = 15.0     # beyond this, slope×t > 150 → dead zone at slope=10
BETA_MIN:      float = 0.875    # LEAK_SHIFT=3 (fast leak)
BETA_MAX:      float = 0.9999   # avoid log2(0) in hardware export

# Spike-rate regularisation targets per layer (L0, L1, L2+).
# Spike reg provides an independent gradient path that pushes thresholds toward
# healthy firing rates even when CE loss is flat (dead neuron bootstrap problem).
# λ_reg is annealed to 0.0 in Phase 4 once CE loss takes over.
SPIKE_TARGETS: list[float] = [0.30, 0.25, 0.25]
MIN_SPIKE_RATE: float       = 0.05   # floor used when --spike-reg-mode=floor

# Phase durations in epochs. Cumulative sums give absolute epoch boundaries.
# Default [10, 20, 30, 20] → boundaries 10 / 30 / 60 / 80 (total = 80 epochs).
DEFAULT_PHASE_DURATIONS: list[int] = [10, 20, 30, 20]

# Per-phase hyper-parameters: (slope_start, slope_end, lr, lambda_reg)
PHASE_SCHEDULE: list[tuple] = [
    (0.6,  0.6,  1e-3, 0.10),   # Phase 1 — establish spike rates
    (0.6,  3.0,  5e-4, 0.05),   # Phase 2 — adapt to binary weights
    (3.0,  10.0, 1e-4, 0.01),   # Phase 3 — maximise accuracy
    (10.0, 10.0, 5e-5, 0.00),   # Phase 4 — fine-tune, freeze thresh
]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Phase schedule
# ─────────────────────────────────────────────────────────────────────────────

def build_phase_cfg(durations: list[int]) -> dict[int, dict]:
    """
    Convert per-phase epoch durations into a fully-specified phase config dict.

    Args:
        durations : list of epoch counts per phase, e.g. [10, 20, 30, 20].
                    Must have the same length as PHASE_SCHEDULE (4 phases).
    Returns:
        Dict keyed 1..N, each containing:
          start, end              — inclusive epoch range
          slope_s, slope_e       — surrogate slope linearly interpolated across phase
          lr                     — base learning rate (cosine-annealed in phases 3 & 4)
          lam                    — spike-rate regularisation weight (λ_reg)
    """
    if len(durations) != len(PHASE_SCHEDULE):
        raise ValueError(f"Expected {len(PHASE_SCHEDULE)} phase durations, got {len(durations)}")
    cfg, boundary = {}, 0
    for i, (dur, (ss, se, lr, lam)) in enumerate(zip(durations, PHASE_SCHEDULE), start=1):
        cfg[i] = dict(start=boundary + 1, end=boundary + dur,
                      slope_s=ss, slope_e=se, lr=lr, lam=lam)
        boundary += dur
    return cfg


def get_surrogate_slope(epoch: int, phase_cfg: dict) -> float:
    """
    Return the linearly-interpolated fast_sigmoid slope for the current epoch.

    Args:
        epoch     : current epoch (1-indexed)
        phase_cfg : phase config from build_phase_cfg()
    Returns:
        Interpolated slope value for this epoch.
    """
    cfg = next((c for c in phase_cfg.values() if c["start"] <= epoch <= c["end"]),
               phase_cfg[max(phase_cfg)])
    t = (epoch - cfg["start"]) / max(cfg["end"] - cfg["start"], 1)
    return cfg["slope_s"] + t * (cfg["slope_e"] - cfg["slope_s"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. Loss functions
# ─────────────────────────────────────────────────────────────────────────────

def majority_vote_loss(output: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """
    Interleaved majority-vote cross-entropy — matches hardware RTL scheduler.

    Hardware assigns output neurons by round-robin:
        neuron 0,12,24,… → class 0
        neuron 1,13,25,… → class 1  …
    Logits = sum of each class's VOTES_PER_CLS votes.

    Uses snn_hw_utils.interleaved_logits — single source of truth shared with
    snn_reference_model.classify() and test_full_network_debug._votes_and_class().

    Args:
        output : (batch, N_OUTPUT) raw spike tensor
        labels : (batch,) integer class indices
    """
    logits = interleaved_logits(output, N_CLASSES)
    return F.cross_entropy(logits, labels, label_smoothing=0.1)


def spike_rate_loss(
    activations: list[torch.Tensor],
    lambda_reg:  float,
    mode:        str = "target",   # "target" | "floor"
) -> torch.Tensor:
    """
    Asymmetric L2 spike-rate regularisation.

    Penalises rates below target 10× more strongly than rates above target.
    Rationale: dead neurons (rate < 1%) kill gradients entirely, so we prevent
    them aggressively; slightly-above-target rates are acceptable.

        penalty = λ × relu(target − rate)²      ← push up aggressively
                + 0.1λ × relu(rate − target)²   ← gently restrain

    mode="floor" only prevents collapse (rate < MIN_SPIKE_RATE global) without
    targeting a specific rate — useful when natural layer variation is high.

    Args:
        activations : list of per-layer spike tensors from forward_with_internals()
        lambda_reg  : regularisation weight; 0.0 → returns zero (no-op)
        mode        : "target" (default) or "floor"
    """
    if lambda_reg == 0.0:
        return torch.zeros(1, device=activations[0].device).squeeze()

    dev, dtype = activations[0].device, activations[0].dtype
    loss = torch.zeros(1, device=dev, dtype=dtype).squeeze()

    if mode == "floor":
        floor = torch.tensor(MIN_SPIKE_RATE, device=dev, dtype=dtype)
        for act in activations:
            loss = loss + lambda_reg * F.relu(floor - act.mean()).pow(2)
        return loss

    # Pad targets so deeper models always have a target for every layer
    padded = SPIKE_TARGETS + [SPIKE_TARGETS[-1]] * max(0, len(activations) - len(SPIKE_TARGETS))
    for act, tgt in zip(activations, padded):
        rate  = act.mean()
        t     = torch.tensor(tgt, device=dev, dtype=dtype)
        loss  = loss + lambda_reg * F.relu(t - rate).pow(2) \
                     + 0.1 * lambda_reg * F.relu(rate - t).pow(2)
    return loss


def accuracy(output: torch.Tensor, labels: torch.Tensor) -> float:
    """
    Classification accuracy via interleaved majority vote — matches hardware.

    Args:
        output : (batch, N_OUTPUT) raw spike tensor
        labels : (batch,) ground-truth class indices
    Returns:
        Fraction of correctly classified samples in [0.0, 1.0].
    """
    logits = interleaved_logits(output, N_CLASSES)
    return (logits.argmax(dim=1) == labels).float().mean().item()


@torch.no_grad()
def clamp_lif_params(model: SNNNetwork) -> None:
    """
    Clamp threshold and beta to hardware-valid ranges after each optimizer step.

    Default: threshold ∈ [1, 15], beta ∈ [BETA_MIN, BETA_MAX].
    multi_threshold: threshold ∈ [1, 65535] (full 16-bit unsigned range).
    """
    th_max = 65535.0 if getattr(model, "multi_threshold", False) else THRESHOLD_MAX
    for cores in model._layers:
        for core in cores:
            core.lif.threshold.clamp_(THRESHOLD_MIN, th_max)
            core.lif.beta.clamp_(BETA_MIN, BETA_MAX)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Train / evaluate one epoch
# ─────────────────────────────────────────────────────────────────────────────

def train_epoch(
    model:          SNNNetwork,
    loader:         torch.utils.data.DataLoader,
    optimizer:      torch.optim.Optimizer,
    device:         torch.device,
    epoch:          int,
    phase_cfg:      dict,
    spike_reg_mode: str,
) -> tuple[float, float, list[float]]:
    """
    Run one full training epoch: forward → losses → backward → step → clamp.

    Gradient clipping (max_norm=5.0) prevents rare exploding gradients when
    the surrogate slope reaches 10 in Phase 4.

    Args:
        model          : SNNNetwork instance
        loader         : DataLoader over the training split
        optimizer      : Adam optimizer (LR already set by caller)
        device         : torch.device
        epoch          : current epoch number (1-indexed)
        phase_cfg      : phase config from build_phase_cfg()
        spike_reg_mode : "target" or "floor" — passed to spike_rate_loss()
    Returns:
        (mean_cls_loss, mean_accuracy, mean_spike_rates_per_layer)
    """
    model.train()

    # Update surrogate gradient slope for this epoch
    slope   = get_surrogate_slope(epoch, phase_cfg)
    grad_fn = surrogate.fast_sigmoid(slope=slope)
    for cores in model._layers:
        for core in cores:
            core.lif.spike_grad = grad_fn

    # Look up λ_reg for the current phase
    phase_now  = next((c for c in phase_cfg.values() if c["start"] <= epoch <= c["end"]),
                      phase_cfg[max(phase_cfg)])
    lambda_reg = phase_now["lam"]

    total_loss, total_acc = 0.0, 0.0
    spike_accum = [0.0] * len(model.layer_configs)

    for x, y in loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()

        acts   = forward_with_internals(model, x)
        output = acts[-1]

        cls_loss = majority_vote_loss(output, y)
        loss = cls_loss + spike_rate_loss(acts, lambda_reg, mode=spike_reg_mode)
        loss.backward()

        nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()
        clamp_lif_params(model)

        total_loss += cls_loss.detach().item()
        total_acc  += accuracy(output.detach(), y)
        for i, a in enumerate(acts):
            spike_accum[i] += a.detach().mean().item()

    n = len(loader)
    return total_loss / n, total_acc / n, [s / n for s in spike_accum]


@torch.no_grad()
def evaluate(
    model:  SNNNetwork,
    loader: torch.utils.data.DataLoader,
    device: torch.device,
) -> tuple[float, list[float]]:
    """
    Evaluate the model on a data split without gradient computation.

    Args:
        model  : SNNNetwork instance
        loader : DataLoader over the evaluation split
        device : torch.device
    Returns:
        (accuracy, spike_rates_per_layer)
    """
    model.eval()
    total_acc   = 0.0
    spike_accum = [0.0] * len(model.layer_configs)

    for x, y in loader:
        x, y = x.to(device), y.to(device)
        acts   = forward_with_internals(model, x)
        total_acc += accuracy(acts[-1], y)
        for i, a in enumerate(acts):
            spike_accum[i] += a.mean().item()

    n = len(loader)
    return total_acc / n, [s / n for s in spike_accum]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3: Train SNN on DVS128Gesture")
    parser.add_argument("--data-dir",   type=Path, default=Path("data"))
    parser.add_argument("--batch-size", type=int,  default=32)
    parser.add_argument("--epochs",     type=int,  default=80)
    parser.add_argument("--multiphase", action="store_true",
                        help="Enable the legacy 4-phase training schedule (annealing slope/LR). "
                             "If False (default), uses constant --lr, --slope, and --lambda-reg.")
    parser.add_argument("--phase-durations", type=int, nargs=4,
                        default=DEFAULT_PHASE_DURATIONS, metavar=("D1", "D2", "D3", "D4"),
                        help="Per-phase epoch counts for --multiphase mode "
                             f"(default {DEFAULT_PHASE_DURATIONS})")
    parser.add_argument("--ckpt-dir",   type=Path, default=Path("checkpoints"))

    # ── Threshold initialisation ────────────────────────────────────────────────
    parser.add_argument("--init-threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="Initial LIF threshold for all layers (learned during training). "
                             "Default: nvm_parameter.NEURON_THRESHOLD.")

    parser.add_argument("--input-scale", type=int, default=256,
                        help="Quantise raw uint16 features to [0, INPUT_SCALE] before "
                             "feeding to the model.  256 (default) prevents 16-bit "
                             "hardware accumulator saturation (64 × 256 < POS_SAT). "
                             "Pass 0 to disable scaling (raw uint16, legacy behaviour).")
    parser.add_argument("--augment", action="store_true",
                        help="Apply training augmentations (spatial jitter, Gaussian noise, "
                             "time-window dropout). Training split only; test unchanged.")
    parser.add_argument("--multi-threshold", action="store_true",
                        help="Learn per-layer integer thresholds via IntegerThresholdSTE. "
                             "Widens threshold clamp to [1, 65535] (16-bit). "
                             "Checkpoint gains threshold_per_layer: list[int]. "
                             "Default flow (flag off) is byte-identical to current code.")
    parser.add_argument("--resume",    type=Path,  default=None,
                        help="Resume from a .pt checkpoint")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Smoke test on 64 synthetic samples — no real data needed")
    parser.add_argument("--only-test", action="store_true",
                        help="Skip training; evaluate --resume checkpoint only")

    # ── Test-time parameter overrides (--only-test mode) ───────────────────────
    parser.add_argument("--override-threshold", type=float, nargs="+", default=None,
                        metavar="TH",
                        help="Override LIF threshold in --only-test mode. "
                             "One value → applied to all layers. "
                             "Multiple values → one per layer (last reused if list is short). "
                             "Example: --override-threshold 2.0  or  --override-threshold 3.0 2.5 2.0")
    parser.add_argument("--test-leak-shift", type=int, default=None,
                        help="Override leak register in --only-test mode. "
                             "Sets beta = 1 - 1/2^N (e.g. N=10 → beta ≈ 0.999). "
                             "Matches nvm_parameter.NEURON_LEAK_SHIFT.")
    parser.add_argument("--spike-reg-mode", choices=["target", "floor"], default="target")
    parser.add_argument("--no-recovery", action="store_true",
                        help="Disable automatic LR-halving when L0 activity < 5%.")

    # ── Single-phase parameters (only used if --multiphase is False) ──────────
    parser.add_argument("--lr",         type=float, default=1e-3, help="Learning rate (default: 1e-3)")
    parser.add_argument("--slope",      type=float, default=0.6,  help="Surrogate slope (default: 0.6)")
    parser.add_argument("--lambda-reg", type=float, default=0.1,  help="Spike-rate reg weight (default: 0.1)")

    args = parser.parse_args()

    # Validate mutually exclusive / mode-specific arguments
    if (args.override_threshold is not None or args.test_leak_shift is not None) \
            and not args.only_test:
        parser.error("--override-threshold / --test-leak-shift require --only-test")
    if args.multiphase and (args.lr != 1e-3 or args.slope != 0.6 or args.lambda_reg != 0.1):
        parser.error("--lr, --slope, --lambda-reg are ignored when --multiphase is set; "
                     "edit PHASE_SCHEDULE in the file to change per-phase values")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if args.multiphase:
        phase_cfg = build_phase_cfg(args.phase_durations)
    else:
        phase_cfg = {1: dict(start=1, end=args.epochs,
                             slope_s=args.slope, slope_e=args.slope,
                             lr=args.lr, lam=args.lambda_reg)}

    print(f"Device: {device}")
    if args.multi_threshold:
        print("Multi-threshold mode ON — IntegerThresholdSTE active, clamp=[1, 65535].")

    # ── Dry-run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        import numpy as _np
        from torch.utils.data import DataLoader as _DL
        print("\n[dry-run] Building model with synthetic data …")
        rng    = _np.random.default_rng(0)
        feats  = rng.integers(0, 32767, size=(64, DEFAULT_N_INPUTS)).astype(_np.uint16)
        labels = rng.integers(0, N_CLASSES, size=(64,)).astype(_np.int64)
        _dry_scale = args.input_scale if args.input_scale > 0 else None
        loader = _DL(DVS128Dataset(feats, labels, input_scale=_dry_scale), batch_size=32, shuffle=True)
        model  = build_model(init_threshold=args.init_threshold,
                             multi_threshold=args.multi_threshold).to(device)
        opt    = torch.optim.Adam(model.parameters(), lr=1e-3)
        train_epoch(model, loader, opt, device, epoch=1, phase_cfg=phase_cfg,
                    spike_reg_mode=args.spike_reg_mode)
        with torch.no_grad():
            acts = forward_with_internals(model, next(iter(loader))[0].to(device))
        print(f"[dry-run] spike_rates={[f'{a.mean().item()*100:.1f}%' for a in acts]}")
        print("[dry-run] PASSED — forward/backward/clamp all ran without error.")
        return

    # ── Data ──────────────────────────────────────────────────────────────────
    _input_scale = args.input_scale if args.input_scale > 0 else None
    train_loader, test_loader, _ = make_loaders(args.data_dir, args.batch_size,
                                                augment=args.augment,
                                                input_scale=_input_scale)

    # ── Model ─────────────────────────────────────────────────────────────────
    # All layers start at args.init_threshold. Each LIFCore owns a separate
    # threshold parameter (learn_threshold=True) that the optimiser updates
    # independently, causing per-layer divergence during training.
    model = build_model(
        init_threshold=args.init_threshold,
        layers=HARDWARE_LAYERS,
        init_beta=0.999,
        surrogate_slope=0.6,    # slope × threshold < 4 at init → non-zero gradient
        multi_threshold=args.multi_threshold,
    ).to(device)

    # Initial spike-rate sanity check
    x0, _ = next(iter(train_loader))
    with torch.no_grad():
        init_rates = [a.mean().item() for a in forward_with_internals(model, x0.to(device))]
    print(f"Initial spike rates: {[f'{r*100:.1f}%' for r in init_rates]}")
    if init_rates[0] < 0.05:
        print("WARNING: L0 spike rate < 5% at init — consider lowering --init-threshold")

    # ── Optimiser ─────────────────────────────────────────────────────────────
    optimizer   = torch.optim.Adam(model.parameters(), lr=phase_cfg[1]["lr"])
    start_epoch = 1
    best_acc    = 0.0

    # ── Resume ────────────────────────────────────────────────────────────────
    if args.resume is not None:
        if not args.resume.exists():
            print(f"ERROR: checkpoint not found: {args.resume}"); return
        ckpt        = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        start_epoch = ckpt["epoch"] + 1
        best_acc    = ckpt.get("val_acc", 0.0)
        resumed_ph  = next((c for c in phase_cfg.values()
                            if c["start"] <= start_epoch <= c["end"]),
                           phase_cfg[max(phase_cfg)])
        for pg in optimizer.param_groups:
            pg["lr"] = resumed_ph["lr"]
        print(f"Resumed from epoch {ckpt['epoch']}  "
              f"(best val_acc={best_acc*100:.2f}%)  → epoch {start_epoch}")

    # ── Test-only ─────────────────────────────────────────────────────────────
    if args.only_test:
        if args.resume is None:
            parser.error("--only-test requires --resume <checkpoint.pt>")

        # Resolve --override-threshold: 1 value → scalar, N values → list
        override_th = None
        if args.override_threshold is not None:
            override_th = (args.override_threshold[0]
                           if len(args.override_threshold) == 1
                           else args.override_threshold)

        has_overrides = override_th is not None or args.test_leak_shift is not None
        ctx = (override_lif_params(model, threshold=override_th,
                                   leak_shift=args.test_leak_shift)
               if has_overrides else contextlib.nullcontext())
        with ctx:
            if has_overrides:
                _hw = get_hardware_params(model)
                th_display = (f"{override_th}" if isinstance(override_th, list)
                              else f"{_hw['threshold']:.3f}")
                print(f"TEST OVERRIDES: threshold={th_display}  "
                      f"leak_shift={args.test_leak_shift}")
            val_acc, val_rates = evaluate(model, test_loader, device)
        hw = get_hardware_params(model)
        print(f"\nTest accuracy : {val_acc*100:.2f}%")
        print(f"Spike rates   : {[f'{r*100:.1f}%' for r in val_rates]}")
        print(f"LIF params    : threshold={hw['threshold']:.3f}  "
              f"leak_shift={hw['leak_shift']}")
        if "threshold_per_layer" in hw:
            print(f"Per-layer thr : {hw['threshold_per_layer']}")
        return

    # ── Checkpoint dir + CSV log ───────────────────────────────────────────────
    args.ckpt_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.ckpt_dir / "training_log.csv"
    if not log_path.exists():
        log_path.write_text(
            "epoch,phase,slope,lr,tr_loss,tr_acc,val_acc,"
            "l0_rate,l1_rate,l2_rate,l3_rate,threshold,leak_shift\n"
        )

    # ── Training loop ─────────────────────────────────────────────────────────
    prev_phase  = 0
    dead_epochs = 0   # consecutive epochs with L0 rate < 5%

    print(f"\n{'Ep':>3}  {'Ph':>2}  {'slope':>5}  {'loss':>7}  {'tr_acc':>6}  "
          f"{'val_acc':>7}  {'L0':>5}  {'L1':>5}  {'L2':>5}  {'L3':>5}  {'thr':>5}  {'lk':>3}")
    print("─" * 88)

    for epoch in range(start_epoch, args.epochs + 1):
        phase_num = next((ph for ph, c in phase_cfg.items()
                          if c["start"] <= epoch <= c["end"]), max(phase_cfg))
        phase_now = phase_cfg[phase_num]

        # Phase transition: update LR and freeze/unfreeze params
        if args.multiphase and (phase_num != prev_phase):
            prev_phase = phase_num
            for pg in optimizer.param_groups:
                pg["lr"] = phase_now["lr"]
            if phase_num == 1:
                print(f"\n=== Phase 1: Bootstrapping firing rates ===\n")
            elif phase_num == 2:
                print(f"\n=== Phase 2: Binary weight adaptation (slope annealing) ===\n")
            elif phase_num == 3:
                print(f"\n=== Phase 3: Accuracy maximization (steep gradients) ===\n")
            elif phase_num == 4:
                for cores in model._layers:
                    for core in cores:
                        core.lif.threshold.requires_grad_(False)
                for core in model._layers[-1]:
                    core.linear.weight.requires_grad_(False)
                print(f"\n=== Phase 4: thresholds + output-layer weights frozen ===\n")

        # Cosine LR annealing within phases 3 and 4 (multiphase mode only)
        if args.multiphase and phase_num in (3, 4):
            ep_in  = epoch - phase_now["start"]
            total  = phase_now["end"] - phase_now["start"] + 1
            cos_lr = phase_now["lr"] * 0.5 * (1.0 + math.cos(math.pi * ep_in / total))
            for pg in optimizer.param_groups:
                pg["lr"] = max(cos_lr, 1e-6)

        tr_loss, tr_acc, tr_rates = train_epoch(
            model, train_loader, optimizer, device, epoch, phase_cfg,
            spike_reg_mode=args.spike_reg_mode,
        )
        val_acc, val_rates = evaluate(model, test_loader, device)

        slope  = get_surrogate_slope(epoch, phase_cfg)
        hw     = get_hardware_params(model)
        lr_now = optimizer.param_groups[0]["lr"]

        l3_col = (f"{val_rates[3]*100:>4.1f}%  " if len(val_rates) > 3 else "      ")
        print(f"{epoch:>3}  {phase_num:>2}  {slope:>5.2f}  {tr_loss:>7.4f}  "
              f"{tr_acc*100:>5.1f}%  {val_acc*100:>6.1f}%  "
              f"{val_rates[0]*100:>4.1f}%  {val_rates[1]*100:>4.1f}%  "
              f"{val_rates[2]*100:>4.1f}%  {l3_col}"
              f"{hw['threshold']:>5.2f}  {hw['leak_shift']:>3}")

        # Per-layer threshold breakdown — each layer's mean threshold across its
        # cores is printed so divergence is visible.
        if args.multi_threshold:
            per_layer_th = [
                sum(c.lif.threshold.item() for c in cores) / len(cores)
                for cores in model._layers
            ]
            th_str = "  ".join(
                f"{model.layer_configs[i].label or f'L{i}'}={th:.3f}"
                for i, th in enumerate(per_layer_th)
            )
            print(f"     thresholds: {th_str}")

        with open(log_path, "a") as f:
            rates_str = ",".join(f"{r:.4f}" for r in val_rates)
            # rates_str may have 3 or 4 values depending on topology (HARDWARE vs DEEP)
            f.write(f"{epoch},{phase_num},{slope:.4f},{lr_now:.2e},"
                    f"{tr_loss:.6f},{tr_acc:.6f},{val_acc:.6f},"
                    f"{rates_str},{hw['threshold']:.4f},{hw['leak_shift']}\n")

        # Dead-neuron recovery: 3 consecutive < 5% epochs → halve LR
        # Only trigger in Phase 3+ (accuracy maximization) to avoid killing the
        # learning rate during the initial bootstrap (Phases 1 & 2).
        if phase_num >= 3 and not args.no_recovery and val_rates[0] < 0.05:
            dead_epochs += 1
            if dead_epochs >= 3:
                old_lr = optimizer.param_groups[0]["lr"]
                for pg in optimizer.param_groups:
                    pg["lr"] = old_lr * 0.5
                print(f"  [recovery] L0 < 5% for {dead_epochs} epochs "
                      f"→ LR halved to {old_lr*0.5:.2e}")
                dead_epochs = 0
        else:
            dead_epochs = 0

        if val_acc > best_acc:
            best_acc = val_acc
            torch.save({
                "epoch":            epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state":  optimizer.state_dict(),
                "val_acc":          val_acc,
                "spike_rates":      val_rates,
                "hardware_params":  hw,
                "init_threshold":   args.init_threshold,
                "multi_threshold":  args.multi_threshold,
                "phase_durations":  args.phase_durations,
            }, args.ckpt_dir / "best.pt")

    # ── Final report ──────────────────────────────────────────────────────────
    hw = get_hardware_params(model)
    print(f"\n{'='*60}")
    print(f" Training complete  |  Best val acc: {best_acc*100:.2f}%")
    print(f" Hardware params : threshold={hw['threshold']:.3f}  "
          f"beta={hw['beta']:.6f}  leak_shift={hw['leak_shift']}")
    print(f"\n Write to verilog/tb/nvm_parameter.py:")
    print(f"   NEURON_THRESHOLD  = {hw['threshold']:.2f}")
    print(f"   NEURON_LEAK_SHIFT = {hw['leak_shift']}")
    print(f"\n CSV log: {log_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
