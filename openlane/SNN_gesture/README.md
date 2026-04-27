# OpenLane Hardening — SNN Gesture Recognition

This directory contains the OpenLane configuration and auxiliary files for hardening the
**SNN Gesture Recognition** user-project wrapper to GDS, targeting the
[ChipFoundry Caravel](https://github.com/efabless/caravel) open-source shuttle.

---

## Directory Contents

| File / Directory | Purpose |
|---|---|
| `config.json` | Main OpenLane 2 configuration — design files, macro hooks, PDN, timing |
| `manual_macro_placement.cfg` | Fixed (x, y, orientation) for all 8 Neuromorphic_X1 macros |
| `signoff.sdc` | Timing constraints used during signoff (CTS + STA) |
| `pdn_override.tcl` | Power-delivery network overrides for macro power strapping |
| `fixed_dont_change/` | Caravel-provided DEF template; **do not edit** |
| `vsrc/` | Voltage-source files for IR-drop analysis |
| `runs/` | OpenLane run artifacts (generated; not committed) |

---

## Hardware Limitation — 8 Macros Instead of 16

**Original design intent:** 16 × Neuromorphic_X1 ReRAM macros per neuron core
(16 × 32×32 = 16 384 bits → 256 axons × 64 neurons per tile).

**Tapeout reality:** After floor-planning inside the Caravel user-project wrapper
(die area 2920 × 3520 µm), only **8 macros** can be placed without violating:
- Metal-4 routing DRC near the Caravel ring
- PDN stripe pitch constraints (`FP_PDN_VPITCH = 180 µm`, `FP_PDN_HPITCH = 180 µm`)
- Required macro horizontal/vertical halos (`FP_MACRO_HORIZONTAL_HALO = 50`,
  `FP_MACRO_VERTICAL_HALO = 20`)

**Consequence:** `NUM_OF_MACRO = 8` → 8 × 4 neuron rows = **32 neurons per tile**.

| Parameter | 16-macro (original) | 8-macro (tapeout) |
|---|---|---|
| `NUM_OF_MACRO` | 16 | **8** |
| Neurons per tile | 64 | **32** |
| Cores L0 (832 neurons) | 13 | **26** |
| Cores L1 (256 neurons) | 4 | **8** |
| Cores L2 (256 neurons) | 4 | **8** |
| `NUM_AXON_LAYER_1` | 208 | **104** |

Training and weight export adapt automatically once `nvm_parameter.py` is updated
(already done). See [Training README](../../training/README.md).

---

## Macro Placement

8 macros are arranged in a **2-column × 4-row** grid, rotated 90° (`R270`) to
align macro long axes with the Caravel horizontal PDN stripes:

```
Column 1 (x = 750 µm)         Column 2 (x = 1850 µm)
  macro[0]  y =   96 µm          macro[4]  y =   96 µm
  macro[1]  y =  952 µm          macro[5]  y =  952 µm
  macro[2]  y = 1808 µm          macro[6]  y = 1808 µm
  macro[3]  y = 2664 µm          macro[7]  y = 2664 µm
```

The placement is specified in [`manual_macro_placement.cfg`](manual_macro_placement.cfg).
Instance names follow the generate-loop pattern:
`neuron_core_inst.synapse_matrix_inst.genblk1[N].X1_inst` for N = 0..7.

---

## PDN Power Hooks

Each Neuromorphic_X1 macro has two power domains connected via `FP_PDN_MACRO_HOOKS`:

| Net (Caravel) | Macro pin | Domain |
|---|---|---|
| `vccd1` / `vssd1` | `VDDC` / `VSS` | Digital core (1.8 V) |
| `vdda1` / `vssd1` | `VDDA` / `VSS` | Analog / ReRAM array |

---

## Running the Hardening Flow

From the project root:

```bash
# Harden just the neuron core macro first (optional step)
cd openlane && make neuron_core

# Harden the full user_project_wrapper (includes 8 Neuromorphic_X1 macros)
cd openlane && make SNN_gesture
```

OpenLane 2 must be installed and on `$PATH`. The Caravel PDK (`SKY130A`) must be
set via `$PDK_ROOT`. Refer to the
[Caravel user-project template](https://github.com/efabless/caravel_user_project)
for environment setup.

---

## Key OpenLane Configuration Choices

| Variable | Value | Rationale |
|---|---|---|
| `PL_TARGET_DENSITY` | 0.1 | Low density needed: macros occupy most of the floor plan |
| `DPL_CELL_PADDING` | 15 | Extra spacing to ease routing around macro keepout zones |
| `MACRO_PLACEMENT_CFG` | `manual_macro_placement.cfg` | Automatic placement fails due to tight PDN constraints |
| `SYNTH_ELABORATE_ONLY` | false | Full synthesis required (not a pre-hardened macro) |
| `ERROR_ON_PDN_VIOLATIONS` | true | Any PDN shorts are fatal — tapeout critical |
| `CLOCK_PERIOD` | 25 ns | 40 MHz target; Caravel RISC-V core runs at 10 MHz by default |
| `FP_DEF_TEMPLATE` | Caravel fixed DEF | Pin locations are fixed by Caravel harness — do not change |

---

## References

- [Caravel User Project Template](https://github.com/efabless/caravel_user_project)
- [OpenLane 2 Documentation](https://openlane2.readthedocs.io/)
- [BM Labs Neuromorphic X1 IP](https://bm-labs.com) — ReRAM crossbar macro used for in-memory VMM
- [SKY130 PDK](https://github.com/google/skywater-pdk) — 130 nm process node
- [System overview and data flow](../../snn_gesture_working.md)
- [RTL module hierarchy and design decisions](../../verilog/rtl/SNN_gesture/README.md)
