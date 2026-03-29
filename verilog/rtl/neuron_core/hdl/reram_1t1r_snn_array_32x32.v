`timescale 1ns/1ps

module reram_1t1r_snn_array_32x32 #(
    parameter integer ROWS = 32,
    parameter integer N_NEURONS = 16,
    parameter integer G_BITS = 3,
    parameter integer MEM_BITS = 16,
    parameter signed [MEM_BITS-1:0] THRESHOLD = 16'sd24,
    parameter signed [MEM_BITS-1:0] MEM_RESET = 16'sd0,
    parameter signed [MEM_BITS-1:0] MEM_FLOOR = -16'sd64,
    parameter integer LEAK_SHIFT = 2
) (
    input  wire                       clk_i,
    input  wire                       rst_ni,
    input  wire                       en_i,
    input  wire [ROWS-1:0]            spike_i,
    input  wire                       cfg_we_i,
    input  wire [3:0]                 cfg_neuron_i,
    input  wire                       cfg_sign_i,
    input  wire [4:0]                 cfg_row_i,
    input  wire [G_BITS-1:0]          cfg_level_i,
    output wire [N_NEURONS-1:0]       spike_o,
    output wire [N_NEURONS*MEM_BITS-1:0] membrane_o,
    output wire [N_NEURONS*MEM_BITS-1:0] syn_sum_o
);

    genvar gi;
    generate
        for (gi = 0; gi < N_NEURONS; gi = gi + 1) begin : gen_neuron
            wire local_cfg_we;
            assign local_cfg_we = cfg_we_i && (cfg_neuron_i == gi);

            reram_1t1r_snn_neuron #(
                .ROWS(ROWS),
                .G_BITS(G_BITS),
                .MEM_BITS(MEM_BITS),
                .THRESHOLD(THRESHOLD),
                .MEM_RESET(MEM_RESET),
                .MEM_FLOOR(MEM_FLOOR),
                .LEAK_SHIFT(LEAK_SHIFT)
            ) u_neuron (
                .clk_i(clk_i),
                .rst_ni(rst_ni),
                .en_i(en_i),
                .cfg_we_i(local_cfg_we),
                .cfg_sign_i(cfg_sign_i),
                .cfg_row_i(cfg_row_i),
                .cfg_level_i(cfg_level_i),
                .spike_i(spike_i),
                .spike_o(spike_o[gi]),
                .membrane_o(membrane_o[(gi+1)*MEM_BITS-1 -: MEM_BITS]),
                .syn_sum_o(syn_sum_o[(gi+1)*MEM_BITS-1 -: MEM_BITS])
            );
        end
    endgenerate

endmodule
