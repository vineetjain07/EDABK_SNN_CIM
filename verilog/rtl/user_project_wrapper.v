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
    input  [`MPRJ_IO_PADS-1:0] io_in,
    output [`MPRJ_IO_PADS-1:0] io_out,
    output [`MPRJ_IO_PADS-1:0] io_oeb,

    // Analog IOs (analog_io[k] <-> GPIO pad k+7)
    inout  [`MPRJ_IO_PADS-10:0] analog_io,

    // Extra user clock
    input   user_clock2,

    // IRQs
    output [2:0] user_irq
);
  parameter [31:0] ADDR_MATCH    = 32'h3000_000C; // only addr can access X1 IP (already defined in nvm_synapse_matrix)

  // ─────────────────────────────────────────────────────────────────────────
  // HARDWARE LIMITATION — OpenLane / Caravel die-area constraint
  //
  // The original design targeted 16 Neuromorphic_X1 ReRAM macros per neuron
  // core, providing 64 neurons per crossbar tile (16 macros × 4 neuron rows).
  //
  // After OpenLane floor-planning on the Caravel 2920×3520 µm user-project
  // wrapper, only 8 macros fit without violating routing DRC or PDN stripes.
  // The design is therefore taped out with NUM_OF_MACRO=8, giving:
  //   - 32 neurons per tile  (8 macros × 4 neuron rows)
  //   - 8 × 32 = 256 total weights per axon row, not 16 × 32 = 512
  //
  // Impact on accuracy: training must target NUM_NEURON=32 (nvm_parameter.py).
  // The SNN topology (L0=832, L1=256, L2=256) is unchanged — layer widths
  // remain valid multiples of 32 — but the core count doubles (26/8/8 instead
  // of 13/4/4 for 16-macro hardware).  See openlane/SNN_gesture/README.md.
  // ─────────────────────────────────────────────────────────────────────────

  nvm_neuron_core_256x64 #(
    .NUM_OF_MACRO(8)   // 8 macros: Caravel area-constrained tapeout configuration
  ) neuron_core_inst (
    `ifdef USE_POWER_PINS
        .VDDC (vccd1),
        .VDDA (vdda1),
        .VSS  (vssd1),
    `endif
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

    // Scan/Test Pins
    .ScanInCC  (io_in[4]),
    .ScanInDL  (io_in[1]),
    .ScanInDR  (io_in[2]),
    .TM        (io_in[5]),
    .ScanOutCC (io_out[0]),

    // Analog Pins
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
    // Note: ReRAM instances are now removed from the top-level 
    // because nvm_neuron_core_256x64 handles synapses internally.
    // ------------------------------------------------------------

endmodule
// `default_nettype wire
