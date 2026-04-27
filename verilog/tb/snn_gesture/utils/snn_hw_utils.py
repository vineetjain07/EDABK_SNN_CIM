"""
Shared hardware-contract utilities for the SNN neuromorphic core.

This module is the single source of truth for two hardware rules that must
be identical across all three implementation levels:
  - PyTorch training   (train_dvs128.py, validate_reference_model.py)
  - Python reference   (snn_reference_model.py)
  - cocotb RTL tests   (test_full_network_debug.py)

If either rule is defined in more than one place, a divergence will silently
cause HW/SW accuracy gaps (Root Cause 1 in hw_sw_accuracy_gap_rca.md).

Hardware rules implemented
--------------------------
1. Interleaved majority vote  — neuron i votes for class (i % NUM_CLASS).
   Hardware RTL scheduler assigns output neurons in round-robin order.

2. Axon sign encoding         — odd-indexed axons negate the stimulus.
   RTL: weight_type = col[0]; stimuli = weight_type ? -val : +val
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# 1. Interleaved majority vote — plain Python (reference model, cocotb)
# ─────────────────────────────────────────────────────────────────────────────

def interleaved_vote(spikes: list[int], num_class: int) -> int:
    """
    Classify a single spike vector using interleaved round-robin voting.

    Neuron i votes for class (i % num_class). This matches the hardware RTL
    scheduler exactly.

    Args:
        spikes    : flat list of 0/1 spike values (length = NUM_VOTES)
        num_class : number of output classes (NUM_CLASS = 12)

    Returns:
        Predicted class index (0 … num_class-1).
    """
    votes = [0] * num_class
    for i, s in enumerate(spikes):
        if s:
            votes[i % num_class] += 1
    return votes.index(max(votes))


def interleaved_vote_counts(spikes: list[int], num_class: int) -> list[int]:
    """
    Return the per-class vote tally (useful for debug logging).

    Args:
        spikes    : flat list of 0/1 spike values
        num_class : number of output classes

    Returns:
        List of length num_class — vote count per class.
    """
    votes = [0] * num_class
    for i, s in enumerate(spikes):
        if s:
            votes[i % num_class] += 1
    return votes


def interleaved_accuracy(preds: list[int], labels: list[int]) -> float:
    """
    Accuracy over a list of predictions and ground-truth labels.

    Args:
        preds  : predicted class indices
        labels : ground-truth class indices

    Returns:
        Fraction correct in [0.0, 1.0].
    """
    n = min(len(preds), len(labels))
    if n == 0:
        return 0.0
    return sum(p == l for p, l in zip(preds[:n], labels[:n])) / n


# ─────────────────────────────────────────────────────────────────────────────
# 2. Interleaved majority vote — PyTorch (training, validation)
# ─────────────────────────────────────────────────────────────────────────────

def interleaved_logits(output, num_class: int):
    """
    Compute per-class vote sums from a batch of spike tensors (PyTorch).

    Equivalent to interleaved_vote() but operates on batched float tensors
    for use with cross-entropy loss and argmax classification during training.

    Args:
        output    : (batch, N_OUTPUT) spike tensor — raw or soft spikes
        num_class : number of output classes (NUM_CLASS = 12)

    Returns:
        (batch, num_class) logit tensor — sum of each class's votes.
    """
    import torch
    return torch.stack(
        [output[:, c::num_class] for c in range(num_class)], dim=1
    ).sum(dim=2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Axon sign encoding — hardware contract
# ─────────────────────────────────────────────────────────────────────────────

def axon_is_inhibitory(axon_idx: int) -> bool:
    """
    Return True if axon_idx carries an inhibitory (negated) stimulus.

    Hardware rule: weight_type = col[0] (LSB of column index within macro).
    Since axon_idx maps to a column by axon_idx % 32 inside each macro group,
    and col = axon_idx % 32, the parity is simply axon_idx % 2.

    This is the single authoritative definition for:
      - snn_model.py  : axon_sign = 1 - 2*(arange(n_in) % 2)
      - snn_reference_model.py : stimuli_from_val_col — col & 1

    Args:
        axon_idx : 0-based axon index

    Returns:
        True  → stimulus should be negated (odd axon)
        False → stimulus passes through (even axon)
    """
    return bool(axon_idx % 2)


def axon_sign_vector(n_axons: int):
    """
    Build a float sign vector (+1 / -1) for vectorised stimulus encoding.

    Matches the register_buffer in snn_model.py:LIFCore:
        axon_sign = 1.0 - 2.0 * (torch.arange(n_in) % 2).float()

    Args:
        n_axons : number of input axons

    Returns:
        list[float] — +1.0 for even indices, -1.0 for odd indices.
    """
    return [1.0 if i % 2 == 0 else -1.0 for i in range(n_axons)]


# ─────────────────────────────────────────────────────────────────────────────
# 4. nvm_parameter.py loader — single source of truth for hardware constants
# ─────────────────────────────────────────────────────────────────────────────

def load_nvm_parameter(override_path=None):
    """
    Load nvm_parameter.py and return it as a module.

    Resolution order:
      1. NVM_PARAMETER_PATH env var (allows CI/test overrides)
      2. override_path argument
      3. nvm_parameter.py in the same directory as this file (verilog/tb/)

    Since this file lives in verilog/tb/, option 3 always resolves correctly
    regardless of which file calls load_nvm_parameter() — __file__ here refers
    to snn_hw_utils.py, not the caller.

    This replaces the 4-line importlib boilerplate that was duplicated across:
      training/snn_model.py, training/dvs128_dataset.py,
      training/export_weights.py, training/export_stimuli.py,
      verilog/tb/snn_reference_model.py, verilog/tb/read_file.py

    Args:
        override_path : str | Path | None — explicit path to nvm_parameter.py

    Returns:
        Loaded module with all hardware constants as attributes.
    """
    env = os.environ.get("NVM_PARAMETER_PATH")
    p = Path(env if env else (override_path if override_path else
             Path(__file__).resolve().parent.parent / "nvm_parameter.py"))
    spec = importlib.util.spec_from_file_location("nvm_parameter", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
