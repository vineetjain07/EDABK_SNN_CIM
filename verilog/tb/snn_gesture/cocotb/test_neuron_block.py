"""
Phase 3: Neuron Block Integration & Spike Generation
DUT: nvm_neuron_core_256x64 (top-level, driven via Wishbone)

This test suite validates the LIF (Leaky Integrate-and-Fire) logic within 
the neuron blocks, including accumulation, symmetric leak, threshold 
comparison, and saturation.

Run: cd verilog/tb/snn_gesture/cocotb && make MODULE=test_neuron_block SIM=icarus

RTL key facts:
  - enable = slave_ack_o[0]  (synapse matrix filtered ACK, fires only on READ)
  - connection = slave_dat_o[0][15:0]  (1 bit per macro)
  - stimuli sign: col[0]==0 → +val, col[0]==1 → -val
  - spike_o[i] = (potential[i] >= THRESHOLD)  THRESHOLD = NEURON_THRESHOLD (default 10)
  - picture_done is combinatorial (addr[15:12]==2) → high priority over enable
  - After reset: potential=0 → spike=0 for ALL neurons (below threshold by default)
  - picture_done: Triggers latching of spikes and reset of potentials. 
    Has priority over 'enable' in the hardware scheduler.

Tests:
  T1  - test_neuron_initial_spike_after_reset  : all neurons silent (=0) after reset (potential < threshold)
  T2  - test_neuron_accumulation_positive      : even col → positive potential
  T3  - test_neuron_accumulation_negative      : odd col → negative potential, no spike
  T4  - test_stimuli_sign_convention           : even+odd same magnitude → cancel to 0
  T5  - test_picture_done_reset                : latch races verified, potentials reset
  T6  - test_neuron_isolation                  : only one neuron accumulates
  T7  - test_multiple_axon_accumulation        : sum over multiple axons correct
  T8  - test_potential_saturation               : 16-bit signed saturation at +32767
  T9  - test_threshold_boundary                : spike transitions at NEURON_THRESHOLD boundary
  T10 - test_enable_picture_done_priority      : picture_done wins over enable (firmware hazard)
  
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
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles
from nvm_parameter import (
    NEURON_THRESHOLD, SYNAPSE_ADDR, SPIKE_LO, SPIKE_HI,
    MODE_READ, RD_Dly
)
from snn_test_utils import (
    setup_dut, nvm_program, nvm_inject, trigger_picture_done, wb_read,
    get_potential
)


# ---------------------------------------------------------------------------
# T1 — test_neuron_initial_spike_after_reset
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_neuron_initial_spike_after_reset(dut):
    """
    After reset, potential[i]=0  →  spike_o[i] = (0 >= NEURON_THRESHOLD) = 0 for all i.
    KEY NON-OBVIOUS BEHAVIOR: neurons are SILENT by default — must accumulate past threshold.
    """
    await setup_dut(dut)
    await trigger_picture_done(dut)  # latch current (reset) state into sram

    lo = await wb_read(dut, SPIKE_LO)  # {sram[1], sram[0]}
    hi = await wb_read(dut, SPIKE_HI)   # {sram[3], sram[2]}

    assert lo == 0x00000000, \
        f"T1 FAIL: neurons 0-31 expected all-0 spikes after reset (potential=0 < THRESHOLD={NEURON_THRESHOLD}), got {hex(lo)}"
    assert hi == 0x00000000, \
        f"T1 FAIL: neurons 32-63 expected all-0 spikes after reset (potential=0 < THRESHOLD={NEURON_THRESHOLD}), got {hex(hi)}"
    dut._log.info(f"T1 PASS: all 64 neurons fire=0 by default after reset (threshold={NEURON_THRESHOLD})")


# ---------------------------------------------------------------------------
# T2 — test_neuron_accumulation_positive
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_neuron_accumulation_positive(dut):
    """
    Even col → positive stimuli.
    Program only macro 0 connected at [row=0,col=0]. Inject stim=1000.
    Expect potential[0]=1000, all others stay 0.
    """
    await setup_dut(dut)

    stim = 1000
    # Connect only macro bit 0
    await nvm_program(dut, row=0, col=0, data16=0x0001)
    await nvm_inject(dut, row=0, col=0, val=stim)

    p0 = get_potential(dut, 0)
    assert p0 == stim, f"T2 FAIL: potential[0] expected {stim}, got {p0}"
    for i in range(1, 16):
        pi = get_potential(dut, i)
        assert pi == 0, f"T2 FAIL: potential[{i}] should be 0, got {pi}"

    spike = int(dut.neuron_block_inst.spike_o.value)
    assert spike & 0x0001, "T2 FAIL: neuron 0 should spike (potential>=0)"

    dut._log.info(f"T2 PASS: neuron 0 accumulated +{stim}, spike=1")


# ---------------------------------------------------------------------------
# T3 — test_neuron_accumulation_negative
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_neuron_accumulation_negative(dut):
    """
    Odd col → stimuli = -val_16bit.
    Program macro 0 at [row=0,col=1]. Inject val=500.
    RTL: stimuli = -wbs_dat_i[15:0] = -500
    Expect potential[0]=-500, spike=0 (negative → sign bit=1 → ~1=0).
    """
    await setup_dut(dut)

    val = 500
    await nvm_program(dut, row=0, col=1, data16=0x0001)
    await nvm_inject(dut, row=0, col=1, val=val)

    p0 = get_potential(dut, 0)
    assert p0 == -val, f"T3 FAIL: potential[0] expected {-val}, got {p0}"

    spike = int(dut.neuron_block_inst.spike_o.value)
    assert not (spike & 0x0001), \
        f"T3 FAIL: neuron 0 should NOT spike (potential={p0}<0), got spike_o={spike}"

    dut._log.info(f"T3 PASS: neuron 0 integrated {-val} via odd col, spike=0")


# ---------------------------------------------------------------------------
# T4 — test_stimuli_sign_convention
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_stimuli_sign_convention(dut):
    """
    Program neuron 0 at both even col=0 (+) and odd col=1 (-).
    Inject same magnitude twice → they cancel → potential stays 0 → spike=1.
    """
    await setup_dut(dut)

    mag = 500
    # Connect macro 0 at both col=0 (positive) and col=1 (negative)
    await nvm_program(dut, row=0, col=0, data16=0x0001)
    await nvm_program(dut, row=0, col=1, data16=0x0001)

    # Even col: +500
    await nvm_inject(dut, row=0, col=0, val=mag)
    p0_after_pos = get_potential(dut, 0)
    assert p0_after_pos == mag, \
        f"T4 FAIL: after even-col inject, expected {mag}, got {p0_after_pos}"

    # Odd col: -500
    await nvm_inject(dut, row=0, col=1, val=mag)
    p0_final = get_potential(dut, 0)
    assert p0_final == 0, \
        f"T4 FAIL: after odd-col cancel, expected 0, got {p0_final}"

    spike = int(dut.neuron_block_inst.spike_o.value)
    assert not (spike & 0x0001), \
        f"T4 FAIL: neuron 0 should NOT spike at potential=0 (0 < THRESHOLD={NEURON_THRESHOLD})"

    dut._log.info(f"T4 PASS: even/odd columns cancel to 0; no spike (0 < threshold={NEURON_THRESHOLD})")


# ---------------------------------------------------------------------------
# T5 — test_picture_done_reset
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_picture_done_reset(dut):
    """
    RACE CONDITION VERIFICATION:
    Accumulate positive potential so neuron 0 spikes (spike=1). Issue picture_done.
    Verify spike_out LATCHES THE PRE-RESET value (1), NOT the post-reset value (0).
    Then verify potential has been reset to 0.

    Why this works (Verilog non-blocking assignment scheduling):
      - spike_out sram captures RHS (old spike_o) before any LHS updates.
      - So sram gets the "before-reset" spike value.

    With NEURON_THRESHOLD={NEURON_THRESHOLD}: inject +50 → potential=50 → spike=1.
    After picture_done: potential resets to 0 → spike=0.
    SRAM must show spike=1 (the pre-reset state, not the post-reset state).
    All other neurons remain at potential=0 → spike=0 throughout.
    """
    await setup_dut(dut)

    # Make neuron 0 spike=1 by pushing potential above threshold
    await nvm_program(dut, row=0, col=0, data16=0x0001)  # even col = positive
    await nvm_inject(dut, row=0, col=0, val=50)         # potential[0] = 50 >= THRESHOLD
    p0 = get_potential(dut, 0)
    assert p0 >= NEURON_THRESHOLD, \
        f"T5 FAIL: pre-condition: potential[0]={p0} should be >= THRESHOLD={NEURON_THRESHOLD}"

    # Trigger picture_done for group 0 only (neurons 0-15)
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = 0x30002000
    dut.wbs_dat_i.value = 0
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0
    await ClockCycles(dut.wb_clk_i, 3)

    # Read latched spike at neurons 0-31
    # sram[0] contains neurons 0-15 (written by picture_done at 0x30002000)
    # sram[1] contains neurons 16-31 (was NOT reset here — stays at hardware reset value 0)
    lo = await wb_read(dut, SPIKE_LO)  # {sram[1], sram[0]}

    sram0 = lo & 0xFFFF          # neurons 0-15
    sram1 = (lo >> 16) & 0xFFFF  # neurons 16-31 (never written)

    # sram[0]: neuron 0 spike=1 (latched pre-reset), neurons 1-15 spike=0 (potential=0 < THRESHOLD)
    assert sram0 == 0x0001, \
        f"T5 FAIL: sram[0] expected 0x0001 (bit0=1 latched pre-reset, others=0), got {hex(sram0)}"

    # sram[1] was never written — must still be 0 (hardware reset value)
    assert sram1 == 0x0000, \
        f"T5 FAIL: sram[1] should be 0 (never written), got {hex(sram1)}"

    # Verify potential[0] has been reset by picture_done
    p0_after = get_potential(dut, 0)
    assert p0_after == 0, \
        f"T5 FAIL: potential[0] should be 0 after picture_done, got {p0_after}"

    dut._log.info("T5 PASS: spike=1 latched correctly (no race), potential reset to 0 after picture_done")


# ---------------------------------------------------------------------------
# T6 — test_neuron_isolation
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_neuron_isolation(dut):
    """
    Only macro bit 3 set → only neuron 3 accumulates.
    All other 15 neurons remain at 0.
    """
    await setup_dut(dut)

    await nvm_program(dut, row=0, col=0, data16=0x0008)  # bit 3 only
    for _ in range(5):
        await nvm_inject(dut, row=0, col=0, val=200)

    p3 = get_potential(dut, 3)
    assert p3 == 1000, f"T6 FAIL: potential[3] expected 1000, got {p3}"

    for i in range(16):
        if i == 3:
            continue
        pi = get_potential(dut, i)
        assert pi == 0, f"T6 FAIL: potential[{i}] should be 0 (isolated), got {pi}"

    dut._log.info("T6 PASS: only neuron 3 accumulated through isolated connection")


# ---------------------------------------------------------------------------
# T7 — test_multiple_axon_accumulation
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_multiple_axon_accumulation(dut):
    """
    Program 10 different (row, col) all-even positions with macro 0 bit set.
    Inject stim=50 through each. Expect potential[0] = 10 * 50 = 500.
    """
    await setup_dut(dut)

    stim = 50
    axons = [(r, c) for r in range(0, 4) for c in range(0, 2, 1)]
    # 4 rows × 2 even cols = 8 axons (use only first 10 using rows 0-4 × col 0, col 2)
    axons = [(0,0),(0,2),(1,0),(1,2),(2,0),(2,2),(3,0),(3,2),(4,0),(4,2)]

    for row, col in axons:
        await nvm_program(dut, row=row, col=col, data16=0x0001)
    for row, col in axons:
        await nvm_inject(dut, row=row, col=col, val=stim)

    p0 = get_potential(dut, 0)
    expected = stim * len(axons)
    assert p0 == expected, \
        f"T7 FAIL: potential[0] expected {expected}, got {p0}"

    dut._log.info(f"T7 PASS: neuron 0 accumulated {expected} over {len(axons)} axons")


# ---------------------------------------------------------------------------
# T8 — test_potential_saturation
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_potential_saturation(dut):
    """
    Verify 16-bit signed saturation at +32767 (RTL saturation logic):
      inject1: potential = 0 + 0x7000 = 28672  (no leak from 0)
      inject2: potential would be 28672 - 28 + 28672 = 57316 mathematically,
               but RTL saturates at 32767 (0x7FFF).
    With saturation, neuron continues to fire (potential >= NEURON_THRESHOLD).
    """
    await setup_dut(dut)

    await nvm_program(dut, row=0, col=0, data16=0x0001)  # neuron 0 connected

    # First injection: 0x7000 = 28672; starting from 0 so no leak
    await nvm_inject(dut, row=0, col=0, val=0x7000)
    p0_first = get_potential(dut, 0)
    assert p0_first == 0x7000, \
        f"T8 FAIL: expected 0x7000 after first inject, got {hex(p0_first & 0xFFFF)}"

    # Second injection: would overflow without saturation
    await nvm_inject(dut, row=0, col=0, val=0x7000)
    p0_sat = get_potential(dut, 0)
    assert p0_sat == 32767, \
        f"T8 FAIL: expected saturation at 32767, got {p0_sat}"

    # Spike must still be 1 (saturated at +32767 >= NEURON_THRESHOLD)
    spike = int(dut.neuron_block_inst.spike_o.value)
    assert spike & 0x0001, \
        "T8 FAIL: spike should be 1 after saturation (potential=32767 >= THRESHOLD)"

    dut._log.info("T8 PASS: 16-bit saturation at +32767 — neuron stays firing when hyper-stimulated")


# ---------------------------------------------------------------------------
# T9 — test_threshold_boundary_zero
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_threshold_boundary_zero(dut):
    """
    Verify threshold boundary transitions of spike_o = (potential >= NEURON_THRESHOLD):
      potential = NEURON_THRESHOLD     → spike = 1  (at threshold, inclusive)
      potential = NEURON_THRESHOLD - 1 → spike = 0  (just below threshold)
      potential = NEURON_THRESHOLD     → spike = 1  (recovery to threshold)

    Values are all < 1024 so LEAK_SHIFT=10 produces zero leak (n >>> 10 = 0 for n < 1024).
    """
    await setup_dut(dut)

    # Program neuron 0 connected at both even (col=0, positive) and odd (col=1, negative)
    await nvm_program(dut, row=0, col=0, data16=0x0001)
    await nvm_program(dut, row=0, col=1, data16=0x0001)

    def check_spike0(expected, label):
        spike = int(dut.neuron_block_inst.spike_o.value) & 0x0001
        assert spike == expected, \
            f"T9 FAIL [{label}]: spike_o[0]={spike}, expected {expected}"

    # Step 1: +NEURON_THRESHOLD → potential=THRESHOLD → spike=1 (at threshold, inclusive)
    await nvm_inject(dut, row=0, col=0, val=NEURON_THRESHOLD)
    p0 = get_potential(dut, 0)
    assert p0 == NEURON_THRESHOLD, \
        f"T9 FAIL: expected potential={NEURON_THRESHOLD}, got {p0}"
    check_spike0(1, f"potential={NEURON_THRESHOLD} (at threshold)")

    # Step 2: -1 → potential=THRESHOLD-1 → spike=0 (just below threshold)
    await nvm_inject(dut, row=0, col=1, val=1)
    p0 = get_potential(dut, 0)
    assert p0 == NEURON_THRESHOLD - 1, \
        f"T9 FAIL: expected potential={NEURON_THRESHOLD - 1}, got {p0}"
    check_spike0(0, f"potential={NEURON_THRESHOLD - 1} (just below threshold)")

    # Step 3: +1 → potential=THRESHOLD → spike=1 (recovery)
    await nvm_inject(dut, row=0, col=0, val=1)
    p0 = get_potential(dut, 0)
    assert p0 == NEURON_THRESHOLD, \
        f"T9 FAIL: expected potential={NEURON_THRESHOLD} (recovery), got {p0}"
    check_spike0(1, f"potential={NEURON_THRESHOLD} (recovery)")

    dut._log.info(f"T9 PASS: threshold boundary transitions verified (threshold={NEURON_THRESHOLD})")


# ---------------------------------------------------------------------------
# T10 — test_enable_picture_done_priority
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_enable_picture_done_priority(dut):
    """
    PROTOCOL HAZARD VERIFICATION: picture_done priority over enable.

    RTL priority in nvm_neuron_block.v:
      if (rst)                         potential <= 0   ← highest
      else if (picture_done)           potential <= 0   ← wins over enable
      else if (enable & connection[i]) potential += stimuli

    If both picture_done and enable are high on the SAME posedge, the
    accumulation is SILENTLY DISCARDED. No error flag, no retry.
    This is a firmware protocol hazard.

    Exact timing exploit used:
      Cycle A:   Issue WB READ → X1 fires core_ack=1 via NBA (visible next cycle)
      Cycle A+1: Immediately drive addr=0x3000_2000 (picture_done=1 combinatorially)
                 Neuron block posedge now sees:
                   enable      = 1  (slave_ack_o[0] = core_ack from Cycle A)
                   picture_done = 1  (from address decoder, combinatorial)
                 → picture_done wins → potential stays 0 → stim silently dropped

    Firmware rule confirmed: ALL nvm_inject calls must fully complete
    (both WB WRITE + WB READ steps + settling) before picture_done is issued.
    """
    await setup_dut(dut)

    stim = 500

    # 1. Program neuron 0 connected at even col=0 (positive stimulus)
    await nvm_program(dut, row=0, col=0, data16=0x0001)

    # 2. Step 1 of inject: enqueue the READ command (WB WRITE with MODE_READ)
    packet = (MODE_READ << 30) | (0 << 25) | (0 << 20) | stim
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

    # 3. Wait for X1 engine to complete READ and push 1-bit result into op_fifo
    await ClockCycles(dut.wb_clk_i, RD_Dly + 2)

    # 4. Step 2 of inject (PARTIAL): Issue WB READ for exactly 1 cycle
    #    → X1 fires core_ack=1 at END of this cycle (NBA, visible in Cycle A+1)
    await RisingEdge(dut.wb_clk_i)             # Setup: drive WB READ
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 0                    # READ: wbs_we_i_reversed=1 → ACK gates through
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    await RisingEdge(dut.wb_clk_i)             # Cycle A done — core_ack=1 (NBA resolved)

    # 5. IMMEDIATELY (NO wait) collide picture_done into the SAME Cycle A+1
    #    At this exact moment: enable=1 (core_ack carried over) && picture_done goes 1
    dut.wbs_adr_i.value = 0x30002000           # picture_done=1 fires combinatorially
    dut.wbs_we_i.value  = 1                    # write
    # cyc=stb=1 stay asserted from the WB READ above
    await RisingEdge(dut.wb_clk_i)             # Cycle A+1: neuron posedge sees enable=1 AND picture_done=1
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0

    # Settle
    await ClockCycles(dut.wb_clk_i, 2)

    # 6. Assert: picture_done won — potential = 0, NOT 500 (integration discarded)
    p0 = get_potential(dut, 0)
    assert p0 == 0, (
        f"T10 FAIL: picture_done priority violated — "
        f"potential should be 0 (reset won), got {p0}. "
        f"Integration of stim={stim} was NOT discarded."
    )

    # 7. With potential=0, spike must be 0 (0 < NEURON_THRESHOLD)
    spike = int(dut.neuron_block_inst.spike_o.value) & 0x0001
    assert spike == 0, \
        f"T10 FAIL: spike should be 0 (potential=0 < THRESHOLD={NEURON_THRESHOLD}), got {spike}"

    dut._log.info(
        f"T10 PASS: picture_done priority confirmed — stim={stim} silently discarded, "
        f"spike=0 (potential=0 < threshold={NEURON_THRESHOLD}). "
        "FIRMWARE RULE: all injects must complete before picture_done is issued."
    )
