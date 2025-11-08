module nvm_neuron_core_256x64 (

`ifdef USE_PG_PIN
      input VDDC,
      input VDDA,
      input VSS,
`endif
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

  wire synapse_matrix_select; // Addr is pointing to synap_matrix block
  wire neuron_spike_out_select; // Addr is pointing to neuron_spikeout block
  wire picture_done;

  wire [15:0] spike_o;

  wire [31:0] slave_dat_o [1:0]; // 3 component (neuron_stimuli=0,synap_matrix=1,spikeout=2)
  wire  [1:0] slave_ack_o;

  wire  [4:0] row;          // pointed row/col in X1 IP
  wire  [4:0] col;
  // wire  [7:0] axon;         // 0 to 255
  wire        weight_type;  // 1 or -1
  wire signed [15:0] stimuli;

  wire [15:0] connection;

  assign row        = wbs_dat_i[29:25];
  assign col        = wbs_dat_i[24:20];
  assign connection = slave_dat_o[0][15:0];
  // assign axon       = (row[2:0] << 5) + col;  // xem comment ben duoi cung
  // assign weight_type= axon[0];
  assign weight_type= col[0];
  assign stimuli    = weight_type ? -wbs_dat_i[15:0] : wbs_dat_i[15:0];

  nvm_core_decoder core_decoder_inst (
    .addr                   (wbs_adr_i),
    .synapse_matrix_select (synapse_matrix_select),
    .neuron_spike_out_select(neuron_spike_out_select),
    .picture_done           (picture_done)
  );

  nvm_synapse_matrix synapse_matrix_inst (
    `ifdef USE_PG_PIN
    .VDDC(VDDC),
    .VDDA(VDDA),
    .VSS (VSS),
    `endif
    .wb_clk_i (wb_clk_i),
    .wb_rst_i (wb_rst_i),
    .wbs_stb_i(wbs_stb_i & synapse_matrix_select),
    .wbs_cyc_i(wbs_cyc_i & synapse_matrix_select),
    .wbs_we_i (wbs_we_i  & synapse_matrix_select),
    .wbs_sel_i(wbs_sel_i),
    .wbs_dat_i(wbs_dat_i),
    .wbs_adr_i(wbs_adr_i),
    .wbs_dat_o(slave_dat_o[0]),
    .wbs_ack_o(slave_ack_o[0]),

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

  nvm_neuron_block neuron_block_inst (
    .clk        (wb_clk_i),
    .rst        (wb_rst_i),
    .stimuli    (stimuli),
    .connection (connection),
    .picture_done(picture_done),
    .enable     (slave_ack_o[0]),
    .spike_o    (spike_o)
  );

  nvm_neuron_spike_out spike_out_inst (
    .wb_clk_i    (wb_clk_i),
    .wb_rst_i    (wb_rst_i),
    .wbs_cyc_i   (wbs_cyc_i & (neuron_spike_out_select|picture_done)),
    .wbs_stb_i   (wbs_stb_i & (neuron_spike_out_select|picture_done)),
    .wbs_we_i    (wbs_we_i  & (neuron_spike_out_select|picture_done)),
    .wbs_sel_i   (wbs_sel_i),
    // .wbs_cyc_i   (picture_done ? 1'b1 : (wbs_cyc_i & neuron_spike_out_select)),
    // .wbs_stb_i   (picture_done ? 1'b1 : (wbs_stb_i & neuron_spike_out_select)),
    // .wbs_we_i    (picture_done ? 1'b1 : (wbs_we_i  & neuron_spike_out_select)),
    // .wbs_sel_i   (picture_done ? 4'hF : wbs_sel_i),
    .wbs_adr_i   (wbs_adr_i),
    .wbs_dat_i   ({16'b0,spike_o}),
    .wbs_ack_o   (slave_ack_o[1]), 
    .wbs_dat_o   (slave_dat_o[1])
  );

  assign wbs_dat_o = synapse_matrix_select ? slave_dat_o[0] :
                     neuron_spike_out_select ? slave_dat_o[1] :
                     32'b0;
  assign wbs_ack_o = |slave_ack_o;

endmodule

// - Đánh số thứ tự từ 0
// - Neuron Core: 256 axon x 64 neuron.
// - Chỉ lưu synapse. Weight mặc định là +1 -1. threshold mặc định là 0. Không dùng bias.
// - Synapse Matrix hình thành bởi 16 IP Neuromorphic X1 32x32
//   + IP 0: Lưu synap giữa mọi axon với neuron 0,16,32,48 (8 hàng đầu của neuron 0, 8 hàng sau của neuron 16)
//   + Chỉ 1 địa chỉ 0x3000_0000, nhưng mỗi lần đọc/ghi phải đi kèm data.
//   Viết vào và đọc ra từ 16 IP X1 cùng một lúc, mỗi lần 1 bit (1 bit này ở cùng vị trí hàng/cột trong cả 16 IP)
// Khi viết     MODE   ROW    COL    NONE   DATA (synap connection, chia ra mỗi IP 1 bit)
//  wbs_dat_i: [31:30][29:25][24:20][19:16][15:0]
// Khi đọc      MODE   ROW    COL    NONE   STIMULI
//  wbs_dat_i: [31:30][29:25][24:20][19:16][15:0]

  // Ví dụ IP 0:
  // Row Col Axon Neuron
  // 0   0   0    0
  // 0   1   1    0
  // 1   0   32   0
  // 7   31  255  0
  // 15  31  255  16
  // 23  31  255  32
  // 31  31  255  48

// Done pic, viết spike từ Neuron Block vào Neuron Spikeout: viết vào một trong 4 địa chỉ sau
  // Địa chỉ     Neuron
  // 0x3000_2000 0-15
  // 0x3000_2002 16-31
  // 0x3000_2004 32-47
  // 0x3000_2006 48-63

// - Neuron Spikeout: 64 bit. Đọc từ một trong địa chỉ này ra
  // Địa chỉ     Neuron
  // 0x3000_1000 0-31
  // 0x3000_1004 32-63
