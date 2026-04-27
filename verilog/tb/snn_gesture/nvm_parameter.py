# All parameters used in TOP MODULE
PERIOD                  = 20
# 20ns - 50 MHz

### 1. Fixed hardware Neuron Core parameter
# Number of Neuromorphic_X1 ReRAM macros per core (32×32 each).
# HARDWARE LIMITATION (OpenLane/Caravel): reduced from 16 to 8 due to die-area
# constraints of the Caravel 2920×3520 µm wrapper. 8 macros × 4 neuron rows = 32
# neurons per crossbar tile. NUM_NEURON below is derived as NUM_OF_MACRO × 4.

# Uncomment below if doing simulation, generating weights for 8 macros
# NUM_OF_MACRO    = 8 
NUM_OF_MACRO    = 16

MODE_PROGRAM= 0b11
MODE_READ   = 0b01
MEM_HIGH    = 0b11111111
MEM_LOW     = 0b00000000
WR_Dly      = 200
RD_Dly      = 44
NUM_AXON    = 256
NUM_NEURON  = NUM_OF_MACRO * 4   # 32 — physical columns per crossbar tile (8 macros × 4 neuron rows)

### 3. Testbench parameters
WB_DATAWIDTH            = 32
NUM_CLASS               = 12    
NUM_VOTES               = 240   
SUM_OF_PICS             = 5
#1123

### 4. NoC Parameters

# ── Primary inputs ────────────────────────────────────────────────────────────
NUM_AXON_LAYER_0    = 256   # input feature width (DVS128 spatial_focus: 2×11×11 = 242, padded)

# Total neurons per layer — must be multiples of NUM_NEURON (hardware tile width = 32 for 8 macros)
NUM_NEURONS_LAYER_0 = 832   # L0: 26 cores × 16
NUM_NEURONS_LAYER_1 = 256   # L1:  8 cores × 16
NUM_NEURONS_LAYER_2 = 256   # L2:  8 cores × 16

# ── Derived: cores per layer ──────────────────────────────────────────────────
NUM_CORES_LAYER_0   = NUM_NEURONS_LAYER_0 // NUM_NEURON   # 13
NUM_CORES_LAYER_1   = NUM_NEURONS_LAYER_1 // NUM_NEURON   #  4
NUM_CORES_LAYER_2   = NUM_NEURONS_LAYER_2 // NUM_NEURON   #  4

# ── Derived: axon widths for downstream layers ────────────────────────────────
# L1 uses partitioned routing: each core sees L0_total / L1_cores inputs
NUM_AXON_LAYER_1    = NUM_NEURONS_LAYER_0 // NUM_CORES_LAYER_1   
# L2 uses broadcast routing: each core sees all L1 outputs
NUM_AXON_LAYER_2    = NUM_NEURONS_LAYER_1                        

NUM_SLICE            = 8
NUM_INST_WORD        = 16
NUM_NEURON_PER_SLICE = 32

NUM_STIMULI_WORD    = NUM_AXON_LAYER_0 // 2

### 5. Neuron block LIF parameters — must match verilog/tb/hdl/nvm_neuron_block.v
NEURON_THRESHOLD  = 4    # signed 16-bit; spike fires when potential >= NEURON_THRESHOLD
NEURON_LEAK_SHIFT = 16    # arithmetic right-shift: leak = potential >>> NEURON_LEAK_SHIFT

from pathlib import Path
PWD = Path(__file__).resolve().parent
MEM_BASE_DIR = PWD / "../../rtl/SNN_gesture/mem"

### 6. Wishbone Address Map
SYNAPSE_ADDR = 0x30000000          # synapse_matrix_select (decoder: addr[15:12]==0)
SPIKE_LO     = 0x30001000          # {sram[1], sram[0]} — neurons 0-31
SPIKE_HI     = 0x30001004          # {sram[3], sram[2]} — neurons 32-63
PD           = [0x30002000, 0x30002002, 0x30002004, 0x30002006]  # picture_done → sram[0..3]