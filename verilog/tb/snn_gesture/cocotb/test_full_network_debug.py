"""
Phase 7 Debug: Single-Gesture Recognition — Hardware vs Reference Model
File: verilog/tb/test_full_network_debug.py

Runs hardware inference alongside the Python reference model in lock-step,
logging mismatches at group and core granularity.

Run:
    cd verilog/tb && make MODULE=test_full_network_debug SIM=icarus

Voting: interleaved i%NUM_CLASS (matches training and snn_reference_model.classify()).
Stimuli: [0, 256] scale — regenerate with:
    python training/export_stimuli.py --input-scale 256 --num-samples 100

Verbosity flags (edit before running):
    VERBOSE_INJECTION = False   # per-injection detail (very slow; use for single-core debug)
    VERBOSE_GROUP     = True    # per-group potential mismatch after each picture_done
    VERBOSE_CORE      = True    # full spike vector + mismatch count at each core boundary
"""

import sys
import os
from pathlib import Path

# Add paths to hardware utilities and parameters
PWD = Path(__file__).resolve().parent
sys.path.insert(0, str(PWD.parent))          # for nvm_parameter.py
sys.path.insert(0, str(PWD.parent / "utils")) # for snn_test_utils.py

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

from read_file     import read_matrix_from_file, list_to_binary
from nvm_parameter import (
    NUM_AXON_LAYER_0, NUM_AXON_LAYER_1, NUM_AXON_LAYER_2,
    NUM_CORES_LAYER_0, NUM_CORES_LAYER_1, NUM_CORES_LAYER_2,
    NUM_NEURONS_LAYER_0, NUM_NEURONS_LAYER_1,
    NUM_STIMULI_WORD, NUM_VOTES, NUM_CLASS,
    SPIKE_LO, SPIKE_HI, PD, NEURON_THRESHOLD, MEM_BASE_DIR
)
from snn_test_utils import (
    setup_dut, nvm_program, nvm_inject, pd_write, wb_read,
    spikes_from_readback, get_potential,
)
from snn_reference_model import (
    make_core, reset_core, program_core, inject as ref_inject,
    picture_done as ref_picture_done,
    stimuli_from_val_col,
)
from snn_hw_utils import interleaved_vote, interleaved_vote_counts
from test_full_network import load_all_weights

# ---------------------------------------------------------------------------
# Verbosity flags
# ---------------------------------------------------------------------------
VERBOSE_INJECTION = False
VERBOSE_GROUP     = True
VERBOSE_CORE      = True

# ---------------------------------------------------------------------------
# Data loader (load once, shared across tests)
# ---------------------------------------------------------------------------
_loaded        = False
_conn_mats     = {}
_stimuli_lines = []
_tb_correct    = []


def _ensure_data():
    global _loaded, _conn_mats, _stimuli_lines, _tb_correct
    if _loaded:
        return
    _conn_mats = load_all_weights()
    with open(MEM_BASE_DIR / "stimuli/stimuli.txt") as f:
        for i, line in enumerate(f):
            if i >= NUM_STIMULI_WORD:   # only first gesture (pic 0)
                break
            _stimuli_lines.append(list_to_binary([int(c) for c in line.strip()]))
    tc = read_matrix_from_file(MEM_BASE_DIR / "testbench/tb_correct.txt")
    _tb_correct.append(list_to_binary(tc[0]))
    _loaded = True


# ---------------------------------------------------------------------------
# Hardware + reference model inference helpers
# ---------------------------------------------------------------------------

async def _hw_program_core(dut, connection_data, num_neuron_layer, ref_core):
    """Program hardware AND reference core with the same connection data."""
    for row in range(32):
        for col in range(32):
            axon        = (row & 0x07) * 32 + col
            neuron_base = ((row >> 3) & 0x03) * 16
            val_slice   = connection_data[axon][
                num_neuron_layer - (neuron_base + 16) : num_neuron_layer - neuron_base
            ]
            data16 = list_to_binary(val_slice)
            await nvm_program(dut, row, col, data16)
            # Program reference core using the same connection matrix
            program_core(ref_core, connection_data)   # program_core handles all rows/cols at once
    # Note: program_core() is called once per core (it loops internally).
    # Re-program ref_core from the connection matrix directly for accuracy.


async def _hw_program_core_v2(dut, connection_data, num_neuron_layer, ref_core):
    """Program hardware row-by-row; feed the same data to the reference core."""
    # Reset reference core before programming
    reset_core(ref_core)
    program_core(ref_core, connection_data)   # reference does all rows at once

    # Program hardware row-by-row (required by cocotb/RTL interface)
    for row in range(32):
        for col in range(32):
            axon        = (row & 0x07) * 32 + col
            neuron_base = ((row >> 3) & 0x03) * 16
            val_slice   = connection_data[axon][
                num_neuron_layer - (neuron_base + 16) : num_neuron_layer - neuron_base
            ]
            data16 = list_to_binary(val_slice)
            await nvm_program(dut, row, col, data16)


async def _hw_run_core_inference(dut, layer, core_idx, stimuli_in, ref_core,
                                  pic=0, pad_override=None):
    """
    Run one core inference on hardware while mirroring every inject/picture_done
    to the Python reference core.

    Returns (hw_spikes_64, ref_spikes_64, mismatch_list)
    """
    # Reset reference spike accumulator
    for i in range(64):
        ref_core["spikes"][i] = 0

    for row in range(32):
        for col in range(32):
            axon   = (row & 0x07) * 32 + col
            active = False
            val    = 0

            if layer == 0:
                if pad_override is not None and axon >= NUM_AXON_LAYER_0:
                    val = pad_override; active = True
                else:
                    word_idx = pic * NUM_STIMULI_WORD + axon // 2
                    word_val = _stimuli_lines[word_idx] if word_idx < len(_stimuli_lines) else 0
                    val      = (word_val >> 16) & 0xFFFF if axon % 2 == 0 else word_val & 0xFFFF
                    active   = True
            elif layer == 1:
                if axon < NUM_AXON_LAYER_1:
                    idx = core_idx * NUM_AXON_LAYER_1 + axon
                    if stimuli_in[pic][idx] == 1:
                        active = True; val = 1
            elif layer == 2:
                if axon < NUM_AXON_LAYER_2:
                    if stimuli_in[pic][axon] == 1:
                        active = True; val = 1

            if active:
                await nvm_inject(dut, row, col, val)
                ref_inject(ref_core, row, col, val)

                if VERBOSE_INJECTION:
                    hw_pots  = [get_potential(dut, i) for i in range(16)]
                    ref_pots = list(ref_core["potential"])
                    misses   = [(i, hw_pots[i], ref_pots[i])
                                for i in range(16) if hw_pots[i] != ref_pots[i]]
                    if misses:
                        sv = stimuli_from_val_col(val, col)
                        dut._log.warning(
                            f"  inject row={row} col={col} axon={axon} val={val} "
                            f"stimuli={sv} POTENTIAL MISMATCH: {misses}"
                        )

            # picture_done at end of each group of 8 rows
            if col == 31:
                group = {7: 0, 15: 1, 23: 2, 31: 3}.get(row)
                if group is not None:
                    hw_pots_pre  = [get_potential(dut, i) for i in range(16)]
                    ref_pots_pre = list(ref_core["potential"])

                    await pd_write(dut, PD[group])
                    ref_picture_done(ref_core, group)

                    if VERBOSE_GROUP:
                        hw_spk  = [1 if hw_pots_pre[i]  >= NEURON_THRESHOLD else 0 for i in range(16)]
                        ref_spk = ref_core["spikes"][group * 16 : (group + 1) * 16]
                        pot_mm  = [(i, hw_pots_pre[i], ref_pots_pre[i])
                                   for i in range(16) if hw_pots_pre[i] != ref_pots_pre[i]]
                        dut._log.info(
                            f"  Group {group}: HW spikes={sum(hw_spk)}/16 "
                            f"REF spikes={sum(ref_spk)}/16 "
                            f"pot_mismatches={len(pot_mm)}"
                        )
                        if pot_mm:
                            dut._log.warning(f"    Potential mismatch detail: {pot_mm}")

    lo = await wb_read(dut, SPIKE_LO)
    hi = await wb_read(dut, SPIKE_HI)
    hw_spikes  = spikes_from_readback(lo, hi)
    ref_spikes = list(ref_core["spikes"])

    mismatches = [(i, hw_spikes[i], ref_spikes[i])
                  for i in range(64) if hw_spikes[i] != ref_spikes[i]]
    return hw_spikes, ref_spikes, mismatches


# ---------------------------------------------------------------------------
# Voting helper — delegates to snn_hw_utils (single source of truth)
# ---------------------------------------------------------------------------

def _votes_and_class(spikes_240):
    """Interleaved majority vote: neuron i → class (i % NUM_CLASS)."""
    votes = interleaved_vote_counts(spikes_240, NUM_CLASS)
    return interleaved_vote(spikes_240, NUM_CLASS), votes


# ---------------------------------------------------------------------------
# Main debug test
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_gesture_1_hardware_vs_model(dut):
    """Verbose single-gesture (pic=0) debug: HW vs Python reference model.

    For each layer/core:
      1. Program HW and reference with identical weights
      2. Log connection density
      3. Run inference with per-injection (optional) and per-group logging
      4. Compare full 64-bit spike vector HW vs reference
    Final: interleaved majority vote; assert HW matches ground truth.
    """
    _ensure_data()
    await setup_dut(dut)

    # One shared core state dict — reset and reprogram before each core
    ref_core = make_core()

    spike_l0_hw  = [[0] * NUM_NEURONS_LAYER_0]
    spike_l0_ref = [[0] * NUM_NEURONS_LAYER_0]
    spike_l1_hw  = [[0] * NUM_NEURONS_LAYER_1]
    spike_l1_ref = [[0] * NUM_NEURONS_LAYER_1]
    spike_l2_hw  = [[0] * NUM_VOTES]
    spike_l2_ref = [[0] * NUM_VOTES]

    total_layer_mismatches = {0: 0, 1: 0, 2: 0}

    # ── Layer 0 — 13 cores ─────────────────────────────────────────────────
    dut._log.info("=" * 60)
    dut._log.info("LAYER 0 — 13 cores (256 axons → 832 spikes)")
    dut._log.info("=" * 60)

    for core in range(NUM_CORES_LAYER_0):
        conn_data = _conn_mats[core]
        reset_core(ref_core)

        ones    = sum(b for row in conn_data for b in row)
        total   = sum(len(row) for row in conn_data)
        density = ones / total if total else 0.0
        dut._log.info(f"[L0 core {core:2d}] density={density:.3f}  programming HW + ref ...")

        await _hw_program_core_v2(dut, conn_data, 64, ref_core)
        hw_sp, ref_sp, mm = await _hw_run_core_inference(
            dut, 0, core, _stimuli_lines, ref_core, pic=0,
        )

        for i in range(64):
            spike_l0_hw[0][core * 64 + i]  = hw_sp[i]
            spike_l0_ref[0][core * 64 + i] = ref_sp[i]

        if VERBOSE_CORE:
            dut._log.info(f"  HW  {sum(hw_sp):3d}/64  {hw_sp}")
            dut._log.info(f"  REF {sum(ref_sp):3d}/64  {ref_sp}")

        if mm:
            total_layer_mismatches[0] += len(mm)
            dut._log.warning(
                f"  [L0 core {core}] MISMATCH {len(mm)}/64: {mm[:8]}"
                + (" ..." if len(mm) > 8 else "")
            )
        else:
            dut._log.info(f"  [L0 core {core}] HW == REF  OK")

    dut._log.info(
        f"L0 summary: HW={sum(spike_l0_hw[0])}/832  "
        f"REF={sum(spike_l0_ref[0])}/832  mismatches={total_layer_mismatches[0]}"
    )

    # ── Layer 1 — 4 cores ─────────────────────────────────────────────────
    dut._log.info("=" * 60)
    dut._log.info("LAYER 1 — 4 cores (208 axons/core → 256 spikes)")
    dut._log.info("=" * 60)

    _L1_OFFSET = NUM_CORES_LAYER_0  # = 13
    for core in range(NUM_CORES_LAYER_1):
        conn_data = _conn_mats[_L1_OFFSET + core]
        reset_core(ref_core)

        ones    = sum(b for row in conn_data for b in row)
        total   = sum(len(row) for row in conn_data)
        density = ones / total if total else 0.0
        l1_active = sum(spike_l0_hw[0][core * NUM_AXON_LAYER_1 : (core + 1) * NUM_AXON_LAYER_1])
        dut._log.info(
            f"[L1 core {core:2d}] density={density:.3f}  "
            f"L1 input HW active: {l1_active}/{NUM_AXON_LAYER_1}"
        )

        await _hw_program_core_v2(dut, conn_data, 64, ref_core)
        hw_sp, ref_sp, mm = await _hw_run_core_inference(
            dut, 1, core, spike_l0_hw, ref_core, pic=0,
        )

        for i in range(64):
            spike_l1_hw[0][core * 64 + i]  = hw_sp[i]
            spike_l1_ref[0][core * 64 + i] = ref_sp[i]

        if VERBOSE_CORE:
            dut._log.info(f"  HW  {sum(hw_sp):3d}/64  {hw_sp}")
            dut._log.info(f"  REF {sum(ref_sp):3d}/64  {ref_sp}")

        if mm:
            total_layer_mismatches[1] += len(mm)
            dut._log.warning(
                f"  [L1 core {core}] MISMATCH {len(mm)}/64: {mm[:8]}"
                + (" ..." if len(mm) > 8 else "")
            )
        else:
            dut._log.info(f"  [L1 core {core}] HW == REF  OK")

    dut._log.info(
        f"L1 summary: HW={sum(spike_l1_hw[0])}/256  "
        f"REF={sum(spike_l1_ref[0])}/256  mismatches={total_layer_mismatches[1]}"
    )

    # ── Layer 2 — 4 cores, 60 active outputs per core ─────────────────────
    dut._log.info("=" * 60)
    dut._log.info("LAYER 2 — 4 cores (256 axons → 240 spikes, 60/core)")
    dut._log.info("=" * 60)

    _L2_OFFSET = NUM_CORES_LAYER_0 + NUM_CORES_LAYER_1  # = 17
    _ACTIVE_PER_CORE = NUM_VOTES // NUM_CORES_LAYER_2    # = 60
    dut._log.info(f"  L2 input (HW L1 spikes total): {sum(spike_l1_hw[0])}/256")

    for core in range(NUM_CORES_LAYER_2):
        conn_data = _conn_mats[_L2_OFFSET + core]
        reset_core(ref_core)

        ones    = sum(b for row in conn_data for b in row)
        total   = sum(len(row) for row in conn_data)
        density = ones / total if total else 0.0
        dut._log.info(f"[L2 core {core:2d}] density={density:.3f}  programming HW + ref ...")

        await _hw_program_core_v2(dut, conn_data, 64, ref_core)
        hw_sp, ref_sp, mm = await _hw_run_core_inference(
            dut, 2, core, spike_l1_hw, ref_core, pic=0,
        )

        for i in range(_ACTIVE_PER_CORE):
            spike_l2_hw[0][core * _ACTIVE_PER_CORE + i]  = hw_sp[i]
            spike_l2_ref[0][core * _ACTIVE_PER_CORE + i] = ref_sp[i]

        if VERBOSE_CORE:
            dut._log.info(f"  HW  {sum(hw_sp[:60]):3d}/60  {hw_sp[:60]}")
            dut._log.info(f"  REF {sum(ref_sp[:60]):3d}/60  {ref_sp[:60]}")

        if mm:
            total_layer_mismatches[2] += len(mm)
            dut._log.warning(
                f"  [L2 core {core}] MISMATCH {len(mm)}/64: {mm[:8]}"
                + (" ..." if len(mm) > 8 else "")
            )
        else:
            dut._log.info(f"  [L2 core {core}] HW == REF  OK")

    # ── Classification — interleaved majority vote ─────────────────────────
    dut._log.info("=" * 60)
    dut._log.info("CLASSIFICATION — interleaved i%NUM_CLASS voting")
    dut._log.info("=" * 60)

    hw_pred,  hw_votes  = _votes_and_class(spike_l2_hw[0])
    ref_pred, ref_votes = _votes_and_class(spike_l2_ref[0])
    gt = _tb_correct[0]

    dut._log.info(f"Ground truth: class {gt}")
    dut._log.info(f"HW  prediction: class {hw_pred}  ({'PASS' if hw_pred == gt else 'FAIL'})")
    dut._log.info(f"REF prediction: class {ref_pred} ({'PASS' if ref_pred == gt else 'FAIL'})")
    dut._log.info(f"HW  votes ({NUM_CLASS} classes): {hw_votes}")
    dut._log.info(f"REF votes ({NUM_CLASS} classes): {ref_votes}")
    dut._log.info(f"HW-REF vote delta: {[hw_votes[c] - ref_votes[c] for c in range(NUM_CLASS)]}")
    dut._log.info(
        f"Total layer mismatches — L0:{total_layer_mismatches[0]}  "
        f"L1:{total_layer_mismatches[1]}  L2:{total_layer_mismatches[2]}"
    )

    assert hw_pred == gt, (
        f"Gesture 0 FAILED: expected class {gt}, got {hw_pred}. "
        f"Layer mismatches: {total_layer_mismatches}. "
        f"Enable VERBOSE_GROUP/VERBOSE_INJECTION for per-injection details."
    )
    dut._log.info("test_gesture_1_hardware_vs_model PASSED")
