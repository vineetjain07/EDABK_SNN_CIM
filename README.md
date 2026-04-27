<table>
  <tr>
    <td align="center"><img src="img/bm-lab-logo-white.jpg" alt="BM LABS Logo" width="200"/></td>
    <td align="center"><img src="img/chip_foundry_logo.png" alt="Chipfoundry Logo" width="200"/></td>
    <td align="center"><img src="img/EDA_logo_Darkblue.png" alt="EDABK Logo" width="110"/></td>
  </tr>
</table>

# EDABK_SNN_CIM

**Neuromorphic Gesture Recognition SoC — Silicon 2 Systems by ChipFoundry**

> A **62% hardware / 66% software accurate** neuromorphic hand-gesture classifier featuring
> 8 × Neuromorphic_X1 ReRAM macros taped out on ChipFoundry Caravel (SKY130, 2920×3520 µm).
> Binary-weight 3-layer Leaky-Integrate-and-Fire (LIF) SNN with in-memory Vector-Matrix
> Multiplication via BM Labs ReRAM crossbar.

---

## What This Project Is

This is a **neuromorphic hand-gesture recognition System-on-Chip (SoC)** that runs on the
[ChipFoundry Caravel](https://github.com/efabless/caravel) open-source RISC-V platform.
The chip classifies **12 distinct DVS128 hand gestures** in real time using a **Spiking Neural
Network (SNN)** executed on an in-memory compute engine.

### Why Neuromorphic?

Conventional deep learning inference on edge devices burns energy reading weights from DRAM and
shuffling them through multiply-accumulate (MAC) arrays. Neuromorphic computing attacks both
bottlenecks:

- **In-memory compute**: BM Labs **Neuromorphic X1 ReRAM crossbar** stores binary synaptic
  weights directly in resistive memory cells and performs the Vector-Matrix Multiplication
  (VMM) *inside* the memory array, with no weight movement.
  
- **Binary weights**: Weights are restricted to {+1, −1} (represented as {1, 0} bits in ReRAM).
  This halves storage and replaces multiply-accumulate with simple accumulate-or-skip.
  
- **Spike-based output**: Instead of a continuous activation, each neuron emits a binary spike
  {0, 1}. Downstream layers receive sparse, all-integer inputs, eliminating floating-point.

**Result:** Orders-of-magnitude improvement in **energy efficiency** and **latency** compared
to traditional von Neumann architectures — ideal for edge AI applications.

---

## Contributors

| Name | GitHub 
|---|---|
| [Vineet Jain](https://github.com/vineetjain07) | @vineetjain07  
| [Nikunj Bhatt](https://github.com/Nikunj2608) | @Nikunj2608  
|  [Samarth Jain](https://github.com/Samarthjainabout) | BM Labs 

---

## Abstract

The application of hand gesture recognition can be extended to advanced human-machine interaction, enabling touchless control in various domains (e.g., automotive, healthcare). However, deploying such Artificial Intelligence (AI) models on edge devices is often hindered by the latency and power consumption arising from the von Neumann bottleneck, where data must be constantly shuttled between memory and processing units.

From an algorithmic standpoint, Spiking Neural Networks (SNNs) offer a promising solution. Inspired by how the biological brain communicates using discrete neural spikes, SNNs can reduce the quantity and complexity of computations. To compensate for the potential accuracy degradation in pure SNNs, a hybrid approach combining them with Artificial Neural Networks (ANNs) is employed. This allows high-precision input features to be processed, leading to significant accuracy improvements over traditional SNNs.

On the hardware side, implementing large models presents challenges, especially concerning the storage of trainable parameters (e.g., weights, synaptic connections) which would otherwise need to be reloaded into SRAM or flip-flops before each classification. The use of Non-Volatile ReRAM addresses this by preserving the parameters even when the embedded device enters a deep-sleep state. Furthermore, the provided Neuromorphic X1 IP promises in-memory computing capabilities, which minimize the energy and time required for accumulation operations.

Therefore, **EDABK_SNN_CIM** integrates the ReRAM-based NVM IP from BM Labs and the ChipFoundry Caravel SoC Platform, achieving state-of-the-art accuracy on 12-class DVS128 gesture recognition with minimal power overhead.

---

## System Architecture

![Neuron Core Diagram](img/README_block_diagram.png)

The proposed system accepts 256-axon feature vectors (encoding DVS128 event camera data) and
predicts which gesture class the motion belongs to. A hardware/software co-design:

- **Hardware (SoC):** Caravel user-project wrapper integrates the BM Labs Neuromorphic X1
  ReRAM crossbar for in-memory VMM plus digital LIF neurons for spike generation.
- **Software (Host):** Encodes sensor data, controls hardware via Wishbone interface, performs
  majority-vote classification from neuron spikes.

The system achieves **62% hardware accuracy** on a real GDS tape-out, closing the HW/SW gap
via precise leak compensation and negative-potential handling.

---

## Documentation Map

### System Overview

| Document | What it covers |
|---|---|
| [**snn_gesture_working.md**](snn_gesture_working.md) | Complete system overview: end-to-end data flow (8 stages), 3-layer network topology, hardware parameters, 4-milestone accuracy journey |
| [**PROPOSAL.md**](PROPOSAL.md) | Original Silicon 2 Systems proposal: problem statement, innovation points, architecture |
| [**README_original.md**](README_original.md) | Original submission README (preserved for reference) |

### Training & Weights

| Document | What it covers |
|---|---|
| [**training/README.md**](training/README.md) | 6-phase training pipeline: DVS128 preprocessing, SNN model definition, binary weight training, weight export, reference model validation, quick-start commands |
| [**training/SNN_Training_Walkthrough.ipynb**](training/SNN_Training_Walkthrough.ipynb) | Interactive end-to-end walkthrough with full pipeline explanation (runs with synthetic data — no external dataset required) |

### RTL Design & Verification

| Document | What it covers |
|---|---|
| [**verilog/rtl/SNN_gesture/README.md**](verilog/rtl/SNN_gesture/README.md) | RTL module hierarchy, Wishbone slave interface, ReRAM behavioral model, 4-stage inference pipeline, LIF design decisions, hardware invariants, firmware constraints |
| [**verilog/tb/snn_gesture/README.md**](verilog/tb/snn_gesture/README.md) | Python reference model (bit-accurate SNN simulation), 7-phase cocotb verification framework, hardware constraints, test utilities, debugging guide |

### Physical Design & Tapeout

| Document | What it covers |
|---|---|
| [**openlane/SNN_gesture/README.md**](openlane/SNN_gesture/README.md) | OpenLane 2 hardening flow, 8-macro tapeout limitation (Caravel die-area constraint), macro placement grid, PDN power hooks, configuration choices, references |

---

## Repository Structure

| Directory | Role |
|-----------|------|
| `training/` | DVS128 event preprocessing, PyTorch SNN model definition, weight export pipeline |
| `verilog/rtl/SNN_gesture/hdl/` | Tapeout-ready RTL: Wishbone bridge + ReRAM IP + LIF neurons |
| `verilog/tb/snn_gesture/` | Cocotb testbench + Python reference model (software-equivalent of RTL) |
| `verilog/tb/hdl/` | Simulation-only baseline design (separate codebase, used for early development) |
| `openlane/SNN_gesture/` | OpenLane hardening scripts for GDS tapeout |
| `ip/Neuromorphic_X1_32x32/` | BM Labs ReRAM IP (behavioral model, documentation) |

---

## Quick Start

### I'm a new contributor — where do I start?
→ [**training/SNN_Training_Walkthrough.ipynb**](training/SNN_Training_Walkthrough.ipynb) — interactive walkthrough, no dependencies.

### I want to train the model and export weights
→ [**training/README.md**](training/README.md) — run the 3-phase pipeline:
```bash
cd training
python dvs128_preprocess.py --encoding spatial_focus
python train_dvs128.py --epochs 80
python export_weights.py --checkpoint checkpoints/best.pt
```

### I want to run RTL co-simulation
→ [**verilog/tb/snn_gesture/README.md**](verilog/tb/snn_gesture/README.md) — run cocotb tests:
```bash
cd verilog/tb && make sim
```

### I want to harden to GDS
→ [**openlane/SNN_gesture/README.md**](openlane/SNN_gesture/README.md) — run the OpenLane flow:
```bash
cd openlane && make SNN_gesture
```

---

## Accuracy Journey

### Performance Benchmarks

| Encoding | Multi Phase (8 thr) | Single Phase (8 thr) | Multi Phase (4 thr) | Single Phase (4 thr) | Single Phase (1 thr) |
|---|---|---|---|---|---|
| `temporal2` (default) | 45.49% | 53.82% | 43.06% | 55.90% | 55.90% |
| `spatial_focus` | — | 63.89% | 57.29% | **65.62%** | 63.19% |
| `temporal4_merged` | — | 60.76% | — | 57.99% | 54.17% |

*Values in **bold** represent the best overall configuration (Software Accuracy).*

### Summary Roadmap

| Milestone | HW Acc | SW Acc | Key Change |
|---|---|---|---|
| Placeholder weights | 2% | — | Initial setup |
| First trained weights | ~4% | ~56% | First weights trained, HW bugs unresolved |
| After leak fix (F-24) | +30.5pp | — | Per-axon leak bias corrected |
| **`spatial_focus` (taped out)** | **62%** | **66%** | **Final state**: 11x11 grid + 4-threshold training |

The ~4pp HW/SW gap is due to network quantization.
See [**snn_gesture_working.md**](snn_gesture_working.md#accuracy-journey) for full details.

---

## Role of the ReRAM IP in In-Memory Computing (IMC)

The Neuromorphic X1 ReRAM IP from BM Labs is the **core hardware that enables
In-Memory Computing (IMC)**. Each cell in the ReRAM crossbar stores a synaptic weight.

The digital RTL we designed:

- Sends READ or PROGRAM commands to the ReRAM IP (`nvm_synapse_matrix.v`)
- Receives the resulting binary synapse outputs (1-bit per macro per axon)
- Passes these into the digital neuron array (`nvm_neuron_block.v`), where accumulation and spike generation occur

This architecture eliminates the energy and latency cost of reading weights from DRAM,
achieving orders-of-magnitude improvement in energy efficiency for inference.

---

## Hardware Limitations & Design Trade-offs

**8 Macros (not 16):** The original design targeted 16 Neuromorphic_X1 macros (64 neurons per
tile). After OpenLane floor-planning inside the Caravel 2920×3520 µm wrapper, only 8 macros fit
without violating PDN stripe constraints and routing DRC. This reduces neurons per tile to 32,
requiring more cores in each layer (26/8/8 instead of 13/4/4). The SNN topology remains valid;
training and weight export scale automatically.

See [**openlane/SNN_gesture/README.md**](openlane/SNN_gesture/README.md) for full details.

---

## References

- [BM Labs Neuromorphic X1 IP](https://bm-labs.com)
- [ChipFoundry Caravel User Project Template](https://github.com/efabless/caravel_user_project)
- [OpenLane 2 Documentation](https://openlane2.readthedocs.io/)
- [SKY130 PDK (Google Skywater)](https://github.com/google/skywater-pdk)
- [snnTorch: PyTorch SNN Framework](https://snntorch.readthedocs.io/)

---

## License

This project is licensed under Apache 2.0 — see [LICENSE](LICENSE) file for details.

---

**For detailed system architecture, data flow, and design decisions, see**
[**snn_gesture_working.md**](snn_gesture_working.md).
