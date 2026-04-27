# SNN Gesture Recognition — Complete System Guide

## What This Project Is

This is a **neuromorphic hand-gesture recognition System-on-Chip (SoC)** that runs on the
[ChipFoundry Caravel](https://github.com/efabless/caravel) open-source RISC-V platform.
The chip classifies 12 distinct DVS128 hand gestures in real time using a **Spiking Neural
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

---

## Directory Map

| Directory | Role |
|-----------|------|
| `training/` | DVS128 event preprocessing, PyTorch SNN model definition, weight export pipeline |
| `verilog/rtl/SNN_gesture/hdl/` | Tapeout-ready RTL: Wishbone bridge + ReRAM IP + LIF neurons |
| `verilog/tb/snn_gesture/` | Cocotb testbench + Python reference model (software-equivalent of RTL) |
| `verilog/tb/hdl/` | Simulation-only baseline design (separate codebase, used for early development) |
| `openlane/SNN_gesture/` | OpenLane hardening scripts for GDS tapeout |

---

## Network Topology

The SNN has three fully-connected layers. Each layer is partitioned across multiple physical
`nvm_neuron_core_256x64` modules called *cores*. All cores in a layer share the same
architecture (256 axons in, 64 neurons out) but are programmed with different weight files.

| Layer | Cores | Axons per Core | Neurons per Core | Total Neurons | Routing |
|-------|-------|---------------|------------------|---------------|---------|
| L0 | 13 (`NUM_CORES_LAYER_0`) | 256 (`NUM_AXON_LAYER_0`) | 64 | 832 | **Broadcast** — all 13 cores receive the same 256 input axons |
| L1 | 4 (`NUM_CORES_LAYER_1`) | 208 (`NUM_AXON_LAYER_1`) | 64 | 256 | **Partitioned** — core k receives L0 output spikes `[k×208 : (k+1)×208]` |
| L2 | 4 (`NUM_CORES_LAYER_2`) | 256 (`NUM_AXON_LAYER_2`) | 64 (60 active) | 240 active (`NUM_VOTES`) | **Broadcast** — all 4 cores receive all 256 L1 output spikes |

**L0 routing (broadcast)**: All 13 L0 cores see the same 256-axon input feature vector.
They compute different linear projections in parallel (each has different weights), producing
832 diverse feature spikes collectively.

**L1 routing (partitioned)**: The 832 L0 spikes are split into 4 non-overlapping segments
of 208 spikes. Core k of L1 takes segment k as input. This keeps the axon count ≤ 256 per
core while routing the full L0 output through the network.

**L2 routing (broadcast)**: All 4 L2 cores see all 256 L1 output spikes. Each L2 core
applies different weights, so together they produce 256 votes for the 12 classes via
interleaved majority vote.

**Why 64 neurons per core?**  
Each `nvm_neuron_core_256x64` has `NUM_OF_MACRO=16` physical ReRAM macros, each 32×32.
The neuron block time-multiplexes 16 physical neurons into 64 virtual neurons by processing
4 groups of 16 in sequence (each group mapped to a different row band in the macro).

---

## End-to-End Data Flow

### Stage 1 — DVS128 Event Preprocessing
**Script**: `training/dvs128_preprocess.py`  
**Output**: `data/dvs128_train.npz`, `data/dvs128_test.npz`  
**Active encoding**: `spatial_focus` (pass `--encoding spatial_focus`)

**What happens**:
The input sensor is a **DVS128 event camera** — a bio-inspired sensor that fires per-pixel
events when brightness *changes*, not at a fixed frame rate. This gives microsecond-resolution
motion data with very low power.
The DVS128 event camera produces a stream of `(x, y, polarity, timestamp)` tuples for each
gesture. The preprocessing script bins these events into a fixed-size feature vector:

1. Split each gesture's events into **2 equal time windows** (early / late motion phase).
2. Project events onto an **11×11 spatial grid** centered on the active region of the sensor.
3. **Merge polarities**: sum ON-events and OFF-events together in each grid cell.
4. Flatten and concatenate both windows → 2 × 121 = 242 values.
5. **Zero-pad** to 256 to match the hardware axon bus width (`NUM_AXONS=256`).
6. **Normalize** by clipping raw counts at the 99th-percentile of the training set, then scaling
   to `[0, 32767]` (unsigned 16-bit). This prevents signed overflow in the 16-bit hardware
   accumulator during inference while preserving relative magnitudes.

**Why this encoding?**  
Earlier encodings (`temporal2`, `static`, `temporal4_merged`) used 8×8 or 7×17 grids. The
`spatial_focus` encoding's 11×11 grid captures the hand more tightly, improving spatial
resolution in the region that matters most. The two-window split preserves temporal dynamics
(e.g., direction of motion) without requiring a time loop in hardware.

**Four available encodings** (for reference):

| Encoding | Windows | Grid | Polarity | Axons |
|---|---|---|---|---|
| `temporal2` (legacy default) | 2 | 8×8 | separate ON/OFF | 256 |
| `static` | 1 | 7×17 | separate ON/OFF | 238 (padded to 256) |
| `temporal4_merged` | 4 | 8×8 | merged | 256 |
| **`spatial_focus`** (**active**) | **2** | **11×11** | **merged** | **242 (padded to 256)** |

---

### Stage 2 — SNN Model Training
**Script**: `training/train_dvs128.py`  
**Model definition**: `training/snn_model.py`  
**Output**: `checkpoints/best.pt` (PyTorch weights)

**What the model looks like**:
The SNN has 3 fully-connected layers (called L0, L1, L2) using `BinaryLinear` layers — a
custom linear layer whose weights are binarized to {0, 1} during the forward pass using the
Straight-Through Estimator (STE) for gradient flow during training.

Each `BinaryLinear` is followed by a Leaky Integrate-and-Fire (LIF) neuron layer implemented
via `snntorch`. The LIF membrane potential decays each step, and the neuron fires a spike (1)
when the potential crosses the threshold. This matches the hardware LIF behavior exactly.

**Training strategy**:
- **Binary Weights {0, 1}**: Physically stored as active (1) or silent (0) bits in ReRAM.
- **Axon-Sign Encoding**: Odd-indexed axons negate the stimulus, creating effective excitatory (+1) and inhibitory (-1) connections without needing negative bits in memory.
- **Learned Thresholds & Beta**: The network learns the optimal firing threshold (`NEURON_THRESHOLD`) and leak factor (`NEURON_LEAK_SHIFT`) for every core.
- **Surrogate Gradients**: Uses **Fast Sigmoid** surrogate gradients to allow backpropagation through non-differentiable spiking neurons.
- **Loss Function**: majority-vote cross-entropy + asymmetric spike-rate regularization.
- **Spike-rate Regularization**: keeps each layer firing near 25–30% to prevent dead neurons or saturation.

**Why binary weights?**  
The ReRAM crossbar physically stores one bit per cell. A floating-point weight would require
ADC/DAC circuitry that consumes orders of magnitude more power. Binary weights are the only
option compatible with direct 1T1R ReRAM programming.

---

### Stage 3 — Weight Export
**Script**: `training/export_weights.py`  
**Output**: `mem/connection/connection_000` through `connection_020` (21 files)

**What happens**:
After training, the binary weight matrices are extracted from the PyTorch checkpoint and
written to text files, one file per hardware core:

- Each file is a `NUM_AXONS × NEURONS_PER_CORE` bit matrix (256 rows × 64 columns = 16384 bits).
- File naming encodes which network layer and core number each file corresponds to:
  - `connection_000` – `connection_012` → Layer 0 (13 cores)
  - `connection_013` – `connection_016` → Layer 1 (4 cores)
  - `connection_017` – `connection_020` → Layer 2 (4 cores)
  - Total: 21 files, one per core.

**Format detail**:
Each row in a `connection_XXX.txt` file is a 64-character binary string (one bit per neuron).
Row `r`, column `c` = the weight between axon `r` and neuron `c` in that core. A `1` means
the synapse is active; a `0` means it is silent.

**Why 21 files?**  
Each hardware core is a physical `nvm_neuron_core_256x64` module with its own ReRAM array.
There is no shared weight bus — every core must be programmed independently.

---

### Stage 4 — ReRAM Weight Programming (Hardware)
**RTL module**: `verilog/rtl/SNN_gesture/hdl/nvm_synapse_matrix.v`  
**Address decoder**: `verilog/rtl/SNN_gesture/hdl/nvm_core_decoder.v`  
**Wishbone address**: `0x3000_000C`

**What happens**:
Before inference can run, the ReRAM cells must be programmed with the trained weights. The
Caravel RISC-V core (management SoC) performs Wishbone write transactions to program each
axon-neuron connection one row at a time.

**Data packet format** (same 32-bit word for PROGRAM and READ):
```
wbs_dat_i[31:30]  — MODE:  0b11 = PROGRAM,  0b01 = READ (inject axon)
wbs_dat_i[29:25]  — ROW:   5-bit row address (0–31) inside each 32×32 macro
wbs_dat_i[24:20]  — COL:   5-bit column address (0–31) inside each 32×32 macro
wbs_dat_i[19:16]  — (unused)
wbs_dat_i[15:0]   — DATA:  For PROGRAM: bits[15:0] are the 16 weight bits sent to 16 macros
                            For READ:    bits[15:0] are the 16-bit signed stimulus value
```

**Macro topology**:
The synapse matrix contains `NUM_OF_MACRO=16` instances of the `Neuromorphic_X1` 32×32
ReRAM tile, instantiated in `nvm_synapse_matrix.v`. All 16 macros share the same (row, col)
address and receive the PROGRAM command simultaneously — `wbs_dat_i[i]` is the weight bit
written to macro `i`. This means one Wishbone write programs all 16 neurons' weights for a
given (axon, group) position.

**Timing**: ReRAM PROGRAM operations are slow. The hardware **never returns an ACK** for
PROGRAM transactions; firmware waits `2×WR_Dly+1 = 401` cycles unconditionally before
issuing the next write. This is a hardware contract: attempting a second write before the
wait time corrupts the cell state.

**Why no ACK for PROGRAM?**  
The Neuromorphic_X1 IP does not have a ready signal for write completion. The `wbs_ack_o`
in `nvm_synapse_matrix.v` is gated by `wbs_we_i_reversed` (a 1-cycle delayed `~wbs_we_i`),
which suppresses ACKs during writes while allowing them during reads.

---

### Stage 5 — Axon Injection (Inference)
**RTL modules**: `nvm_synapse_matrix.v` → `nvm_neuron_block.v`  
**Wishbone address**: `0x3000_0000` (READ transaction with MODE=`0b01`)  
**Read latency**: `RD_Dly=44` cycles after strobe

**What happens**:
Inference begins by injecting the 256-element axon vector (each of 16-bit) into the core one axon at a time.
For each axon `a` with value `val`:

1. The firmware encodes `(row, col, val)` into a 32-bit data packet and issues a Wishbone
   READ to `0x3000_000C`.
2. The synapse matrix decodes `row` and `col` from `wbs_dat_i[29:25]` and `wbs_dat_i[24:20]`
   (not from the address — the address is always `0x3000_000C`).
3. All 16 macros perform a READ of cell (row, col) simultaneously. Each macro returns the
   1-bit synapse weight for its neuron group. The 16 bits are concatenated into a 16-bit
   `connection` vector.
4. The `Neuromorphic_X1` engine ACKs after `RD_Dly=44` cycles.
5. The ACK pulse is routed to `nvm_neuron_block` as the `enable` signal. The neuron block
   uses `connection[i]` to decide whether neuron `i` integrates the stimulus.

**Sign convention — axon polarity**:
Binary weight values {0, 1} cannot represent inhibition directly. The solution is the
**axon-sign encoding**: `col[0]` (the LSB of the column address) determines the sign:
- `col[0] = 0` → even column → stimulus = `+val` (excitatory)
- `col[0] = 1` → odd column → stimulus = `−val` (inhibitory)

This is implemented in `nvm_neuron_core_256x64.v`:
```verilog
assign weight_type = col[0];
assign stimuli     = weight_type ? -wbs_dat_i[15:0] : wbs_dat_i[15:0];
```

The training script mirrors this in `axon_sign` buffers so the PyTorch forward pass
computes the same signed accumulation as the hardware.

---

### Stage 6 — LIF Neuron Integration
**RTL module**: `verilog/rtl/SNN_gesture/hdl/nvm_neuron_block.v`  
**Parameters**: `NEURON_THRESHOLD=4`, `NEURON_LEAK_SHIFT=16` (from `nvm_parameter.vh`)

**What happens**:
The LIF (Leaky Integrate-and-Fire) neuron block processes each incoming stimulus:

For each axon where `connection[i]=1` (synapse is active for neuron `i`):
```
potential[i] += stimuli   (16-bit signed accumulation)
```

The "leak" is applied *differently from a classical time-stepping SNN* — see the critical
design note below.

**Leak implementation (round-toward-zero)**:
```
abs_pot   = |potential|
leak_mag  = abs_pot >>> LEAK_SHIFT
leak      = potential[15] ? −leak_mag : +leak_mag   (sign-preserve)
next_pot  = potential − leak + stimuli
```

At `LEAK_SHIFT=16`, the leak of a 16-bit value is always 0 (since 16-bit >>> 16 = 0).
The leak term effectively does nothing during accumulation — it exists as a regularizer
to prevent potential from growing unboundedly if `LEAK_SHIFT` is reduced.

**Saturation**:
Potentials are clamped to the signed 16-bit range [−32768, +32767] using a 17-bit
intermediate wire to catch overflow before truncation.

**Threshold check**:
After `picture_done` (the end-of-gesture signal), for each neuron `i`:
```
spike_o[i] = (potential[i] >= NEURON_THRESHOLD)   // NEURON_THRESHOLD = 4
```

> **Critical design note — "Flattened Time"**:
> This SNN does **not** use spike trains over time. All 256 axons encode a complete
> gesture as spatial channels. Leak is applied *once* per picture_done, not per axon.
> If leak were applied per-axon inside the injection loop, early axons would decay
> ~256× more than late axons, introducing severe input-order bias (this was Root Cause F-24
> in the accuracy RCA: applying leak per-axon caused a 30.5pp accuracy drop). Correct
> behavior: accumulate all axons first, apply leak+threshold once at picture_done.

---

### Stage 7 — Spike Latch and Readback
**RTL module**: `verilog/rtl/SNN_gesture/hdl/nvm_neuron_spike_out.v`  
**picture_done addresses**: `0x3000_2000`, `0x3000_2002`, `0x3000_2004`, `0x3000_2006`  
**Readback addresses**: `0x3000_1000` (neurons 0–31), `0x3000_1004` (neurons 32–63)

**What happens**:
At the end of each gesture's axon-injection loop, the firmware signals `picture_done` by
writing to any of the four `0x3000_2xxx` addresses. This triggers two actions simultaneously:

1. **Spike latch**: The 64 spike values (`spike_o[0:63]`) are written into a 4×16-bit SRAM
   in `nvm_neuron_spike_out`. Each write captures 16 spikes:
   - Write to `0x3000_2000` → latches neurons 0–15
   - Write to `0x3000_2002` → latches neurons 16–31
   - Write to `0x3000_2004` → latches neurons 32–47
   - Write to `0x3000_2006` → latches neurons 48–63

2. **Potential reset**: `picture_done` resets all 64 neuron potentials to zero, preparing
   the core for the next gesture.

**Readback**:
The firmware reads back the latched spikes:
- `wb_read(0x3000_1000)` returns `{neurons_16_31, neurons_0_15}` (32 bits)
- `wb_read(0x3000_1004)` returns `{neurons_48_63, neurons_32_47}` (32 bits)

> **Do not read `0x3000_1006`** — this address decodes to the spike SRAM but is out of
> range and returns undefined data.

---

### Stage 8 — Classification by Majority Vote
**Function**: `interleaved_vote()` in `verilog/tb/snn_gesture/utils/snn_hw_utils.py`

**What happens**:
After reading all 64 spikes from a core, the firmware collects the spike vectors from all
L2 cores (4 cores × 64 neurons = 256 total neurons, though only the first 240 are active,
giving `NUM_VOTES=240`). Classification uses **interleaved majority voting**:

- Neuron `i` votes for class `i % NUM_CLASS` (where `NUM_CLASS=12`)
- Each class accumulates 240/12 = 20 votes from the 240 active L2 neurons
- The class with the most votes is the prediction: `argmax(vote_counts)`

**Why interleaved voting?**  
The hardware RTL assigns neurons to output positions in round-robin order (core 0 neuron 0,
core 1 neuron 0, core 2 neuron 0, core 3 neuron 0, core 0 neuron 1, …). Interleaved voting
matches this assignment exactly, so each class receives votes from neurons spread evenly
across all 4 L2 cores rather than being dominated by one core.

---


## Hardware Physical Structure (for Openlane Hardening)

### ReRAM Macro Topology

One `nvm_neuron_core_256x64` contains:
- **8 × Neuromorphic_X1** ReRAM macros (tapeout), each a 32-row × 32-column bit array
- **Total bits**: 8 × 32 × 32 = 8,192 bits = 256 axons × 32 neurons per tile

> **Note**: The original design used 16 macros (64 neurons/tile). The tapeout configuration
> uses 8 macros due to Caravel die-area constraints. `NUM_OF_MACRO` is fully parametric —
> see [openlane/SNN_gesture/README.md](openlane/SNN_gesture/README.md).

Axon-to-macro mapping:
- Axon index = `(row[2:0] << 5) | col` → maps a (row, col) pair in the macro to one axon
- All 8 macros share the same (row, col) address; macro `i` stores the weight for neuron
  group `i`

A single PROGRAM write to `0x3000_000C` simultaneously sets 1 weight bit in all 8 macros
(for the same axon position). Programming all weights takes 256×4 = 1024 Wishbone writes
per core (256 axon positions, 4 row-groups).


---

## Parameters

All hardware-critical constants live in exactly **two** files that must stay synchronized:

| Parameter | RTL source | Python source | Value |
|---|---|---|---|
| `NUM_OF_MACRO` | `nvm_parameter.vh` | `nvm_parameter.py` | **8** (tapeout) / 16 (original) |
| `NEURON_THRESHOLD` | `nvm_parameter.vh` | `nvm_parameter.py` | 4 |
| `NEURON_LEAK_SHIFT` | `nvm_parameter.vh` | `nvm_parameter.py` | 16 |
| `NUM_AXON` | `nvm_parameter.py` | (RTL: port width) | 256 |
| `NUM_NEURON` | `nvm_parameter.py` | (derived: `NUM_OF_MACRO×4`) | **32** (tapeout) / 64 (original) |
| `NUM_CLASS` | `nvm_parameter.py` | `snn_model.py` | 12 |

> **Tapeout hardware limitation**: `NUM_OF_MACRO` was reduced from 16 to 8 due to
> Caravel die-area constraints. See [openlane/SNN_gesture/README.md](openlane/SNN_gesture/README.md)
> for full details. Training and weight export adapt automatically via `nvm_parameter.py`.

`nvm_parameter.vh` is `\`include`d by every RTL module that needs these values.
`nvm_parameter.py` is imported by every Python test and reference model.

> **If you change `NUM_OF_MACRO`**: it is defined once in `nvm_parameter.vh` and propagated
> via Verilog parameter override from `nvm_neuron_core_256x64` down to `nvm_synapse_matrix`
> and `nvm_neuron_block`. On the Python side, update `nvm_parameter.py` — the reference
> model and test utilities import it from there automatically.

---

## Accuracy Journey

### Performance Benchmarks

Below is the accuracy achieved across various preprocessing encodings and training strategies. The **Single Phase** strategy (training with a single global threshold) consistently outperforms the Multi Phase strategy.

| Encoding | Multi Phase (8 thr) | Single Phase (8 thr) | Multi Phase (4 thr) | Single Phase (4 thr) | Multi Phase (1 thr) | Single Phase (1 thr) |
|---|---|---|---|---|---|---|
| `temporal2` (default) | 45.49% | 53.82% | 43.06% | 55.90% | 46.18% | 55.90% |
| `spatial_focus` | — | 63.89% | 57.29% | **65.62%** | 50.00% | 63.19% |
| `temporal4_merged` | — | 60.76% | — | 57.99% | — | 54.17% |

*Values in **bold** represent the best overall configuration used for final hardware deployment.*

### Detailed Ablation Results (Threshold Sweeps)

For selected configurations, we swept the hardware threshold during inference to observe the impact of quantization. The notation `X% - Y% (Z)` indicates `X%` accuracy at the original threshold, and `Y%` at an optimized inference threshold `Z`.

| Encoding | Phase | Result (Baseline -> Best Quantized) |
|---|---|---|
| `temporal2` | Single | 55.90% -> 51.04% (1) |
| `spatial_focus` | Single | 65.62% -> **62.15% (4)** |
| `temporal4_merged` | Single | 60.76% -> 57.64% (7) |

### Accuracy Roadmap

| Milestone | HW Accuracy | SW Accuracy | Key Change |
|---|---|---|---|
| **Placeholder** | 2% | — | Initial project setup with random weights |
| **First Training** | ~4% | ~56% | First weights trained with `temporal2`, but HW bugs unresolved |
| **Leak Fix (F-24)** | +30.5pp | +0pp | Corrected leak rounding to be symmetric across signs |
| **Quantization Alignment** | 53% | 56% | Matched Python/Hardware potential saturation logic |
| **`spatial_focus` Encoding** | **62%** | **66%** | **Final state**: Switch to spatial-focus grid and 4-threshold training |

The final ~4pp gap between Software and Hardware is a result of full network quantization (weights and potentials) across all three layers.

---

## Navigation Table

| I want to… | Go here |
|---|---|
| Understand training pipeline, encodings, and weight export | [training/README.md](training/README.md) |
| Walk through the full pipeline interactively (runnable notebook) | [training/SNN_Training_Walkthrough.ipynb](training/SNN_Training_Walkthrough.ipynb) |
| Understand the Python reference model and verification invariants | [verilog/tb/snn_gesture/README.md](verilog/tb/snn_gesture/README.md) |
| Understand RTL modules, Wishbone interface, and design decisions | [verilog/rtl/SNN_gesture/README.md](verilog/rtl/SNN_gesture/README.md) |
| Understand OpenLane hardening, 8-macro limitation, and placement | [openlane/SNN_gesture/README.md](openlane/SNN_gesture/README.md) |
