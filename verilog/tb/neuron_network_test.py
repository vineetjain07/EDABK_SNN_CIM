import os
import sys
from pathlib import Path

import cocotb
from rram_neuron_model import conductance_at_age
# from cocotb.binary import BinaryRepresentation, BinaryValue
from cocotb.triggers import Timer
from cocotb.clock import Clock
from cocotb.handle import SimHandleBase
from cocotb.queue import Queue
# from cocotb.runner import get_runner
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, Join
from nvm_parameter import *
from read_file import *


BASE_DIR = "./mem/connection"
INPUT_FILE = "./mem/stimuli/stimuli.txt"
# --- Helper Functions for Wishbone and NVM Access ---

# Wishbone Write: Used to send control or configuration data to the DUT.
async def wishbone_write(dut, address, data):
    """
    Performs a Wishbone write transaction.
    
    The transaction is:
    1. Drive signals on positive clock edge.
    2. De-assert signals on the next positive clock edge.
    3. Wait for one falling edge (optional, often used for cycle completion).
    """
    # Cycle 1: Assert request signals
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1       # Cycle valid
    dut.wbs_stb_i.value = 1       # Strobe (data valid)
    dut.wbs_we_i.value = 1        # Write enable
    dut.wbs_sel_i.value = 0b1111  # Byte select (all bytes enabled for 32-bit write)
    dut.wbs_adr_i.value = address # Address
    dut.wbs_dat_i.value = data    # Write data

    # Cycle 2: De-assert request signals
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value = 0
    dut.wbs_sel_i.value = 0b0000

    # Wait for completion (often necessary depending on DUT design)
    await FallingEdge(dut.wb_clk_i)

# Wishbone Read: Used for reading spikes out or output packets from the last core.
async def wishbone_read(dut, address, spike_o_matrix=None, pic=0, slice_idx=0, layer=0, core=0):
    """
    Performs a Wishbone read transaction.
    
    The transaction is:
    1. Assert request signals (read enable = 0) on positive clock edge.
    2. De-assert signals on the next positive clock edge.
    3. Read data on the falling edge after the de-assertion.
    
    If spike_o_matrix is provided, it extracts spike data from the read value.
    """
    # Cycle 1: Assert request signals
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1       # Cycle valid
    dut.wbs_stb_i.value = 1       # Strobe (data valid)
    dut.wbs_we_i.value = 0        # Read enable (Write enable is 0)
    dut.wbs_sel_i.value = 0b1111  # Byte select
    dut.wbs_adr_i.value = address # Address
    dut.wbs_dat_i.value = 0       # Don't care for read

    # Cycle 2: De-assert request signals
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_sel_i.value = 0
        
    # Wait for data to be stable (assuming data is valid after de-assertion)
    await FallingEdge(dut.wb_clk_i)
    
    # Read the output data from the DUT
    # The output spike is expected to be reversed (LSB first) for easier indexing.
    # Assumes dut.wbs_dat_o.value returns a BinaryValue
    output_spike = dut.wbs_dat_o.value.binstr[::-1] if hasattr(dut.wbs_dat_o.value, 'binstr') else str(dut.wbs_dat_o.value)[::-1] 
    
    # If a spike matrix is provided, parse and store the spike outputs
    if spike_o_matrix is not None:
        # NUM_NEURON_PER_SLICE must be the number of bits in output_spike
        for i in range(NUM_NEURON_PER_SLICE):
            # Calculate the global neuron index in the layer's output matrix
            global_neuron_index = core * NUM_NEURON + slice_idx * NUM_NEURON_PER_SLICE + i
            # Store the spike (0 or 1)
            spike_o_matrix[pic][global_neuron_index] = int(output_spike[i])

# NVM Write: Performs a Wishbone write with an additional delay for Non-Volatile Memory (NVM) programming.
async def nvm_write(dut, address, data):
    """
    Performs a Write operation to the NVM block, incorporating the NVM programming delay.
    """
    async def drive_wishbone():
        # Wishbone transaction setup
        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 1
        dut.wbs_stb_i.value = 1
        dut.wbs_we_i.value = 1
        dut.wbs_sel_i.value = 0b1111
        dut.wbs_adr_i.value = address
        dut.wbs_dat_i.value = data

        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 0
        dut.wbs_stb_i.value = 0
        dut.wbs_we_i.value = 0
        dut.wbs_sel_i.value = 0

    async def wait_for_delay():
        # Wait for the NVM Write Delay (WR_Dly) to ensure programming completes
        await ClockCycles(dut.wb_clk_i, (2 * WR_Dly + 1))

    # Start the Wishbone drive and the delay concurrently
    drive_task = cocotb.start_soon(drive_wishbone())
    delay_task = cocotb.start_soon(wait_for_delay())

    # Wait for both tasks to complete (drive_task finishes quickly, delay_task takes time)
    await drive_task
    await delay_task

# NVM Read: Performs a pseudo-write (for command/stimulus) followed by an NVM Read operation.
async def nvm_read(dut, addr, data):
    """
    Performs a Read operation from the NVM block, consisting of:
    1. A 'Write' phase to configure the address/stimulus (no NVM write delay needed here).
    2. A delay for NVM Read access time (RD_Dly).
    3. A subsequent 'Read' phase to get the data.
    """
    async def operation_1_write():
        # Phase 1: 'Write' operation to set up command/stimulus (like a configuration write)
        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 1
        dut.wbs_stb_i.value = 1
        dut.wbs_we_i.value = 1
        dut.wbs_sel_i.value = 0xF
        dut.wbs_adr_i.value = addr
        dut.wbs_dat_i.value = data

        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 0
        dut.wbs_stb_i.value = 0
        dut.wbs_we_i.value  = 0
        dut.wbs_sel_i.value = 0

    async def operation_2_read_after_delay():
        # Wait for the NVM Read Delay (RD_Dly)
        await ClockCycles(dut.wb_clk_i, (RD_Dly + 2))

        # Phase 2: 'Read' operation
        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 1
        dut.wbs_stb_i.value = 1
        dut.wbs_we_i.value  = 0 # Read: we_i = 0
        dut.wbs_sel_i.value = 0xF
        dut.wbs_adr_i.value = addr # Re-assert address
        # dut.wbs_dat_i.value is don't care for read

        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 0
        dut.wbs_stb_i.value = 0
        dut.wbs_sel_i.value = 0

    # Start the two operations sequentially (task_1 must finish before task_2 can proceed past the delay)
    task_1 = cocotb.start_soon(operation_1_write())
    await task_1 
    
    task_2 = cocotb.start_soon(operation_2_read_after_delay())
    await task_2

# --- Testbench Functions ---

def get_connection_file_path(base_dir, index, part=None):
    """Constructs the full path for a connection file."""
    if part:
        filename = f"connection_{index:03}_part{part}.txt"
    else:
        filename = f"connection_{index:03}.txt"
    # NOTE: Hardcoded base path should ideally be an environment variable or argument
    return f"{base_dir}/{filename}"

def load_connection_matrices(base_path):
    """Loads all connection matrices into a dictionary."""
    print("Loading connection files...")
    connection_matrices = {}
    
    # Layer 0 connections (0 to 12)
    for i in range(13):
        path = get_connection_file_path(base_path, i)
        connection_matrices[i] = read_matrix_from_file(path)
        
    # Layer 1 connections (13 to 16)
    for i in range(13, 17):
        path = get_connection_file_path(base_path, i)
        connection_matrices[i] = read_matrix_from_file(path)
        
    # Layer 2 connection (index 26 parts 1 to 4)
    for part in range(1, 5):
        index = 26 + part / 10 # Using float key temporarily
        path = get_connection_file_path(base_path, 26, part)
        connection_matrices[index] = read_matrix_from_file(path)
        
    return connection_matrices

async def program_layer_connections(dut, core_idx, layer_conn, NUM_NEURON_LAYER):
    """
    Programs the connection weights for a single core in a layer.
    **INJECTS REAL-WORLD RRAM PHYSICS DECAY BEFORE WRITING**
    """
    for row_i in range(32):
        for col_i in range(32):
            row = row_i
            col = col_i
            
            axon_group = (row & 0x07) * 32 
            axon = axon_group + col 
            
            neuron_index_group = (row >> 3) & 0x03
            neuron = neuron_index_group * 16 
            
            # Get the ideal, perfect bits from the text file
            val_slice = layer_conn[axon][NUM_NEURON_LAYER - (neuron + 16):NUM_NEURON_LAYER - neuron] 
            
            # --- APPLY RRAM DECAY PHYSICS ---
            simulation_age_s = 5000.0 # Age the chip by 5,000 seconds
            read_threshold = 1.1      # Normalized conductance threshold to read a '1'
            
            degraded_slice = []
            for ideal_bit in val_slice:
                if ideal_bit == 1:
                    # Calculate exactly how much the memory has leaked over 5,000 seconds
                    g_final = conductance_at_age(age_s=simulation_age_s, state="LRS", modulation="ramp")
                    
                    # Does the decayed conductance still cross the read threshold?
                    if g_final >= read_threshold:
                        degraded_slice.append(1)
                    else:
                        degraded_slice.append(0) # BIT FLIP ERROR! The memory leaked too much.
                else:
                    degraded_slice.append(0) # HRS stays 0
            
            # Convert the degraded array back into a number for the Wishbone bus
            int_val = list_to_binary(degraded_slice)
            # --------------------------------
            
            data_to_write = (
                (MODE_PROGRAM << 30) |  
                (row            << 25) |  
                (col            << 20) |  
                (0              << 16) |  
                (int_val)                 
            )

            await nvm_write(dut, 0x30000000, data_to_write)
            
async def run_layer_for_all_pics(dut, core_idx, layer, num_cores, spike_in_matrix, spike_out_matrix, stimuli=None, layer_axon_limit=None):
    """
    Runs the simulation for all input pictures for a specific core (EVERY PIC step).
    
    This corresponds to the 'MODE_READ' operation (stimulus application).
    """
    for pic in range(SUM_OF_PICS):
        print(f"Layer {layer} - Core {core_idx} - Pic {pic}")
        
        # Iterate over the NVM array structure
        for row_i in range(32):
            for col_i in range(32):
                row = row_i
                col = col_i
                
                # Axon index calculation
                axon = ((row & 0x07) * 32) + col 
                
                # Check for axon limit specific to the layer (e.g., if the layer has fewer than 256 inputs)
                if layer_axon_limit is not None and axon >= layer_axon_limit:
                    continue 
                
                # Neuron index calculation (not used directly here, but for completeness)
                # neuron = ((row >> 3) & 0x03) * 16 
                
                spike_active = False
                val_slice = 0
                
                # Input stimuli (spike_in) depends on the layer:
                if layer == 0:
                    # Layer 0: Input comes from the stimuli file
                    stimuli_val = stimuli[axon // 2]  # Axons are grouped into pairs (32-bit stimuli value)
                    full_stimuli_val = list_to_binary(stimuli_val)
                    
                    if (axon % 2) == 0:
                        # Even axon: Take the upper 16 bits [31:16]
                        val_slice = (full_stimuli_val >> 16) & 0xFFFF
                    else:
                        # Odd axon: Take the lower 16 bits [15:0]
                        val_slice = full_stimuli_val & 0xFFFF
                        
                    # For Layer 0, the 'spike_active' condition is implicitly handled by the input value `val_slice` 
                    # being written into the `data_for_read_op` field. The Verilog module likely uses this value directly.
                    spike_active = True # Always 'active' since we're providing the stimulus slice
                    
                else:
                    # Layers 1 and 2: Input comes from the previous layer's spike output
                    input_index = axon # Local axon index
                    if layer == 1:
                        # Layer 1's input comes from the global L0 output matrix, indexed by (core * NUM_AXON_LAYER_1 + axon)
                        global_input_index = core_idx * layer_axon_limit + input_index
                        spike_active = (spike_in_matrix[pic][global_input_index] == 1)
                    elif layer == 2:
                        # Layer 2's input comes from the global L1 output matrix, indexed by (axon)
                        spike_active = (spike_in_matrix[pic][input_index] == 1)
                    
                    # For L1/L2, the actual data written is just '1' if a spike occurred, 
                    # signifying an active input for the read operation.
                    val_slice = 1 if spike_active else 0
                
                
                if spike_active:
                    # Construct the 32-bit data word for NVM Read Operation (stimulus application)
                    # {MODE_READ(2), row(5), col(5), padding(4), stimulus_data(16)}
                    data_for_read_op = (
                        (MODE_READ << 30) |  # 2 MSBs for MODE
                        (row         << 25) |  # 5 bits for row index
                        (col         << 20) |  # 5 bits for column index
                        (0           << 16) |  # 4 bits padding (0)
                        (val_slice)             # 16 LSBs for stimulus data (or just '1' for spike)
                    )
                    
                    await nvm_read(dut, 0x30000000, data_for_read_op)

                # Control Register Writes (e.g., resetting internal slice/neuron logic after an NVM row sweep)
                # These addresses (0x3000200x) likely correspond to control registers for neuron slices.
                # The writes happen after every NVM array row group (e.g., after rows 7, 15, 23, 31)
                if col == 31:
                    if row == 7:
                        await wishbone_write(dut, 0x30002000, 0)
                    elif row == 15:
                        await wishbone_write(dut, 0x30002002, 0)
                    elif row == 23:
                        await wishbone_write(dut, 0x30002004, 0)
                    elif row == 31:
                        await wishbone_write(dut, 0x30002006, 0)

        # Read the output spikes from the two slices of the core after processing all inputs
        await wishbone_read(dut, 0x30001000, spike_out_matrix, pic, slice_idx=0, layer=layer, core=core_idx)
        await wishbone_read(dut, 0x30001004, spike_out_matrix, pic, slice_idx=1, layer=layer, core=core_idx) 

# --- Cocotb Test ---

@cocotb.test()
async def neuron_network_test(dut): 
    # Determine the base directory for input files (assuming a fixed structure)
    base_dir = BASE_DIR
    
    # Load all connection matrices efficiently
    connection_matrices = load_connection_matrices(base_dir)
    
    # Load stimuli and correct output files
    stimuli = read_matrix_from_file(INPUT_FILE)
    
    # Initialize spike output matrices for each layer
    spike_out_layer_0 = [[0 for _ in range(NUM_CORES_LAYER_0 * NUM_NEURON)] for __ in range(SUM_OF_PICS)]
    spike_out_layer_1 = [[0 for _ in range(NUM_CORES_LAYER_1 * NUM_NEURON)] for __ in range(SUM_OF_PICS)]
    spike_out_layer_2 = [[0 for _ in range(NUM_CORES_LAYER_2 * NUM_NEURON)] for __ in range(SUM_OF_PICS)]
    
    # --- Clock and Reset Initialization ---
    print("\nStarting Clock and Reset\n")
    clock = Clock(dut.wb_clk_i, PERIOD, units="ns")
    cocotb.start_soon(clock.start(start_high=True))
    
    # Initial state (assert reset)
    dut.wb_rst_i.value = 1
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value = 0
    dut.wbs_sel_i.value = 0b0000
    dut.wbs_adr_i.value = 0
    dut.wbs_dat_i.value = 0
    await RisingEdge(dut.wb_clk_i)
    
    # De-assert reset after a short delay
    await Timer(PERIOD * 1, units="ns")
    dut.wb_rst_i.value = 0
    
    # --- Layer 0 Simulation ---
    # The cores in Layer 0 are indexed 0 to NUM_CORES_LAYER_0 - 1, corresponding to connection files 0 to 12.
    print("\n########################## START LAYER 0 ########################")
    layer = 0
    for core_layer_0 in range(NUM_CORES_LAYER_0):
        # 1. Configuration (ONCE)
        connection_layer_0 = connection_matrices[core_layer_0]
        await program_layer_connections(dut, core_layer_0, connection_layer_0, NUM_NEURON_LAYER_0)

        # 2. Simulation (EVERY PIC)
        # L0 input: stimuli (stimuli matrix, no core-specific indexing needed)
        await run_layer_for_all_pics(dut, core_layer_0, layer, NUM_CORES_LAYER_0, None, spike_out_layer_0, stimuli=stimuli)

    print("\n########################## FINISH LAYER 0 ########################")
    print(f"L0 output: {spike_out_layer_0}")
    await Timer(PERIOD * 1, units="ns")

    # --- Layer 1 Simulation ---
    # The cores in Layer 1 are indexed 0 to NUM_CORES_LAYER_1 - 1, corresponding to connection files 13 to 16.
    print("\n########################## START LAYER 1 ########################")
    layer = 1
    for core_layer_1 in range(NUM_CORES_LAYER_1):
        # The connection index starts from 13
        conn_idx = 13 + core_layer_1
        connection_layer_1 = connection_matrices[conn_idx]
        
        # 1. Configuration (ONCE)
        await program_layer_connections(dut, core_layer_1, connection_layer_1, NUM_NEURON_LAYER_1)
        
        # 2. Simulation (EVERY PIC)
        # L1 input: spike_out_layer_0
        await run_layer_for_all_pics(dut, core_layer_1, layer, NUM_CORES_LAYER_1, spike_out_layer_0, spike_out_layer_1, layer_axon_limit=NUM_AXON_LAYER_1)

    print("\n########################## FINISH LAYER 1 ########################")
    print(f"L1 output: {spike_out_layer_1}")
    await Timer(PERIOD * 1, units="ns")

    # --- Layer 2 Simulation ---
    # The cores in Layer 2 are indexed 0 to NUM_CORES_LAYER_2 - 1, corresponding to connection files 26_part1 to 26_part4.
    print("\n########################## START LAYER 2 ########################")
    layer = 2
    for core_layer_2 in range(NUM_CORES_LAYER_2):
        # The connection index is a float (e.g., 26.1, 26.2) for the parts
        conn_idx = 26 + (core_layer_2 + 1) / 10
        connection_layer_2 = connection_matrices[conn_idx]
        
        # 1. Configuration (ONCE)
        await program_layer_connections(dut, core_layer_2, connection_layer_2, NUM_NEURON_LAYER_2)

        # 2. Simulation (EVERY PIC)
        # L2 input: spike_out_layer_1. Note: core_idx is not used for L2 input indexing in run_layer_for_all_pics
        # because the original code suggests the L1 output is consolidated and indexed linearly for L2 input.
        await run_layer_for_all_pics(dut, core_layer_2, layer, NUM_CORES_LAYER_2, spike_out_layer_1, spike_out_layer_2, layer_axon_limit=NUM_AXON_LAYER_2)

    print("\n########################## FINISH LAYER 2 ########################")
    print(f"L2 output: {spike_out_layer_2}")
    await Timer(PERIOD * 1, units="ns")

    # --- Final Results Calculation ---
    correct_pic = 0
    predict_class = calculate_majority_class(spike_out_layer_2)
    print(f"\nPrediction: Gesture Class {predict_class}")
        
    print("\nTest Completed.")