module nvm_neuron_block(
  input               clk,
  input               rst,
  input signed [15:0] stimuli,
  input         [3:0] connection,
  input               picture_done,
  input               enable, // actually: ack from synapse matrix
  output        [3:0] spike_o
  );

  parameter NUM_OF_MACRO = 4;   // number of NVM Neuromorphic X1 macro, 32x32 each
  reg signed [15:0] potential [NUM_OF_MACRO-1:0]; // tinh 4 neuron mot luc

  generate
    genvar i;
    for (i = 0; i < NUM_OF_MACRO; i=i+1) begin
      always @(posedge clk or posedge rst) begin
        if (rst) potential[i] <= 16'b0;
        else if (picture_done) potential[i] <= 16'b0;
        else if (enable & connection[i]) potential[i] <= potential[i] + stimuli;
        else potential[i] <= potential[i];
      end

      assign spike_o[i] = ~potential[i][15]; // so sanh voi threshold=0;
    end
  endgenerate
endmodule