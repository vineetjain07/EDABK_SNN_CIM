# SNN Gesture — cocotb Verification Makefile
#
# This Makefile manages the multi-phase bottom-up test suite for the 
# 256×64 LIF neuron core. Each phase targets a specific subsystem or 
# integration level.
#
# Run a specific phase by overriding MODULE on the command line:
#
#   make MODULE=test_wb_interface      # Phase 1: Wishbone protocol compliance
#   make MODULE=test_synapse_matrix    # Phase 2: ReRAM synapse programming and readback
#   make MODULE=test_neuron_block      # Phase 3: LIF accumulation, leak, and threshold logic
#   make MODULE=test_spike_out         # Phase 4: Spike storage SRAM and packing logic
#   make MODULE=test_single_core       # Phase 5: End-to-end single core inference
#   make MODULE=test_layer_inference   # Phase 6: Multi-core layer-level routing and voting
#   make MODULE=test_full_network      # Phase 7: Full 3-layer network accuracy validation
#
# Default MODULE below is a placeholder; always supply MODULE= explicitly.

TOPLEVEL_LANG ?= verilog
SIM ?= icarus
TOPLEVEL := nvm_neuron_core_256x64

PWD=$(shell pwd)

COCOTB?=$(PWD)

MODULE = neuron_network_test

HDL_DIR = $(PWD)/../../../rtl/SNN_gesture/hdl

ifeq ($(TOPLEVEL_LANG),verilog)
    VERILOG_SOURCES = $(HDL_DIR)/nvm_neuron_core_256x64.v \
    				  $(HDL_DIR)/nvm_core_decoder.v \
    				  $(HDL_DIR)/nvm_neuron_block.v \
    				  $(HDL_DIR)/nvm_synapse_matrix.v \
    				  $(HDL_DIR)/nvm_neuron_spike_out.v \
    				  $(HDL_DIR)/Neuromorphic_X1_Beh.v

    COMPILE_ARGS += -DGENERATE_VCD -I$(HDL_DIR)
    ifneq ($(filter $(SIM),riviera activehdl),)
        COMPILE_ARGS += -sv2k12
    endif

else ifeq ($(TOPLEVEL_LANG),vhdl)
    VHDL_SOURCES =  $(COCOTB)/wrapper_neuron_core.vhd

    ifneq ($(filter $(SIM),ius xcelium),)
        COMPILE_ARGS += -v93
    endif
else
    $(error A valid value (verilog or vhdl) was not provided for TOPLEVEL_LANG=$(TOPLEVEL_LANG))
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
