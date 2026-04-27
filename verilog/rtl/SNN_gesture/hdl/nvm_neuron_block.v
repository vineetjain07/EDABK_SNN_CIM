// -----------------------------------------------------------------------------
// nvm_neuron_block — 16-neuron LIF (Leaky Integrate-and-Fire) accumulator
//
// This module performs the integration of stimuli into neuron potentials.
// It implements a leaky integrate-and-fire model with the following features:
//   - Symmetric Leak: Rounding toward zero prevents negative bias.
//   - 17-bit Intermediate: Prevents wrap-around during accumulation.
//   - Saturation: Potentials are clamped to the 16-bit signed range (±32767).
//
// The 16 physical neurons are time-multiplexed to support 64 virtual neurons.
// -----------------------------------------------------------------------------

// module nvm_neuron_block(
//   input               clk,
//   input               rst,
//   input signed [15:0] stimuli,
//   input        [15:0] connection,
//   input               picture_done,
//   input               enable, // actually: ack from synapse matrix
//   output       [15:0] spike_o
//   );
// 
//   parameter NUM_OF_MACRO = 8;    // number of NVM Neuromorphic X1 macro, 32x32 each
//   reg signed [15:0] potential [NUM_OF_MACRO-1:0]; // tinh 16 neuron mot luc
// 
//   // --- LIF PARAMETERS ---
// `include "nvm_parameter.vh"
//   parameter signed [15:0] THRESHOLD = `NEURON_THRESHOLD;
//   parameter [15:0] LEAK_SHIFT = `NEURON_LEAK_SHIFT;
// 
//   
//   generate
//     genvar i;
//     for (i = 0; i < NUM_OF_MACRO; i=i+1) begin
//       always @(posedge clk or posedge rst) begin
//         if (rst) 
//             potential[i] <= 16'b0;
//         else if (picture_done) 
//             potential[i] <= 16'b0;
//         else if (enable & connection[i]) 
//             // Simple integration with a slow leak. No artificial gain needed.
//             potential[i] <= potential[i] - (potential[i] >>> LEAK_SHIFT) + stimuli;
//         else 
//             potential[i] <= potential[i];
//       end
// 
//       assign spike_o[i] = ($signed(potential[i]) >= THRESHOLD);
//     end
//   endgenerate
// endmodule

module nvm_neuron_block #(
  parameter NUM_OF_MACRO = 8    // must match nvm_parameter.vh `NUM_OF_MACRO
) (
  input               clk,
  input               rst,
  input signed [15:0] stimuli,
  input [NUM_OF_MACRO-1:0] connection,
  input               picture_done,
  input               enable,
  output [NUM_OF_MACRO-1:0] spike_o
  );
  reg signed [15:0] potential [NUM_OF_MACRO-1:0];

  // --- LIF PARAMETERS ---
`include "nvm_parameter.vh"
  parameter signed [15:0] THRESHOLD = `NEURON_THRESHOLD;
  parameter [15:0] LEAK_SHIFT = `NEURON_LEAK_SHIFT;

  // Saturation limits: full signed 16-bit range — allows negative intermediate potentials.
  // Inhibitory (odd-col) contributions must be able to drive potential negative so that
  // the net MAC result matches the SW batch computation (x_signed @ W_bin).
  // NEG_SAT = -32768 means the floor almost never triggers for typical inputs (scale=256,
  // 256 axons → max |potential| ≈ 16384 << 32768).
  localparam signed [15:0] POS_SAT    = 16'h7FFF; //  32767
  localparam signed [15:0] NEG_SAT    = 16'h8000; // -32768
  localparam signed [16:0] POS_SAT_17 = {1'b0, POS_SAT};
  localparam signed [16:0] NEG_SAT_17 = {1'b1, NEG_SAT};

  // 17-bit signed intermediate wires to hold the addition safely (no wrap-around)
  wire signed [16:0] next_potential [NUM_OF_MACRO-1:0];
  wire signed [15:0] leak          [NUM_OF_MACRO-1:0];
  wire signed [15:0] abs_pot       [NUM_OF_MACRO-1:0];
  wire signed [15:0] leak_mag      [NUM_OF_MACRO-1:0];

  generate
    genvar i;
    for (i = 0; i < NUM_OF_MACRO; i=i+1) begin

      // Round leak toward zero (not toward -inf as arithmetic shift does).
      // At LEAK_SHIFT=16 with 16-bit potential: pot>>>16 = 0 for pos, -1 for
      // negative pot, injecting a +1 bias per step.  Truncating via magnitude
      // keeps leak symmetric across signs and preserves batch-MAC equivalence.
      assign abs_pot[i]  = potential[i][15] ? -potential[i] : potential[i];
      assign leak_mag[i] = abs_pot[i] >>> LEAK_SHIFT;
      assign leak[i]     = potential[i][15] ? -leak_mag[i] : leak_mag[i];
      assign next_potential[i] = potential[i] - leak[i] + stimuli;

      always @(posedge clk or posedge rst) begin
        if (rst)
            potential[i] <= 16'b0;
        else if (picture_done)
            potential[i] <= 16'b0;
        else if (enable & connection[i]) begin
            // SATURATION LOGIC: clamp to full signed 16-bit range
            if (next_potential[i] > POS_SAT_17)
                potential[i] <= POS_SAT;
            else if (next_potential[i] < NEG_SAT_17)
                potential[i] <= NEG_SAT;
            else
                potential[i] <= next_potential[i][15:0]; // Safe to truncate
        end
        else
            potential[i] <= potential[i];
      end

      assign spike_o[i] = ($signed(potential[i]) >= THRESHOLD);
    end
  endgenerate
endmodule
