module nvm_synapse_matrix (

`ifdef USE_PG_PIN
      input VDDC,
      input VDDA,
      input VSS,
`endif
  input         wb_clk_i, 
  input         wb_rst_i, 
  input         wbs_stb_i,
  input         wbs_cyc_i,
  input         wbs_we_i, 
  input  [3:0]  wbs_sel_i,
  input  [31:0] wbs_dat_i,
  input  [31:0] wbs_adr_i,
  output [31:0] wbs_dat_o,
  output reg    wbs_ack_o,

  // Scan/Test Pins
  input         ScanInCC,        // Scan enable
  input         ScanInDL,        // Data scan chain input (user_clk domain)
  input         ScanInDR,        // Data scan chain input (wb_clk domain)
  input         TM,              // Test mode
  output        ScanOutCC,       // Data scan chain output

  // Analog Pins
  input         Iref,            // 100 µA current reference
  input         Vcc_read,        // 0.3 V read rail
  input         Vcomp,           // 0.6 V comparator bias
  input         Bias_comp2,      // 0.6 V comparator bias
  input         Vcc_wl_read,     // 0.7 V wordline read rail
  input         Vcc_wl_set,      // 1.8 V wordline set rail
  input         Vbias,           // 1.8 V analog bias
  input         Vcc_wl_reset,    // 2.6 V wordline reset rail
  input         Vcc_set,         // 3.3 V array set rail
  input         Vcc_reset,       // 3.3 V array reset rail
  input         Vcc_L,           // 5 V level shifter supply
  input         Vcc_Body         // 5 V body-bias supply
);
  parameter NUM_OF_MACRO = 16;   // number of NVM Neuromorphic X1 macro, 32x32 each
  parameter [31:0] MACRO_PADDING = 32'h100;
  parameter [31:0] ADDR_MATCH    = 32'h3000_000C; // only addr can access X1 IP
  parameter  [7:0] MEM_HIGH      = 8'hFF;
  parameter  [7:0] MEM_LOW       = 8'h00;

  wire [31:0] slave_dat_o [NUM_OF_MACRO-1:0];
  wire [NUM_OF_MACRO-1:0] slave_ack_o;
  wire [7:0] mem [NUM_OF_MACRO-1:0];
  reg wbs_we_i_reversed;

  generate
    genvar i;
    for (i = 0; i < NUM_OF_MACRO; i=i+1) begin
      assign mem[i] = wbs_dat_i[i] ? MEM_HIGH : MEM_LOW;

      Neuromorphic_X1 X1_inst (
        `ifdef USE_PG_PIN
        .VDDC(VDDC),
        .VDDA(VDDA),
        .VSS (VSS),
        `endif
        .user_clk (wb_clk_i),
        .user_rst (wb_rst_i),
        .wb_clk_i (wb_clk_i),
        .wb_rst_i (wb_rst_i),
        .wbs_stb_i(wbs_stb_i),
        .wbs_cyc_i(wbs_cyc_i),
        .wbs_we_i (wbs_we_i),
        .wbs_sel_i(wbs_sel_i),
        .wbs_dat_i({wbs_dat_i[31:8],mem[i]}),
        .wbs_adr_i(ADDR_MATCH),
        .wbs_dat_o(slave_dat_o[i]),
        .wbs_ack_o(slave_ack_o[i]),

        // Scan/Test Pins
        .ScanInCC(ScanInCC),
        .ScanInDL(ScanInDL),
        .ScanInDR(ScanInDR),
        .TM(TM),
        .ScanOutCC(ScanOutCC),

        // Analog Pins
        .Iref(Iref),
        .Vcc_read(Vcc_read),
        .Vcomp(Vcomp),
        .Bias_comp2(Bias_comp2),
        .Vcc_wl_read(Vcc_wl_read),
        .Vcc_wl_set(Vcc_wl_set),
        .Vbias(Vbias),
        .Vcc_wl_reset(Vcc_wl_reset),
        .Vcc_set(Vcc_set),
        .Vcc_reset(Vcc_reset),
        .Vcc_L(Vcc_L),
        .Vcc_Body(Vcc_Body)
      );
    end
  endgenerate

  assign wbs_dat_o = {16'b0,
     slave_dat_o[15][0],slave_dat_o[14][0],slave_dat_o[13][0],slave_dat_o[12][0],
     slave_dat_o[11][0],slave_dat_o[10][0],slave_dat_o[9][0],slave_dat_o[8][0],
     slave_dat_o[7][0],slave_dat_o[6][0],slave_dat_o[5][0],slave_dat_o[4][0],
     slave_dat_o[3][0],slave_dat_o[2][0],slave_dat_o[1][0],slave_dat_o[0][0]};

  always @(posedge wb_clk_i) begin
    wbs_we_i_reversed <= ~wbs_we_i;
  end
  assign wbs_ack_o = wbs_we_i_reversed & (|slave_ack_o);

endmodule