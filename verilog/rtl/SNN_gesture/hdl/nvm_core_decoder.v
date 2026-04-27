// -----------------------------------------------------------------------------
// nvm_core_decoder — Wishbone address decoder
//
// Routes the incoming address to one of three subsystems based on addr[15:12]:
//
//   addr[15:12]  Signal                   Address range
//   0            synapse_matrix_select    0x3000_0xxx  → ReRAM synapse matrix
//   1            neuron_spike_out_select  0x3000_1xxx  → Spike output SRAM (read)
//   2            picture_done             0x3000_2xxx  → Latch spikes, reset potentials
//
// All three outputs are mutually exclusive and combinatorial (no state).
// Only one is asserted per cycle; all others default to 0.
// -----------------------------------------------------------------------------
module nvm_core_decoder (
  input      [31:0] addr,
  output reg        synapse_matrix_select,
  output reg        neuron_spike_out_select,
  output reg        picture_done
  );

  always @(*) begin
    synapse_matrix_select = 0;
    neuron_spike_out_select = 0;
    picture_done = 0;

    case (addr[15:12])
      0: synapse_matrix_select = 1;
      1: neuron_spike_out_select = 1;
      2: picture_done = 1;
      default:;
    endcase
  end
endmodule