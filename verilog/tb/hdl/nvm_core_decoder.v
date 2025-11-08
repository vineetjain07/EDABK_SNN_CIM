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