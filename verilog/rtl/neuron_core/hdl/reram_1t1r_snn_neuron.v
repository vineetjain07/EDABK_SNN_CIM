`timescale 1ns/1ps

module reram_1t1r_snn_neuron #(
    parameter integer ROWS = 32,
    parameter integer G_BITS = 3,
    parameter integer MEM_BITS = 16,
    parameter signed [MEM_BITS-1:0] THRESHOLD = 16'sd24,
    parameter signed [MEM_BITS-1:0] MEM_RESET = 16'sd0,
    parameter signed [MEM_BITS-1:0] MEM_FLOOR = -16'sd64,
    parameter integer LEAK_SHIFT = 2
) (
    input  wire                     clk_i,
    input  wire                     rst_ni,
    input  wire                     en_i,
    input  wire                     cfg_we_i,
    input  wire                     cfg_sign_i,
    input  wire [4:0]               cfg_row_i,
    input  wire [G_BITS-1:0]        cfg_level_i,
    input  wire [ROWS-1:0]          spike_i,
    output reg                      spike_o,
    output reg signed [MEM_BITS-1:0] membrane_o,
    output reg signed [MEM_BITS-1:0] syn_sum_o
);

    reg [G_BITS-1:0] g_pos [0:ROWS-1];
    reg [G_BITS-1:0] g_neg [0:ROWS-1];

    integer idx;
    reg signed [MEM_BITS-1:0] pos_sum_comb;
    reg signed [MEM_BITS-1:0] neg_sum_comb;
    reg signed [MEM_BITS-1:0] syn_sum_comb;
    reg signed [MEM_BITS-1:0] leak_comb;
    reg signed [MEM_BITS-1:0] mem_next_comb;

    always @* begin
        pos_sum_comb = {MEM_BITS{1'b0}};
        neg_sum_comb = {MEM_BITS{1'b0}};
        for (idx = 0; idx < ROWS; idx = idx + 1) begin
            if (spike_i[idx]) begin
                pos_sum_comb = pos_sum_comb + $signed({1'b0, g_pos[idx]});
                neg_sum_comb = neg_sum_comb + $signed({1'b0, g_neg[idx]});
            end
        end
        syn_sum_comb = pos_sum_comb - neg_sum_comb;
        leak_comb = membrane_o >>> LEAK_SHIFT;
        mem_next_comb = membrane_o - leak_comb + syn_sum_comb;
    end

    integer reset_idx;
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            spike_o <= 1'b0;
            membrane_o <= MEM_RESET;
            syn_sum_o <= {MEM_BITS{1'b0}};
            for (reset_idx = 0; reset_idx < ROWS; reset_idx = reset_idx + 1) begin
                g_pos[reset_idx] <= {G_BITS{1'b0}};
                g_neg[reset_idx] <= {G_BITS{1'b0}};
            end
        end else begin
            spike_o <= 1'b0;
            syn_sum_o <= syn_sum_comb;

            if (cfg_we_i) begin
                if (cfg_sign_i) begin
                    g_neg[cfg_row_i] <= cfg_level_i;
                end else begin
                    g_pos[cfg_row_i] <= cfg_level_i;
                end
            end else if (en_i) begin
                if (mem_next_comb >= THRESHOLD) begin
                    membrane_o <= MEM_RESET;
                    spike_o <= 1'b1;
                end else if (mem_next_comb <= MEM_FLOOR) begin
                    membrane_o <= MEM_FLOOR;
                end else begin
                    membrane_o <= mem_next_comb;
                end
            end
        end
    end

endmodule
