// -----------------------------------------------------------------------------
// nvm_parameter.vh — Hardware LIF Neuron Parameters
//
// [IMPORTANT] These parameters MUST be synchronized with the training-side
// constants in verilog/tb/snn_gesture/nvm_parameter.py to ensure 
// inference accuracy matches software simulation.
// -----------------------------------------------------------------------------
`ifndef NVM_PARAMETER_VH
`define NVM_PARAMETER_VH

// Number of Neuromorphic_X1 ReRAM macros per neuron core (32×32 each).
// HARDWARE LIMITATION (OpenLane/Caravel): reduced from 16 to 8 due to die-area
// constraints of the Caravel 2920×3520 µm wrapper. 8 macros × 4 neuron rows = 32
// physical neurons per tile (vs. 64 with 16 macros). NUM_NEURON in
// nvm_parameter.py must be kept at 32 to match.
// Changing this value here propagates to nvm_synapse_matrix and nvm_neuron_block
// via parameter override from nvm_neuron_core_256x64.

`ifndef NUM_OF_MACRO
`define NUM_OF_MACRO 16
`endif

// Neuron block LIF parameters — must match verilog/tb/snn_gesture/nvm_parameter.py
// Signed 16-bit threshold; spike fires when potential >= THRESHOLD
`ifndef NEURON_THRESHOLD
`define NEURON_THRESHOLD  16'd4   
`endif

// Arithmetic right-shift: leak = potential >>> NEURON_LEAK_SHIFT
`ifndef NEURON_LEAK_SHIFT
`define NEURON_LEAK_SHIFT 16'd16    
`endif

`endif
