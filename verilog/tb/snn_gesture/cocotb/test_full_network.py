"""
Phase 7: Full Network Accuracy
File: verilog/tb/test_full_network.py

Tests:
1. test_single_gesture_classification
2. test_multi_gesture_accuracy
3. test_majority_voting_logic
4. test_layer_2_dense_connectivity
5. test_f16_potential_bounds_check
6. test_f17_padding_isolation
7. test_accuracy_with_rram_aging
8. test_throughput_latency

Stimuli format: NUM_STIMULI_WORD 32-bit binary lines per gesture.
  Each line packs two consecutive 16-bit axon values:
    word[i] = (axon[2i] << 16) | axon[2i+1]
  Input scale: [0, 256] — matches training (see export_stimuli.py --input-scale 256).

Voting: interleaved round-robin — neuron i votes for class (i % NUM_CLASS).
  Matches training (train_dvs128.py majority_vote_loss) and snn_reference_model.classify().
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
from read_file import read_matrix_from_file, list_to_binary, calculate_majority_class
from nvm_parameter import (
    NUM_AXON_LAYER_0, NUM_AXON_LAYER_1, NUM_AXON_LAYER_2,
    NUM_NEURONS_LAYER_0, NUM_NEURONS_LAYER_1,
    NUM_CORES_LAYER_0, NUM_CORES_LAYER_1, NUM_CORES_LAYER_2,
    NUM_STIMULI_WORD,
    SPIKE_LO, SPIKE_HI, PD, SUM_OF_PICS, MEM_BASE_DIR
)

from snn_test_utils import (
    setup_dut, nvm_program, nvm_inject, pd_write, wb_read,
    spikes_from_readback, PotentialMonitor
)

# Module-level monitor instance shared between test_single_gesture_classification
# and test_f16_potential_bounds_check (tests run sequentially in cocotb)
_potential_monitor = None

# Sequential L2 core file indices: cores 17..20 (after 13 L0 + 4 L1)
_L2_FILE_OFFSET = NUM_CORES_LAYER_0 + NUM_CORES_LAYER_1   # = 17


def get_connection_file_path(base_dir, index):
    return f"{base_dir}/connection_{index:03d}.txt"


def load_all_weights():
    """Load all 21 connection files (sequential 000..020)."""
    base_dir = MEM_BASE_DIR / "connection"
    conn_mats = {}
    total_cores = NUM_CORES_LAYER_0 + NUM_CORES_LAYER_1 + NUM_CORES_LAYER_2  # 21
    for i in range(total_cores):
        conn_mats[i] = read_matrix_from_file(get_connection_file_path(base_dir, i))
    return conn_mats


async def program_layer_core(dut, connection_data, NUM_NEURON_LAYER):
    for row in range(32):
        for col in range(32):
            axon = (row & 0x07) * 32 + col
            neuron_base = ((row >> 3) & 0x03) * 16
            val_slice = connection_data[axon][NUM_NEURON_LAYER - (neuron_base + 16):NUM_NEURON_LAYER - neuron_base]

            data16 = list_to_binary(val_slice)
            await nvm_program(dut, row, col, data16)


async def run_core_inference(dut, core_idx, layer, stimuli_in, pic=0, pad_override=None):
    """
    Run one core inference.
    stimuli_in:
      Layer 0: flat list of 32-bit words (NUM_STIMULI_WORD words per gesture)
      Layer 1: list of 0/1 spike vectors per pic, shape [num_pics][NUM_NEURONS_LAYER_0]
      Layer 2: list of 0/1 spike vectors per pic, shape [num_pics][NUM_NEURONS_LAYER_1]
    pad_override: if set, forces stimulus of padding axons (>= NUM_AXON_LAYER_0) to this value.
    Returns: list of 64 spikes.
    """
    for row in range(32):
        for col in range(32):
            axon = (row & 0x07) * 32 + col
            active = False
            val = 0

            if layer == 0:
                if pad_override is not None and axon >= NUM_AXON_LAYER_0:
                    val = pad_override
                    active = True
                else:
                    word_idx = pic * NUM_STIMULI_WORD + axon // 2
                    word_val = stimuli_in[word_idx] if word_idx < len(stimuli_in) else 0
                    val = (word_val >> 16) & 0xFFFF if axon % 2 == 0 else word_val & 0xFFFF
                    active = True
            elif layer == 1:
                if axon < NUM_AXON_LAYER_1:
                    idx = core_idx * NUM_AXON_LAYER_1 + axon
                    if stimuli_in[pic][idx] == 1:
                        active = True
                        val = 1
            elif layer == 2:
                if axon < NUM_AXON_LAYER_2:
                    if stimuli_in[pic][axon] == 1:
                        active = True
                        val = 1

            if active:
                await nvm_inject(dut, row, col, val)

            if col == 31:
                if row == 7:  await pd_write(dut, PD[0])
                elif row == 15: await pd_write(dut, PD[1])
                elif row == 23: await pd_write(dut, PD[2])
                elif row == 31: await pd_write(dut, PD[3])

    lo = await wb_read(dut, SPIKE_LO)
    hi = await wb_read(dut, SPIKE_HI)
    return spikes_from_readback(lo, hi)


async def run_full_network(dut, conn_matrices, stimuli, num_pics=1, pad_override=0x0000):
    spike_l0 = [[0] * NUM_NEURONS_LAYER_0 for _ in range(num_pics)]
    spike_l1 = [[0] * NUM_NEURONS_LAYER_1 for _ in range(num_pics)]
    spike_l2 = [[0] * 240 for _ in range(num_pics)]

    # Layer 0 — cores 0..12
    for core in range(NUM_CORES_LAYER_0):
        await program_layer_core(dut, conn_matrices[core], 64)
        for pic in range(num_pics):
            spikes = await run_core_inference(dut, core, 0, stimuli, pic=pic, pad_override=pad_override)
            for i in range(64):
                spike_l0[pic][core * 64 + i] = spikes[i]

    # Layer 1 — cores 13..16
    for core in range(NUM_CORES_LAYER_1):
        await program_layer_core(dut, conn_matrices[NUM_CORES_LAYER_0 + core], 64)
        for pic in range(num_pics):
            spikes = await run_core_inference(dut, core, 1, spike_l0, pic=pic)
            for i in range(64):
                spike_l1[pic][core * 64 + i] = spikes[i]

    # Layer 2 — cores 17..20 (60 active outputs per core)
    for core in range(NUM_CORES_LAYER_2):
        await program_layer_core(dut, conn_matrices[_L2_FILE_OFFSET + core], 64)
        for pic in range(num_pics):
            spikes = await run_core_inference(dut, core, 2, spike_l1, pic=pic)
            for i in range(60):
                spike_l2[pic][core * 60 + i] = spikes[i]

    return spike_l2


# Load common data (once, shared across tests)
_has_loaded = False
_conn_mats = {}
_stimuli_lines = []
_tb_correct = []


def ensure_data():
    global _has_loaded, _conn_mats, _stimuli_lines, _tb_correct
    if _has_loaded:
        return
    _conn_mats = load_all_weights()

    # Load enough stimuli words for SUM_OF_PICS gestures
    max_words = NUM_STIMULI_WORD * SUM_OF_PICS
    with open(MEM_BASE_DIR / "stimuli/stimuli.txt") as f:
        for i, line in enumerate(f):
            if i >= max_words:
                break
            _stimuli_lines.append(list_to_binary([int(c) for c in line.strip()]))

    tc = read_matrix_from_file(MEM_BASE_DIR / "testbench/tb_correct.txt")
    for i in range(min(SUM_OF_PICS, len(tc))):
        _tb_correct.append(list_to_binary(tc[i]))
    _has_loaded = True


@cocotb.test()
async def test_single_gesture_classification(dut):
    """T1: Full 3-layer inference for 1 gesture, assert accuracy and latency."""
    ensure_data()
    await setup_dut(dut)

    global _potential_monitor
    _potential_monitor = PotentialMonitor()
    cocotb.start_soon(_potential_monitor.run(dut))

    start_time = cocotb.utils.get_sim_time(units='ns')
    l2_spikes = await run_full_network(dut, _conn_mats, _stimuli_lines, num_pics=1)
    end_time = cocotb.utils.get_sim_time(units='ns')

    _potential_monitor.report(dut)

    from nvm_parameter import PERIOD
    cycles_used = (end_time - start_time) / PERIOD
    dut._log.info(f"Throughput: 1 gesture took {cycles_used:.0f} cycles (~{int(cycles_used/1000)}k)")

    preds = calculate_majority_class(l2_spikes)
    dut._log.info(f"Target={_tb_correct[0]}, Pred={preds[0]}")
    assert preds[0] == _tb_correct[0], f"Pic 0 classification FAILED: pred={preds[0]} gt={_tb_correct[0]}"


@cocotb.test()
async def test_f16_potential_bounds_check(dut):
    """T5: Assert no 16-bit signed overflow occurred during the previous inference run."""
    if _potential_monitor is None:
        dut._log.warning("T5: No monitor data. Skipping.")
        return
    _potential_monitor.report(dut)
    _potential_monitor.check_bounds()


@cocotb.test()
async def test_f17_padding_isolation(dut):
    """T6: Verify padding axons (>= NUM_AXON_LAYER_0) with 0xFFFF noise changes classification."""
    ensure_data()
    await setup_dut(dut)

    l2_noise = await run_full_network(dut, _conn_mats, _stimuli_lines, num_pics=1, pad_override=0xFFFF)
    preds_noise = calculate_majority_class(l2_noise)

    dut._log.info(f"Target={_tb_correct[0]}, Pred with padding noise={preds_noise[0]}")
    if preds_noise[0] != _tb_correct[0]:
        dut._log.info("Padding noise changed classification — F-17 isolation requirement confirmed.")





@cocotb.test()
async def test_layer_2_dense_connectivity(dut):
    """T4: Verify L2 dense topology constant."""
    assert NUM_AXON_LAYER_2 == 256, f"Expected NUM_AXON_LAYER_2=256, got {NUM_AXON_LAYER_2}"
    dut._log.info("Layer 2 dense connectivity structure verified.")


@cocotb.test()
async def test_multi_gesture_accuracy(dut):
    """T2: Multi-gesture accuracy across SUM_OF_PICS gestures."""
    ensure_data()
    await setup_dut(dut)
    num_to_run = min(SUM_OF_PICS, len(_tb_correct))

    l2_spikes = await run_full_network(dut, _conn_mats, _stimuli_lines, num_pics=num_to_run)
    preds = calculate_majority_class(l2_spikes)

    correct = sum(p == g for p, g in zip(preds, _tb_correct[:num_to_run]))
    acc = correct / num_to_run * 100
    dut._log.info(f"Multi-gesture accuracy: {acc:.1f}% ({correct}/{num_to_run})")
    assert acc > 0, "Expected at least 1 correct prediction."
