# All parameters used in TOP MODULE
PERIOD                  = 20
# 20ns - 50 MHz

### 1. Fixed hardware Neuron Core parameter
MODE_PROGRAM= 0b11
MODE_READ   = 0b01
MEM_HIGH    = 0b11111111
MEM_LOW     = 0b00000000
WR_Dly      = 200
RD_Dly      = 44
NUM_AXON    = 256
NUM_NEURON  = 64

### 3. Testbench parameters
WB_DATAWIDTH            = 32
NUM_CLASS               = 20
NUM_VOTES               = 240
SUM_OF_PICS             = 1
#1123

### 4. NoC Parameters
NUM_NEURON_LAYER_0  = 64
NUM_NEURON_LAYER_1  = 64
NUM_NEURON_LAYER_2  = 64 # 240
NUM_AXON_LAYER_0    = 238
NUM_AXON_LAYER_1    = 208
NUM_AXON_LAYER_2    = 256

NUM_SLICE           = 8
NUM_INST_WORD       = 16
NUM_NEURON_PER_SLICE = 32

NUM_CORES_LAYER_0   = 13
NUM_CORES_LAYER_1   = 4
NUM_CORES_LAYER_2   = 4

NUM_STIMULI_WORD    = NUM_AXON_LAYER_0 // 2