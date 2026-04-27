"""
Phase 2: ReRAM Synapse Matrix — Program & Read-back
DUT: nvm_neuron_core_256x64 (top-level, sim baseline)

Run: cd verilog/tb && make MODULE=test_synapse_matrix SIM=icarus

Tests:
  T1  - test_program_single_cell      : program known pattern, read back, verify dat_o[15:0]
  T2  - test_program_all_ones         : data=0xFFFF → all 16 macros store 1
  T3  - test_program_all_zeros        : data=0x0000 → all 16 macros store 0
  T4  - test_program_alternating      : 0xAAAA and 0x5555 at adjacent cells, cross-check
  T5  - test_program_multiple_locations : 4 cells with distinct patterns, no aliasing
  T6  - test_overwrite_cell           : write A then B at same cell → readback = B
  T7  - test_full_row_program         : all 32 cols in row 0, unique pattern per col
  T8  - test_timing_early_readback    : READ before WR_Dly+RD_Dly → 0xDEAD_C0DE; after → correct
  T9  - test_dead_code_empty_fifo     : WB READ with empty op_fifo → ACK=1, dat_o=0xDEAD_C0DE
  T10 - test_connection_bit_mapping   : each macro bit set independently, verify bit isolation

RTL constraints (from code review of nvm_synapse_matrix.v / Neuromorphic_X1_Beh.v):
  - Row/col are in dat_i[29:20]; WB address only selects the submodule via decoder
  - All 16 X1 instances share ADDR_MATCH=0x3000_000C (hardcoded in nvm_synapse_matrix)
  - Readback: wbs_dat_o[i] = slave_dat_o[i][0] for i in [0:15], dat_o[31:16] = 0
  - Empty op_fifo read: ACK=1 + dat_o=0xDEAD_C0DE (not silent!)
  - PROGRAM ACK is suppressed at top level via wbs_we_i_reversed — use nvm_write()
  - nvm_read() drives the bus but does NOT capture dat_o — sample it explicitly
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
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, Timer
from nvm_parameter import MODE_PROGRAM, MODE_READ, WR_Dly, RD_Dly, SYNAPSE_ADDR
from snn_test_utils import setup_dut, nvm_program

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEAD_C0DE = 0xDEAD_C0DE


# ---------------------------------------------------------------------------
# Synapse-matrix-specific helpers
# ---------------------------------------------------------------------------
def make_program_packet(row, col, data16):
    """Build 32-bit PROGRAM packet: {MODE_PROGRAM[1:0], row[4:0], col[4:0], 4'b0, data[15:0]}"""
    assert 0 <= row <= 31, f"row {row} out of range"
    assert 0 <= col <= 31, f"col {col} out of range"
    assert 0 <= data16 <= 0xFFFF, f"data16 {data16:#06x} out of range"
    return (MODE_PROGRAM << 30) | (row << 25) | (col << 20) | data16


def make_read_packet(row, col, stimuli16=0):
    """Build 32-bit READ (stimuli inject) packet."""
    assert 0 <= row <= 31
    assert 0 <= col <= 31
    return (MODE_READ << 30) | (row << 25) | (col << 20) | (stimuli16 & 0xFFFF)


async def nvm_read_cell(dut, row, col, stimuli16=0):
    """
    Issue a READ command (stimuli inject via WB WRITE with MODE_READ),
    wait RD_Dly for the result to land in op_fifo, then issue a WB READ
    to pop it and return the 32-bit dat_o value.
    """
    packet = make_read_packet(row, col, stimuli16)

    # Step 1: WB WRITE to enqueue the READ command into X1 ip_fifo
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = packet

    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF

    # Step 2: Wait for X1 engine to execute the read and push to op_fifo
    await ClockCycles(dut.wb_clk_i, RD_Dly + 2)

    # Step 3: WB READ to pop the result from op_fifo
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = 0

    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_sel_i.value = 0xF

    await FallingEdge(dut.wb_clk_i)
    return int(dut.wbs_dat_o.value)


async def wb_read_raw(dut):
    """
    Bare WB READ at SYNAPSE_ADDR — pops whatever is in op_fifo
    (or returns DEAD_C0DE if empty). Returns (ack, dat_o).
    """
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = 0

    ack = 0
    dat = 0
    for _ in range(3):
        await RisingEdge(dut.wb_clk_i)
        if int(dut.wbs_ack_o.value) == 1:
            ack = 1
            dat = int(dut.wbs_dat_o.value)
            break

    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_sel_i.value = 0xF
    await FallingEdge(dut.wb_clk_i)
    return ack, dat


# ---------------------------------------------------------------------------
# T1 — test_program_single_cell
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_program_single_cell(dut):
    """Program a known pattern at (row=1, col=2), read back, verify dat_o[15:0]."""
    await setup_dut(dut)

    pattern = 0x1234   # arbitrary 16-bit test pattern
    await nvm_program(dut, row=1, col=2, data16=pattern)
    result = await nvm_read_cell(dut, row=1, col=2)

    connection = result & 0xFFFF
    upper      = (result >> 16) & 0xFFFF

    assert connection == pattern, \
        f"T1 FAIL: expected connection=0x{pattern:04X}, got 0x{connection:04X}"
    assert upper == 0, \
        f"T1 FAIL: dat_o[31:16] should be 0, got 0x{upper:04X}"

    dut._log.info(f"T1 PASS: single cell readback 0x{connection:04X}")


# ---------------------------------------------------------------------------
# T2 — test_program_all_ones
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_program_all_ones(dut):
    """data=0xFFFF: all 16 macros get MEM_HIGH(0xFF) > 0x7F → store 1. Expect readback 0xFFFF."""
    await setup_dut(dut)

    await nvm_program(dut, row=0, col=0, data16=0xFFFF)
    result = await nvm_read_cell(dut, row=0, col=0)
    connection = result & 0xFFFF

    assert connection == 0xFFFF, \
        f"T2 FAIL: expected 0xFFFF, got 0x{connection:04X}"

    dut._log.info("T2 PASS: all-ones programmed and read back correctly")


# ---------------------------------------------------------------------------
# T3 — test_program_all_zeros
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_program_all_zeros(dut):
    """data=0x0000: all macros get MEM_LOW(0x00) <= 0x7F → store 0. Expect readback 0x0000."""
    await setup_dut(dut)

    # First program ones so we're overwriting, not relying on initial state
    await nvm_program(dut, row=0, col=1, data16=0xFFFF)
    await nvm_program(dut, row=0, col=1, data16=0x0000)
    result = await nvm_read_cell(dut, row=0, col=1)
    connection = result & 0xFFFF

    assert connection == 0x0000, \
        f"T3 FAIL: expected 0x0000, got 0x{connection:04X}"

    dut._log.info("T3 PASS: all-zeros programmed and read back correctly")


# ---------------------------------------------------------------------------
# T4 — test_program_alternating
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_program_alternating(dut):
    """
    Program 0xAAAA at (row=0, col=2) and 0x5555 at (row=0, col=3).
    Read both back. Verify no pattern cross-contamination between cells.
    """
    await setup_dut(dut)

    await nvm_program(dut, row=0, col=2, data16=0xAAAA)
    await nvm_program(dut, row=0, col=3, data16=0x5555)

    r_aa = (await nvm_read_cell(dut, row=0, col=2)) & 0xFFFF
    r_55 = (await nvm_read_cell(dut, row=0, col=3)) & 0xFFFF

    assert r_aa == 0xAAAA, f"T4 FAIL: col=2 expected 0xAAAA, got 0x{r_aa:04X}"
    assert r_55 == 0x5555, f"T4 FAIL: col=3 expected 0x5555, got 0x{r_55:04X}"

    dut._log.info(f"T4 PASS: alternating patterns verified (0x{r_aa:04X} / 0x{r_55:04X})")


# ---------------------------------------------------------------------------
# T5 — test_program_multiple_locations
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_program_multiple_locations(dut):
    """
    Program 4 distinct (row, col) locations. Read all back.
    Verify each returns its own pattern and no aliasing exists.
    """
    await setup_dut(dut)

    cells = [
        (1, 0, 0x0F0F),
        (1, 1, 0xF0F0),
        (2, 0, 0x00FF),
        (2, 1, 0xFF00),
    ]

    for row, col, pattern in cells:
        await nvm_program(dut, row=row, col=col, data16=pattern)

    for row, col, pattern in cells:
        result = (await nvm_read_cell(dut, row=row, col=col)) & 0xFFFF
        assert result == pattern, \
            f"T5 FAIL: ({row},{col}) expected 0x{pattern:04X}, got 0x{result:04X}"

    dut._log.info("T5 PASS: 4 distinct locations read back without aliasing")


# ---------------------------------------------------------------------------
# T6 — test_overwrite_cell
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_overwrite_cell(dut):
    """Program cell with pattern A, then overwrite with pattern B. Readback must return B."""
    await setup_dut(dut)

    pattern_a = 0xAAAA
    pattern_b = 0x1234

    await nvm_program(dut, row=3, col=3, data16=pattern_a)
    rb_a = (await nvm_read_cell(dut, row=3, col=3)) & 0xFFFF
    assert rb_a == pattern_a, \
        f"T6 FAIL: first write — expected 0x{pattern_a:04X}, got 0x{rb_a:04X}"

    await nvm_program(dut, row=3, col=3, data16=pattern_b)
    rb_b = (await nvm_read_cell(dut, row=3, col=3)) & 0xFFFF
    assert rb_b == pattern_b, \
        f"T6 FAIL: overwrite — expected 0x{pattern_b:04X}, got 0x{rb_b:04X}"

    dut._log.info(f"T6 PASS: overwrite verified (A=0x{rb_a:04X} → B=0x{rb_b:04X})")


# ---------------------------------------------------------------------------
# T7 — test_full_row_program
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_full_row_program(dut):
    """
    Program all 32 columns in row 4 with unique patterns.
    Read all back and verify no cross-column contamination.
    Pattern: col * 0x0041 (gives unique 16-bit values across 0..31).
    """
    await setup_dut(dut)

    ROW = 4
    patterns = [(col * 0x0041) & 0xFFFF for col in range(32)]

    for col, pat in enumerate(patterns):
        await nvm_program(dut, row=ROW, col=col, data16=pat)

    for col, pat in enumerate(patterns):
        result = (await nvm_read_cell(dut, row=ROW, col=col)) & 0xFFFF
        assert result == pat, \
            f"T7 FAIL: row={ROW} col={col} expected 0x{pat:04X}, got 0x{result:04X}"

    dut._log.info(f"T7 PASS: all 32 cols in row {ROW} read back correctly")


# ---------------------------------------------------------------------------
# T8 — test_timing_early_readback
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_timing_early_readback(dut):
    """
    Issue PROGRAM then READ command back-to-back (< WR_Dly gap).
    Attempt a WB READ before RD_Dly completes — must see DEAD_C0DE.
    After full WR_Dly + RD_Dly, read again — must see the correct value.

    RTL note: empty op_fifo pop returns core_ack=1 + DO=0xDEAD_C0DE
    (Neuromorphic_X1_beh.v:230-232). ACK is never silent.
    """
    await setup_dut(dut)

    pattern = 0xBEEF
    prog_packet = make_program_packet(row=5, col=5, data16=pattern)
    read_packet = make_read_packet(row=5, col=5)

    # --- PROGRAM (enqueue only, don't wait WR_Dly) ---
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = prog_packet
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0

    # --- READ command enqueue immediately (before PROGRAM completes) ---
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = read_packet
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0

    # Wait only a few cycles — well before WR_Dly + RD_Dly
    await ClockCycles(dut.wb_clk_i, 5)

    # --- Attempt early WB READ: op_fifo still empty ---
    # X1 internally returns DEAD_C0DE with ACK=1, but nvm_synapse_matrix only
    # passes bit[0] of each X1's DO to wbs_dat_o. DEAD_C0DE[0]=0, so all 16
    # bits are 0 → top-level dat_o = 0x0000. DEAD_C0DE is NOT visible here.
    ack_early, dat_early = await wb_read_raw(dut)
    assert ack_early == 1, \
        f"T8 FAIL: expected ACK=1 on empty fifo read, got {ack_early}"
    assert dat_early == 0, \
        f"T8 FAIL: expected 0x00000000 (empty fifo, DEAD_C0DE filtered by bit-pack), got 0x{dat_early:08X}"

    # --- Wait the full WR_Dly + RD_Dly for both operations to finish ---
    await ClockCycles(dut.wb_clk_i, WR_Dly + RD_Dly + 5)

    # --- Now the real result should be in op_fifo ---
    ack_late, dat_late = await wb_read_raw(dut)
    connection = dat_late & 0xFFFF
    assert ack_late == 1, \
        f"T8 FAIL: expected ACK=1 on real result read, got {ack_late}"
    assert connection == pattern, \
        f"T8 FAIL: expected 0x{pattern:04X} after full delay, got 0x{connection:04X}"

    dut._log.info(
        f"T8 PASS: early read=0x0000 (empty fifo, DEAD_C0DE not visible), late read=0x{connection:04X}"
    )


# ---------------------------------------------------------------------------
# T9 — test_dead_code_empty_fifo
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_dead_code_empty_fifo(dut):
    """
    After reset, op_fifo is empty. WB READ must return ACK=1 and dat_o=0x0000.

    X1 internally returns DEAD_C0DE (0xDEADC0DE) with ACK=1 on empty reads,
    but nvm_synapse_matrix packs only bit[0] of each macro's DO into wbs_dat_o.
    DEAD_C0DE[0] = 0, so all 16 connection bits are 0 → top-level dat_o = 0x0000.
    Firmware implication: cannot distinguish empty-fifo from a legitimate all-zero
    connection by value alone — it must use sequencing (wait RD_Dly after READ cmd).
    """
    await setup_dut(dut)

    ack, dat = await wb_read_raw(dut)

    assert ack == 1, \
        f"T9 FAIL: expected ACK=1 on empty fifo, got {ack}"
    assert dat == 0, \
        f"T9 FAIL: expected 0x00000000 (DEAD_C0DE invisible through bit-pack), got 0x{dat:08X}"

    dut._log.info("T9 PASS: empty op_fifo returns ACK=1 + dat_o=0x0000 (DEAD_C0DE filtered)")


# ---------------------------------------------------------------------------
# T10 — test_connection_bit_mapping
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_connection_bit_mapping(dut):
    """
    Set exactly one bit in data[15:0] at a time (powers of 2).
    For each, program at a dedicated row/col, read back, verify:
      - dat_o[i] = 1 only for the programmed bit position i
      - all other dat_o bits are 0
    Catches any bit reversal or off-by-one in the generate loop wiring.
    """
    await setup_dut(dut)

    # Use row=6, cols 0-15 (one col per macro bit to keep them independent)
    ROW = 6
    for bit in range(16):
        pattern = 1 << bit
        col     = bit   # unique column per bit test

        await nvm_program(dut, row=ROW, col=col, data16=pattern)
        result = (await nvm_read_cell(dut, row=ROW, col=col)) & 0xFFFF

        assert result == pattern, \
            f"T10 FAIL: bit={bit} expected 0x{pattern:04X}, got 0x{result:04X} " \
            f"(extra bits set: 0x{result & ~pattern & 0xFFFF:04X})"

    dut._log.info("T10 PASS: all 16 macro bits map correctly to dat_o[15:0]")
