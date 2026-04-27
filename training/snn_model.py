#!/usr/bin/env python3
"""
Phase 2: PyTorch SNN Model Architecture

Generic multi-layer binary-weight SNN faithful to the ReRAM crossbar.
Layer topology is driven by a list of LayerConfig objects so any depth
or width can be swept without touching the hardware-faithful building blocks.

Default topology (HARDWARE_LAYERS) mirrors the chip's 13-4-4 core layout
as defined in nvm_parameter.py (single source of truth for all dimensions):

  Layer 0 │ 256 axons → 13 cores × 64 neurons = 832 spikes  (broadcast)
  Layer 1 │ 832 spikes →  4 cores × 64 neurons = 256 spikes  (partitioned)
  Layer 2 │ 256 spikes →  4 cores × 60 neurons = 240 output  (broadcast)

Hardware constraints encoded in the model:
  - Binary {0, 1} weights in every layer       (BinaryWeight STE)
  - Odd-indexed input axons negated             (axon_sign buffer in LIFCore)
  - Single time-step LIF, mem reset each sample (matches RTL picture_done)
  - learn_threshold=True / learn_beta=True      (no manual calibration needed)

Public API
----------
  Classes   : LayerConfig, BinaryLinear, LIFCore, SNNNetwork
  Presets   : HARDWARE_LAYERS, WIDE_LAYERS, DEEP_LAYERS
  Constants : NEURONS_PER_CORE, DEFAULT_N_INPUTS, DEFAULT_THRESHOLD,
              DEFAULT_BETA, DEFAULT_LEAK_SHIFT, N_CLASSES
  Functions : build_model, forward_with_internals, get_binary_weights,
              get_hardware_params, override_lif_params, print_model_summary

Dependencies:
    pip install snntorch torch numpy
"""

from __future__ import annotations

import contextlib
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import torch
import torch.nn as nn
import snntorch as snn
from snntorch import surrogate

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture"))
sys.path.insert(0, str(root / "verilog" / "tb" / "snn_gesture" / "utils"))
from snn_hw_utils import load_nvm_parameter


# ─────────────────────────────────────────────────────────────────────────────
# 1. Hardware parameter import (nvm_parameter.py → single source of truth)
# ─────────────────────────────────────────────────────────────────────────────

_nvm = load_nvm_parameter()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Module-level hardware constants (sourced from nvm_parameter)
# ─────────────────────────────────────────────────────────────────────────────

NEURONS_PER_CORE:  int   = _nvm.NUM_NEURON              # 64  — ReRAM crossbar tile width
DEFAULT_N_INPUTS:  int   = _nvm.NUM_AXON_LAYER_0        # 256 — hardware tile width (DVS128 uses 256 axons; unused rows zero-padded)
DEFAULT_THRESHOLD: float = float(_nvm.NEURON_THRESHOLD) # 2.0 — initial LIF spike threshold
DEFAULT_LEAK_SHIFT: int  = _nvm.NEURON_LEAK_SHIFT       # 10  — leak = potential >> LEAK_SHIFT
DEFAULT_BETA:      float = 1.0 - 1.0 / (2 ** DEFAULT_LEAK_SHIFT)  # ≈ 0.999
N_CLASSES:         int   = _nvm.NUM_CLASS               # 12  — gesture classes


# ─────────────────────────────────────────────────────────────────────────────
# 3. Layer Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LayerConfig:
    """
    Describes one layer of virtual neuron cores.

    Specify total neurons in the layer; n_cores is derived automatically
    as n_neurons // NEURONS_PER_CORE (hardware constant = 64).

    Attributes
    ----------
    n_neurons : total neurons in this layer; must be a multiple of
                NEURONS_PER_CORE (64).  n_cores = n_neurons // 64.
    routing   : "broadcast"   — every core sees the full previous output.
                "partitioned" — each core k sees an equal non-overlapping
                slice of the previous output (prev_total must be divisible
                by n_cores).
    n_active  : total active neurons exposed downstream; -1 = all n_neurons.
                Must be divisible by n_cores (trimmed equally per core).
                E.g. n_neurons=256, n_active=240  →  4 cores × 60 active.
    label     : human-readable name shown in print_model_summary.
    """
    n_neurons: int
    routing:   Literal["broadcast", "partitioned"] = "broadcast"
    n_active:  int = -1   # -1 → all n_neurons are active
    label:     str = ""

    def __post_init__(self) -> None:
        if self.n_neurons % NEURONS_PER_CORE != 0:
            raise ValueError(
                f"n_neurons={self.n_neurons} must be a multiple of "
                f"NEURONS_PER_CORE={NEURONS_PER_CORE}"
            )
        #if self.n_active != -1 and self.n_active % self.n_cores != 0:
        #    raise ValueError(
        #        f"n_active={self.n_active} must be divisible by "
        #        f"n_cores={self.n_cores}"
        #    )

    @property
    def n_cores(self) -> int:
        """Derived: n_neurons // NEURONS_PER_CORE."""
        return self.n_neurons // NEURONS_PER_CORE

    @property
    def total_output(self) -> int:
        """Total spikes exposed downstream (= n_active if set, else n_neurons)."""
        return self.n_neurons if self.n_active == -1 else self.n_active

    @property
    def _active_per_core(self) -> int:
        """Used internally: active neurons per tile after trimming."""
        return self.total_output // self.n_cores


# ── Preset topologies ─────────────────────────────────────────────────────────
# LayerConfig(**spec) is used directly — no wrapper function needed.

# Hardware-faithful 13-4-4 topology (all dimensions mirror nvm_parameter.py)
HARDWARE_LAYERS: list[LayerConfig] = [
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_0, label="L0"),
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_1, routing="partitioned", label="L1"),
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_2, n_active=_nvm.NUM_VOTES, label="L2-output"),
]

# Wider first layer — more representational capacity, same output shape
WIDE_LAYERS: list[LayerConfig] = [
    LayerConfig(n_neurons=1024, label="L0-wide"),                                         # 16 × 64
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_1, routing="partitioned"),
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_2, n_active=_nvm.NUM_VOTES, label="L2-output"),
]

# 4-layer depth variant — extra hidden layer between L1 and output
DEEP_LAYERS: list[LayerConfig] = [
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_0, label="L0"),
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_1, routing="partitioned", label="L1"),
    LayerConfig(n_neurons=_nvm.NUM_NEURONS_LAYER_2, n_active=_nvm.NUM_VOTES, label="L3-output"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Binary Weight Straight-Through Estimator
# ─────────────────────────────────────────────────────────────────────────────

class BinaryWeight(torch.autograd.Function):
    """
    Forward : W → {0, 1}   (threshold at 0)
    Backward: STE — gradient flows through; zeroed for |W| > 1 (Hinton clip)

    Why manual STE instead of Brevitas:
      Export to connection_XXX.txt needs plain numpy {0,1}. With manual STE:
        W_bin = (model._layers[0][0].linear.weight > 0).cpu().numpy()
      Brevitas wraps weights in proxy layers that require internal surgery.
    """

    @staticmethod
    def forward(ctx, weight: torch.Tensor) -> torch.Tensor:
        ctx.save_for_backward(weight)
        return (weight > 0).float()

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor) -> torch.Tensor:
        (weight,) = ctx.saved_tensors
        grad = grad_output.clone()
        # Hinton clipping: weights far from decision boundary don't need updating
        grad[weight.abs() > 1.0] = 0.0
        return grad


class IntegerThresholdSTE(torch.autograd.Function):
    """
    Forward : threshold → round(threshold)  (nearest integer)
    Backward: STE — gradient flows through unchanged.

    Used when --multi-threshold is active to quantise each layer's threshold to
    a 16-bit integer value that the hardware threshold register can represent
    exactly, while still allowing gradient-based optimisation.
    """

    @staticmethod
    def forward(ctx, threshold: torch.Tensor) -> torch.Tensor:
        return threshold.round()

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor) -> torch.Tensor:
        return grad_output


# ─────────────────────────────────────────────────────────────────────────────
# 5. Binary Linear Layer  (thin nn.Module — owns one weight parameter)
# ─────────────────────────────────────────────────────────────────────────────

class BinaryLinear(nn.Module):
    """
    Linear layer with binary {0,1} weights.

    Continuous weights are maintained for gradient flow. On each forward pass
    they are binarised via BinaryWeight.apply() — the STE lets gradients
    pass through this discrete operation during training.

    Weight shape: (n_in, n_out) — stored as float, thresholded at 0 in fwd.
    """

    def __init__(self, n_in: int, n_out: int):
        super().__init__()
        # Uniform [-0.5, 0.5]: straddles the binarisation threshold cleanly.
        # All weights start near the boundary, so early STE gradients are meaningful.
        self.weight = nn.Parameter(torch.empty(n_in, n_out).uniform_(-0.5, 0.5))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:    x  (batch, n_in)
        Returns:    (batch, n_out) — sum of binary synapse activations
        """
        W_bin = BinaryWeight.apply(self.weight)   # {0,1} fwd, STE bwd
        return x @ W_bin                           # (batch, n_out)

    def get_binary_weights(self) -> np.ndarray:
        """Return binarised weights as (n_in, n_out) uint8 for file export."""
        with torch.no_grad():
            return (self.weight > 0).cpu().numpy().astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
# 6. LIF Core  (thin nn.Module — one crossbar tile = 64 neurons)
# ─────────────────────────────────────────────────────────────────────────────

class LIFCore(nn.Module):
    """
    One NEURONS_PER_CORE-neuron virtual core: BinaryLinear + snnTorch Leaky LIF.

    Axon sign encoding
    ------------------
    Hardware: col = axon % 32; sign = col % 2 = axon % 2
    stimuli = sign == 1 ? -val : +val   (odd columns negated)

    In training: the same sign flip is applied to the input before the MAC
    via a fixed (non-trainable) axon_sign buffer. The BinaryWeight STE
    is unaffected.

    Single time-step
    ----------------
    Hardware evaluates each gesture in one pass ("flattened time").
    We match this by initialising mem = 0 at every forward() call.
    snn.Leaky is called once with (input, mem=0) → spike, new_mem.
    new_mem is discarded — no state carry-over between samples.
    """

    def __init__(
        self,
        n_in:            int,
        n_out:           int   = NEURONS_PER_CORE,
        init_threshold:  float = DEFAULT_THRESHOLD,
        init_beta:       float = DEFAULT_BETA,
        surrogate_slope: float = 0.6,
        multi_threshold: bool  = False,
    ):
        """
        Args:
            n_in            : number of input axons / spikes
            n_out           : neurons per core (hardware = NEURONS_PER_CORE = 64)
            init_threshold  : initial LIF threshold (learned during training;
                              sourced from nvm_parameter.NEURON_THRESHOLD)
            init_beta       : initial leak factor (learned during training;
                              derived from nvm_parameter.NEURON_LEAK_SHIFT via
                              beta = 1 - 1/2^LEAK_SHIFT)
            surrogate_slope : slope for fast_sigmoid surrogate gradient.
                              Keep slope × threshold < 4 for nonzero gradient
                              at v=0.  Annealed to ~10 during Phase 3 training.
        """
        super().__init__()
        self.n_out = n_out
        self.multi_threshold = multi_threshold

        self.linear = BinaryLinear(n_in, n_out)

        self.lif = snn.Leaky(
            beta=init_beta,
            threshold=init_threshold,
            learn_beta=True,
            learn_threshold=True,
            spike_grad=surrogate.fast_sigmoid(slope=surrogate_slope),
            reset_mechanism="zero",   # V → 0 at spike; matches RTL picture_done
        )

        # Fixed sign buffer: even axons → +1, odd axons → -1  (vectorised)
        self.register_buffer(
            "axon_sign",
            1.0 - 2.0 * (torch.arange(n_in) % 2).float()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:    x  (batch, n_in)  — stimulus values (float)
        Returns:    (batch, n_out) — binary spikes {0,1}
        """
        # 1. Apply hardware sign encoding to inputs
        x_signed = x * self.axon_sign                          # (batch, n_in)

        # 2. Binary synapse integration — batch MAC matches HW sequential accumulation.
        #    HW RTL: accumulate axons one-by-one with saturation clamp [-32768, 32767].
        #    With NEG_SAT=-32768 the floor never triggers for typical inputs (scale=256,
        #    256 axons → |potential| ≤ ~16384 << 32768), so sequential = batch sum.
        #    No per-step clamp or loop is needed.
        potential = self.linear(x_signed)                      # (batch, n_out)

        # 3. LIF: single time-step, mem starts at zero each gesture
        mem = torch.zeros(x.shape[0], self.n_out, device=x.device, dtype=x.dtype)
        if self.multi_threshold:
            threshold = IntegerThresholdSTE.apply(self.lif.threshold)
            spk = self.lif.spike_grad(potential - threshold)   # (batch, n_out)
        else:
            spk, _ = self.lif(potential, mem)                  # (batch, n_out)

        return spk


# ─────────────────────────────────────────────────────────────────────────────
# 7. SNN Network  (thin nn.Module shell — holds parameters, dispatches forward)
# ─────────────────────────────────────────────────────────────────────────────

class SNNNetwork(nn.Module):
    """
    Thin nn.Module shell: registers all layer parameters and dispatches forward.

    Analysis helpers are free functions that accept an SNNNetwork instance:
      forward_with_internals — like forward() but returns every layer's output
      get_binary_weights     — export {0,1} weights as numpy arrays
      get_hardware_params    — read back threshold / beta / leak_shift
      print_model_summary    — print per-layer shape and parameter table

    Routing rules (per LayerConfig.routing)
    ----------------------------------------
    "broadcast"   : every core in this layer receives the full previous output.
    "partitioned" : the previous output is split evenly across cores;
                    prev_total_output must be divisible by n_cores.

    Default topology — HARDWARE_LAYERS (13-4-4, chip-faithful):
      Layer 0 │ 256 axons  → 13×64 = 832 spikes  (broadcast)
      Layer 1 │ 832 spikes →  4×64 = 256 spikes  (partitioned, 208/core)
      Layer 2 │ 256 spikes →  4×60 = 240 output  (broadcast, 60 active/core)
    """

    def __init__(
        self,
        n_inputs:        int                      = DEFAULT_N_INPUTS,
        layers:          list[LayerConfig]        = None,   # None → HARDWARE_LAYERS
        init_threshold:  float | list[float]      = DEFAULT_THRESHOLD,
        init_beta:       float                    = DEFAULT_BETA,
        surrogate_slope: float                    = 0.6,
        multi_threshold: bool                     = False,
    ):
        """
        Args:
            n_inputs        : number of input features (default DEFAULT_N_INPUTS = 256)
            layers          : topology as list[LayerConfig] (None → HARDWARE_LAYERS)
            init_threshold  : initial LIF threshold, learned during training.
                              Accepts a single float applied to all layers, or a
                              list[float] with one value per layer (last entry reused
                              for any additional layers).
                              Default: DEFAULT_THRESHOLD (= nvm_parameter.NEURON_THRESHOLD).
            init_beta       : initial leak factor, learned during training.
                              Derived from nvm_parameter.NEURON_LEAK_SHIFT as
                              beta = 1 - 1/2^LEAK_SHIFT.
            surrogate_slope : slope for fast_sigmoid surrogate gradient.
                              Keep slope × threshold < 4 at init for non-zero gradient.
        """
        super().__init__()
        if layers is None:
            layers = HARDWARE_LAYERS

        self.layer_configs: list[LayerConfig] = layers
        self.n_inputs = n_inputs
        self.multi_threshold = multi_threshold

        # Normalise init_threshold to a list (one float per layer).
        # A scalar is broadcast to all layers; a list is indexed by layer,
        # with the last value reused if the list is shorter than the topology.
        if isinstance(init_threshold, (int, float)):
            thresh_list = [float(init_threshold)] * len(layers)
        else:
            thresh_list = [float(t) for t in init_threshold]
            if len(thresh_list) < len(layers):
                thresh_list += [thresh_list[-1]] * (len(layers) - len(thresh_list))

        # Build one nn.ModuleList per layer; compute n_in for each core dynamically
        all_layers: list[nn.ModuleList] = []
        prev_total = n_inputs
        for i, cfg in enumerate(layers):
            if cfg.routing == "broadcast":
                n_in = prev_total
            else:                                            # partitioned
                if prev_total % cfg.n_cores != 0:
                    raise ValueError(
                        f"Partitioned layer: prev_total={prev_total} not "
                        f"divisible by n_cores={cfg.n_cores}"
                    )
                n_in = prev_total // cfg.n_cores

            cores = nn.ModuleList([
                LIFCore(n_in, NEURONS_PER_CORE, thresh_list[i], init_beta, surrogate_slope,
                        multi_threshold=multi_threshold)
                for _ in range(cfg.n_cores)
            ])
            all_layers.append(cores)
            prev_total = cfg.total_output

        # ModuleList-of-ModuleLists so PyTorch tracks all parameters
        self._layers = nn.ModuleList(all_layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:    x  (batch, n_inputs)
        Returns:    (batch, last_layer.total_output)
        """
        act = x
        for cfg, cores in zip(self.layer_configs, self._layers):
            act = _run_layer(act, cfg, cores)
        return act


# ─────────────────────────────────────────────────────────────────────────────
# 8. Layer execution  (_run_layer — private; used by forward and forward_with_internals)
# ─────────────────────────────────────────────────────────────────────────────

def _run_layer(
    act:   torch.Tensor,
    cfg:   LayerConfig,
    cores: nn.ModuleList,
) -> torch.Tensor:
    """
    Execute one layer and return its trimmed spike output.

    Args:
        act   : (batch, prev_total) — spike tensor from the previous layer
        cfg   : routing and shape descriptor for this layer
        cores : nn.ModuleList of LIFCore objects

    Returns:
        (batch, cfg.total_output) — concatenated, per-core-trimmed spikes
    """
    n_trim = cfg._active_per_core   # neurons to keep per core after trimming
    if cfg.routing == "broadcast":
        outs = [c(act)[:, :n_trim] for c in cores]
    else:                                               # partitioned
        n_in = act.shape[1] // cfg.n_cores
        outs = [
            cores[k](act[:, k * n_in : (k + 1) * n_in])[:, :n_trim]
            for k in range(cfg.n_cores)
        ]
    return torch.cat(outs, dim=1)


def forward_with_internals(
    model: SNNNetwork,
    x:     torch.Tensor,
) -> list[torch.Tensor]:
    """
    Same as model.forward() but returns the output of every layer.

    Args:
        model : SNNNetwork instance
        x     : (batch, n_inputs)

    Returns:
        List of length len(layers), each (batch, layer_i.total_output).
        Index 0 is Layer 0 output; index -1 is the final output.
    """
    act = x
    activations: list[torch.Tensor] = []
    for cfg, cores in zip(model.layer_configs, model._layers):
        act = _run_layer(act, cfg, cores)
        activations.append(act)
    return activations


# ─────────────────────────────────────────────────────────────────────────────
# 9. Accessors  (free functions operating on SNNNetwork)
# ─────────────────────────────────────────────────────────────────────────────

def get_binary_weights(model: SNNNetwork) -> dict[str, list[np.ndarray]]:
    """
    Export all layer weights as binary {0,1} numpy arrays.

    Args:
        model : SNNNetwork instance

    Returns:
        { 'l0': [W_core0, ...], 'l1': [...], ... }
        Each W_coreK has shape (n_in, NEURONS_PER_CORE) uint8.
    """
    return {
        f"l{i}": [c.linear.get_binary_weights() for c in cores]
        for i, cores in enumerate(model._layers)
    }


def get_hardware_params(model: SNNNetwork) -> dict[str, float | int]:
    """
    Read back trained LIF parameters and compute hardware register values.

    The hardware supports only a single global threshold and leak register
    shared across ALL cores.  This function uses Layer 0 Core 0 as the
    representative for those export values.  It also reports the cross-core
    spread so callers can detect and warn about divergence before export.

    Use print_model_summary() to see per-layer min/max breakdowns.

    Args:
        model : SNNNetwork instance

    Returns:
        threshold        : float → representative value; write to nvm_parameter.NEURON_THRESHOLD
        beta             : float   (learned decay factor from L0 C0)
        leak_shift       : int   → write to nvm_parameter.NEURON_LEAK_SHIFT
                                   (= round(-log2(1 - beta)))
        threshold_spread : float → max - min across all cores (0.0 ideal for hardware)
        beta_spread      : float → max - min across all cores (0.0 ideal for hardware)
    """
    ref          = model._layers[0][0].lif    # representative: L0 C0
    threshold    = float(ref.threshold.item())
    beta         = float(ref.beta.item())
    beta_clamped = min(max(beta, 1e-6), 1.0 - 1e-6)
    leak_shift   = int(round(-math.log2(1.0 - beta_clamped)))

    all_cores = [core for cores in model._layers for core in cores]
    all_th    = [float(c.lif.threshold.item()) for c in all_cores]
    all_b     = [float(c.lif.beta.item())      for c in all_cores]

    result = {
        "threshold":        threshold,
        "beta":             beta,
        "leak_shift":       leak_shift,
        "threshold_spread": max(all_th) - min(all_th),
        "beta_spread":      max(all_b)  - min(all_b),
    }

    if getattr(model, "multi_threshold", False):
        # Per-layer mean threshold, rounded to nearest integer (hardware register value)
        result["threshold_per_layer"] = [
            int(round(sum(c.lif.threshold.item() for c in cores) / len(cores)))
            for cores in model._layers
        ]

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 10. LIF parameter override
# ─────────────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def override_lif_params(
    model:      SNNNetwork,
    threshold:  float | list[float] | None = None,
    beta:       float | None               = None,
    leak_shift: int   | None               = None,
):
    """
    Context manager: temporarily override LIF params, restore on exit.

    Saves the current (threshold, beta) of every core, applies the overrides,
    and restores originals on exit — even if an exception is raised.

    threshold can be a scalar (applied to all layers) or a list[float] (one
    value per layer; last value reused for any extra layers).

    leak_shift takes precedence over beta if both are provided
    (beta = 1 - 1/2^leak_shift).

    Note: beta/leak_shift are always applied globally — the hardware has a
    single leak register shared across all cores.

    Args:
        model      : SNNNetwork instance
        threshold  : float  → same threshold for all layers
                     list   → one per layer, last value reused if list is short
                     None   → leave unchanged
        beta       : temporary beta, or None to leave unchanged
        leak_shift : hardware leak register value (overrides beta if provided)

    Example — global override:
        with override_lif_params(model, threshold=2.0, leak_shift=10):
            run_inference(model, x)

    Example — per-layer threshold override:
        with override_lif_params(model, threshold=[3.0, 2.5, 2.0]):
            run_inference(model, x)
    """
    all_cores = [core for cores in model._layers for core in cores]
    snapshot  = [(c.lif.threshold.item(), c.lif.beta.item()) for c in all_cores]

    # Resolve beta from leak_shift if provided (global; hardware has one register)
    if leak_shift is not None:
        beta = 1.0 - 1.0 / (2 ** leak_shift)

    with torch.no_grad():
        # Threshold: scalar → all cores, list → indexed by layer
        if isinstance(threshold, list):
            for i, cores in enumerate(model._layers):
                th = threshold[min(i, len(threshold) - 1)]
                for core in cores:
                    core.lif.threshold.fill_(th)
        elif threshold is not None:
            for core in all_cores:
                core.lif.threshold.fill_(threshold)

        # Beta: always global
        if beta is not None:
            for core in all_cores:
                core.lif.beta.fill_(beta)
    try:
        yield
    finally:
        with torch.no_grad():
            for core, (saved_th, saved_b) in zip(all_cores, snapshot):
                core.lif.threshold.fill_(saved_th)
                core.lif.beta.fill_(saved_b)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Summary printer
# ─────────────────────────────────────────────────────────────────────────────

def print_model_summary(model: SNNNetwork) -> None:
    """
    Print a concise per-layer architecture summary with LIF parameter spread.

    Prints three sections:
      1. Per-layer table: input width, cores, output spikes, parameter count, routing.
      2. Per-layer LIF min/max: threshold and beta range across cores in each layer.
      3. Global hardware export: L0 C0 threshold and leak_shift to write back to
         nvm_parameter.py, plus a WARNING if cross-core spread > 0.01.

    Args:
        model : SNNNetwork instance
    """
    param_counts = {f"l{i}": sum(p.numel() for c in cores for p in c.parameters())
                    for i, cores in enumerate(model._layers)}
    total_params = sum(param_counts.values())

    hw   = get_hardware_params(model)
    prev = model.n_inputs

    print("=" * 85)
    print(f" SNNNetwork  ({len(model.layer_configs)} layers, {total_params:,} total params)")
    print("=" * 85)

    print(f" {'Layer':<15} │ {'Input':>5} → {'Cores':<7} = {'Spikes':>6} │ {'Params':>12} │ {'Routing':<11}")
    print(f" {'─'*15}┼{'─'*23}┼{'─'*14}┼{'─'*11}")
    for i, cfg in enumerate(model.layer_configs):
        name = cfg.label or f"L{i}"
        n_in = (prev // cfg.n_cores) if cfg.routing == "partitioned" else prev
        out  = cfg.total_output
        print(f" {name:<15} │ {n_in:>5} → {cfg.n_cores}×{cfg._active_per_core:<3} "
              f"= {out:>6} │ {param_counts[f'l{i}']:>12,} │ {cfg.routing}")
        prev = out
    print(f" {'─'*15}┴{'─'*23}┴{'─'*14}┴{'─'*11}")
    print(f" {'Total':<15}                                   {total_params:>12,}")
    print()

    print(" LIF Parameters (per-layer min..max):")
    for i, cores in enumerate(model._layers):
        name = model.layer_configs[i].label or f"L{i}"
        ths  = [c.lif.threshold.item() for c in cores]
        bts  = [c.lif.beta.item()      for c in cores]
        print(f"   {name:<13} threshold: {min(ths):.3f}..{max(ths):.3f}"
              f"   beta: {min(bts):.5f}..{max(bts):.5f}")

    print(f"\n Global Hardware Export:")
    print(f"   NEURON_THRESHOLD  = {hw['threshold']:.4f}  (from L0 C0)")
    print(f"   NEURON_LEAK_SHIFT = {hw['leak_shift']}  (from L0 C0, beta={hw['beta']:.5f})")
    if hw["threshold_spread"] > 0.01 or hw["beta_spread"] > 0.001:
        print(f"\n   WARNING: Cross-core param spread detected "
              f"(th: {hw['threshold_spread']:.3f}, beta: {hw['beta_spread']:.4f}).")
        print("            Hardware only supports a single global value for all cores.")
    print("=" * 85)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Factory
# ─────────────────────────────────────────────────────────────────────────────

def build_model(
    layers:          list[LayerConfig]   = None,
    n_inputs:        int                 = DEFAULT_N_INPUTS,
    init_threshold:  float | list[float] = DEFAULT_THRESHOLD,
    init_beta:       float               = DEFAULT_BETA,
    surrogate_slope: float               = 0.6,
    multi_threshold: bool                = False,
) -> SNNNetwork:
    """
    Convenience factory: construct SNNNetwork and move it to the available device.

    Pass a custom `layers` list to sweep topologies, and a list of thresholds
    to give each layer a distinct starting point:

        # Hardware-faithful default (single threshold from nvm_parameter)
        model = build_model()

        # Per-layer initial thresholds (lower threshold for output layer)
        model = build_model(init_threshold=[3.0, 2.5, 2.0])

        # Shallower 2-layer variant (512 = 8 cores × 64)
        model = build_model(layers=[
            LayerConfig(n_neurons=512),
            LayerConfig(n_neurons=256, routing="partitioned", n_active=240),
        ])

    Args:
        layers          : topology (None → HARDWARE_LAYERS)
        n_inputs        : input feature width (default DEFAULT_N_INPUTS = 256)
        init_threshold  : initial LIF threshold, learned during training.
                          Float → same threshold for all layers.
                          List[float] → one per layer; last value reused if list
                          is shorter than the number of layers.
                          Default: DEFAULT_THRESHOLD (= nvm_parameter.NEURON_THRESHOLD).
        init_beta       : initial leak factor (learned; derived from NEURON_LEAK_SHIFT)
        surrogate_slope : slope for fast_sigmoid surrogate gradient

    Returns:
        SNNNetwork moved to CUDA if available, else CPU.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model  = SNNNetwork(n_inputs, layers, init_threshold, init_beta, surrogate_slope,
                        multi_threshold=multi_threshold)
    return model.to(device)
