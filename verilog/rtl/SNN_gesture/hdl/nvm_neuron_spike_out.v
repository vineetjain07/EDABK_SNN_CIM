// -----------------------------------------------------------------------------
// nvm_neuron_spike_out — Spike storage and readback SRAM
//
// This module provides a small SRAM (4x16 bits) to store the output spikes of 
// 64 neurons. Spikes are latched from the neuron block on picture_done and 
// can be read back by the host via the Wishbone interface.
//
// Address Mapping (Local):
//   - 0x1000: Returns neurons 0-31 (packed as {16'h0, spikes[15:0], 16'h0, ...})
//   - Readback returns two 16-bit spike words concatenated.
// -----------------------------------------------------------------------------
module nvm_neuron_spike_out (
  // Wishbone slave interface
  input             wb_clk_i,  // Clock
  input             wb_rst_i,  // Reset
  input             wbs_cyc_i, // Indicates an active Wishbone cycle
  input             wbs_stb_i, // Active during a valid address phase
  input             wbs_we_i,  // Determines read or write operation
  input       [3:0] wbs_sel_i, // Byte lanes selector
  input      [31:0] wbs_adr_i, // Address input
  input      [31:0] wbs_dat_i, // Data input for writes
  output reg        wbs_ack_o, // Acknowledgment for data transfer
  output reg [31:0] wbs_dat_o // Data output
  );

  reg        [15:0] sram [3:0]; // storage for spikes (64 neurons)
  wire        [1:0] addr;       // which of four array above
  assign addr = wbs_adr_i[2:1];

  always @(posedge wb_clk_i or posedge wb_rst_i) begin
    if (wb_rst_i) begin
      wbs_ack_o <= 1'b0;
      wbs_dat_o <= 32'b0;
      sram[0]   <= 16'b0;
      sram[1]   <= 16'b0;
      sram[2]   <= 16'b0;
      sram[3]   <= 16'b0;
    end
    else if (wbs_cyc_i && wbs_stb_i) begin
        wbs_ack_o <= 1'b1;
        if (wbs_we_i) begin
          // Byte-specific writes based on wbs_sel_i
          if (wbs_sel_i[0]) sram[addr][7:0] <= wbs_dat_i[7:0];
          if (wbs_sel_i[1]) sram[addr][15:8] <= wbs_dat_i[15:8];
        end
        // Force 2-bit wrap-around to prevent OOB sram[4] and simulation X-propagation.
        else wbs_dat_o <= {sram[(addr+1) & 2'b11], sram[addr]};
    end
    else begin
      wbs_ack_o <= 1'b0; 
      wbs_dat_o <= 32'b0;
    end
  end
  
endmodule