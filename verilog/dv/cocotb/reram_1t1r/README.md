# Cocotb check for the ReRAM 1T1R SNN block

This directory contains a standalone cocotb regression for the behavioral
ReRAM 1T1R SNN array.

## Files

- `test_reram_1t1r.py`
  - Programs several positive and negative conductance levels into three
    neurons and checks spike output, membrane state and signed synaptic
    sum against a Python reference model.
- `Makefile`
  - Builds `reram_1t1r_snn_array_32x32` with cocotb.

## Run

```bash
cd verilog/dv/cocotb/reram_1t1r
make SIM=icarus
```

## Expected behavior

- neuron 0 spikes after two strong `{0,1,2}` input patterns
- neuron 1 integrates over repeated `{4,5}` patterns
- neuron 2 responds to mixed positive and negative weighted inputs
- unconfigured neurons remain quiet
