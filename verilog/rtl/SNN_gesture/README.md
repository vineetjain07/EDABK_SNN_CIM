# RTL: SNN Gesture Core

Tapeout-ready 256-axon × 64-neuron LIF inference core on the Caravel SoC platform, interfaced via Wishbone. Binary-weight synapse matrix uses BM Labs Neuromorphic X1 ReRAM IP for in-memory computing.

**Platform**: Wishbone interface on Caravel SoC  
**Neurons**: 64 LIF (Leaky Integrate-and-Fire)  
**Weights**: Binary (0 or 1) stored in ReRAM crossbar  
**Inference**: Single pass per gesture (all 256 inputs processed in one batch, no time steps)

---

## Module Hierarchy

```
nvm_neuron_core_256x64           top-level: Wishbone interface + inference orchestration
├── nvm_core_decoder              address decoder: routes Wishbone to synapse/spike/picture_done
├── nvm_synapse_matrix            256-axon × 64-neuron ReRAM crossbar
│   └── Neuromorphic_X1_Beh ×16  behavioral shim for BM Labs 32×32 ReRAM macro (16 instances)
├── nvm_neuron_block              16 LIF neurons each.
└── nvm_neuron_spike_out          4×16-bit SRAM: latches 64 spike outputs on picture_done
```

| Module | File | Description |
|--------|------|-------------|
| `nvm_neuron_core_256x64` | `nvm_neuron_core_256x64.v` | Top-level: Wishbone slave + orchestration of all sub-blocks |
| `nvm_core_decoder` | `nvm_core_decoder.v` | Decodes `wbs_adr_i[15:12]` to select synapse (0), spike-out (1), or picture_done (2) |
| `nvm_synapse_matrix` | `nvm_synapse_matrix.v` | Instantiates 16 × Neuromorphic_X1 macros (32×32 each, `NUM_OF_MACRO=16`); broadcasts PROGRAM/READ; aggregates 1-bit synapse outputs; all 16 macros daisy-chained on one scan chain |
| `Neuromorphic_X1_Beh` | `Neuromorphic_X1_Beh.v` | Behavioral shim for the 32×32 ReRAM IP; supports PROGRAM and READ operation modes |
| `nvm_neuron_block` | `nvm_neuron_block.v` | 16 LIF neurons: accumulate synapse current, apply leak, check threshold, fire spike |
| `nvm_neuron_spike_out` | `nvm_neuron_spike_out.v` | Stores 64 spike bits in 4×16-bit registers; readable via Wishbone at `0x3000_1xxx` |
| `nvm_parameter.vh` | `nvm_parameter.vh` | Hardware LIF parameters — **must match `verilog/tb/snn_gesture/nvm_parameter.py`** |

---

## ReRAM Behavioral Model: Hardware, Constraints & Wait Cycles

### Architecture Overview

The ReRAM synapse matrix uses **16 instances of the Neuromorphic X1 32×32 1-bit array** (parametrized as `NUM_OF_MACRO=16`). Each macro stores synapses between 256 input axons and one neuron's destination. The 16 macros are accessed in **parallel on a shared address bus** at `0x3000_000C`, with one bit per macro forming a 16-bit result (one per neuron group).

```
┌─────────────────────────────────────────────┐
│  Wishbone Interface (0x3000_000C)           │
│  MODE[31:30] | ROW[29:25] | COL[24:20] | ..│
└───────────────┬──────────────────────────────┘
                │
    ┌───────────┴───────────┬──────────────────────────────┐
    │                       │                              │
    ▼                       ▼                              ▼
┌──────────┐          ┌──────────┐                   ┌──────────┐
│ X1_0     │          │ X1_1     │  ...             │ X1_15    │
│ 32×32    │          │ 32×32    │                   │ 32×32    │
│ 1-bit    │          │ 1-bit    │                   │ 1-bit    │
│ array    │          │ array    │                   │ array    │
└────┬─────┘          └────┬─────┘                   └────┬─────┘
     │ (1 bit)             │ (1 bit)                      │ (1 bit)
     └─────────────────────┼──────────────────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ connection[15:0] │
                  │ (packed result)  │
                  └──────────────────┘
```

Each macro has internal state machines for:
- **Input FIFO** (32 deep): enqueues PROGRAM and READ commands
- **Output FIFO** (32 deep): holds READ results (one per request)
- **32×32 1-bit array**: the physical memory (all zero-initialized)
- **Background engine**: executes commands asynchronously

### Operating Modes

#### PROGRAM (MODE = `2'b11`)

**Purpose**: Write a synapse weight to ReRAM.

**Command packet** (latched in ip_fifo):
```
wbs_dat_i[31:30]  = 2'b11       (PROGRAM mode)
wbs_dat_i[29:25]  = row[4:0]    (which row in the 32-row macro)
wbs_dat_i[24:20]  = col[4:0]    (which column)
wbs_dat_i[7:0]    = weight_byte (>0x7F → write 1; ≤0x7F → write 0)
```

**Hardware sequence**:
1. Master writes packet to Wishbone @ `0x3000_000C`
2. Macros enqueue command; `core_ack` fires **immediately** (fire-and-forget)
3. Background engine waits `WR_Dly=200` cycles (simulink-only delay for real chip timing)
4. Engine writes 1-bit to `array_mem[row][col]` in all 16 macros
5. Operation completes silently; no acknowledgment signal fires

**Key constraint — No ACK feedback**: Firmware cannot detect completion. Must wait fixed time.

**Wait time**: `401 cycles` (200 write delay + 201 setup/teardown margin)

---

#### READ (MODE = `2'b01`)

**Purpose**: Fetch synapse weights and immediately integrate into neurons.

**Command packet**:
```
wbs_dat_i[31:30]  = 2'b01           (READ mode)
wbs_dat_i[29:25]  = row[4:0]
wbs_dat_i[24:20]  = col[4:0]
wbs_dat_i[15:0]   = stimulus[15:0]  (will be accumulated if synapse=1)
```

**Hardware sequence**:
1. Master writes packet to Wishbone @ `0x3000_000C`
2. Macros enqueue command; **no immediate ACK**
3. Background engine (sim-only) waits `RD_Dly=44` cycles
4. Engine reads 1-bit from each macro: `bit[i] = array_mem[row][col]` from X1_i
5. Packs bits into result: `{0…0, bit[15], …, bit[0]}`
6. Pushes result into op_fifo
7. **When op_fifo has a result**, next Wishbone READ (different cycle) pops result and fires `core_ack`
8. Neuron block integrates: `if (connection[j]==1) potential[j] += stimulus`

**Key insight**: The ACK comes from op_fifo **pop**, not from the hardware READ itself. This creates a 44-cycle pipeline latency followed by a transaction boundary.

**Wait time**: `44 cycles` (RD_Dly hardcoded in behavioral model)

---

### Wait Cycle Requirements and Rationale

#### Why 44 cycles for READ?

The 44-cycle wait breaks down as:

| Phase | Cycles | Purpose | Source |
|-------|--------|---------|--------|
| **Enqueue** | 1 | Wishbone WRITE lands in ip_fifo | [`Neuromorphic_X1_Beh.v:244-248`](hdl/Neuromorphic_X1_Beh.v#L244) (WB WRITE handler) |
| **Access delay** | ~35–40 | Analog ReRAM physics: word-line settling, cell current sensing, comparator delay, ADC conversion (real chip); behavioral model uses fixed 44 for reproducibility | [`Neuromorphic_X1_Beh.v:197`](hdl/Neuromorphic_X1_Beh.v#L197) (parameter `RD_Dly=44`) |
| **Output FIFO push** | 1 | Result pushed to op_fifo | [`Neuromorphic_X1_Beh.v:293-296`](hdl/Neuromorphic_X1_Beh.v#L293) (op_fifo enqueue) |
| **Read ACK** | 2–3 | Next Wishbone READ pops op_fifo and fires ACK; firmware stalls here until result is available | [`Neuromorphic_X1_Beh.v:251-255`](hdl/Neuromorphic_X1_Beh.v#L251) (WB READ handler + ACK logic) |

**Behavioral model**: Nested `@(posedge CLKin)` loops in `always @(posedge CLKin)` block at [`Neuromorphic_X1_Beh.v:289–291`](hdl/Neuromorphic_X1_Beh.v#L289). The `for (j = 0; j < RD_Dly; j++)` loop spins `RD_Dly=44` times on the clock edge, then pushes to op_fifo.

**Firmware constraint**: Between READ writes (stimulus injections), firmware **MUST wait exactly 44 cycles** before issuing the next command. Any shorter and op_fifo may be empty, causing the next write to stall indefinitely. Any longer wastes cycles.

```c
// Correct: 44-cycle wait ensures op_fifo has a result when next WRITE arrives
for (i = 0; i < 256; i++) {
  stimulus = get_input(i);
  write_to_hardware(0x3000_0000, encode_READ(row, col, stimulus));
  wait_cycles(44);  // EXACTLY 44
}
```

#### Why 401 cycles for PROGRAM?

The 401-cycle wait breaks down as:

| Phase | Cycles | Purpose | Source |
|-------|--------|---------|--------|
| **Enqueue** | 1 | PROGRAM command lands in ip_fifo | [`Neuromorphic_X1_Beh.v:244-248`](hdl/Neuromorphic_X1_Beh.v#L244) (WB WRITE handler) |
| **Write delay** | 200 | Behavioral model's `WR_Dly=200` (real chip: ~1000 cycles for ReRAM device physics) | [`Neuromorphic_X1_Beh.v:198`](hdl/Neuromorphic_X1_Beh.v#L198) (parameter `WR_Dly=200`); [`Neuromorphic_X1_Beh.v:278-280`](hdl/Neuromorphic_X1_Beh.v#L278) (sim-only delay loop) |
| **Safety margin** | ~100 | Account for ip_fifo depth, worst-case contention, simulator overhead | Implementation margin for behavioral model |
| **Drain guarantee** | ~100 | Ensure previous PROGRAM completely settles before next one can start | Required for in-flight operation clearance |

**Why no ACK?**: The `wbs_we_i_reversed` flip-flop ([`nvm_synapse_matrix.v:142–144`](../hdl/nvm_synapse_matrix.v#L142)) explicitly masks PROGRAM ACKs:

```verilog
always @(posedge wb_clk_i or posedge wb_rst_i) begin
  if (wb_rst_i) wbs_we_i_reversed <= 1'b1;
  else          wbs_we_i_reversed <= ~wbs_we_i;
end
assign wbs_ack_o = wbs_we_i_reversed & (|slave_ack_o);
// wbs_we_i=1 (WRITE) → wbs_we_i_reversed=0 → ACK suppressed
// wbs_we_i=0 (READ)  → wbs_we_i_reversed=1 → ACK passes through
```

This is intentional: because `core_ack` arrives 1 cycle late (after `wbs_we_i` drops), every ACK would otherwise look like a READ, triggering spurious neuron integrations during PROGRAM operations.

**Firmware constraint**: Must wait fixed time; no polling mechanism exists.


### ACK Timing and Master/Slave Handshake

Wishbone `ack_o` signals **transaction completion**, not **command execution completion**:

| Transaction | ACK Fires | Actual Execution | Source |
|---|---|---|---|
| PROGRAM WRITE | 1 cycle after WRITE (suppressed) | 200+ cycles later (background engine) | [`nvm_synapse_matrix.v:142-145`](../hdl/nvm_synapse_matrix.v#L142) (ACK suppression logic); [`Neuromorphic_X1_Beh.v:271-285`](hdl/Neuromorphic_X1_Beh.v#L271) (PROGRAM handler) |
| READ WRITE | 1 cycle after WRITE (no ACK yet) | 44 cycles later → result in op_fifo | [`Neuromorphic_X1_Beh.v:287-299`](hdl/Neuromorphic_X1_Beh.v#L287) (READ handler + op_fifo push) |
| READ READ | 1 cycle after READ (if op_fifo has result) | N/A (read-out only) | [`Neuromorphic_X1_Beh.v:251-259`](hdl/Neuromorphic_X1_Beh.v#L251) (op_fifo pop + ACK generation) |

**PROGRAM WRITE**: [`nvm_synapse_matrix.v:142-145`](../hdl/nvm_synapse_matrix.v#L142) ensures ACK is always suppressed via `wbs_we_i_reversed` flip-flop, so master must use timeout loop or wait fixed time.

**READ WRITE (stimulus injection)**: No ACK on the WRITE (it's a command enqueue). Master must wait 44 cycles before issuing next WRITE (see [`Neuromorphic_X1_Beh.v:244-248`](hdl/Neuromorphic_X1_Beh.v#L244)). If master issues second WRITE before op_fifo has the first result, the second enqueue succeeds (ip_fifo is 32 deep at [`Neuromorphic_X1_Beh.v:206-208`](hdl/Neuromorphic_X1_Beh.v#L206)), but the next neuron integration will block if op_fifo is empty.

**READ READ (pop result)**: [`Neuromorphic_X1_Beh.v:256-259`](hdl/Neuromorphic_X1_Beh.v#L256) shows `core_ack` fires only when `op_fifo_size > 0`. If op_fifo is empty (master read too early), master stalls forever.

---

### FIFO and Pipeline Behavior

#### Input FIFO (`ip_fifo`)

- **Depth**: 32 entries ([`Neuromorphic_X1_Beh.v:206-208`](hdl/Neuromorphic_X1_Beh.v#L206))
- **Enqueue trigger**: Wishbone WRITE (when `EN && W_RB` at [`Neuromorphic_X1_Beh.v:244-248`](hdl/Neuromorphic_X1_Beh.v#L244))
- **Dequeue trigger**: Background engine (when `DI_local[31:30]` matches MODE at [`Neuromorphic_X1_Beh.v:271-299`](hdl/Neuromorphic_X1_Beh.v#L271))
- **Behavior**: 
  - On enqueue: `core_ack` fires immediately (command is accepted)
  - If full: subsequent writes stall (Wishbone waits for ACK=1)
  - Commands are **not** executed in order if different modes mix (not recommended)

#### Output FIFO (`op_fifo`)

- **Depth**: 32 entries ([`Neuromorphic_X1_Beh.v:207-208`](hdl/Neuromorphic_X1_Beh.v#L207))
- **Dequeue trigger**: Wishbone READ (when `EN && !W_RB` and `op_fifo_size > 0` at [`Neuromorphic_X1_Beh.v:251-255`](hdl/Neuromorphic_X1_Beh.v#L251))
- **Result format**: `{31'b0, 1-bit synapse result}` (one bit from one macro at [`Neuromorphic_X1_Beh.v:293`](hdl/Neuromorphic_X1_Beh.v#L293))
- **On empty**: Returns `0xDEAD_C0DE` with `core_ack=0` (master stalls indefinitely at [`Neuromorphic_X1_Beh.v:256-259`](hdl/Neuromorphic_X1_Beh.v#L256))
- **Behavior**: 
  - Background engine pushes (1 result per READ command after 44-cycle delay at [`Neuromorphic_X1_Beh.v:287-299`](hdl/Neuromorphic_X1_Beh.v#L287))
  - Master pops (1 per Wishbone READ transaction)
  - If master reads faster than engine produces: op_fifo empties → stall

**Key design**: The 44-cycle READ delay is enforced entirely in the background engine (lines 289–291 at [`Neuromorphic_X1_Beh.v:289-291`](hdl/Neuromorphic_X1_Beh.v#L289)); Wishbone READ transactions simply pop op_fifo. This decouples the command latency from the response latency.

---

### Simulation-Only Behavioral Constraints

The `Neuromorphic_X1_beh` module is **not synthesizable** due to nested `@(posedge)` waits (lines 278–280, 289–291 at [`Neuromorphic_X1_Beh.v:278-280`](hdl/Neuromorphic_X1_Beh.v#L278) and [`Neuromorphic_X1_Beh.v:289-291`](hdl/Neuromorphic_X1_Beh.v#L289)):

```verilog
for (i = 0; i < WR_Dly; i = i + 1) begin
  @(posedge CLKin);  // Non-synthesizable loop delay
end
```

This simulates delay asynchronously. In the **real hardened X1 macro**, timing constraints from the analog design enforce delays via:
- Analog supply settling time
- Wordline driver propagation delay
- Sense amplifier response time
- A/D converter (if used for analog readout)
- Output buffer setup/hold

The behavioral model's `WR_Dly=200` and `RD_Dly=44` (at [`Neuromorphic_X1_Beh.v:197-198`](hdl/Neuromorphic_X1_Beh.v#L197)) are **approximations** chosen for simulation speed (1000+ real cycles would slow verification). Firmware must use **fixed wait times** that work with both the behavioral model and real silicon.

---

### Common Pitfalls

| Pitfall | Why It Breaks | Fix | Source |
|---------|---------------|-----|--------|
| Wait < 44 cycles after READ WRITE | op_fifo not ready; next WRITE stalls indefinitely | Use exactly 44 or more cycles | [`Neuromorphic_X1_Beh.v:197`](hdl/Neuromorphic_X1_Beh.v#L197) (`RD_Dly=44` hardcoded) |
| Wait < 401 cycles after PROGRAM WRITE | Previous write still in flight; new command corrupts pending write | Use fixed 401 or measure with timeout | [`Neuromorphic_X1_Beh.v:198`](hdl/Neuromorphic_X1_Beh.v#L198) (`WR_Dly=200` + margin) |
| Issue READ WRITE without waiting | ip_fifo fills; Wishbone bus hangs | Enforce 44-cycle wait discipline | [`Neuromorphic_X1_Beh.v:206-208`](hdl/Neuromorphic_X1_Beh.v#L206) (ip_fifo depth=32) |
| Interleave PROGRAM and READ without draining | Commands mix in ip_fifo; mode ambiguity causes stale reads | Always fully drain ip_fifo/op_fifo before switching modes | [`Neuromorphic_X1_Beh.v:271-299`](hdl/Neuromorphic_X1_Beh.v#L271) (mode-specific handlers) |
| Read spike result with `0x3000_1006` (F-10) | Out-of-bounds address returns garbage or causes MCU fault | Only use `0x3000_1000` (neurons 0–31) and `0x3000_1004` (neurons 32–63) | [`nvm_core_decoder.v:26-29`](../hdl/nvm_core_decoder.v#L26) (address routing) |

---

### Reference Implementation (Firmware Loop)

```c
// Stage 1: PROGRAM weights (fire-and-forget, no ACK)
for (int w = 0; w < NUM_WEIGHTS; w++) {
  uint32_t packet = (MODE_PROGRAM << 30) | (row << 25) | (col << 20) | weight_byte;
  wishbone_write(0x3000_0000, packet);
  wait_cycles(401);  // Enforce fixed delay
}

// Stage 2: INJECT stimuli (44-cycle pipeline)
for (int i = 0; i < 256; i++) {
  int16_t stimulus = get_axon_input(i);
  uint32_t packet = (MODE_READ << 30) | (row << 25) | (col << 20) | stimulus;
  wishbone_write(0x3000_0000, packet);
  wait_cycles(44);  // EXACTLY 44: allows op_fifo to accumulate 1 result per iteration
}

// Stage 3: Latch spikes and reset
wishbone_write(0x3000_2000, 0xDEADBEEF);  // Full 32-bit write
wait_cycles(10);

// Stage 4: Read spikes
uint32_t spikes_0_31  = wishbone_read(0x3000_1000);
uint32_t spikes_32_63 = wishbone_read(0x3000_1004);
```

---

## Data Flow & Inference Pipeline

### Overview: Single Gesture Inference (One Forward Pass)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     FIRMWARE (Management Core)                       │
│                                                                       │
│  Step 1: PROGRAM        Step 2: INJECT (×256)      Step 3: PICTURE_ │
│  weights via WB         axon stimuli via WB        DONE + READBACK   │
└──────────┬──────────────────────┬──────────────────────┬────────────┘
           │                      │                      │
           ▼                      ▼                      ▼
     [Wishbone Bus] ────────────────────────────────────────────────
           │
           ▼
    ┌──────────────────────────────────────────────────────────┐
    │        nvm_neuron_core_256x64 (Top-level)               │
    │                                                           │
    │  ┌─────────────────────────────────────────────────────┐ │
    │  │ nvm_core_decoder                                    │ │
    │  │ • Decodes address & MODE                           │ │
    │  │ • Routes to PROGRAM / INJECT / picture_done        │ │
    │  └──┬───────────────────┬──────────────────┬──────────┘ │
    │     │                   │                  │            │
    │     ▼                   ▼                  ▼            │
    │  [PROGRAM]      [INJECT: Stimuli]   [picture_done]      │
    │     │                   │                  │            │
    │     │                   ▼                  │            │
    │     │            MODE=0b01 READ           │            │
    │     ▼                   │                  ▼            │
    │  ┌─────────────────────┼──────────────────────────────┐ │
    │  │ nvm_synapse_matrix  │                              │ │
    │  │                     │                              │ │
    │  │ ┌──────────────────┼──────────────────┐           │ │
    │  │ │ Neuromorphic_X1  │                  │           │ │
    │  │ │ ×16 macros       │ (ReRAM IP)       │ (16 bits) │ │
    │  │ │ (32×32 each)     │                  │           │ │
    │  │ └──────────────────┼──────────────────┘           │ │
    │  │                    ▼                              │ │
    │  │        connection[15:0] (binary synapse)          │ │
    │  └────────────────────┬───────────────────────────────┘ │
    │                       │                                 │
    │                       ▼                                 │
    │  ┌────────────────────────────────────────────────────┐ │
    │  │ nvm_neuron_block                                   │ │
    │  │ • 64 LIF neurons (×4 groups of 16)                │ │
    │  │ • Accumulate: if(synapse==1) potential += stimulus│ │
    │  │ • At picture_done:                                 │ │
    │  │   - Apply leak: potential >>>= LEAK_SHIFT         │ │
    │  │   - Compare: spike = (potential >= THRESHOLD)     │ │
    │  │   - Reset: potential = 0                           │ │
    │  └─────────────┬──────────────────────────────────────┘ │
    │               │                                         │
    │               │ 64-bit spike vector                     │
    │               ▼                                         │
    │  ┌────────────────────────────────────────────────────┐ │
    │  │ nvm_neuron_spike_out                               │ │
    │  │ • 4×16-bit SRAM registers                          │ │
    │  │ • Latches on picture_done pulse                    │ │
    │  │ • Readable via Wishbone @ 0x3000_1000/1004        │ │
    │  └────────────────────────────────────────────────────┘ │
    │                                                          │
    └──────────────────────────────────────────────────────────┘
           │
           ▼
     [Wishbone Bus] ← 64 spike bits read back to firmware
```

---

## Stage 1: Load Weights

**What happens**: Firmware sends all network weights to the ReRAM.

**How firmware does it**:
```c
for each weight {
  packet = encode(MODE_PROGRAM, row, col, weight_bits);
  write_to_hardware(0x3000_0000, packet);
  wait(401 cycles);  // IMPORTANT: no acknowledgment, must wait fixed time
}
```

**What hardware does**:
1. Decoder reads the MODE and address
2. All 16 ReRAM macros store the bits at the given location
3. Returns to waiting for next command

**Key constraint**: Hardware does NOT send an acknowledgment signal. Firmware must use a fixed wait time.

---

## Stage 2: Inject 256 Input Signals (The Main Loop)

**What happens**: For each of 256 input features, firmware sends a stimulus value. Hardware reads the stored weights at that address, multiplies (weight × stimulus), and accumulates the result in each neuron.

**How firmware does it**:
```c
for (i = 0; i < 256; i++) {
  stimulus = get_input_signal(i);
  
  // Convert axon index to address
  row = (i >> 5) & 0x07;    // which row?
  col = i & 0x1F;           // which column?
  
  // Send it
  packet = encode(MODE_READ, row, col, stimulus);
  write_to_hardware(0x3000_0000, packet);
  
  wait(44 cycles);  // IMPORTANT: exactly 44 cycles, nothing else in between!
}
```

**What hardware does** (each iteration):
1. Decoder sends READ command to ReRAM
2. ReRAM engines read 16 bits (one per neuron) at that address
3. Each neuron that has a "1" bit adds the stimulus to its accumulator:
   ```
   if (synapse_bit[neuron] == 1)
     potential[neuron] += stimulus;
   ```
4. Returns acknowledgment; firmware continues

**Key constraint**: Hardware locks the Wishbone bus for exactly 44 cycles. Firmware cannot issue any other command during this time, or data gets corrupted.

**Sign encoding**: 
- If column is even → stimulus is positive (excitatory)
- If column is odd → stimulus is negative (inhibitory)

This lets binary weights (0/1) represent both +1 and -1 connections.

---

## Stage 3: Finalize and Generate Spikes

**What happens**: After all 256 inputs are injected, firmware tells hardware to "finish up." Hardware applies leak (reduces the accumulated values), compares each to a threshold, and produces 64 spike bits.

**How firmware does it**:
```c
// Trigger finalization
write_to_hardware(0x3000_2000, 0xDEADBEEF);  // value doesn't matter
wait(10 cycles);
```

**What hardware does**:
1. Applies leak: `potential[i] = potential[i] >> 16` (right-shift)
2. Compares to threshold: `spike[i] = (potential[i] >= 4)`
3. Stores 64 spike bits in output SRAM
4. Resets all potentials to 0 (ready for next gesture)

**Key constraint**: Write must be full 32-bit (all 4 bytes). Narrow writes (8-bit or 16-bit) are silently ignored.

**Why leak only happens once**: Applying leak inside the 256-input loop would cause early inputs to decay 256× more than late inputs. By leaking once after all inputs are collected, we treat it as a single biological "time step."

---

## Stage 4: Read the Results

**What happens**: Firmware reads the 64 spike bits from hardware.

**How firmware does it**:
```c
spikes_part1 = read_from_hardware(0x3000_1000);  // neurons 0-31
spikes_part2 = read_from_hardware(0x3000_1004);  // neurons 32-63

for (i = 0; i < 64; i++) {
  spike = extract_bit(spikes_part1 or spikes_part2, i);
  // Use spike for classification (e.g., sum them, take max, etc.)
}
```

**Bit mapping**:
```
Address 0x3000_1000 → 32-bit register
  Bit 0 = neuron 0 spike
  Bit 1 = neuron 1 spike
  ...
  Bit 31 = neuron 31 spike

Address 0x3000_1004 → 32-bit register
  Bit 0 = neuron 32 spike
  ...
  Bit 31 = neuron 63 spike
```

---

## Key Design Decisions

| Decision | Rationale | Implementation | Source |
|----------|-----------|-----------------|--------|
| **Flattened-time SNN** | All 256 axons encode one complete gesture in a single pass (not a time sequence) | Single forward pass per gesture; no spike trains over time | [`nvm_neuron_core_256x64.v:8-9`](hdl/nvm_neuron_core_256x64.v#L8) (docstring) |
| **Leak once at picture_done** | Prevent input-order bias (early axons decay ~256× more if leaked per-axon) | Accumulate all 256 axons first; leak exactly once as one "time step" | [`nvm_neuron_block.v:90-96`](hdl/nvm_neuron_block.v#L90) (symmetric leak implementation) |
| **Full-range 16-bit potential** | Allow negative intermediates to represent inhibitory contributions correctly | No zero-clamping; use 17-bit saturation arithmetic | [`nvm_neuron_block.v:70-78`](hdl/nvm_neuron_block.v#L70) (saturation limits: `NEG_SAT_17`, `POS_SAT_17`) |
| **`wbs_we_i_reversed` flip-flop** | X1 `core_ack` arrives 1 cycle after `wbs_we_i` drops, making ACK ambiguous; capture earlier to distinguish PROGRAM vs. READ | Latch `wbs_we_i` on posedge clock; use for ACK gating | [`nvm_synapse_matrix.v:131-145`](../hdl/nvm_synapse_matrix.v#L131) (flip-flop + ACK masking logic) |
| **`picture_done` priority** | Ensure spike latch fires regardless of address decode | OR spike-latch enable with `picture_done` pulse | [`nvm_neuron_core_256x64.v:170-172`](hdl/nvm_neuron_core_256x64.v#L170) (priority logic for spike output) |

---

## Hardware Invariants & Firmware Constraints

These are non-obvious behaviors discovered during RTL verification. **Firmware must comply or risk silent data corruption.**

| ID | Issue | Constraint | Impact | Workaround | Source |
|-------|--------|-----------|--------|-----------|--------|
| **F-04** | PROGRAM writes never ACK | `wbs_we_i_reversed` flip-flop masks ACK during MODE=0b11 | Ambiguous write completion | Wait 401 cycles before next PROGRAM write (fire-and-forget) | [`nvm_synapse_matrix.v:142-145`](../hdl/nvm_synapse_matrix.v#L142); [`Neuromorphic_X1_Beh.v:271-285`](hdl/Neuromorphic_X1_Beh.v#L271) |
| **F-08** | Interleaved WB ops corrupt stimulus | Stimuli latched combinatorially at READ time (cycle 44), not WRITE time | Silent data corruption if ops overlap | Enforce **no other WB transactions** during 44-cycle wait after READ WRITE | [`nvm_neuron_core_256x64.v:108-109`](hdl/nvm_neuron_core_256x64.v#L108) (stimulus sign decode); [`Neuromorphic_X1_Beh.v:287-299`](hdl/Neuromorphic_X1_Beh.v#L287) (READ latching) |
| **F-10** | Out-of-bounds spike read | `0x3000_1006` returns undefined (F-10 flag) | May read garbage or page fault | Only read `0x3000_1000` (neurons 0–31) and `0x3000_1004` (neurons 32–63) | [`nvm_core_decoder.v:26-29`](../hdl/nvm_core_decoder.v#L26) (address routing: only 0x1xxx decoded) |
| **F-14** | Bit-order mismatch in connection files | File format: MSB-first (char 0 = bit 15), RTL expects LSB-first (bit 0 = bit 0) | Weights loaded in reverse bit order → ~50% accuracy drop | Bit-reverse each 16-bit word before PROGRAM write to `0x3000_0000` | [`nvm_synapse_matrix.v:124-129`](../hdl/nvm_synapse_matrix.v#L124) (output packing: LSB-first) |
| **F-15** | Narrow `picture_done` writes fail | Spike SRAM latch requires `wbs_sel_i=4'hF` (all 4 bytes) | Narrow writes (8-bit `sb`, 16-bit `sh`) silently skip latch → spike loss | Use full 32-bit store (`sw`) instruction only; never `sb` or `sh` | [`nvm_neuron_spike_out.v`](hdl/nvm_neuron_spike_out.v) (full-width write gating) |
| **F-17** | Unused axons inject garbage | Layer 0: 256 physical axons, 238 logical (18 unused); Layer 1: 256 physical, 208 logical (48 unused) | Undefined stimulus accumulates → inference error | Inject `0x0000` stimulus for all unused axons | [`nvm_parameter.vh`](hdl/nvm_parameter.vh) (NUM_AXON_LAYER_* parameters) |
| **Leak** | Applied once at `picture_done` | Leak shift `>>>NEURON_LEAK_SHIFT` happens once per gesture, not per axon | If applied in per-axon loop: early axons decay ~256× more than late axons | Accumulate all 256 axons first; apply leak exactly once at picture_done | [`nvm_neuron_block.v:99-115`](hdl/nvm_neuron_block.v#L99) (leak only on picture_done) |
| **Drain** | ReRAM engine has no reset | After PROGRAM or READ, in-flight operations must clear | Stale operations corrupt next transaction | Wait `WR_Dly + RD_Dly + 10 = 254` cycles after each operation | [`Neuromorphic_X1_Beh.v:197-198`](hdl/Neuromorphic_X1_Beh.v#L197) (WR_Dly + RD_Dly hardcoded) |

---

## Settings (nvm_parameter.vh)

These must match `verilog/tb/snn_gesture/nvm_parameter.py`:

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `NEURON_THRESHOLD` | 4 | Spike fires if potential ≥ 4 |
| `NEURON_LEAK_SHIFT` | 16 | Divide potential by 2^16 (almost no leak for typical 16-bit values) |
| `NUM_NEURON` | 64 | Total neurons |
| `NUM_AXON` | 256 | Total inputs |
| `NUM_OF_MACRO` | 16 | ReRAM macros (each 32×32) |

---

## Verification & Testing

- **Simulation tests**: See `verilog/tb/snn_gesture/README.md`
- **System overview**: See `snn_gesture_working.md`
- **Training info**: See `training/README.md`
