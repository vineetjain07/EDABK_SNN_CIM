"""
Phase 4: Spike Output — nvm_neuron_spike_out verification
DUT: nvm_neuron_core_256x64 (sim baseline)

Run: cd verilog/tb && make MODULE=test_spike_out SIM=icarus

Tests (6):
  T1 - test_spike_latch_all_groups     : 4 distinct patterns → 4 picture_done writes
  T2 - test_spike_read_32bit_packing   : verify {sram[1],sram[0]} and {sram[3],sram[2]}
  T3 - test_spike_persistence          : sram holds old value after inject without picture_done
  T4 - test_spike_clear_on_new_picture : consecutive picture_done frames overwrite
  T5 - test_sram_reset_value           : sram=0 after hardware reset, no picture_done
  T6 - test_dat_o_clears_on_idle       : dat_o=0 one cycle after bus de-asserts
  T7 - test_partial_picture_done       : unaddressed groups retain prior sram values

RTL facts (nvm_neuron_spike_out.v):
  addr = wbs_adr_i[2:1]
  WRITE: sram[addr][7:0]  ← dat_i[7:0]  if sel[0]  |  dat_i from top = {16'b0, spike_o}
         sram[addr][15:8] ← dat_i[15:8] if sel[1]
  READ:  dat_o ← {sram[addr+1], sram[addr]}
  IDLE:  dat_o ← 0, ack ← 0

Address map:
  picture_done write  →  sram slot  →  neurons
  0x3000_2000 (addr=0) → sram[0]   → 0-15
  0x3000_2002 (addr=1) → sram[1]   → 16-31
  0x3000_2004 (addr=2) → sram[2]   → 32-47
  0x3000_2006 (addr=3) → sram[3]   → 48-63

  spike read addr      →  dat_o
  0x3000_1000 (addr=0) → {sram[1], sram[0]}   dat_o[31:16]=neurons 16-31, [15:0]=0-15
  0x3000_1004 (addr=2) → {sram[3], sram[2]}   dat_o[31:16]=neurons 48-63, [15:0]=32-47
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
from nvm_parameter import SPIKE_LO, SPIKE_HI, PD
from snn_test_utils import setup_dut, nvm_program, nvm_inject, pd_write, wb_read




# ---------------------------------------------------------------------------
# T1 — test_spike_latch_all_groups
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_spike_latch_all_groups(dut):
    """
    Drive 4 distinct spike_o patterns into sram[0..3] by:
      - programming different connection masks per group row-range
      - injecting negative stimuli to suppress specific neurons
      - issuing picture_done for each group after its inject

    Row-range → neuron group → picture_done addr → sram slot:
      rows  0-7  → group 0 → PD[0]=0x3000_2000 → sram[0]
      rows  8-15 → group 1 → PD[1]=0x3000_2002 → sram[1]
      rows 16-23 → group 2 → PD[2]=0x3000_2004 → sram[2]
      rows 24-31 → group 3 → PD[3]=0x3000_2006 → sram[3]

    Expected (even col → positive → triggers connected neurons):
      sram[0] = 0x0001  (bit0=1: neuron0 spike=1, rest=0)
      sram[1] = 0x0003  (bits 0,1=1: neurons 0,1 spike=1)
      sram[2] = 0x0007  (bits 0,1,2=1)
      sram[3] = 0x000F  (bits 0,1,2,3=1)
    -->
      0x3000_1000 = {sram[1],sram[0]} = 0x00030001
      0x3000_1004 = {sram[3],sram[2]} = 0x000F0007
    """
    await setup_dut(dut)

    # --- Group 0: neuron 0 triggers ---
    await nvm_program(dut, row=0,  col=0, data16=0x0001)  # macro 0 connected, even col=pos
    await nvm_inject(dut,  row=0,  col=0, val=1000)        # potential[0] = 1000 → spike[0]=1
    await pd_write(dut, PD[0])                             # sram[0] = 0x0001
 
    # --- Group 1: neurons 0,1 trigger ---
    await nvm_program(dut, row=8,  col=0, data16=0x0003)  # macros 0,1 connected, pos
    await nvm_inject(dut,  row=8,  col=0, val=1000)
    await pd_write(dut, PD[1])                             # sram[1] = 0x0003
 
    # --- Group 2: neurons 0,1,2 trigger ---
    await nvm_program(dut, row=16, col=0, data16=0x0007)
    await nvm_inject(dut,  row=16, col=0, val=1000)
    await pd_write(dut, PD[2])                             # sram[2] = 0x0007
 
    # --- Group 3: neurons 0,1,2,3 trigger ---
    await nvm_program(dut, row=24, col=0, data16=0x000F)
    await nvm_inject(dut,  row=24, col=0, val=1000)
    await pd_write(dut, PD[3])                             # sram[3] = 0x000F

    lo = await wb_read(dut, SPIKE_LO)
    hi = await wb_read(dut, SPIKE_HI)

    sram = [lo & 0xFFFF, (lo >> 16) & 0xFFFF,
            hi & 0xFFFF, (hi >> 16) & 0xFFFF]

    assert sram[0] == 0x0001, f"T1 FAIL sram[0]: exp 0x0001, got 0x{sram[0]:04X}"
    assert sram[1] == 0x0003, f"T1 FAIL sram[1]: exp 0x0003, got 0x{sram[1]:04X}"
    assert sram[2] == 0x0007, f"T1 FAIL sram[2]: exp 0x0007, got 0x{sram[2]:04X}"
    assert sram[3] == 0x000F, f"T1 FAIL sram[3]: exp 0x000F, got 0x{sram[3]:04X}"
    dut._log.info(f"T1 PASS: sram=[{', '.join(f'0x{s:04X}' for s in sram)}]")


# ---------------------------------------------------------------------------
# T2 — test_spike_read_32bit_packing
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_spike_read_32bit_packing(dut):
    """
    Verify dat_o packing:
      0x3000_1000 → {sram[1], sram[0]}:  dat_o[31:16]=sram[1], dat_o[15:0]=sram[0]
      0x3000_1004 → {sram[3], sram[2]}:  dat_o[31:16]=sram[3], dat_o[15:0]=sram[2]

    Use distinct values: sram[0]=0xAAAA, sram[1]=0x5555, sram[2]=0x1234, sram[3]=0xBEEF
    so that upper/lower word swaps are immediately visible.
    """
    await setup_dut(dut)

    # After reset, potentials=0 → spike_o=0xFFFF (all fire). picture_done latches this.
    # To get distinct values, inject negative stimuli into specific macros before each pd_write.

    # bits 1,3,5...=1, bits 0,2,4...=0
    # Connect macros 1,3,5,...(odd) via even col (pos) → triggers even neurons → spike_o=0xAAAA
    await nvm_program(dut, row=0, col=0, data16=0xAAAA)  # 0xAAAA bits set
    await nvm_inject(dut,  row=0, col=0, val=1000)
    await pd_write(dut, PD[0])  # sram[0] = 0xAAAA

    # sram[1]=0x5555: odd bits (1,3,5...) = 0 → connect even macros via even col
    await nvm_program(dut, row=8, col=0, data16=0x5555)  # even bits set
    await nvm_inject(dut,  row=8, col=0, val=1000)
    await pd_write(dut, PD[1])  # sram[1] = 0x5555

    # sram[2]=0x0F0F (lower nybbles trigger)
    await nvm_program(dut, row=16, col=0, data16=0x0F0F)
    await nvm_inject(dut,  row=16, col=0, val=1000)
    await pd_write(dut, PD[2])  # sram[2] = 0x0F0F

    # sram[3]=0xFF00 (upper byte trigger)
    await nvm_program(dut, row=24, col=0, data16=0xFF00)
    await nvm_inject(dut,  row=24, col=0, val=1000)
    await pd_write(dut, PD[3])  # sram[3] = 0xFF00

    lo = await wb_read(dut, SPIKE_LO)
    hi = await wb_read(dut, SPIKE_HI)

    sram0_got = lo & 0xFFFF
    sram1_got = (lo >> 16) & 0xFFFF
    sram2_got = hi & 0xFFFF
    sram3_got = (hi >> 16) & 0xFFFF

    assert sram0_got == 0xAAAA, f"T2 FAIL: sram[0] exp 0xAAAA, got 0x{sram0_got:04X}"
    assert sram1_got == 0x5555, f"T2 FAIL: sram[1] exp 0x5555, got 0x{sram1_got:04X}"
    assert sram2_got == 0x0F0F, f"T2 FAIL: sram[2] exp 0x0F0F, got 0x{sram2_got:04X}"
    assert sram3_got == 0xFF00, f"T2 FAIL: sram[3] exp 0xFF00, got 0x{sram3_got:04X}"
    dut._log.info("T2 PASS: 32-bit packing {sram[1],sram[0]} and {sram[3],sram[2]} verified")


# ---------------------------------------------------------------------------
# T3 — test_spike_persistence
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_spike_persistence(dut):
    """
    sram must hold its latched value across further inject/accumulation cycles
    without another picture_done. spike_o changes, but sram is frozen.
    """
    await setup_dut(dut)

    # Frame 1: trigger neuron 0 → sram[0]=0x0001
    await nvm_program(dut, row=0, col=0, data16=0x0001)
    await nvm_inject(dut,  row=0, col=0, val=1000)
    await pd_write(dut, PD[0])

    lo_before = await wb_read(dut, SPIKE_LO)
    assert (lo_before & 0xFFFF) == 0x0001, \
        f"T3 FAIL: pre-condition sram[0] exp 0x0001, got 0x{lo_before & 0xFFFF:04X}"

    # Now inject more — spike_o changes (potential keeps going negative)
    await nvm_inject(dut, row=0, col=1, val=1000)
    await nvm_inject(dut, row=0, col=1, val=1000)

    # sram must NOT have changed — no picture_done was issued
    lo_after = await wb_read(dut, SPIKE_LO)
    assert (lo_after & 0xFFFF) == 0x0001, \
        f"T3 FAIL: sram[0] changed without picture_done! got 0x{lo_after & 0xFFFF:04X}"
    dut._log.info("T3 PASS: sram holds latched value despite further inject")


# ---------------------------------------------------------------------------
# T4 — test_spike_clear_on_new_picture
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_spike_clear_on_new_picture(dut):
    """
    Frame 1: some neurons trigger → sram[0]=0x000F.
    Frame 2: silent state (after reset/PD) → sram[0]=0x0000.
    Confirms second picture_done fully overwrites first.
    """
    await setup_dut(dut)

    # Frame 1: trigger macros 0,1,2,3
    await nvm_program(dut, row=0, col=0, data16=0x000F)
    await nvm_inject(dut,  row=0, col=0, val=1000)
    await pd_write(dut, PD[0])

    lo1 = await wb_read(dut, SPIKE_LO)
    assert (lo1 & 0xFFFF) == 0x000F, \
        f"T4 FAIL: Frame 1 sram[0] exp 0x000F, got 0x{lo1 & 0xFFFF:04X}"

    # Frame 2: potentials reset to 0 after pd_write → spike_o=0x0000 (below threshold)
    await pd_write(dut, PD[0])
    lo2 = await wb_read(dut, SPIKE_LO)
    assert (lo2 & 0xFFFF) == 0x0000, \
        f"T4 FAIL: Frame 2 sram[0] exp 0x0000, got 0x{lo2 & 0xFFFF:04X}"
    dut._log.info("T4 PASS: multi-frame overwrite works")


# ---------------------------------------------------------------------------
# T5 — test_sram_reset_value
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_sram_reset_value(dut):
    """
    After hardware reset (no picture_done), all sram[i] must be 0x0000.
    spike_o is 0x0000 (below threshold) and sram has NOT been latched.
    """
    await setup_dut(dut)

    lo = await wb_read(dut, SPIKE_LO)
    hi = await wb_read(dut, SPIKE_HI)

    assert lo == 0x00000000, f"T5 FAIL: lo exp 0x00000000, got 0x{lo:08X}"
    assert hi == 0x00000000, f"T5 FAIL: hi exp 0x00000000, got 0x{hi:08X}"
    dut._log.info("T5 PASS: sram=0 after reset before any picture_done")



# ---------------------------------------------------------------------------
# T7 — test_dat_o_clears_on_idle
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_dat_o_clears_on_idle(dut):
    """
    dat_o is a registered output. RTL clears it ({else wbs_dat_o <= 32'b0}) on every
    cycle where !(cyc && stb). dat_o during ACK must be non-zero (when sram is non-zero),
    and zero on the very next clock edge after bus de-assert.
    """
    await setup_dut(dut)

    # Latch a known non-zero spike pattern (trigger macro 0)
    await nvm_program(dut, row=0, col=0, data16=0x0001)
    await nvm_inject(dut,  row=0, col=0, val=1000)
    await pd_write(dut, PD[0])    # sram[0]=0x0001

    # Manual WB read — capture dat_o both during ACK AND after idle
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SPIKE_LO

    dat_during_ack = None
    for _ in range(5):
        await RisingEdge(dut.wb_clk_i)
        if dut.wbs_ack_o.value == 1:
            dat_during_ack = int(dut.wbs_dat_o.value)
            break

    assert dat_during_ack is not None, "T7 FAIL: no ACK received"
    assert dat_during_ack != 0, \
        f"T7 FAIL: pre-condition — dat_o during ACK should be non-zero, got 0x{dat_during_ack:08X}"

    # De-assert bus
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0

    # One posedge with cyc=0: RTL's else branch fires → dat_o <= 0
    await RisingEdge(dut.wb_clk_i)
    await FallingEdge(dut.wb_clk_i)
    dat_after_idle = int(dut.wbs_dat_o.value)

    assert dat_after_idle == 0, \
        f"T7 FAIL: dat_o exp 0 after idle, got 0x{dat_after_idle:08X}"
    dut._log.info(
        f"T7 PASS: dat_o=0x{dat_during_ack & 0xFFFF:04X} during ACK → 0x{dat_after_idle:08X} after idle"
    )


# ---------------------------------------------------------------------------
# T8 — test_partial_picture_done
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_partial_picture_done(dut):
    """
    Issue picture_done for groups 0 and 1 only.
    sram[0] and sram[1] must be updated; sram[2] and sram[3] must retain reset value (0).
    """
    await setup_dut(dut)

    # Trigger bits 0-3 in groups 0,1.
    await nvm_program(dut, row=0, col=0, data16=0x000F)
    await nvm_inject(dut, row=0, col=0, val=1000)
    await pd_write(dut, PD[0])  # sram[0] = 0x000F

    await nvm_program(dut, row=8, col=0, data16=0x000F)
    await nvm_inject(dut, row=8, col=0, val=1000)
    await pd_write(dut, PD[1])  # sram[1] = 0x000F
    # sram[2], sram[3] never written → remain 0x0000 from hardware reset

    lo = await wb_read(dut, SPIKE_LO)
    hi = await wb_read(dut, SPIKE_HI)

    sram0 = lo & 0xFFFF
    sram1 = (lo >> 16) & 0xFFFF
    sram2 = hi & 0xFFFF
    sram3 = (hi >> 16) & 0xFFFF

    assert sram0 == 0x000F, f"T8 FAIL: sram[0] exp 0x000F (latched), got 0x{sram0:04X}"
    assert sram1 == 0x000F, f"T8 FAIL: sram[1] exp 0x000F (latched), got 0x{sram1:04X}"
    assert sram2 == 0x0000, f"T8 FAIL: sram[2] exp 0x0000 (never written), got 0x{sram2:04X}"
    assert sram3 == 0x0000, f"T8 FAIL: sram[3] exp 0x0000 (never written), got 0x{sram3:04X}"
    dut._log.info("T8 PASS: partial picture_done — unaddressed sram slots retain prior values")


