module neuron_core (

  // POWER
      inout VDDC,
      inout VDDA,
      inout VSS,

  // MASTER
  input         wb_clk_i,     // Wishbone clock
  input         wb_rst_i,     // Wishbone reset (Active High)
  input         wbs_stb_i,    // Wishbone strobe
  input         wbs_cyc_i,    // Wishbone cycle indicator
  input         wbs_we_i,     // Wishbone write enable: 1=write, 0=read
  input  [3:0]  wbs_sel_i,    // Wishbone byte select (must be 4'hF for 32-bit op)
  input  [31:0] wbs_dat_i,    // Wishbone write data (becomes DI to core)
  input  [31:0] wbs_adr_i,    // Wishbone address
  output [31:0] wbs_dat_o,    // Wishbone read data output (driven by DO from core)
  output        wbs_ack_o,     // Wishbone acknowledge output (core_ack from core)

  // SLAVEs
  input  [31:0] slave_0_dat_i,
  input  [31:0] slave_1_dat_i,
  input  [31:0] slave_2_dat_i,
  input  [31:0] slave_3_dat_i,
  input   [3:0] slave_ack_i,
  output        slave_stb_o,
  output        slave_cyc_o,
  output        slave_we_o,
  output [31:0] slave_0_dat_o,
  output [31:0] slave_1_dat_o,
  output [31:0] slave_2_dat_o,
  output [31:0] slave_3_dat_o
);

  parameter NUM_OF_MACRO = 4;   // number of NVM Neuromorphic X1 macro, 32x32 each
  parameter  [7:0] MEM_HIGH      = 8'hFF;
  parameter  [7:0] MEM_LOW       = 8'h00;

  wire synapse_matrix_select; // Addr is pointing to X1 IPs
  wire neuron_spike_out_select; // Addr is pointing to neuron_spikeout block
  wire picture_done;

  wire         [3:0] spike_o;
  wire         [4:0] row;          // pointed row/col in X1 IP
  wire         [4:0] col;
  wire               weight_type;  // 1 or -1
  wire signed [15:0] stimuli;
  wire         [3:0] connection;
  wire               enable;
  reg                wbs_we_i_reversed;

  assign row        = wbs_dat_i[29:25];
  assign col        = wbs_dat_i[24:20];
  assign connection = {slave_3_dat_i[0],
                       slave_2_dat_i[0],
                       slave_1_dat_i[0],
                       slave_0_dat_i[0]};
  assign weight_type= col[0];
  assign stimuli    = weight_type ? -wbs_dat_i[15:0] : wbs_dat_i[15:0];

  nvm_core_decoder core_decoder_inst (
    .addr                   (wbs_adr_i),
    .synapse_matrix_select (synapse_matrix_select),
    .neuron_spike_out_select(neuron_spike_out_select),
    .picture_done           (picture_done)
  );

  nvm_neuron_block neuron_block_inst (
    .clk        (wb_clk_i),
    .rst        (wb_rst_i),
    .stimuli    (stimuli),
    .connection (connection),
    .picture_done(picture_done),
    .enable     (enable),
    .spike_o    (spike_o)
  );

  nvm_neuron_spike_out spike_out_inst (
    .wb_clk_i    (wb_clk_i),
    .wb_rst_i    (wb_rst_i),
    .wbs_cyc_i   (wbs_cyc_i & (neuron_spike_out_select|picture_done)),
    .wbs_stb_i   (wbs_stb_i & (neuron_spike_out_select|picture_done)),
    .wbs_we_i    (wbs_we_i  & (neuron_spike_out_select|picture_done)),
    .wbs_sel_i   (wbs_sel_i),
    .wbs_adr_i   (wbs_adr_i),
    .wbs_dat_i   ({28'b0,spike_o}),
    .wbs_ack_o   (wbs_ack_o), 
    .wbs_dat_o   (wbs_dat_o)
  );

  assign slave_stb_o = wbs_stb_i & synapse_matrix_select;
  assign slave_cyc_o = wbs_cyc_i & synapse_matrix_select;
  assign slave_we_o  = wbs_we_i  & synapse_matrix_select;
  assign slave_0_dat_o = {wbs_dat_i[31:8],wbs_dat_i[0] ? MEM_HIGH : MEM_LOW};
  assign slave_1_dat_o = {wbs_dat_i[31:8],wbs_dat_i[1] ? MEM_HIGH : MEM_LOW};
  assign slave_2_dat_o = {wbs_dat_i[31:8],wbs_dat_i[2] ? MEM_HIGH : MEM_LOW};
  assign slave_3_dat_o = {wbs_dat_i[31:8],wbs_dat_i[3] ? MEM_HIGH : MEM_LOW};

  always @(posedge wb_clk_i) begin
    wbs_we_i_reversed <= ~wbs_we_i;
  end
  assign enable = wbs_we_i_reversed & (|slave_ack_i);

endmodule
