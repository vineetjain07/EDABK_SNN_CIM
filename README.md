<table>
  <tr>
    <td align="center"><img src="img/bm-lab-logo-white.jpg" alt="BM LABS Logo" width="200"/></td>
    <td align="center"><img src="img/chip_foundry_logo.png" alt="Chipfoundry Logo" width="200"/></td>
    <td align="center"><img src="img/EDA_logo_Darkblue.png" alt="EDABK Logo" width="110"/></td>
  </tr>
</table>

# EDABK_SNN_CIM

> This project, submitted to **The NVM Innovation Contest**, introduces a Neurosynaptic Core for hand gesture recognition. The design is based on a hybrid Artificial and Spiking Neural Network architecture and integrates the ReRAM-based NVM IP from BM Labs with the ChipFoundry Caravel SoC Platform.

## Contributors

All members are affiliated to EDABK Laboratory, School of Electrical and Electronic Engineering, Hanoi University of Science and Technology (HUST).

| No. | Name                                                         | Study programme                           | Relevant link |
| --- | ------------------------------------------------------------ | ----------------------------------------- | ------------- |
| 1   | [Phuong-Linh Nguyen](mailto:linh.nguyenphuong1@sis.hust.edu.vn) | Master of Engineer in IC Design           |               |
| 2   | [Anh-Dung Hoang](mailto:dung.ha240324e@sis.hust.edu.vn)         | Master of Engineer in IC Design           |               |
| 3   | [Ngoc-Duong Nguyen](mailto:duong.nn242535m@sis.hust.edu.vn)     | Master of Science in IC Design            |               |
| 4   | [Hoang-Son Nguyen](mailto:son.nh210741@sis.hust.edu.vn)         | Bachelor in Electronics Engineering       |               |
| 5   | [Viet-Tung Pham](mailto:tung.pv224415@sis.hust.edu.vn)          | Senior student in Electronics Engineering |               |
| 6   | [Thanh-Hang Vu](mailto:hang.vt233385@sis.hust.edu.vn)           | Junior student in Electronics Engineering |               |

## Abstract

The application of hand gesture recognition can be extended to advanced human-machine interaction, enabling touchless control in various domains (e.g., automotive, healthcare). However, deploying such Artificial Intelligence (AI) models on edge devices is often hindered by the latency and power consumption arising from the von Neumann bottleneck, where data must be constantly shuttled between memory and processing units.

From an algorithmic standpoint, Spiking Neural Networks (SNNs) offer a promising solution. Inspired by how the biological brain communicates using discrete neural spikes, SNNs can reduce the quantity and complexity of computations. To compensate for the potential accuracy degradation in pure SNNs, a hybrid approach combining them with Artificial Neural Networks (ANNs) is employed. This allows high-precision input features to be processed, leading to significant accuracy improvements over traditional SNNs.

On the hardware side, implementing large models presents challenges, especially concerning the storage of trainable parameters (e.g., weights, synaptic connections) which would otherwise need to be reloaded into SRAM or flip-flops before each classification. The use of Non-Volatile ReRAM addresses this by preserving the parameters even when the embedded device enters a deep-sleep state. Furthermore, the provided Neuromorphic X1 IP promises in-memory computing capabilities, which minimize the energy and time required for accumulation operations.

Therefore, our team proposes **EDABK_SNN_CIM**, a solution integrating the ReRAM-based NVM IP from BM Labs and the ChipFoundry Caravel SoC Platform. The overall architecture is described in the [System Block Diagram](#system-block-diagram) section.

## System Block Diagram

![Neuron Core Diagram](img/README_block_diagram.png)
The proposed system accepts 13 features as input, corresponding to position, orientation, acceleration, and angular velocity, which are captured by Inertial Measurement Unit (IMU) sensors during human hand movements. Based on this data, the system predicts which gesture class the motion belongs to.

A hardware/software co-design approach is planned for the system implementation. The hardware component, responsible for the primary Neural Network computations, is a Caravel SoC integrated with BM Labs’ NVM IP. The software component, which can run on a host PC or an embedded device, is tasked with encoding sensor data, inferring the final gesture label, and controlling the hardware's operation.

Within the hardware's `user_project_wrapper`, a Controller utilizing a Wishbone Interface manages overall data exchange. The encoded sensor data is first pushed into a Stimuli-in Buffer before being processed by the ReRAM Crossbar array within the BM Labs’ NVM IP. An Address Decoder determines the specific IP commands, thereby selecting the appropriate rows and columns of the array to be accessed. The computational results are then stored in a Spike-out Buffer before being returned to the software component.

## Timeline

- Week 1 (October 13-19):

  + Research and select an optimal Neural Network model for gesture recognition.
  + Architectural design the Neural Accelerator.
- Week 2 (October 20-26):

  + Develop RTL code and perform functional verification for the modules within the Neural Accelerator.
  + Integrate the custom modules with the provided IP and the Caravel Template.
- Week 3 (October 27 - November 2):

  + Conduct system-level simulation and verification, including timing constraints.
  + Resolve any DRC and LVS violations that arise from the tool flow.

## Role of the ReRAM IP in In-Memory Computing (IMC)

The Neuromorphic X1 ReRAM IP from BM Labs is used in this project not only as a storage element, but as the **core hardware that enables In-Memory Computing (IMC)**. Each cell in the ReRAM crossbar stores a synaptic weight.

The digital RTL we designed:

- Sends READ or PROGRAM commands to the ReRAM IP (`nvm_synapse_matrix.v`),
- Receives the resulting binary synapse outputs (i.e., whether current exceeds a threshold),
- Passes these into the digital neuron array (`nvm_neuron_block.v`), where final accumulation and spike generation occur.

## RTL Implementation Overview

The digital hardware of the system is implemented entirely inside the [`SNN_gesture/`](https://github.com/<username>/EDABK_SNN_CIM/tree/main/verilog/rtl/SNN_gesture) directory.
The design follows a modular structure and is fully synthesizable on the Caravel SoC.

| Module                       | Function                                                                                                                                                          |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nvm_core_decoder.v`       | Decodes address ranges (`wbs_adr_i[15:12]`) and routes Wishbone signals to either Synapse Matrix, Spike Memory, or Picture-Done handler.                        |
| `nvm_synapse_matrix.v`     | Instantiates 16 Neuromorphic_X1 ReRAM macros. Broadcasts commands (PROGRAM/READ) to all macros and concatenates their 1-bit outputs into a 16-bit synapse vector. |
| `nvm_neuron_block.v`       | Digital neuron array, each neuron integrates signed input (stimulus) if synapse=1. Fires (spike=1) if potential ≥ 0. Resets on `picture_done`.                 |
| `nvm_neuron_spike_out.v`   | Stores 64 output spikes into 4×16-bit registers. Accessible via Wishbone at address `0x3000_1000`.                                                             |
| `nvm_neuron_core_256x64.v` | Top-level module combining all blocks, interfaces to Wishbone bus, controls data flow between software, ReRAM synapses, neurons, and spike output memory.         |

## RTL Operation Description

The RTL operates in four main stages:

### **1. Command from Firmware**

- Firmware writes a 32-bit word via Wishbone.
- The address determines whether the command is:
  - Synapse READ / PROGRAM
  - Spike output read
  - Picture-done/reset
- `nvm_core_decoder.v` activates the correct internal block.

### **2. In-Memory Synapse Access (IMC Stage)**

- `nvm_synapse_matrix.v` forwards the command to the ReRAM synapse IP.
- For READ:
  - The ReRAM array performs **in-memory synaptic multiplication**.
  - Each ReRAM column returns a **1-bit output**, forming `connection[15:0]`.
- For PROGRAM:
  - The selected synapse weight (conductance state) is updated.

### **3. Neuron Accumulation and Spike Generation**

- `nvm_neuron_block.v` takes:
  - The 16-bit `connection` vector from the synapse matrix.
  - A signed input `stimulus` from the Wishbone data.
- Each neuron integrates the value if connection is active:
  ```verilog
  if (enable && connection[i])
      potential[i] <= potential[i] + stimulus;
  spike_o[i] = (potential[i] >= 0);

  ```
- If the membrane potential reaches or exceeds zero → a spike (1) is generated.
- If picture_done is asserted, all neuron potentials are cleared for the next frame.

### **Step 4: Spike Output and Readback**

Once all input features for a gesture frame have been processed, the neuron block produces a 64-bit spike vector (`spike_o`). This value is transferred into the `nvm_neuron_spike_out.v` module, where it is stored in four 16-bit registers.

| Wishbone Address | Data Returned             |
| ---------------- | ------------------------- |
| `0x3000_1000`  | Spikes for neurons 0–15  |
| `0x3000_1002`  | Spikes for neurons 16–31 |
| `0x3000_1004`  | Spikes for neurons 32–47 |
| `0x3000_1006`  | Spikes for neurons 48–63 |

To finalize one classification event, the firmware writes to the **picture-done address** `0x3000_2000`. This triggers three actions in hardware:

1. **Spike latch** → Current 64-bit spike results are saved.
2. **Neuron reset** → All membrane potentials (`potential[i]`) are cleared.
3. **Ready for next frame** → The system waits for new synaptic inputs.

After this point, the firmware can read spikes via Wishbone and interpret them as the output class of the gesture.

## ReRAM SNN 1T1R Additions

A new **ReRAM-based SNN flow using 1T1R neuron/synapse abstractions** has been added as an optional path for development and verification. This addition is intended for users who want to evaluate a generic ReRAM SNN implementation alongside the original digital flow, without changing the existing baseline RTL structure.

### What was added

The following new files were added:

```text
analog_snn/
├── README.md
├── reram_snn_32x32.py
├── reram_snn_32x32_1t1r.py
└── demo_reram_snn_32x32_1t1r.py

verilog/rtl/neuron_core/hdl/
├── reram_1t1r_snn_neuron.v
└── reram_1t1r_snn_array_32x32.v

verilog/dv/cocotb/reram_1t1r/
├── README.md
├── Makefile
└── test_reram_1t1r.py
```

### Purpose of the new ReRAM SNN files

- `analog_snn/reram_snn_32x32.py`  
  Base behavioral ReRAM crossbar model.

- `analog_snn/reram_snn_32x32_1t1r.py`  
  1T1R ReRAM SNN behavioral model for 32×32 array-style experiments.

- `analog_snn/demo_reram_snn_32x32_1t1r.py`  
  Minimal runnable demo showing how to instantiate and execute the Python model.

- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_neuron.v`  
  Behavioral RTL abstraction of a ReRAM 1T1R spiking neuron.

- `verilog/rtl/neuron_core/hdl/reram_1t1r_snn_array_32x32.v`  
  Behavioral RTL abstraction of a 32×32 ReRAM 1T1R SNN array.

- `verilog/dv/cocotb/reram_1t1r/test_reram_1t1r.py`  
  Cocotb-based verification for the added ReRAM 1T1R SNN RTL.

### How to use the Python ReRAM SNN model

From the repository root:

```bash
cd analog_snn
python demo_reram_snn_32x32_1t1r.py
```

This runs the behavioral 1T1R ReRAM SNN example and prints the resulting output activity.

### How to use the Cocotb verification

From the repository root:

```bash
cd verilog/dv/cocotb/reram_1t1r
make
```

This launches the cocotb-based verification flow for the newly added ReRAM 1T1R SNN RTL files.

### Integration note

These additions are **optional** and are meant to extend the repository with a ReRAM-based SNN path. They do not replace the original digital implementation described above unless the user explicitly chooses to integrate them into the main system path.


## Replicating Locally

### Follow these steps to set up your environment and harden the design:

1. **Clone the Repository:**

```bash
git clone https://github.com/schizoneko/EDABK_SNN_CIM.git
```

2. **Prepare Your Environment:**

```bash
cd EDABK_SNN_CIM
make setup
```

3. **Install IPM:**

```bash
pip install cf-ipm
```

4. **Install the Neuromorphic X1 IP:**

```bash
ipm install Neuromorphic_X1_32x32
```

5. **Edit Behavioral Model Name in IP:**

The cocotb simulation flow uses `verilog/includes/includes.rtl.caravel_user_project` as its source files, which includes a path to the Neuromorphic IP behavioral model. In order to avoid making a second `user_project_wrapper.v`, it is simpler to modify the behavioral model module name from `Neuromorphic_X1` to `Neuromorphic_X1_wb` to align with the stub that is used when actually hardening. With this change, the same `user_project_wrapper.v` works for both (cocotb) testbenching as well as hardening.

In other words, rename line 16...
```
File: ip/Neuromorphic_X1_32x32/hdl/beh_model/Neuromorphic_X1_Beh.v
16: module Neuromorphic_X1_wb (
```

6. **Harden the Neuron Core:**

```bash
make neuron_core
```
7. **Harden the Design:**

```bash
make SNN_gesture
```

## Documentation

- Details about the Neuromorphic X1 IP: [Neuromorphic X1 documentation](https://github.com/BMsemi/Neuromorphic_X1_32x32)
- Competition details: [ChipFoundry BM Labs Challenge](https://chipfoundry.io/challenges/bmlabs)

## License

This project is licensed under Apache 2.0 - see LICENSE file for details.
