TOPLEVEL_LANG ?= verilog
SIM ?= icarus
TOPLEVEL ?= reram_1t1r_snn_array_32x32
MODULE ?= test_reram_1t1r

PWD := $(shell pwd)
VERILOG_SOURCES := \
	$(PWD)/../../../rtl/neuron_core/hdl/reram_1t1r_snn_neuron.v \
	$(PWD)/../../../rtl/neuron_core/hdl/reram_1t1r_snn_array_32x32.v

include $(shell cocotb-config --makefiles)/Makefile.sim
