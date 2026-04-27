"""
Mixed-Signal Co-Simulation: Analog ReRAM Physics → Digital LIF Verilog

This test bridges two simulation domains:
  - Analog domain: Samarth's ReRAM physics model (rram_neuron_model) computes
    conductance values for LRS/HRS states at different ages.
  - Digital domain: conductance is mapped to a 16-bit integer weight and injected
    into the cocotb Verilog DUT (nvm_neuron_block or equivalent).

Three scenarios are exercised:
  A. Fresh LRS  — high conductance → large weight → neuron should fire rapidly.
  B. Relaxed LRS — conductance decays after 2000 s → slower firing.
  C. HRS        — low conductance → small weight → little or no firing.

Requires rram_neuron_model to be installed or on PYTHONPATH.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# Analog physics model — conductance(age, state) and readout gain constant
from rram_neuron_model import conductance_at_age, RRAMModelParams

@cocotb.test()
async def test_hybrid_snn_reram(dut):
    """Mixed-Signal Co-simulation: Analog ReRAM physics driving Digital LIF Verilog"""
    
    # 1. Initialize Samarth's Physics Model
    params = RRAMModelParams()
    
    # Calculate physical conductance for 3 different scenarios:
    # Scenario A: Freshly programmed Low-Resistance State (High Conductance)
    g_fresh = conductance_at_age(age_s=0.0, state="LRS", modulation="ramp")
    
    # Scenario B: Relaxed state after 2000 seconds (Medium Conductance)
    g_relaxed = conductance_at_age(age_s=2000.0, state="LRS", modulation="ramp")
    
    # Scenario C: High-Resistance State (Low Conductance)
    g_hrs = conductance_at_age(age_s=0.0, state="HRS", modulation="ramp")

    # Convert analog conductance to digital 16-bit integer stimuli using his gain
    weight_fresh = int(g_fresh * params.readout_gain)
    weight_relaxed = int(g_relaxed * params.readout_gain)
    weight_hrs = int(g_hrs * params.readout_gain)

    dut._log.info(f"--- ReRAM Physics Mapped to Digital Weights ---")
    dut._log.info(f"Fresh LRS Weight: {weight_fresh}")
    dut._log.info(f"Relaxed LRS Weight: {weight_relaxed}")
    dut._log.info(f"HRS Weight: {weight_hrs}")
    dut._log.info(f"-----------------------------------------------")

    # 2. Start the Digital Clock
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # 3. Reset the Verilog Chip
    dut.rst.value = 1
    dut.enable.value = 0
    dut.picture_done.value = 0
    dut.stimuli.value = 0
    dut.connection.value = 15 # Connect all 4 neurons
    await Timer(20, units="ns")
    dut.rst.value = 0
    dut.enable.value = 1
    await RisingEdge(dut.clk)

    # Helper function to inject a burst of spikes
    async def inject_burst(weight, name):
        dut._log.info(f"Testing {name} (Weight: {weight})")
        for _ in range(15): # 15 pulses
            dut.stimuli.value = weight
            await RisingEdge(dut.clk)
            dut.stimuli.value = 0
            # Wait 3 cycles between pulses to allow for leakage
            await RisingEdge(dut.clk)
            await RisingEdge(dut.clk)
            await RisingEdge(dut.clk)
        
        # Long pause between tests to let potential drain completely
        await Timer(100, units="ns") 

    # 4. Run the 3 Mixed-Signal Tests!
    await inject_burst(weight_fresh, "Fresh LRS (Should fire rapidly)")
    await inject_burst(weight_relaxed, "Relaxed LRS (Should fire slower)")
    await inject_burst(weight_hrs, "HRS (Should barely fire or not at all)")

    dut._log.info("Hybrid Simulation Complete. Check the waveforms!")