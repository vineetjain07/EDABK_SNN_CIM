// -----------------------------------------------------------------------------
// nvm_neuron_core_256x64 — Top-level 256-axon × 64-neuron LIF inference core
//
// This module integrates the ReRAM synapse matrix, the LIF neuron blocks, and
// the spike output buffer into a single Wishbone-compatible core. It supports
// binary-weight SNN inference with NUM_OF_MACRO physical neurons time-multiplexed
// 4× to provide (NUM_OF_MACRO×4) virtual neurons.
// With NUM_OF_MACRO=8 (OpenLane/Caravel tapeout configuration): 8 physical neurons
// × 4 time-steps = 32 virtual neurons per core.
//
// Data Flow (Single Gesture Inference):
//   1. PROGRAM Cycle:
//      - Wishbone writes to 0x3000_0000 set the binary weights ({0, 1}) for 
//        each axon-neuron connection in the ReRAM macros.
//   2. INJECT Cycle (READ/ACK):
//      - Stimuli are injected by writing to 0x3000_000C.
//      - wbs_dat_i[29:20] specifies the axon index (row/col in ReRAM).
//      - wbs_dat_i[15:0] carries the 16-bit signed stimulus value.
//      - The synapse matrix ACKs once the weighted contribution is ready.
//      - This ACK enables the neuron block to accumulate the stimulus.
//   3. LATCH/RESET (picture_done):
//      - A write to 0x3000_2xxx triggers the end of a gesture pass.
//      - Potentials are compared against the THRESHOLD to generate spikes.
//      - Spikes are latched into the SRAM and potentials are reset to zero.
//   4. READBACK:
//      - The 64 output spikes are read back via Wishbone from 0x3000_1xxx.
//
// Hardware Sign Encoding (weight_type):
//   - col[0] of the address packet determines the axon polarity.
//   - even columns (col[0]=0) → stimuli = +val
//   - odd columns  (col[0]=1) → stimuli = -val
//   - This allows the binary {0, 1} weights to represent {+1, -1} contributions.
//
// enable signal:
//   Driven by slave_ack_o[0] (synapse matrix ACK). Neuron block accumulates
//   exactly once per ACK — i.e., once per completed synapse READ cycle.
//
// picture_done priority:
//   picture_done is OR'd into the spike_out write-enable regardless of
//   neuron_spike_out_select, so it always latches spikes and resets potentials
//   even if the address would not otherwise select spike_out.
// -----------------------------------------------------------------------------

`include "nvm_parameter.vh"

module nvm_neuron_core_256x64 #(
  parameter NUM_OF_MACRO = `NUM_OF_MACRO  // number of Neuromorphic_X1 macros (32×32 each); defined in nvm_parameter.vh
) (

`ifdef USE_POWER_PINS
      inout VDDC,
      inout VDDA,
      inout VSS,
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

  wire [NUM_OF_MACRO-1:0] spike_o;

  wire [31:0] slave_dat_o [1:0]; // 3 component (neuron_stimuli=0,synap_matrix=1,spikeout=2)
  wire  [1:0] slave_ack_o;

  // wire  [4:0] row;          // pointed row/col in X1 IP  // to resolve lint warnings
  wire  [4:0] col;
  // wire  [7:0] axon;         // 0 to 255
  wire        weight_type;  // 1 or -1
  wire signed [15:0] stimuli;

  wire [NUM_OF_MACRO-1:0] connection;

  // Pad spike_o to full 32 bits for the spike_out write path.
  // With NUM_OF_MACRO=8: {24'b0, spike_o[7:0]}; with 16: {16'b0, spike_o[15:0]}.
  wire [31:0] spike_o_padded;
  assign spike_o_padded = {{(32-NUM_OF_MACRO){1'b0}}, spike_o};

  // assign row        = wbs_dat_i[29:25]; // to resolve lint warnings
  assign col        = wbs_dat_i[24:20];
  assign connection = slave_dat_o[0][NUM_OF_MACRO-1:0];
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

  nvm_synapse_matrix #(.NUM_OF_MACRO(NUM_OF_MACRO)) synapse_matrix_inst (
    `ifdef USE_POWER_PINS
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

  nvm_neuron_block #(.NUM_OF_MACRO(NUM_OF_MACRO)) neuron_block_inst (
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
    .wbs_we_i    (picture_done || (wbs_we_i & neuron_spike_out_select)),
    .wbs_sel_i   (picture_done ? 4'hF : wbs_sel_i),
    .wbs_adr_i   (wbs_adr_i),
    .wbs_dat_i   (spike_o_padded),
    .wbs_ack_o   (slave_ack_o[1]), 
    .wbs_dat_o   (slave_dat_o[1])
  );

  assign wbs_dat_o = synapse_matrix_select ? slave_dat_o[0] :
                     neuron_spike_out_select ? slave_dat_o[1] :
                     32'b0;
  assign wbs_ack_o = |slave_ack_o;


`ifdef GENERATE_VCD
  initial begin
    $dumpfile("waveform.vcd");
    $dumpvars(0, nvm_neuron_core_256x64);
  end
`endif

endmodule

// ── Memory layout and IP topology reference ──────────────────────────────────
// Indices are 0-based throughout.
// HARDWARE LIMITATION (OpenLane/Caravel): NUM_OF_MACRO=8 (reduced from 16).
// Neuron Core: 256 axons × 32 neurons per tile (8 macros × 4 neuron rows).
// Stores only synapses. Default weights are +1 / -1; default threshold = 0; no bias.
//
// Synapse Matrix is built from 8 Neuromorphic X1 32×32 IPs (NUM_OF_MACRO=8):
//   IP 0: stores synapses between every axon and neurons 0, 8, 16, 24
//         (first 8 rows → neuron 0; next 8 rows → neuron 8; etc.)
//   Single shared address 0x3000_000C; each read/write must carry data.
//   All 8 X1 IPs are accessed simultaneously, 1 bit each — the bit occupies
//   the same (row, col) position across all 8 IPs.
//
// Wishbone data packet format (same field layout for WRITE and READ):
//   WRITE    MODE   ROW    COL    UNUSED  DATA  (synapse bits, 1 bit per IP)
//   READ     MODE   ROW    COL    UNUSED  STIMULI
//   wbs_dat_i: [31:30][29:25][24:20][19:16][15:0]
//
// Example address mapping for IP 0:
//   Row  Col  Axon  Neuron
//   0    0    0     0
//   0    1    1     0
//   1    0    32    0
//   7    31   255   0
//   15   31   255   16
//   23   31   255   32
//   31   31   255   48
//
// picture_done: writes spike bits from Neuron Block into Neuron Spike-Out SRAM.
//   Address       Neurons
//   0x3000_2000   0–15
//   0x3000_2002   16–31
//   0x3000_2004   32–47
//   0x3000_2006   48–63
//
// Neuron Spike-Out: 64-bit register; read back via Wishbone:
//   Address       Neurons
//   0x3000_1000   0–31
//   0x3000_1004   32–63
