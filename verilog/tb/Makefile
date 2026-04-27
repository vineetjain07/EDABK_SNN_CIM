TOPLEVEL_LANG ?= verilog
SIM ?= icarus
TOPLEVEL := nvm_neuron_core_256x64

PWD=$(shell pwd)

COCOTB?=$(PWD)

MODULE = neuron_network_test

ifeq ($(TOPLEVEL_LANG),verilog)
    VERILOG_SOURCES = $(COCOTB)/hdl/nvm_neuron_core_256x64.v \
    				  $(COCOTB)/hdl/nvm_core_decoder.v \
    				  $(COCOTB)/hdl/nvm_neuron_block.v \
    				  $(COCOTB)/hdl/nvm_synapse_matrix.v \
    				  $(COCOTB)/hdl/nvm_neuron_spike_out.v \
    				  $(COCOTB)/hdl/Neuromorphic_X1_Beh.v

    COMPILE_ARGS += -DGENERATE_VCD -I$(PWD)/hdl
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

