Overview
======== 
This directory contain tests to verify the example user project 16 bit counter and 2 other simple tests as examples. 

directory hierarchy
=====================

# counter_tests 
 
contain tests for 16 bit counter for more info refer to [counter_tests](counter_tests/README.md)
 
 # hello_world 
 
 Example test with empty firmware that only power and reset caravel the print "Hello World" 
 
 # hello_world_uart 
 
 Example test That uses the firmware to send "Hello World" using UART TX 
 
# cocotb_tests.py 

Module that should import all the tests used to be seen for cocotb as a test

 
Run tests 
===========
# run hello_world_uart
    ```bash
    caravel_cocotb -t hello_world_uart -tag hello_world 
    ```
# run all counter testlist
    ```bash
    caravel_cocotb -tl counter_tests/counter_tests.yaml -tag counter_tests 
    ```
# run from different directory
    ```bash
    caravel_cocotb -t hello_world_uart -tag hello_world -design_info <path to design_info.yaml>
    ```      
# run with changing the results directory
    ```bash
    caravel_cocotb -t hello_world_uart -tag hello_world -sim  <path to results directory>
    ```

Experimental ReRAM SNN model
============================

The repository now also includes an **experimental ReRAM-based SNN flow** based on a **1T1R (1 transistor + 1 ReRAM) neuron/synapse model**.  
These files are added for early exploration of mixed-signal / memory-centric SNN behavior and cocotb-based verification.

This flow is **experimental**:
- it is intended for architecture, algorithm, and verification exploration
- it should be treated as a behavioral model, not a signoff-accurate analog model
- interfaces, parameters, and file locations may still change as the project evolves

New files added
============================

# Python behavioral model

These files provide a high-level software model of the ReRAM SNN array and are useful for quick experiments before RTL simulation.

- `analog_snn/reram_snn_32x32.py`  
  Base behavioral model for a 32x32 ReRAM SNN array.

- `analog_snn/reram_snn_32x32_1t1r.py`  
  1T1R behavioral model used for experimental SNN evaluation.

- `analog_snn/demo_reram_snn_32x32_1t1r.py`  
  Example script showing how to instantiate the model, load weights, create spike inputs, and run the model.

# RTL files

These files provide an RTL-level experimental implementation.

- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_neuron.v`  
  Behavioral RTL for a single ReRAM 1T1R SNN neuron.

- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_array_32x32.v`  
  Behavioral RTL for the 32x32 array wrapper.

# Cocotb verification files

These files provide cocotb-based checking for the experimental model.

- `verilog/dv/cocotb/reram_1t1r/test_reram_1t1r.py`  
  Main cocotb regression for the ReRAM 1T1R SNN block.

- `verilog/dv/cocotb/reram_1t1r/Makefile`  
  Build and simulation entry point for the cocotb test.

How to use the experimental SNN files
============================

# 1. Use the Python model for quick evaluation

Run the example script from the repository root:

```bash
python analog_snn/demo_reram_snn_32x32_1t1r.py
```

This is the fastest way to:
- test spike inputs
- inspect output spikes
- try different weights
- understand the expected behavior before RTL simulation

# 2. Use the RTL model in hardware-oriented flows

Instantiate the following RTL files in your experimental integration flow:

- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_neuron.v`
- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_array_32x32.v`

Suggested usage:
- use the array wrapper for block-level experiments
- use the single neuron module for focused unit testing
- keep this path separate from production RTL until the model is stabilized

# 3. Run cocotb verification

From the cocotb test directory:

```bash
cd verilog/dv/cocotb/reram_1t1r
make SIM=icarus
```

This test is intended to check:
- basic array/neuron bring-up
- spike generation behavior
- simple integration behavior across cycles
- consistency between expected and simulated outputs

# 4. Recommended workflow

A practical workflow for users is:

1. start with the Python model
2. validate expected spike behavior and weights
3. move to the RTL model
4. run cocotb regression
5. integrate into larger experimental SNN flows

Notes for users
============================

- This model is currently documented as **experimental ReRAM SNN** support.
- The files are meant to help users explore memory-centric SNN design ideas.
- The Python and RTL models are behavioral and may not include all analog device non-idealities.
- For stable product flows, keep these files isolated from existing production test paths until fully validated.

