// `default_nettype none
module user_project_wrapper #(
    parameter BITS = 32
) (
`ifdef USE_POWER_PINS
    inout vdda1, inout vdda2,
    inout vssa1, inout vssa2,
    inout vccd1, inout vccd2,
    inout vssd1, inout vssd2,
`endif

    // Wishbone
    input         wb_clk_i,
    input         wb_rst_i,
    input         wbs_stb_i,
    input         wbs_cyc_i,
    input         wbs_we_i,
    input  [3:0]  wbs_sel_i,
    input  [31:0] wbs_dat_i,
    input  [31:0] wbs_adr_i,
    output        wbs_ack_o,
    output [31:0] wbs_dat_o,

    // Logic Analyzer
    input  [127:0] la_data_in,
    output [127:0] la_data_out,
    input  [127:0] la_oenb,

    // Digital IOs
    input  [38-1:0] io_in,   //  MPRJ_IO_PADS
    output [38-1:0] io_out,
    output [38-1:0] io_oeb,

    // Analog IOs (analog_io[k] <-> GPIO pad k+7)
    inout  [38-10:0] analog_io,

    // Extra user clock
    input   user_clock2,

    // IRQs
    output [2:0] user_irq
);
  parameter [31:0] ADDR_MATCH    = 32'h3000_000C; // only addr can access X1 IP

  wire [31:0] slave_dat [3:0]; // 4 IPs
  wire  [3:0] slave_ack;
  wire        slave_stb;
  wire        slave_cyc;
  wire        slave_we;
  wire [31:0] mem [3:0]; // 4 IPs

  nvm_neuron_core_64x64 neuron_core_inst (
    // MASTER
    .wb_clk_i (wb_clk_i),
    .wb_rst_i (wb_rst_i),
    .wbs_stb_i(wbs_stb_i),
    .wbs_cyc_i(wbs_cyc_i),
    .wbs_we_i (wbs_we_i),
    .wbs_sel_i(wbs_sel_i),
    .wbs_dat_i(wbs_dat_i),
    .wbs_adr_i(wbs_adr_i),
    .wbs_dat_o(wbs_dat_o),
    .wbs_ack_o(wbs_ack_o),

    // SLAVEs
    .slave_0_dat_i(slave_dat[0]),
    .slave_1_dat_i(slave_dat[1]),
    .slave_2_dat_i(slave_dat[2]),
    .slave_3_dat_i(slave_dat[3]),
    .slave_ack_i  (slave_ack),
    .slave_stb_o  (slave_stb),
    .slave_cyc_o  (slave_cyc),
    .slave_we_o   (slave_we),
    .slave_0_dat_o(mem[0]),
    .slave_1_dat_o(mem[1]),
    .slave_2_dat_o(mem[2]),
    .slave_3_dat_o(mem[3])
  );

    // ------------------------------------------------------------
    // Instance 0
    // ------------------------------------------------------------
    Neuromorphic_X1 X1_inst_0 (
    `ifdef USE_POWER_PINS
        .VDDC (vccd1),
        .VDDA (vdda1),
        .VSS  (vssd1),
    `endif
        .user_clk (wb_clk_i),
        .user_rst (wb_rst_i),
        .wb_clk_i (wb_clk_i),
        .wb_rst_i (wb_rst_i),
        .wbs_stb_i (slave_stb),
        .wbs_cyc_i (slave_cyc),
        .wbs_we_i  (slave_we),
        .wbs_sel_i (wbs_sel_i),
        .wbs_dat_i (mem[0]),
        .wbs_adr_i (ADDR_MATCH),
        .wbs_dat_o (slave_dat[0]),
        .wbs_ack_o (slave_ack[0]),

        .ScanInCC  (io_in[4]),
        .ScanInDL  (io_in[1]),
        .ScanInDR  (io_in[2]),
        .TM        (io_in[5]),
        .ScanOutCC (io_out[0]),

        .Iref          (analog_io[0]),
        .Vcc_read      (analog_io[1]),
        .Vcomp         (analog_io[2]),
        .Bias_comp2    (analog_io[3]),
        .Vcc_wl_read   (analog_io[12]),
        .Vcc_wl_set    (analog_io[5]),
        .Vbias         (analog_io[6]),
        .Vcc_wl_reset  (analog_io[7]),
        .Vcc_set       (analog_io[8]),
        .Vcc_reset     (analog_io[9]),
        .Vcc_L         (analog_io[10]),
        .Vcc_Body      (analog_io[11])
    );

    // // ------------------------------------------------------------
    // // Instance 1
    // // ------------------------------------------------------------
    Neuromorphic_X1 X1_inst_1 (
    `ifdef USE_POWER_PINS
        .VDDC (vccd1),
        .VDDA (vdda1),
        .VSS  (vssd1),
    `endif
        .user_clk (wb_clk_i),
        .user_rst (wb_rst_i),
        .wb_clk_i (wb_clk_i),
        .wb_rst_i (wb_rst_i),
        .wbs_stb_i (slave_stb),
        .wbs_cyc_i (slave_cyc),
        .wbs_we_i  (slave_we),
        .wbs_sel_i (wbs_sel_i),
        .wbs_dat_i (mem[1]),
        .wbs_adr_i (ADDR_MATCH),
        .wbs_dat_o (slave_dat[1]),
        .wbs_ack_o (slave_ack[1]),

        .ScanInCC  (io_in[4]),
        .ScanInDL  (io_in[1]),
        .ScanInDR  (io_in[2]),
        .TM        (io_in[5]),
        .ScanOutCC (io_out[1]),

        .Iref          (analog_io[0]),
        .Vcc_read      (analog_io[1]),
        .Vcomp         (analog_io[2]),
        .Bias_comp2    (analog_io[3]),
        .Vcc_wl_read   (analog_io[12]),
        .Vcc_wl_set    (analog_io[5]),
        .Vbias         (analog_io[6]),
        .Vcc_wl_reset  (analog_io[7]),
        .Vcc_set       (analog_io[8]),
        .Vcc_reset     (analog_io[9]),
        .Vcc_L         (analog_io[10]),
        .Vcc_Body      (analog_io[11])
    );

    // ------------------------------------------------------------
    // Instance 2
    // ------------------------------------------------------------
    Neuromorphic_X1 X1_inst_2 (
    `ifdef USE_POWER_PINS
        .VDDC (vccd1),
        .VDDA (vdda1),
        .VSS  (vssd1),
    `endif
        .user_clk (wb_clk_i),
        .user_rst (wb_rst_i),
        .wb_clk_i (wb_clk_i),
        .wb_rst_i (wb_rst_i),
        .wbs_stb_i (slave_stb),
        .wbs_cyc_i (slave_cyc),
        .wbs_we_i  (slave_we),
        .wbs_sel_i (wbs_sel_i),
        .wbs_dat_i (mem[2]),
        .wbs_adr_i (ADDR_MATCH),
        .wbs_dat_o (slave_dat[2]),
        .wbs_ack_o (slave_ack[2]),

        .ScanInCC  (io_in[4]),
        .ScanInDL  (io_in[1]),
        .ScanInDR  (io_in[2]),
        .TM        (io_in[5]),
        .ScanOutCC (io_out[2]),

        .Iref          (analog_io[0]),
        .Vcc_read      (analog_io[1]),
        .Vcomp         (analog_io[2]),
        .Bias_comp2    (analog_io[3]),
        .Vcc_wl_read   (analog_io[12]),
        .Vcc_wl_set    (analog_io[5]),
        .Vbias         (analog_io[6]),
        .Vcc_wl_reset  (analog_io[7]),
        .Vcc_set       (analog_io[8]),
        .Vcc_reset     (analog_io[9]),
        .Vcc_L         (analog_io[10]),
        .Vcc_Body      (analog_io[11])
    );

    // // ------------------------------------------------------------
    // // Instance 3
    // // ------------------------------------------------------------
    Neuromorphic_X1 X1_inst_3 (
    `ifdef USE_POWER_PINS
        .VDDC (vccd1),
        .VDDA (vdda1),
        .VSS  (vssd1),
    `endif
        .user_clk (wb_clk_i),
        .user_rst (wb_rst_i),
        .wb_clk_i (wb_clk_i),
        .wb_rst_i (wb_rst_i),
        .wbs_stb_i (slave_stb),
        .wbs_cyc_i (slave_cyc),
        .wbs_we_i  (slave_we),
        .wbs_sel_i (wbs_sel_i),
        .wbs_dat_i (mem[3]),
        .wbs_adr_i (ADDR_MATCH),
        .wbs_dat_o (slave_dat[3]),
        .wbs_ack_o (slave_ack[3]),

        .ScanInCC  (io_in[4]),
        .ScanInDL  (io_in[1]),
        .ScanInDR  (io_in[2]),
        .TM        (io_in[5]),
        .ScanOutCC (io_out[3]),

        .Iref          (analog_io[0]),
        .Vcc_read      (analog_io[1]),
        .Vcomp         (analog_io[2]),
        .Bias_comp2    (analog_io[3]),
        .Vcc_wl_read   (analog_io[12]),
        .Vcc_wl_set    (analog_io[5]),
        .Vbias         (analog_io[6]),
        .Vcc_wl_reset  (analog_io[7]),
        .Vcc_set       (analog_io[8]),
        .Vcc_reset     (analog_io[9]),
        .Vcc_L         (analog_io[10]),
        .Vcc_Body      (analog_io[11])
    );

endmodule
// `default_nettype wire