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

  reg   [3:0] sram [15:0]; // storage for spikes (64 neurons)
  wire [15:0] addr;        // which of sixteen array above
  assign addr = wbs_adr_i[3:0];

  always @(posedge wb_clk_i or posedge wb_rst_i) begin
    if (wb_rst_i) begin
      wbs_ack_o <= 1'b0;
      wbs_dat_o <= 32'b0;
      sram[0] <= 4'b0; sram[1] <= 4'b0; sram[2] <= 4'b0; sram[3] <= 4'b0;
      sram[4] <= 4'b0; sram[5] <= 4'b0; sram[6] <= 4'b0; sram[7] <= 4'b0;
      sram[8] <= 4'b0; sram[9] <= 4'b0; sram[10]<= 4'b0; sram[11]<= 4'b0;
      sram[12]<= 4'b0; sram[13]<= 4'b0; sram[14]<= 4'b0; sram[15]<= 4'b0;
    end
    else if (wbs_cyc_i && wbs_stb_i) begin
        wbs_ack_o <= 1'b1;
        if (wbs_we_i) begin
          // Byte-specific writes based on wbs_sel_i
          if (wbs_sel_i[0]) sram[addr] <= wbs_dat_i[3:0];
        end
        else wbs_dat_o <= {
          sram[addr+7],sram[addr+6],sram[addr+5],sram[addr+4],
          sram[addr+3],sram[addr+2],sram[addr+1],sram[addr]
        };
    end
    else begin
      wbs_ack_o <= 1'b0; 
      wbs_dat_o <= 32'b0;
    end
  end
  
endmodule