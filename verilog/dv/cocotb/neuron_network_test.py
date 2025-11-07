import os
import sys
from pathlib import Path

import cocotb
from cocotb.binary import BinaryRepresentation, BinaryValue
from cocotb.triggers import Timer
from cocotb.clock import Clock
from cocotb.handle import SimHandleBase
from cocotb.queue import Queue
from cocotb.runner import get_runner
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, Join
from nvm_parameter import *
from read_file import *

##################################################################
# Wishbone Read : Used for reading spikes out or output packets from the last core
async def wishbone_write(dut, address, data):
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value = 1
    dut.wbs_sel_i.value = 0b1111
    dut.wbs_adr_i.value = address
    dut.wbs_dat_i.value = data

    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_we_i.value = 0
    dut.wbs_sel_i.value = 0b0000

    await FallingEdge(dut.wb_clk_i)

# Wishbone Read : Used for reading spikes out or output packets from the last core
async def wishbone_read(dut, address, spike_o_matrix=None, pic=0, slice=0, layer=0, core=0):
    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 1
    dut.wbs_stb_i.value = 1
    dut.wbs_we_i.value = 0
    dut.wbs_sel_i.value = 0b1111
    dut.wbs_adr_i.value = address
    dut.wbs_dat_i.value = 0

    await RisingEdge(dut.wb_clk_i)
    dut.wbs_cyc_i.value = 0
    dut.wbs_stb_i.value = 0
    dut.wbs_sel_i.value = 0
        
    await FallingEdge(dut.wb_clk_i)
    # output_spike = str(dut.wbs_dat_o.value)
    output_spike = dut.wbs_dat_o.value.binstr[::-1]
    if spike_o_matrix is not None:
        for i in range(NUM_NEURON_PER_SLICE):
            spike_o_matrix[pic][core*NUM_NEURON+slice*NUM_NEURON_PER_SLICE+ i] = int(output_spike[i])

    # if (dut.wbs_ack_o.value == 0):
    #     if (address != DONE_PIC_ADDR): 
    #         print("Not receive reading ack! \n")       
    #     else:
    #         print(" ")
    #         # print("Sending pic_done signal")
    # else:
    #     if (address <= PARAM_BASE0 and address >= CORE_BASE) == 0 :
    #         output_spike = str(dut.wbs_dat_o.value)
    #         # print(f"\t\t\tRead at addr {hex(address)}: value {output_spike}")
    #         if spike_o_matrix is not None:
    #             for i in range(NUM_NEURON_PER_SLICE):
    #                 if (layer==0):
    #                     if (NUM_NEURON_PER_SLICE*slice + i >= NUM_NEURON_LAYER_0):
    #                         break
    #                     spike_o_matrix[pic][core*NUM_NEURON_LAYER_0+slice*NUM_NEURON_PER_SLICE+ i] = int(output_spike[i])
    #                 elif (layer==1):
    #                     if (NUM_NEURON_PER_SLICE*slice + i >= NUM_NEURON_LAYER_1):
    #                         break
    #                     spike_o_matrix[pic][core*NUM_NEURON_LAYER_1+slice*NUM_NEURON_PER_SLICE+ i] = int(output_spike[i])
    #                 elif (layer==2):
    #                     if (NUM_NEURON_PER_SLICE*slice + i >= NUM_NEURON_LAYER_2):
    #                         break
    #                     spike_o_matrix[pic][core*NUM_NEURON_LAYER_2+slice*NUM_NEURON_PER_SLICE+ i] = int(output_spike[i])

async def nvm_write(dut, address, data):
    async def drive_wishbone():
        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 1
        dut.wbs_stb_i.value = 1
        dut.wbs_we_i.value = 1
        dut.wbs_sel_i.value = 0b1111
        dut.wbs_adr_i.value = address
        dut.wbs_dat_i.value = data

        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 0
        dut.wbs_stb_i.value = 0
        dut.wbs_we_i.value = 0
        dut.wbs_sel_i.value = 0

    async def wait_for_delay():
        await ClockCycles(dut.wb_clk_i, (2 * WR_Dly + 1))

    drive_task = cocotb.start_soon(drive_wishbone())
    delay_task = cocotb.start_soon(wait_for_delay())

    # await Join(drive_task, delay_task)
    await drive_task
    await delay_task

async def nvm_read(dut, addr, data):
    async def operation_1_write():
        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 1
        dut.wbs_stb_i.value = 1
        dut.wbs_we_i.value  = 1
        dut.wbs_sel_i.value = 0xF
        dut.wbs_adr_i.value = addr
        dut.wbs_dat_i.value = data

        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 0
        dut.wbs_stb_i.value = 0
        dut.wbs_we_i.value  = 0
        dut.wbs_sel_i.value = 0

    async def operation_2_read_after_delay():
        await ClockCycles(dut.wb_clk_i, (RD_Dly + 2))

        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 1
        dut.wbs_stb_i.value = 1
        dut.wbs_we_i.value  = 0
        dut.wbs_sel_i.value = 0xF
        dut.wbs_adr_i.value = addr

        await RisingEdge(dut.wb_clk_i)
        dut.wbs_cyc_i.value = 0
        dut.wbs_stb_i.value = 0
        dut.wbs_sel_i.value = 0

    task_1 = cocotb.start_soon(operation_1_write())
    task_2 = cocotb.start_soon(operation_2_read_after_delay())

    # await Join(task_1, task_2)
    await task_1
    await task_2

##################################################################
@cocotb.test()
async def neuron_network_test(dut): 
    print("Loading file")
    connection_0 = read_matrix_from_file("mem/connection/connection_000.txt")
    connection_1 = read_matrix_from_file("mem/connection/connection_001.txt")
    connection_2 = read_matrix_from_file("mem/connection/connection_002.txt")
    connection_3 = read_matrix_from_file("mem/connection/connection_003.txt")
    connection_4 = read_matrix_from_file("mem/connection/connection_004.txt")
    connection_5 = read_matrix_from_file("mem/connection/connection_005.txt")
    connection_6 = read_matrix_from_file("mem/connection/connection_006.txt")
    connection_7 = read_matrix_from_file("mem/connection/connection_007.txt")
    connection_8 = read_matrix_from_file("mem/connection/connection_008.txt")
    connection_9 = read_matrix_from_file("mem/connection/connection_009.txt")
    connection_10 = read_matrix_from_file("mem/connection/connection_010.txt")
    connection_11 = read_matrix_from_file("mem/connection/connection_011.txt")
    connection_12 = read_matrix_from_file("mem/connection/connection_012.txt")
    connection_13 = read_matrix_from_file("mem/connection/connection_013.txt")
    connection_14 = read_matrix_from_file("mem/connection/connection_014.txt")
    connection_15 = read_matrix_from_file("mem/connection/connection_015.txt")
    connection_16 = read_matrix_from_file("mem/connection/connection_016.txt")
    connection_26_part1 = read_matrix_from_file("mem/connection/connection_026_part1.txt")
    connection_26_part2 = read_matrix_from_file("mem/connection/connection_026_part2.txt")
    connection_26_part3 = read_matrix_from_file("mem/connection/connection_026_part3.txt")
    connection_26_part4 = read_matrix_from_file("mem/connection/connection_026_part4.txt")

    stimuli          = read_matrix_from_file("mem/stimuli/stimuli.txt")
    tb_correct       = read_matrix_from_file("mem/testbench/tb_correct.txt")
    
    spike_out_layer_0 = [[0 for _ in range(NUM_CORES_LAYER_0*NUM_NEURON)] for __ in range(SUM_OF_PICS)]
    spike_out_layer_1 = [[0 for _ in range(NUM_CORES_LAYER_1*NUM_NEURON)] for __ in range(SUM_OF_PICS)]
    spike_out_layer_2 = [[0 for _ in range(NUM_CORES_LAYER_2*NUM_NEURON)] for __ in range(SUM_OF_PICS)]
    
    golden_output    = [0 for _ in range(SUM_OF_PICS)]
    for pic in range(SUM_OF_PICS):
        golden_output[pic] = list_to_binary(tb_correct[pic])
    print("\nGolden Output:")
    print(golden_output)
    
    print("\nStarting Clock\n")
    clock = Clock(dut.wb_clk_i, PERIOD, units="ns")
    cocotb.start_soon(clock.start(start_high=True))
    
    dut.wb_rst_i.value      = 0b1
    dut.wbs_cyc_i.value     = 0b0
    dut.wbs_stb_i.value     = 0b0
    dut.wbs_we_i.value      = 0b0
    dut.wbs_sel_i.value     = 0b0000
    dut.wbs_adr_i.value     = 0
    dut.wbs_dat_i.value     = 0
    await RisingEdge(dut.wb_clk_i)
    
    await Timer(PERIOD*1, units="ns")
    dut.wb_rst_i.value      = 0b0
    
    ########################## START LAYER_0 ########################
    layer = 0
    for core_layer_0 in range (NUM_CORES_LAYER_0): #
        if (core_layer_0==0):
            connection_layer_0 = connection_0
        elif (core_layer_0==1):
            connection_layer_0 = connection_1
        elif (core_layer_0==2):
            connection_layer_0 = connection_2
        elif (core_layer_0==3):
            connection_layer_0 = connection_3
        elif (core_layer_0==4):
            connection_layer_0 = connection_4
        elif (core_layer_0==5):
            connection_layer_0 = connection_5
        elif (core_layer_0==6):
            connection_layer_0 = connection_6
        elif (core_layer_0==7):
            connection_layer_0 = connection_7
        elif (core_layer_0==8):
            connection_layer_0 = connection_8
        elif (core_layer_0==9):
            connection_layer_0 = connection_9
        elif (core_layer_0==10):
            connection_layer_0 = connection_10
        elif (core_layer_0==11):
            connection_layer_0 = connection_11
        elif (core_layer_0==12):
            connection_layer_0 = connection_12

        #===ONCE===#
        for row_i in range(32):
            for col_i in range(32):
                row = row_i
                col = col_i
                # (row & 0x07) tương đương với row[2:0]
                axon = (row & 0x07) * 32 + col
                # ((row >> 3) & 0x03) tương đương với row[4:3]
                neuron_index = (row >> 3) & 0x03 
                neuron = neuron_index * 16 # Giá trị sẽ là 0, 16, 32, hoặc 48
                
                # Lấy 16-bit slice từ 'connection'
                # Gọi hàm reverse_bits
                # Verilog: connection[axon][63-neuron-:16]
                # reversed_val = reverse_bits(val_slice, 16)
                val_slice = connection_layer_0[axon][NUM_NEURON_LAYER_0 - (neuron + 16):NUM_NEURON_LAYER_0 - neuron]                
                int_val = list_to_binary(val_slice)
                
                # Xây dựng dữ liệu 32-bit (từ phép nối Verilog)
                # {MODE_PROGRAM, row, col, 4'b0, reversed_val}
                # Giả sử: MODE(2), row(5), col(5), pad(4), val(16)
                data_to_write = (
                    (MODE_PROGRAM << 30) |  # 2 bit trên cùng
                    (row          << 25) |  # 5 bit tiếp theo
                    (col          << 20) |  # 5 bit tiếp theo
                    (0            << 16) |  # 4 bit padding 0
                    (int_val)          # 16 bit dưới cùng
                )

                await nvm_write(dut, 0x30000000, data_to_write)
        #===ONCE===#

        #===EVERY PIC===#
        for pic in range (SUM_OF_PICS):
            print(f"Layer 0 - Core {core_layer_0} - Pic {pic}")
            for row_i in range(32):
                for col_i in range(32):
                    row = row_i
                    col = col_i
                    axon = (row & 0x07) * 32 + col
                    neuron = ((row >> 3) & 0x03) * 16
              
                    stimuli_val = stimuli[axon // 2]  # axon/2
              
                    if (axon % 2) == 0:
                        # axon chẵn: [31:16] (16 bit trên)
                        val_slice = (list_to_binary(stimuli_val) >> 16) & 0xFFFF
                    else:
                        # axon lẻ: [15:0] (16 bit dưới)
                        val_slice = list_to_binary(stimuli_val) & 0xFFFF
                  
                    data_for_read_op = (
                        (MODE_READ << 30) |  # 2 bit trên cùng
                        (row       << 25) |  # 5 bit tiếp theo
                        (col       << 20) |  # 5 bit tiếp theo
                        (0         << 16) |  # 4 bit padding 0
                        (val_slice)          # 16 bit dưới cùng
                    )
              
                    await nvm_read(dut, 0x30000000, data_for_read_op)
      
                    if col == 31:
                        if row == 7:
                            await wishbone_write(dut, 0x30002000, 0)
                        elif row == 15:
                            await wishbone_write(dut, 0x30002002, 0)
                        elif row == 23:
                            await wishbone_write(dut, 0x30002004, 0)
                        elif row == 31:
                            await wishbone_write(dut, 0x30002006, 0)
            
            await wishbone_read(dut, 0x30001000, spike_out_layer_0, pic, 0, layer, core_layer_0)
            await wishbone_read(dut, 0x30001004, spike_out_layer_0, pic, 1, layer, core_layer_0) 
        #===EVERY PIC===#
    ########################## FINISH LAYER_0 ########################
    
    print(f"L0 output: {spike_out_layer_0}")
    await Timer(PERIOD*1, units="ns")
 
    ########################## START LAYER_1 ########################
    layer = 1
    for core_layer_1 in range (NUM_CORES_LAYER_1): #
        if (core_layer_1==0):
            connection_layer_1 = connection_13
        elif (core_layer_1==1):
            connection_layer_1 = connection_14
        elif (core_layer_1==2):
            connection_layer_1 = connection_15
        elif (core_layer_1==3):
            connection_layer_1 = connection_16

        #===ONCE===#
        for row_i in range(32):
            for col_i in range(32):
                row = row_i
                col = col_i
                axon = (row & 0x07) * 32 + col
                neuron_index = (row >> 3) & 0x03 
                neuron = neuron_index * 16
            
                val_slice = connection_layer_1[axon][NUM_NEURON_LAYER_1 - (neuron + 16):NUM_NEURON_LAYER_1 - neuron]                
                int_val = list_to_binary(val_slice)

                data_to_write = (
                    (MODE_PROGRAM << 30) |  # 2 bit trên cùng
                    (row          << 25) |  # 5 bit tiếp theo
                    (col          << 20) |  # 5 bit tiếp theo
                    (0            << 16) |  # 4 bit padding 0
                    (int_val)          # 16 bit dưới cùng
                )

                await nvm_write(dut, 0x30000000, data_to_write)
        #===ONCE===#


        #===EVERY PIC===#
        for pic in range (SUM_OF_PICS):
            print(f"Layer 1 - Core {core_layer_1} - Pic {pic}")
            for row_i in range(32):
                for col_i in range(32):
                    row = row_i
                    col = col_i
                    axon = (row & 0x07) * 32 + col
                    neuron = ((row >> 3) & 0x03) * 16
              
                    if (spike_out_layer_0[pic][core_layer_1*NUM_AXON_LAYER_1+axon]==1):                  
                        data_for_read_op = (
                            (MODE_READ << 30) |  # 2 bit trên cùng
                            (row       << 25) |  # 5 bit tiếp theo
                            (col       << 20) |  # 5 bit tiếp theo
                            (0         << 16) |  # 4 bit padding 0
                            (1)          # 16 bit dưới cùng
                        )
                    
                        await nvm_read(dut, 0x30000000, data_for_read_op)
      
                    if col == 31:
                        if row == 7:
                            await wishbone_write(dut, 0x30002000, 0)
                        elif row == 15:
                            await wishbone_write(dut, 0x30002002, 0)
                        elif row == 23:
                            await wishbone_write(dut, 0x30002004, 0)
                        elif row == 31:
                            await wishbone_write(dut, 0x30002006, 0)
            
            await wishbone_read(dut, 0x30001000, spike_out_layer_1, pic, 0, layer, core_layer_1)
            await wishbone_read(dut, 0x30001004, spike_out_layer_1, pic, 1, layer, core_layer_1) 
        #===EVERY PIC===#
        
    ########################## FINISH LAYER_1  ########################
    
    print(f"L1 output: {spike_out_layer_1}")
    await Timer(PERIOD*1, units="ns")

    ########################## START LAYER_2 ########################
    layer = 2
    for core_layer_2 in range (NUM_CORES_LAYER_2): #
        if (core_layer_2==0):
            connection_layer_2 = connection_26_part1
        elif (core_layer_2==1):
            connection_layer_2 = connection_26_part2
        elif (core_layer_2==2):
            connection_layer_2 = connection_26_part3
        elif (core_layer_2==3):
            connection_layer_2 = connection_26_part4

        #===ONCE===#
        for row_i in range(32):
            for col_i in range(32):
                row = row_i
                col = col_i
                axon = (row & 0x07) * 32 + col
                neuron_index = (row >> 3) & 0x03 
                neuron = neuron_index * 16
            
                val_slice = connection_layer_2[axon][NUM_NEURON_LAYER_2 - (neuron + 16):NUM_NEURON_LAYER_2 - neuron]                
                int_val = list_to_binary(val_slice)

                data_to_write = (
                    (MODE_PROGRAM << 30) |  # 2 bit trên cùng
                    (row          << 25) |  # 5 bit tiếp theo
                    (col          << 20) |  # 5 bit tiếp theo
                    (0            << 16) |  # 4 bit padding 0
                    (int_val)          # 16 bit dưới cùng
                )

                await nvm_write(dut, 0x30000000, data_to_write)
        #===ONCE===#


        #===EVERY PIC===#
        for pic in range (SUM_OF_PICS):
            print(f"Layer 2 - Core layer 2 part {core_layer_2} - Pic {pic}")
            for row_i in range(32):
                for col_i in range(32):
                    row = row_i
                    col = col_i
                    axon = (row & 0x07) * 32 + col
                    neuron = ((row >> 3) & 0x03) * 16
              
                    if (spike_out_layer_1[pic][axon]==1):                  
                        data_for_read_op = (
                            (MODE_READ << 30) |  # 2 bit trên cùng
                            (row       << 25) |  # 5 bit tiếp theo
                            (col       << 20) |  # 5 bit tiếp theo
                            (0         << 16) |  # 4 bit padding 0
                            (1)          # 16 bit dưới cùng
                        )
                    
                        await nvm_read(dut, 0x30000000, data_for_read_op)
      
                    if col == 31:
                        if row == 7:
                            await wishbone_write(dut, 0x30002000, 0)
                        elif row == 15:
                            await wishbone_write(dut, 0x30002002, 0)
                        elif row == 23:
                            await wishbone_write(dut, 0x30002004, 0)
                        elif row == 31:
                            await wishbone_write(dut, 0x30002006, 0)
            
            await wishbone_read(dut, 0x30001000, spike_out_layer_2, pic, 0, layer, core_layer_2)
            await wishbone_read(dut, 0x30001004, spike_out_layer_2, pic, 1, layer, core_layer_2) 
        #===EVERY PIC===#
        
    ########################## FINISH LAYER_2 ########################
    print(f"L2 output: {spike_out_layer_2}")
    await Timer(PERIOD*1, units="ns")

    correct_pic = 0
    print("Prediction:")
    predict_class = calculate_majority_class(spike_out_layer_2)
    for pic in range (SUM_OF_PICS):
        print(predict_class[pic],end=" ")
        if (predict_class[pic] == golden_output[pic]):
            correct_pic+=1
    
    print(f"\nAccuracy {100*correct_pic/SUM_OF_PICS} %")
    
    # print("\nNumber of clock cycle = ")
    # print(dut.numclk,end=" ")
    
    # num_syn_ops = 0
    # for slice_inx in range (NUM_SLICE):
    #     for neuron_inx in range (NUM_NEURON_PER_SLICE):
    #         num_syn_ops = num_syn_ops +  int(dut.genblk1[slice_inx].neuron_slice_inst.genblk1[neuron_inx].nb_inst.syn_ops)
    # print(f"\nNumber of synaptic operations = {num_syn_ops}")

    # num_operation =  int(dut.operation) + int(dut.choose_weight_inst.operation) + int(dut.neuron_stimuli_inst.operation) + NUM_SLICE*int(dut.genblk1[0].neuron_slice_inst.operation) + NUM_SLICE*int(dut.genblk1[0].neuron_slice_inst.synapse_matrix_instance.operation) + NUM_SLICE*int(dut.genblk1[0].neuron_slice_inst.spike_out_inst.operation) + NUM_SLICE*NUM_NEURON_PER_SLICE*int(dut.genblk1[0].neuron_slice_inst.genblk1[0].np_inst.operation)
    # print(f"\nNumber of arithmetic operations = {num_operation}")

    print("\nTest Completed.")

##################################################################    