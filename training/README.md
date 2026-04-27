# SNN Training Pipeline

This directory contains the full pipeline to convert **DVS128 hand-gesture recordings** into **trained binary-weight files** ready for in-memory neuromorphic hardware.

## Our SNN Architecture

We are training a Spiking Neural Network (SNN) that behaves like a **1-bit Computer-in-Memory (CIM)**. Instead of moving data back and forth between a processor and memory, our chip stores weights in **ReRAM cells** and performs the math directly inside the memory array.

### Data Flow Overview

```text
  1. RAW VIDEO (.aedat)     →  Raw sensor events (x, y, time, polarity)
             ↓
  2. PREPROCESSING         →  Flatten into 256 spatial "axons" (uint16)
  [dvs128_preprocess.py]
             ↓
  3. TRAINING              →  Train SNN with surrogate gradients
  [train_dvs128.py]           Binary weights {0, 1} (Active / Skip)
             ↓
  4. EXPORT                →  Generate bit-weights files (.txt) for hardware
  [export_weights.py]
             ↓
  5. VERIFICATION          →  Run Python reference model & RTL simulation
  [validate_ref_model.py]     Check bit-accuracy before tapeout
```

---

## 🧠 Our SNN Architecture

Our network is a **3-layer binary-weight LIF network**. Unlike traditional SNNs that process spikes over many time steps, this network encodes an entire gesture into a single "spatial snapshot" of 256 axons. It performs one forward pass and outputs a classification.

| Layer | Cores | Axons/Core | Neurons/Core | Total Neurons | Routing |
|-------|-------|-----------|--------------|---------------|---------|
| L0 | 13 (`NUM_CORES_LAYER_0`) | 256 (`NUM_AXON_LAYER_0`) | 64 | 832 | Broadcast |
| L1 | 4 (`NUM_CORES_LAYER_1`) | 208 (`NUM_AXON_LAYER_1`) | 64 | 256 | Partitioned (832/4) |
| L2 | 4 (`NUM_CORES_LAYER_2`) | 256 (`NUM_AXON_LAYER_2`) | 64 | 256 | Broadcast |
| Vote | — | 256 | 12 classes | — | Interleaved (240 active neurons / 20 per class) |

### Binary Weight Mapping
Physically, our weights are **single bits** stored in ReRAM cells: 
- `MEM_HIGH` (Bit 1) = **Active** (Neuron integrates the stimulus)
- `MEM_LOW`  (Bit 0) = **Silent** (Neuron skips the stimulus)

**How do we get -1 weights?**
Since a single ReRAM bit can't be negative, we use **Axon Sign Encoding**. The hardware determines the sign based on the input channel (axon) index:
- **Even axons** provide a **positive** stimulus (`+val`).
- **Odd axons** provide a **negative** stimulus (`-val`).

By setting a weight bit to `1` on an odd axon, we effectively create a **-1 weight** connection. This allows the network to learn both excitatory and inhibitory behaviors using only `{0, 1}` bits in memory.

**LIF parameters** (defined in `nvm_parameter.py` ↔ `nvm_parameter.vh`):
- `NEURON_THRESHOLD = 4` — spike fires when potential ≥ 4
- `NEURON_LEAK_SHIFT = 16` — leak = `potential >>> 16` (arithmetic right-shift, applied once per gesture at `picture_done`)


## Supported Encodings

| Encoding | Flag | Axon count | Description |
|----------|------|-----------|-------------|
| `temporal2` | `--encoding temporal2` | 256 | 2 equal-time windows × 8×8 grid × 2 polarities (ON/OFF) — default |
| `static` | `--encoding static` | 238 | Single window × 7×17 grid × 2 polarities |
| `temporal4_merged` | `--encoding temporal4_merged` | 256 | 4 windows × 8×8 grid × merged polarity |
| `spatial_focus` | `--encoding spatial_focus` | 242 → 256 | 2 windows × 11×11 grid × merged polarity, zero-padded to 256 |

All axon values are uint16, clipped at the 99th percentile of the training set and scaled to [0, 32767] to prevent signed overflow in the hardware accumulator.

---

## 🛠️ Training Workflow

Follow these steps in order to go from raw data to hardware verification.

### Phase 1: Preprocessing (`dvs128_preprocess.py`)
This script downloads the DVS128 Gesture dataset and converts it into feature vectors. 

**What is a "Spatial Focus" Encoding?**
It zooms into the center of the sensor (where the hand is) and creates an 11x11 grid. With 2 time windows (start and end of gesture), this gives us $11 \times 11 \times 2 = 242$ inputs, which we pad to 256.

```bash
# Downloads (~1.5GB) and processes
python dvs128_preprocess.py --encoding spatial_focus

## If getting issue with downloading dataset, download dataset manually and place it in data directory, then run below command:
python dvs128_preprocess.py --encoding spatial_focus --no-download
```

### Phase 2: Training (`train_dvs128.py`)
We use **Surrogate Gradient Descent** to train the network. Since binary weights and spikes aren't differentiable, we use a smooth "surrogate" function during training that gradually becomes sharper (more binary).

```bash
# Train (80 epochs, ~5 mins on CPU), Default starting threshold = 4.
python train_dvs128.py --data-dir data --epochs 80

# Check Accuracy on pretrained results with manually set threshold (int).
python train_dvs128.py --resume checkpoints/best.pt --epochs 80 --override-threshold 4 --only-test

# Advanced: Use the legacy 4-phase schedule (annealing slope/LR)
python train_dvs128.py --data-dir data --multiphase
```

**SNN Training Implementation**

This model is built using **snnTorch**, a PyTorch-based library for Spiking Neural Networks. Unlike traditional networks, we model the physical dynamics of neurons.

- **Leaky Integrate-and-Fire (LIF)**: Each neuron acts as an accumulator. It integrates incoming stimuli into a "membrane potential." If the potential stays below a threshold, it slowly "leaks" away over time.
- **Single-Step Inference ("Flattened Time")**: To match our hardware CIM efficiency, we process each gesture in a single forward pass. We reset the neuron potentials to zero before every gesture, meaning there is no "memory" carried between different samples.
- **Threshold Learning**: The model doesn't just learn weights; it also learns the optimal `NEURON_THRESHOLD` for each core to maximize classification accuracy.
- **Beta (Leak) Learning**: The leak factor ($\beta$) is a trainable parameter. After training, we convert it to the nearest hardware-compatible `NEURON_LEAK_SHIFT` using the relation: $\beta = 1 - 1/2^{\text{leak\_shift}}$.
- **Surrogate Gradients (Fast Sigmoid)**: Since the spiking function (thresholding) is not differentiable, we use a "Fast Sigmoid" surrogate gradient during backpropagation. This allows standard gradient descent to work even though the forward pass uses discrete spikes.

### Phase 3: Export & Validation
Once you have a `best.pt` checkpoint, you need to turn it into something the hardware understands.

1. **Export Weights**: Creates `connection_XXX.txt` files (bit-masks for each core).
2. **Export Stimuli**: Creates `stimuli.txt` (test inputs in hardware packet format).
3. **Validate**: Runs a **bit-accurate Python model** that mimics the RTL exactly.

```bash
python export_weights.py --checkpoint checkpoints/best.pt
python export_stimuli.py
python validate_reference_model.py --checkpoint checkpoints/best.pt
```

---

## 📁 Output Summary

| File | Description | Next Step |
|------|-------------|-----------|
| `data/*.npz` | Preprocessed feature arrays | Training & Validation |
| `checkpoints/best.pt` | Trained PyTorch model | Exporting weights |
| `mem/connection/*.txt` | Bit-masks for ReRAM cores | Hardware Simulation (Cocotb) |
| `mem/stimuli/stimuli.txt` | Hardware-ready input packets | Hardware Simulation (Cocotb) |

---


## Next Steps

Once you have trained weights and exported them:

1. **Run Python Verification** — [`verilog/tb/snn_gesture/README.md`](../verilog/tb/snn_gesture/README.md) — bit-accurate Python model validation.
2. **Run Cocotb Tests** — 7-phase hardware simulation (Phases 1–7).
3. **For End-to-End Context** — [`snn_gesture_working.md`](../snn_gesture_working.md) — system architecture and data flow.
