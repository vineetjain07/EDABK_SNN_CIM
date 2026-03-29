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

# Experimental ReRAM SNN models

This repository also includes an **experimental** ReRAM-based SNN flow for users who want to evaluate analog-style 1T1R neuron and crossbar behavior alongside the existing digital examples. These files are intended for development and evaluation use, and should be treated as behavioral models rather than final silicon-accurate signoff models.

## What is included

- `analog_snn/reram_snn_32x32.py`  
  Base Python model for a 32x32 ReRAM SNN crossbar.

- `analog_snn/reram_snn_32x32_1t1r.py`  
  Experimental 1T1R Python model for running spike-based inference with programmable weights.

- `analog_snn/demo_reram_snn_32x32_1t1r.py`  
  Example script showing how to instantiate the model, load weights, generate a spike train, and run inference.

- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_neuron.v`  
  Behavioral RTL model of a ReRAM SNN neuron.

- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_array_32x32.v`  
  Behavioral RTL model of a 32x32 ReRAM 1T1R SNN array.

- `verilog/dv/cocotb/reram_1t1r/test_reram_1t1r.py`  
  Cocotb testbench for basic verification of the experimental RTL.

## How to use the Python model

Run the demo script:

```bash
python analog_snn/demo_reram_snn_32x32_1t1r.py
```

For custom experiments, use `demo_reram_snn_32x32_1t1r.py` as the reference entry point. The normal flow is:

1. create the ReRAM SNN model,
2. program or load the weight matrix,
3. generate or load an input spike train,
4. run inference,
5. inspect the output spike tensor.

## How to use the RTL + Cocotb flow

Go to the verification directory:

```bash
cd verilog/dv/cocotb/reram_1t1r
```

Run the cocotb test with Icarus Verilog:

```bash
make SIM=icarus
```

If you use another simulator, update the `SIM` variable in the same command or in the local Makefile.

## Notes for users

- This flow is experimental and intended to help users evaluate ReRAM-based SNN concepts inside this repository.
- The Python and RTL models are behavioral and are useful for architecture exploration, dataflow experiments, and early verification.
- Users should validate timing, analog non-idealities, and foundry-specific implementation details separately before relying on this flow for tapeout decisions.

 
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
