# SNN Gesture Recognition — Verification Framework

Python reference model, hardware invariants, and 7-phase cocotb bottom-up test suite for the 256×64 LIF neuromorphic core.

**This testbench targets the tapeout-ready design** (`verilog/rtl/SNN_gesture/hdl/`). For architectural context, see [`snn_gesture_working.md`](../../../snn_gesture_working.md); for RTL module details, see [`verilog/rtl/SNN_gesture/README.md`](../../rtl/SNN_gesture/README.md).

---

## Python Reference Model

[`snn_reference_model.py`](./snn_reference_model.py) is a pure Python implementation that mirrors the RTL **exactly** — same arithmetic, same data flow, same indexing, same memory layout.

**Role**:
- Generates expected outputs for all cocotb tests before running hardware simulation
- Validates trained weights via [`validate_reference_model.py`](../../../training/validate_reference_model.py)
- Implements the complete 3-layer inference pipeline including layer routing and final classification voting.

**Key design**:
- Stateless functions operating on plain Python dicts (no classes)
- Implements three core operations: `program_macro()`, `inject_stimulus()`, `picture_done()`
- Leak applied **once per gesture at `picture_done`** (not per-axon) — see Hardware Constraints table
- 17-bit saturation arithmetic to match RTL behavior on negative potentials

---

## Supporting Python Files

| File | Purpose | Key API |
|------|---------|---------|
| `nvm_parameter.py` | Single source of truth for hardware constants (must sync with `nvm_parameter.vh`) | `NUM_AXON=256`, `NUM_NEURON=64`, `NEURON_THRESHOLD=4`, `NEURON_LEAK_SHIFT=16` |
| `snn_reference_model.py` (~1,100 lines) | Bit-accurate Python mirror of RTL; generates expected outputs for cocotb tests. Implements `make_core()`, `program_macro()`, `inject_stimulus()`, `picture_done()`, `full_network_inference()`. Can run standalone to validate weights before simulation. | `full_network_inference(conn_list, stimuli_list)` |
| `utils/snn_hw_utils.py` | Hardware contract rules (single-source-of-truth to prevent HW/SW gaps). Shared across PyTorch training, Python reference, and cocotb tests. | `interleaved_vote()`, `interleaved_accuracy()`, `load_nvm_parameter()` |
| `utils/snn_test_utils.py` | Cocotb test helpers: clock setup, Wishbone writes/reads, picture_done trigger, potential inspection. | `setup_dut()`, `nvm_program()`, `nvm_inject()`, `trigger_picture_done()`, `wb_read()` |
| `utils/read_file.py` | Data file I/O: parses connection matrices (MSB-first binary), packs stimuli into Wishbone words. | `read_matrix_from_file()`, `list_to_binary()`, `calculate_majority_class()` |

**snn_reference_model.py standalone usage**:
```bash
python snn_reference_model.py --conn-dir mem/connection --stimuli mem/stimuli/stimuli.txt --num-pics 10
```

---

## Hardware Constraints & Verification Invariants

**Firmware & test constraints are detailed in [`verilog/rtl/SNN_gesture/README.md`](../../rtl/SNN_gesture/README.md) — Firmware Constraints section.** Below are verification-specific invariants.

| Constraint | Source | Verification impact | Reference |
|-----------|--------|---------------------|-----------|
| **F-04** PROGRAM never ACKs | RTL | Cocotb must not wait for ACK; wait ≥401 cycles unconditionally | `test_wb_interface.py:test_synapse_write_no_ack` |
| **F-08** Interleaved WB ops corrupt stimulus | RTL | No Wishbone writes allowed during 44-cycle READ wait | `test_synapse_matrix.py:test_read_with_drain` |
| **F-10** Out-of-bounds spike read | RTL | Only read `0x3000_1000` and `0x3000_1004`; never `0x3000_1006` | `test_spike_out.py` |
| **F-14** MSB-first connection format | RTL | Connection files reversed; bit-order mismatch → ~50% accuracy drop | `export_weights.py`, `read_file.py` |
| **F-15** Narrow picture_done writes fail | RTL | Picture_done requires full 32-bit write (`wbs_sel_i=4'hF`) | `test_spike_out.py:test_spike_latch` |
| **F-17** Unused axons (L0: 18, L1: 48) | RTL | Inject `0x0000` for unused positions; prevents garbage accumulation | Layer routing tests |
| **Leak** Applied once at picture_done | RTL | Leak per-axon causes 30.5pp accuracy drop (F-24) | Phase 3–7 tests |
| **Drain** 254 cycles after PROGRAM/READ | RTL | X1 engine has no reset; in-flight ops must drain | `test_synapse_matrix.py:test_read_with_drain` |
| **0xDEAD_C0DE** sentinel from empty FIFO | Test-specific | Exclude sentinel in assertions; don't treat as zero | `test_synapse_matrix.py:test_dead_code_sentinel` |
| **Sign encoding** col[0]=1 → negate | Hardware contract | Odd columns negate; must match `snn_hw_utils.py` | `test_neuron_block.py:test_stimuli_sign_convention` |

---

## 7-Phase Cocotb Verification Framework

Bottom-up test suite: each phase depends on the one below it passing cleanly. All tests live in [cocotb/](./cocotb/).

### Phase 1: Wishbone Interface & Reset (`test_wb_interface.py`)

**DUT**: `nvm_neuron_core_256x64` (top-level)  
**Scope**: Wishbone protocol compliance, reset behavior, address decoding  
**Command**: `cd cocotb && make MODULE=test_wb_interface`

**Key tests**:
- `test_reset_state`: Outputs are 0 after reset
- `test_spike_out_read_ack`: Spike-out reads respond with ACK
- `test_picture_done_ack`: `picture_done` writes respond with ACK
- `test_synapse_write_no_ack`: PROGRAM writes never ACK (due to `wbs_we_i_reversed`)
- `test_sel_not_f_ignored`: Only full 32-bit writes (`wbs_sel_i=4'hF`) are accepted

**Constraints verified**:
- Address decoder routes `0x3000_0xxx` → synapse matrix, `0x3000_1xxx` → spike read, `0x3000_2xxx` → picture_done
- ACK timing respects Wishbone protocol (1 cycle after ready data)
- Narrow writes (8-bit, 16-bit) are silently ignored (F-15 constraint)

### Phase 2: ReRAM Synapse Matrix (`test_synapse_matrix.py`)

**DUT**: `nvm_neuron_core_256x64`  
**Scope**: PROGRAM and READ operations, macro indexing, drain phase  
**Command**: `cd cocotb && make MODULE=test_synapse_matrix`

**Key tests**:
- `test_program_single_macro`: Write one weight, verify it's stored
- `test_program_all_macros`: Write 16 bits simultaneously (one per macro)
- `test_read_with_drain`: Verify drain phase required between consecutive READs
- `test_dead_code_sentinel`: Handle `0xDEAD_C0DE` from empty FIFO
- `test_row_col_address_mapping`: Verify row/col decoding is correct

**Constraints verified**:
- PROGRAM never returns ACK (F-04)
- PROGRAM must wait ≥401 cycles before next PROGRAM (2×WR_Dly+1)
- READ returns data after ≥44 cycles (RD_Dly)
- Macro indexing: data[i] → macro_i
- Address space: `0x3000_0000` is synapse_matrix_select (decoder: `addr[15:12]==0`)

### Phase 3: LIF Neuron Block (`test_neuron_block.py`)

**DUT**: `nvm_neuron_core_256x64`  
**Scope**: Accumulation, leak, threshold, saturation, picture_done  
**Command**: `cd cocotb && make MODULE=test_neuron_block`

**Key tests**:
- `test_neuron_initial_spike_after_reset`: All neurons silent (potential < threshold) at reset
- `test_neuron_accumulation_positive`: Even-column stimulus accumulates correctly
- `test_neuron_accumulation_negative`: Odd-column stimulus negated
- `test_multiple_axon_accumulation`: Multiple stimuli sum correctly
- `test_potential_saturation`: 16-bit saturation at ±32767
- `test_threshold_boundary`: Spike fires at potential ≥ NEURON_THRESHOLD
- `test_picture_done_reset`: Potentials reset to 0 after picture_done

**Constraints verified**:
- Leak applied once (not per-axon) after all 256 axons
- Saturation at signed 16-bit range (17-bit intermediate)
- Picture_done has priority over accumulation enables
- Threshold is inclusive (≥, not >)

### Phase 4: Spike Output SRAM (`test_spike_out.py`)

**DUT**: `nvm_neuron_core_256x64`  
**Scope**: Spike latch, readback SRAM, packing format  
**Command**: `cd cocotb && make MODULE=test_spike_out`

**Key tests**:
- `test_spike_latch_fires_on_picture_done`: Spikes latch into SRAM on picture_done
- `test_spike_readback_lo_hi`: Read addresses `0x3000_1000` (neurons 0–31), `0x3000_1004` (neurons 32–63)
- `test_spike_packing`: Verify bit-to-neuron mapping in SRAM
- `test_invalid_spike_read`: Address `0x3000_1006` (out of bounds) is not readable (F-10)

**Constraints verified**:
- SRAM is 4×16-bit (4 registers, 16 bits each)
- Spike `i` maps to bit `i % 16` in SRAM register `i / 16`
- Picture_done requires full 32-bit write (`wbs_sel_i=4'hF`, F-15)

### Phase 5: Single Core End-to-End (`test_single_core.py`)

**DUT**: `nvm_neuron_core_256x64`  
**Scope**: Full inference pipeline (PROGRAM → INJECT 256× → picture_done → READ)  
**Command**: `cd cocotb && make MODULE=test_single_core`

**Key tests**:
- `test_single_core_vs_reference_model`: Full inference matches `snn_reference_model.py` exactly
- `test_axon_sign_convention`: Even/odd columns apply sign correctly
- `test_layer_routing`: Verify core receives correct subset of axons

**Constraints verified**:
- Bit-accurate match with Python reference model
- Sign encoding matches hardware contract
- All 256 axons accumulated correctly despite time-multiplexing

### Phase 6: Layer-Level Inference (`test_layer_inference.py`)

**DUT**: Multi-core setup simulating layer topology  
**Scope**: L0→L1→L2 routing, partitioned vs broadcast, voting  
**Command**: `cd cocotb && make MODULE=test_layer_inference`

**Key tests**:
- `test_l0_broadcast`: All 13 L0 cores receive same 256-axon input
- `test_l1_partitioned`: 4 L1 cores each receive 208 spikes (non-overlapping partitions)
- `test_l2_broadcast`: All 4 L2 cores receive all 256 L1 spikes
- `test_interleaved_voting`: Final vote matches `interleaved_vote()` from `snn_hw_utils.py`

**Constraints verified**:
- Layer routing correct: L0 → 832 spikes → L1 partitioned → 256 spikes → L2 broadcast → 240 votes
- Voting rule: neuron i votes for class (i % 12)

### Phase 7: Full Network Accuracy (`test_full_network.py`)

**DUT**: Full 3-layer network (21 cores: 13 L0 + 4 L1 + 4 L2)  
**Scope**: End-to-end accuracy on exported test stimuli  
**Command**: `cd cocotb && make MODULE=test_full_network`

**Prerequisite**: Trained weights and stimuli must be exported from training pipeline.

**Key tests**:
- `test_accuracy_vs_reference`: RTL predictions match Python reference model
- `test_accuracy_threshold`: Accuracy ≥ target (default ≥ 53% on test set)
- `test_per_class_recall`: Per-class recall for all 12 gesture classes

**Debug variant**: `test_full_network_debug.py` prints per-sample predictions and potential traces.

---

## Preparing Weights and Stimuli for Verification

### Step 1: Train the Model

From the project root:
```bash
cd training

# Preprocess DVS128 dataset
python dvs128_preprocess.py --encoding spatial_focus

# Train SNN (80 epochs)
python train_dvs128.py --data-dir data --epochs 80

# Verify weights are bit-accurate
python validate_reference_model.py --checkpoint checkpoints/best.pt
```

### Step 2: Export Weights and Stimuli

```bash
cd training

# Export weights (21 files: L0+L1+L2 cores)
python export_weights.py --checkpoint checkpoints/best.pt

# Export test stimuli
python export_stimuli.py
```

### Step 3: Copy to RTL Memory Directory

```bash
# Run from project root
# Connection files and stimuli are now sourced directly from verilog/rtl/SNN_gesture/mem/
cp -r mem/* verilog/rtl/SNN_gesture/mem/

# Verify files
ls -la verilog/rtl/SNN_gesture/mem/connection/ | wc -l  # should be 21
```

### Step 4: Run Cocotb Tests

```bash
cd cocotb

# Run Phase 1 Wishbone interface tests
make MODULE=test_wb_interface SIM=icarus

# Run Phase 2 ReRAM synapse matrix tests
make MODULE=test_synapse_matrix SIM=icarus

# Run Phase 3 Neuron block tests 
make MODULE=test_neuron_block SIM=icarus

# Run Phase 4 Spike Output tests 
make MODULE=test_spike_out SIM=icarus

# Run Phase 5 Single Core E2E tests
make MODULE=test_single_core SIM=icarus

# Run Phase 6 Layer Inference tests
make MODULE=test_layer_inference SIM=icarus

# Run Phase 7 (full network accuracy)
make MODULE=test_full_network SIM=icarus

## To generate waveform for any test, add WAVES=1 flag
make MODULE=<testname> SIM=icarus WAVES=1

```

---

## Quick Debugging

 - **Single complete gesture simulation**:
```bash
cd cocotb
make MODULE=test_full_network_debug SIM=icarus
# Prints predictions, confidence scores, per-gesture traces
```

- **Intermediate values during simulation**:
Use `snn_test_utils.get_potential(dut, neuron_id)` to inspect neuron potentials in real-time. Supported by Verilator/Questa; Icarus may not support this.


- **Cross-check with reference model**:
```bash
python ../snn_reference_model.py \
  --conn-dir ./mem/connection \
  --stimuli ./mem/stimuli/stimuli.txt \
  --num-pics 10
```

---

## Architecture Quick Links

| I want to… | Go here |
|---|---|
| Understand training pipeline, encodings, weight export | [training/README.md](../../../training/README.md) |
| Walk through the full pipeline interactively | [training/SNN_Training_Walkthrough.ipynb](../../../training/SNN_Training_Walkthrough.ipynb) |
| Understand RTL modules and Wishbone interface | [verilog/rtl/SNN_gesture/README.md](../../rtl/SNN_gesture/README.md) |
| Understand full system architecture and end-to-end data flow | [snn_gesture_working.md](../../../snn_gesture_working.md) |
| Run a specific test phase | [cocotb/Makefile](./cocotb/Makefile) |
