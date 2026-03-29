# ReRAM 1T1R SNN model

This directory contains a Python behavioral model for a 32×32 **1T1R ReRAM**
crossbar used as the synaptic front end of a spiking neural network.

## Files

- `reram_snn_32x32.py`
  - Base 32×32 ReRAM crossbar model with differential signed outputs,
    TDC-style readout, optional STDP and LIF neuron support.
- `reram_snn_32x32_1t1r.py`
  - 1T1R extension with source-line, bitline and gate-line effects,
    simple parasitic-aware settling and mixed-signal neuron modes.
- `demo_reram_snn_32x32_1t1r.py`
  - Smoke-test script that programs prototype weights, applies a temporal
    spike pattern and saves traces.

## Quick start

```bash
cd analog_snn
python demo_reram_snn_32x32_1t1r.py --outputs 4 --steps 14
```

## Minimal usage

```python
from reram_snn_32x32 import make_prototype_weights
from reram_snn_32x32_1t1r import (
    ReRAMSNN32x32OneTOneR,
    OneTOneRArrayConfig,
    MixedSignalNeuronConfig,
)

model = ReRAMSNN32x32OneTOneR(
    n_outputs=8,
    seed=1,
    enable_faults=False,
    array=OneTOneRArrayConfig(source_connection="dsc", gate_drive="always_on"),
    neuron=MixedSignalNeuronConfig(activation="tdc_nonlinear", output_mode="lif"),
)

model.program_weights(make_prototype_weights(num_outputs=8, rows=32))
out = model.run(spike_train)
```

## Notes

- The model is intentionally behavioral. It is useful for algorithm, architecture
  and verification work, not transistor-level signoff.
- The 1T1R file is self-contained except for the base crossbar helper imported
  from `reram_snn_32x32.py`.
- If you want to align it with existing repo infrastructure, keep this directory
  at the repo root and import the model from Python-based verification or
  co-simulation flows.
