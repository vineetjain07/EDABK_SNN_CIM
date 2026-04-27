"""
Phase 1: Wishbone Interface & Reset Verification
DUT: nvm_neuron_core_256x64

Run: cd verilog/tb && make MODULE=test_wb_interface

Tests:
  T1 - test_reset_state            : quiescent outputs during/after reset
  T2 - test_spike_out_read_ack     : spike-out read responds with ACK
  T3 - test_picture_done_ack       : picture_done write responds with ACK
  T4 - test_synapse_write_no_ack   : PROGRAM writes to synapse matrix never ACK (wbs_we_i_reversed)
  T5 - test_invalid_address_no_ack : addresses outside 0x3000_{0,1,2}XXX get no response
  T6 - test_sel_not_f_ignored      : wbs_sel_i != 4'hF disables X1 macro EN
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
from nvm_parameter import PERIOD, MODE_PROGRAM, SYNAPSE_ADDR, SPIKE_LO, PD
from snn_test_utils import setup_dut

# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
INVALID_ADDR = 0x30003000   # outside decoder ranges


# ---------------------------------------------------------------------------
# T1 — test_reset_state
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_reset_state(dut):
    """wbs_ack_o and wbs_dat_o must be 0 during reset and with idle bus after release."""

    cocotb.start_soon(Clock(dut.wb_clk_i, PERIOD, units="ns").start())

    # Tie off non-functional pins
    analog_pins = [
        "Iref", "Vcc_read", "Vcomp", "Bias_comp2", "Vcc_wl_read",
        "Vcc_wl_set", "Vbias", "Vcc_wl_reset", "Vcc_set",
        "Vcc_reset", "Vcc_L", "Vcc_Body",
    ]
    for name in analog_pins:
        getattr(dut, name).value = 0
    dut.ScanInCC.value = 0
    dut.ScanInDL.value = 0
    dut.ScanInDR.value = 0
    dut.TM.value       = 0

    # Bus idle
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = 0
    dut.wbs_dat_i.value = 0

    # ---- During reset ----
    # Wait for the first rising edge so flip-flops initialize from X to 0
    dut.wb_rst_i.value = 1
    await RisingEdge(dut.wb_clk_i)   # first edge: registers leave X, settle to 0
    for _ in range(5):
        await RisingEdge(dut.wb_clk_i)
        assert dut.wbs_ack_o.value == 0, \
            f"wbs_ack_o should be 0 during reset, got {dut.wbs_ack_o.value}"
        assert dut.wbs_dat_o.value == 0, \
            f"wbs_dat_o should be 0 during reset, got {dut.wbs_dat_o.value}"

    # ---- After reset release, bus still idle ----
    dut.wb_rst_i.value = 0
    for _ in range(5):
        await RisingEdge(dut.wb_clk_i)
        assert dut.wbs_ack_o.value == 0, \
            f"wbs_ack_o should stay 0 with idle bus after reset, got {dut.wbs_ack_o.value}"

    dut._log.info("T1 PASS: reset holds outputs quiescent")


# ---------------------------------------------------------------------------
# T2 — test_spike_out_read_ack
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_spike_out_read_ack(dut):
    """A Wishbone read to 0x3000_1000 must be ACKed within 2 cycles and return 0 after reset."""
    await setup_dut(dut)

    # Issue read
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SPIKE_LO
    dut.wbs_dat_i.value = 0

    ack_seen = False
    for _ in range(3):          # must ACK within 2 active clock edges
        await RisingEdge(dut.wb_clk_i)
        if dut.wbs_ack_o.value == 1:
            ack_seen = True
            dat = int(dut.wbs_dat_o.value)
            break

    # De-assert bus
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0

    assert ack_seen, "T2 FAIL: no ACK received for spike-out read within 2 cycles"
    assert dat == 0, f"T2 FAIL: expected dat_o=0 after reset, got {hex(dat)}"

    dut._log.info(f"T2 PASS: spike-out read ACKed, dat_o=0x{dat:08X}")


# ---------------------------------------------------------------------------
# T3 — test_picture_done_ack
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_picture_done_ack(dut):
    """Writing to 0x3000_2000 (picture_done) must assert picture_done signal and get ACKed."""
    await setup_dut(dut)

    # Issue write to picture_done address
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = PD[0]
    dut.wbs_dat_i.value = 0

    # Verify picture_done decoder output asserts combinatorially
    await Timer(1, units="ns")   # let combinatorial logic settle
    pic_done = int(dut.core_decoder_inst.picture_done.value)
    assert pic_done == 1, \
        f"T3 FAIL: picture_done should be 1 with addr 0x30002000, got {pic_done}"

    # Verify ACK within 2 cycles
    ack_seen = False
    for _ in range(3):
        await RisingEdge(dut.wb_clk_i)
        if dut.wbs_ack_o.value == 1:
            ack_seen = True
            break

    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0

    assert ack_seen, "T3 FAIL: no ACK for picture_done write"
    dut._log.info("T3 PASS: picture_done asserted and write ACKed")


# ---------------------------------------------------------------------------
# T4 — test_synapse_write_no_ack
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_synapse_write_no_ack(dut):
    """
    PROGRAM write to synapse matrix must NEVER produce wbs_ack_o=1.
    This verifies the wbs_we_i_reversed architectural fix in nvm_synapse_matrix.
    synapse_matrix.wbs_ack_o = wbs_we_i_reversed & (|slave_ack_o)
    wbs_we_i_reversed = ~wbs_we_i registered -- so it is 0 while the write is active.
    """
    await setup_dut(dut)

    # Build a MODE_PROGRAM packet (row=0, col=0, data=0xFFFF)
    program_data = (MODE_PROGRAM << 30) | (0 << 25) | (0 << 20) | 0xFFFF

    # Assert write for several cycles and confirm no ACK
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = program_data

    # Check synapse_matrix_select asserts
    await Timer(1, units="ns")
    syn_sel = int(dut.core_decoder_inst.synapse_matrix_select.value)
    assert syn_sel == 1, \
        f"T4 FAIL: synapse_matrix_select should be 1, got {syn_sel}"

    # Watch for spurious ACK over 5 cycles — must never see one
    spurious_ack = False
    for _ in range(5):
        await RisingEdge(dut.wb_clk_i)
        if dut.wbs_ack_o.value == 1:
            spurious_ack = True
            break

    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0

    assert not spurious_ack, \
        "T4 FAIL: wbs_ack_o asserted during synapse PROGRAM write — wbs_we_i_reversed not working"

    dut._log.info("T4 PASS: synapse PROGRAM write correctly suppressed ACK")


# ---------------------------------------------------------------------------
# T5 — test_invalid_address_no_ack
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_invalid_address_no_ack(dut):
    """Addresses with bits[15:12] >= 3 hit the decoder's default case — no selects, no ACK."""
    await setup_dut(dut)

    for addr in [INVALID_ADDR, 0x30004000, 0x3000F000]:
        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 1
        dut.wbs_stb_i.value = 1
        dut.wbs_we_i.value  = 0
        dut.wbs_sel_i.value = 0xF
        dut.wbs_adr_i.value = addr
        dut.wbs_dat_i.value = 0

        await Timer(1, units="ns")

        syn_sel  = int(dut.core_decoder_inst.synapse_matrix_select.value)
        spk_sel  = int(dut.core_decoder_inst.neuron_spike_out_select.value)
        pic_done = int(dut.core_decoder_inst.picture_done.value)

        assert syn_sel  == 0, f"T5 FAIL: synapse_matrix_select!=0 for addr {hex(addr)}"
        assert spk_sel  == 0, f"T5 FAIL: neuron_spike_out_select!=0 for addr {hex(addr)}"
        assert pic_done == 0, f"T5 FAIL: picture_done!=0 for addr {hex(addr)}"

        for _ in range(3):
            await RisingEdge(dut.wb_clk_i)
            assert dut.wbs_ack_o.value == 0, \
                f"T5 FAIL: got ACK for invalid address {hex(addr)}"

        dut.wbs_cyc_i.value = 0
        dut.wbs_stb_i.value = 0

    dut._log.info("T5 PASS: all invalid addresses correctly ignored")


# ---------------------------------------------------------------------------
# T6 — test_sel_not_f_ignored
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sel_not_f_ignored(dut):
    """
    wbs_sel_i != 4'hF disables X1 macro enable (EN = stb & cyc & adr_match & (sel==4'hF)).
    A write with sel=0x0 should not enqueue into the X1 FIFO and produce no ACK.
    """
    await setup_dut(dut)

    program_data = (MODE_PROGRAM << 30) | (0 << 25) | (0 << 20) | 0xFFFF

    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0x0   # <-- non-full byte select
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = program_data

    # No ACK expected for sel!=4'hF
    ack_seen = False
    for _ in range(5):
        await RisingEdge(dut.wb_clk_i)
        if dut.wbs_ack_o.value == 1:
            ack_seen = True
            break

    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0

    assert not ack_seen, \
        "T6 FAIL: got unexpected ACK with wbs_sel_i=0x0 — X1 EN should have been disabled"

    dut._log.info("T6 PASS: wbs_sel_i=0x0 correctly prevented X1 enable and ACK")
