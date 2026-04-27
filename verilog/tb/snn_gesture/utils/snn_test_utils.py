"""
Shared cocotb test utilities for SNN neuromorphic core verification.

All helper functions and address constants used across Phase 1-7 test files
are consolidated here to eliminate duplication.

Usage in test files:
    from snn_test_utils import (
        setup_dut, nvm_program, nvm_inject, pd_write,
        trigger_picture_done, wb_read, spikes_from_readback,
        program_weights, to_signed16, get_potential,
        lif_step, lif_spike, PotentialMonitor
    )
    from nvm_parameter import SYNAPSE_ADDR, SPIKE_LO, SPIKE_HI, PD
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from nvm_parameter import (
    PERIOD, MODE_PROGRAM, MODE_READ, WR_Dly, RD_Dly,
    SYNAPSE_ADDR, SPIKE_LO, SPIKE_HI, PD,
    NEURON_THRESHOLD, NEURON_LEAK_SHIFT,
    NUM_NEURONS_LAYER_0, NUM_NEURON,
)

try:
    from read_file import list_to_binary
except ImportError:
    list_to_binary = None  # not available in all test contexts


# ---------------------------------------------------------------------------
# DUT Setup
# ---------------------------------------------------------------------------

async def setup_dut(dut):
    """Tie off analog/scan pins, idle bus, apply and release reset.

    Drain phase: the Neuromorphic_X1_beh engine has no reset path.
    Any in-flight PROGRAM or READ from a prior test keeps running.
    Hold rst=0 for WR_Dly+RD_Dly+10 cycles so the worst-case queued
    back-to-back operation can flush before reset fires.
    """
    for name in ["Iref", "Vcc_read", "Vcomp", "Bias_comp2", "Vcc_wl_read",
                 "Vcc_wl_set", "Vbias", "Vcc_wl_reset", "Vcc_set",
                 "Vcc_reset", "Vcc_L", "Vcc_Body"]:
        getattr(dut, name).value = 0
    dut.ScanInCC.value = 0
    dut.ScanInDL.value = 0
    dut.ScanInDR.value = 0
    dut.TM.value       = 0

    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = 0
    dut.wbs_dat_i.value = 0

    cocotb.start_soon(Clock(dut.wb_clk_i, PERIOD, units="ns").start())

    # Drain: let any stale engine operation from a previous failed test finish.
    # Worst-case in-flight: PROGRAM (WR_Dly) + READ (RD_Dly) queued back-to-back.
    dut.wb_rst_i.value = 0
    await ClockCycles(dut.wb_clk_i, WR_Dly + RD_Dly + 10)

    # Clean reset
    dut.wb_rst_i.value = 1
    await ClockCycles(dut.wb_clk_i, 5)
    dut.wb_rst_i.value = 0
    await ClockCycles(dut.wb_clk_i, 2)


# ---------------------------------------------------------------------------
# Wishbone / Synapse Helpers
# ---------------------------------------------------------------------------

async def nvm_program(dut, row, col, data16):
    """PROGRAM synapse weight via MODE_PROGRAM. No ACK. Waits 2×WR_Dly+1."""
    pkt = (MODE_PROGRAM << 30) | (row << 25) | (col << 20) | (data16 & 0xFFFF)
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = pkt
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0
    await ClockCycles(dut.wb_clk_i, 2 * WR_Dly + 1)


async def nvm_inject(dut, row, col, val):
    """Two-step inject: enqueue READ → wait RD_Dly → pop (fires enable → neuron integrates).

    Step 1 – WB WRITE with MODE_READ: enqueues READ into X1 op_fifo.
    Step 2 – WB READ at SYNAPSE_ADDR: pops op_fifo result → fires core_ack=1 → enable → integrate.
    """
    pkt = (MODE_READ << 30) | (row << 25) | (col << 20) | (val & 0xFFFF)
    # Step 1: enqueue READ command
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    dut.wbs_dat_i.value = pkt
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0
    await ClockCycles(dut.wb_clk_i, RD_Dly + 2)
    # Step 2: pop result → fires enable
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = SYNAPSE_ADDR
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_sel_i.value = 0xF
    await ClockCycles(dut.wb_clk_i, 2)


async def pd_write(dut, pd_addr):
    """Issue one picture_done write to the given address."""
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 1
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = pd_addr
    dut.wbs_dat_i.value = 0
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value  = 0
    await ClockCycles(dut.wb_clk_i, 3)


async def trigger_picture_done(dut):
    """Write to all 4 picture_done addresses to latch and reset all 64 neurons."""
    for addr in PD:
        await pd_write(dut, addr)


async def wb_read(dut, address):
    """WB read with ACK poll (5-cycle timeout). Returns int dat_o."""
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value  = 0
    dut.wbs_sel_i.value = 0xF
    dut.wbs_adr_i.value = address
    val = None
    for _ in range(5):
        await RisingEdge(dut.wb_clk_i)
        if dut.wbs_ack_o.value == 1:
            val = int(dut.wbs_dat_o.value)
            break
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    assert val is not None, f"No ACK for WB read at {hex(address)}"
    return val


# ---------------------------------------------------------------------------
# Spike / Weight Helpers
# ---------------------------------------------------------------------------

def spikes_from_readback(lo, hi):
    """Unpack two 32-bit spike words into a 64-element spike list (LSB first)."""
    spikes = []
    for word in [lo, hi]:
        for bit in range(32):
            spikes.append((word >> bit) & 1)
    return spikes


async def program_weights(dut, connection_data, layer_neurons=NUM_NEURON):
    """Program all 32×32 cells from connection_data.

    connection_data: list of binary strings (one per axon, MSB-first, 64 chars each).
    layer_neurons:   total neuron count for the layer (determines slice indexing).
    """
    assert list_to_binary is not None, "read_file.list_to_binary is required for program_weights"
    for row in range(32):
        for col in range(32):
            axon        = (row & 0x07) * 32 + col
            neuron_base = ((row >> 3) & 0x03) * 16
            val_slice   = connection_data[axon][
                layer_neurons - (neuron_base + 16) : layer_neurons - neuron_base
            ]
            data16 = list_to_binary(val_slice)
            await nvm_program(dut, row, col, data16)


# ---------------------------------------------------------------------------
# LIF Reference Model
# ---------------------------------------------------------------------------

def to_signed16(v):
    """Convert unsigned 16-bit integer to Python signed int."""
    return v if v < 0x8000 else v - 0x10000


def get_potential(dut, idx):
    """Read neuron potential[idx] from DUT as signed 16-bit integer."""
    return to_signed16(int(dut.neuron_block_inst.potential[idx].value))


def lif_step(potential, stimuli):
    """Single LIF integration step with symmetric leak and saturation.

    Matches updated RTL (nvm_neuron_block.v):
    1. Symmetric Leak: Rounding toward zero prevents negative bias inherent in
       arithmetic right-shifts of negative numbers.
    2. Saturation: Clamps result to the 16-bit signed range [-32768, 32767]
       to prevent wrap-around.

    Args:
        potential (int): current signed 16-bit potential
        stimuli (int): signed 16-bit stimulus contribution

    Returns:
        int: updated signed 16-bit potential
    """
    # Symmetric leak: rounding toward zero
    leak_mag = abs(potential) >> NEURON_LEAK_SHIFT
    leak = leak_mag if potential >= 0 else -leak_mag

    # Calculate next potential (intermediate result)
    next_pot = potential - leak + stimuli

    # 16-bit signed saturation (clamp)
    if next_pot > 32767:
        return 32767
    elif next_pot < -32768:
        return -32768
    else:
        return next_pot


def lif_spike(potential):
    """Return 1 if potential >= NEURON_THRESHOLD, else 0."""
    return 1 if potential >= NEURON_THRESHOLD else 0


# ---------------------------------------------------------------------------
# Overflow Monitoring
# ---------------------------------------------------------------------------

class PotentialMonitor:
    """Reusable coroutine to track neuron potential bounds during a test.

    Usage:
        monitor = PotentialMonitor()
        cocotb.start_soon(monitor.run(dut))
        # ... run test ...
        monitor.report(dut)   # log summary
        monitor.check_bounds()  # assert no overflow

    The monitor logs a warning immediately when any potential gets near the
    16-bit signed boundary (> 30000 or < -30000), giving per-event visibility
    in the cocotb test log. check_bounds() can then be called to assert the
    hardware never actually overflowed.
    """

    OVERFLOW_WARN_THRESHOLD = 30000  # warn when |potential| > this

    def __init__(self):
        self.max_observed = -999999
        self.min_observed = 999999
        self.overflow_events = []  # list of (sim_time_ns, neuron_idx, value)

    async def run(self, dut):
        """Run as a background coroutine: cocotb.start_soon(monitor.run(dut))."""
        while True:
            await RisingEdge(dut.wb_clk_i)
            for i in range(16):
                try:
                    raw = int(dut.neuron_block_inst.potential[i].value)
                except Exception:
                    continue
                pot = raw if raw < 0x8000 else raw - 0x10000
                if pot > self.max_observed:
                    self.max_observed = pot
                if pot < self.min_observed:
                    self.min_observed = pot
                if abs(pot) > self.OVERFLOW_WARN_THRESHOLD:
                    sim_time = cocotb.utils.get_sim_time(units='ns')
                    dut._log.warning(
                        f"OVERFLOW RISK: neuron[{i}] potential={pot} at {sim_time}ns "
                        f"(within {32767 - abs(pot)} of 16-bit signed boundary)"
                    )
                    self.overflow_events.append((sim_time, i, pot))

    def report(self, dut):
        """Log a summary of observed potential bounds and any overflow events."""
        dut._log.info(
            f"PotentialMonitor summary: max={self.max_observed}, min={self.min_observed}, "
            f"overflow_risk_events={len(self.overflow_events)}"
        )
        if self.overflow_events:
            dut._log.warning(
                f"  First overflow-risk event: neuron[{self.overflow_events[0][1]}] "
                f"potential={self.overflow_events[0][2]} at {self.overflow_events[0][0]}ns"
            )

    def check_bounds(self):
        """Assert that no 16-bit signed overflow occurred during the monitored period."""
        assert self.max_observed <= 32767, \
            f"Potential overflow: max observed {self.max_observed} exceeded +32767"
        assert self.min_observed >= -32768, \
            f"Potential overflow: min observed {self.min_observed} below -32768"
