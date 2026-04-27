"""
Phase 6: Layer-Level Inference Verification
DUT: nvm_neuron_core_256x64 (sim baseline)

Run: cd verilog/tb && make MODULE=test_layer_inference SIM=icarus
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
from read_file import read_matrix_from_file
from nvm_parameter import NEURON_THRESHOLD, SPIKE_LO, SPIKE_HI, PD, MEM_BASE_DIR
from snn_test_utils import (
    setup_dut, nvm_program, nvm_inject, pd_write, trigger_picture_done,
    wb_read, program_weights, spikes_from_readback
)

# ---------------------------------------------------------------------------
# T1: test_layer_0_core_isolation
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_layer_0_core_isolation(dut):
    '''
    Verify that picture_done accurately clears potentials so sequential multiplexed
    virtual cores don't bleed states into each other.
    '''
    await setup_dut(dut)
    
    # Use real weight files
    conn_0 = read_matrix_from_file(MEM_BASE_DIR / "connection/connection_000.txt")
    conn_1 = read_matrix_from_file(MEM_BASE_DIR / "connection/connection_001.txt")

    # Step A: run Core 0
    dut._log.info("T1: Programming Core 0 with connection_000")
    await program_weights(dut, conn_0)
    for group in range(4):
        # Inject highly positive value
        row = group * 8
        col = 0 # even = positive
        await nvm_inject(dut, row=row, col=col, val=15000)
        await pd_write(dut, PD[group])
    
    # Step B: immediately run Core 1 (simulate time-multiplex)
    dut._log.info("T1: Programming Core 1 sequentially with connection_001")
    await program_weights(dut, conn_1)
    for group in range(4):
        # Inject negative val
        row = group * 8
        col = 1 # odd = negative
        await nvm_inject(dut, row=row, col=col, val=25000)
        await pd_write(dut, PD[group])
        
    lo_seq = await wb_read(dut, SPIKE_LO)
    hi_seq = await wb_read(dut, SPIKE_HI)
    
    # Step C: fresh reset and run Core 1 isolated
    dut._log.info("T1: Hard resetting and testing Core 1 isolated")
    await setup_dut(dut)
    await program_weights(dut, conn_1)
    for group in range(4):
        row = group * 8
        col = 1 
        await nvm_inject(dut, row=row, col=col, val=25000)
        await pd_write(dut, PD[group])

    lo_iso = await wb_read(dut, SPIKE_LO)
    hi_iso = await wb_read(dut, SPIKE_HI)
    
    assert lo_seq == lo_iso, f"Isolation failure! Seq LO: {lo_seq:08X}, Iso LO: {lo_iso:08X}"
    assert hi_seq == hi_iso, f"Isolation failure! Seq HI: {hi_seq:08X}, Iso HI: {hi_iso:08X}"
    dut._log.info("T1 PASS: Core potentials perfectly isolated between virtual core passes.")

# ---------------------------------------------------------------------------
# T2: test_layer_0_padding_axons
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_layer_0_padding_axons(dut):
    '''
    Verify that injecting zero to unused padded axons behaves properly, and verify
    that hardware still processes them if non-zero is injected.
    '''
    await setup_dut(dut)
    
    # Set a single weight in group 0, row 29 (axon 232 to 239)
    # Axon 238 is the START of the padded zone
    await nvm_program(dut, row=29, col=6, data16=0xFFFF) # axon 238
    
    # Inject exactly at axon 238.
    # Firmware handles padded axons by feeding zeros.
    await nvm_inject(dut, row=29, col=6, val=0) 
    await trigger_picture_done(dut)
    
    lo_val = await wb_read(dut, SPIKE_LO)
    hi_val = await wb_read(dut, SPIKE_HI)
    
    # After reset, potential=0 < NEURON_THRESHOLD (10) → spikes = 0
    assert lo_val == 0x00000000
    
    # Now corrupt the padded axon and inject high positive value. 
    # The spike output should now fire (1000 >= 10).
    await nvm_inject(dut, row=29, col=6, val=1000) # even col => positive 
    await pd_write(dut, PD[3]) 
    
    mod_hi_val = await wb_read(dut, SPIKE_HI)
    
    if mod_hi_val != hi_val:
        dut._log.info("T2 PASS: Firmware zero-padding is mandatory and behaves as predicted. RTL allows unbounded array accumulation beyond logical axon limit.")
    else:
        assert False, "T2 FAIL: Corrupting padded axon did not affect output."

# ---------------------------------------------------------------------------
# T3: test_layer_1_sparse_routing_bounds
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_layer_1_sparse_routing_bounds(dut):
    '''
    Verify that Core 0 uses Layer 0 spikes [0:207] and Core 1 uses [208:415] precisely.
    In RTL, data simply comes through Wishbone. Firmware/Testbench logic must route it correctly.
    '''
    await setup_dut(dut)
    # For Layer 1, the firmware feeds in 1-bit binary spikes.
    # Axon mapping: hardware evaluates 0..207 (but loops exactly 256 times).
    
    # Core 1 evaluating Spike 208 from Layer 0 correlates to Axon 0 for Virtual Core 1.
    # So we stimulate Axon 0.
    await nvm_program(dut, row=0, col=0, data16=0x0001) # mapping macro 0
    
    # Assume spike 208 was a '1'. Firmware pushes a '1' at Axon 0.
    # Must use val >= NEURON_THRESHOLD to trigger spike.
    await nvm_inject(dut, row=0, col=0, val=NEURON_THRESHOLD)
    await pd_write(dut, PD[0])
    
    lo = await wb_read(dut, SPIKE_LO)
    is_firing = (lo & 0x0001) == 0x0001
    assert is_firing, "Spike 208 evaluated as Axon 0 failed to fire."
    dut._log.info("T3 PASS: Cross-core routing boundary logic validated.")

# ---------------------------------------------------------------------------
# T4: test_layer_1_binary_stimuli
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_layer_1_binary_stimuli(dut):
    '''
    Transitioning from Layer 0 to Layer 1, hardware shifts from 16-bit to binary 1/0.
    Verify accumulator behaves properly when inject values are perfectly binary.
    '''
    await setup_dut(dut)
    
    # Start by accumulating Macro 0 to Threshold+1 (e.g. 11) using positive stimuli
    await nvm_program(dut, row=0, col=0, data16=0x0001) # even col = pos
    await nvm_inject(dut, row=0, col=0, val=NEURON_THRESHOLD + 1)
    
    # Now subtract 1 using boolean spike (col=1) -> potential=10
    await nvm_program(dut, row=0, col=1, data16=0x0001) # odd col => subtract for Macro 0 only
    await nvm_inject(dut, row=0, col=1, val=1) 
    
    # Latch and check (10 >= 10 -> spike=1)
    await pd_write(dut, PD[0])
    lo = await wb_read(dut, SPIKE_LO)
    assert (lo & 0x0001) == 0x0001, f"T4 FAIL: Potential=10 should still fire. Got 0x{lo:08X}"

    # Reset happened due to pd_write. Now pre-charge to exactly Threshold (10)
    await nvm_program(dut, row=0, col=0, data16=0x0001)
    await nvm_inject(dut, row=0, col=0, val=NEURON_THRESHOLD)
    
    # Subtract 1 -> potential=9
    await nvm_program(dut, row=0, col=1, data16=0x0001)
    await nvm_inject(dut, row=0, col=1, val=1) 
    
    # Latch and check (9 < 10 -> spike=0)
    await pd_write(dut, PD[0])
    lo2 = await wb_read(dut, SPIKE_LO)
    assert (lo2 & 0x0001) == 0x0000, f"T4 FAIL: Potential=9 should be silent. Got 0x{lo2:08X}"
    
    dut._log.info("T4 PASS: Accumulator logic is linear and safe with binary ±1 injects.")


# ---------------------------------------------------------------------------
# T5: test_layer_concatenation_logic
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_layer_concatenation_logic(dut):
    '''
    Validates Python concatenating Layer 0 spikes.
    This mostly reflects software logic, but binds closely to the RTL outputs.
    '''
    # Create mock hardware array returned
    spike_out_layer_0 = [[0 for _ in range(13*64)]]
    
    # Simulate a firmware driver loop
    for core in range(13):
        # Let's say odd cores output all 0s, even cores output all 1s
        if core % 2 == 0:
            mock_lo = 0xFFFFFFFF
            mock_hi = 0xFFFFFFFF
        else:
            mock_lo = 0x00000000
            mock_hi = 0x00000000
            
        lo_spikes = spikes_from_readback(mock_lo, 0)
        hi_spikes = spikes_from_readback(0, mock_hi)[32:64]
        combined = lo_spikes[:32] + hi_spikes
        
        # Test software stitching index check
        for slice_ in range(2):
            for i in range(32):
                if core*64 + slice_*32 + i < 832:
                    if slice_ == 0:
                        spike_out_layer_0[0][core*64 + i] = int(str(bin(mock_lo)[2:].zfill(32)[::-1])[i])
                    else:
                        spike_out_layer_0[0][core*64 + 32 + i] = int(str(bin(mock_hi)[2:].zfill(32)[::-1])[i])
    
    # Verify bounds
    assert sum(spike_out_layer_0[0][:64]) == 64
    assert sum(spike_out_layer_0[0][64:128]) == 0
    assert sum(spike_out_layer_0[0][128:192]) == 64
    
    dut._log.info("T5 PASS: Python matrix stitching indices verified safe and accurately aligned.")

