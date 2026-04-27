// -----------------------------------------------------------------------------
// nvm_synapse_matrix — 256-axon × 64-neuron ReRAM crossbar
//
// Topology:
//   16 Neuromorphic_X1 instances (NUM_OF_MACRO=16), each a 32×32 bit array.
//   All 16 macros receive the same (row, col) address per Wishbone transaction.
//   Each macro stores a different neuron's weight for that (axon, col) position:
//     wbs_dat_i[i] → macro i's 1-bit cell at (row, col)
//   On readback: wbs_dat_o[j] = slave_dat_o[j][0] packs 1 bit from each macro.
//
// Scan chain:
//   All 16 macros are daisy-chained: ScanInCC → macro[0] → macro[1] → ...
//   → macro[15] → ScanOutCC. ScanInDL/DR and TM are broadcast to all macros.
//
// ADDR_MATCH:
//   All macros share address 0x3000_000C. The top-level decoder gates stb/cyc
//   so only one core's synapse matrix is active at a time.
// -----------------------------------------------------------------------------
module nvm_synapse_matrix (

`ifdef USE_POWER_PINS
      inout VDDC,
      inout VDDA,
      inout VSS,
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
  output        wbs_ack_o,

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
  // parameter [31:0] MACRO_PADDING = 32'h100;
  parameter [31:0] ADDR_MATCH    = 32'h3000_000C; // only addr can access X1 IP
  parameter  [7:0] MEM_HIGH      = 8'hFF;
  parameter  [7:0] MEM_LOW       = 8'h00;

  wire [31:0] slave_dat_o [NUM_OF_MACRO-1:0];
  wire [NUM_OF_MACRO-1:0] slave_ack_o;
  wire [7:0] mem [NUM_OF_MACRO-1:0];
  reg wbs_we_i_reversed;
  wire [NUM_OF_MACRO:0] scan_chain;
  assign scan_chain[0] = ScanInCC;
  assign ScanOutCC = scan_chain[NUM_OF_MACRO];

  generate
    genvar i;
    for (i = 0; i < NUM_OF_MACRO; i=i+1) begin
      assign mem[i] = wbs_dat_i[i] ? MEM_HIGH : MEM_LOW;

      Neuromorphic_X1 X1_inst (
        `ifdef USE_POWER_PINS
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
        .ScanInCC(scan_chain[i]),
        .ScanInDL(ScanInDL),
        .ScanInDR(ScanInDR),
        .TM(TM),
        .ScanOutCC(scan_chain[i+1]),

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

  integer j;
  reg [31:0] wbs_dat_o_reg;
  always @(*) begin
    wbs_dat_o_reg = 32'b0;
    for (j = 0; j < NUM_OF_MACRO; j = j + 1) begin
      wbs_dat_o_reg[j] = slave_dat_o[j][0];
    end
  end
  assign wbs_dat_o = wbs_dat_o_reg;

// wbs_we_i_reversed :
//   The Neuromorphic_X1 core_ack arrives 1 clock cycle after the Wishbone
//   transaction — by which time the master has already de-asserted wbs_we_i.
//   Without this flip-flop, every ACK would appear as a READ ACK, causing
//   spurious neuron integrations during PROGRAM operations.
//   Fix: register ~wbs_we_i one cycle early so it aligns with core_ack.
//     wbs_ack_o = wbs_we_i_reversed & (|slave_ack_o)
//   → READ ACK  passes through  (wbs_we_i was 0, so _reversed=1)
//   → PROGRAM ACK is suppressed (wbs_we_i was 1, so _reversed=0)

  always @(posedge wb_clk_i or posedge wb_rst_i) begin
    if (wb_rst_i) wbs_we_i_reversed <= 1'b1;
    else          wbs_we_i_reversed <= ~wbs_we_i;
  end
  assign wbs_ack_o = wbs_we_i_reversed & (|slave_ack_o);

endmodule
