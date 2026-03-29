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
  
  // --- NEW LIF PARAMETERS ---
  parameter signed [15:0] THRESHOLD = 16'sd100; // Configurable firing threshold
  parameter signed [15:0] LEAK = 16'sd1;        // Temporal decay 
  parameter signed [15:0] RESET_VAL = 16'sd0;   // Post-spike reset state

  reg signed [15:0] potential [NUM_OF_MACRO-1:0]; // tinh 4 neuron mot luc

  generate
    genvar i;
    for (i = 0; i < NUM_OF_MACRO; i=i+1) begin : neuron_array
      always @(posedge clk or posedge rst) begin
        if (rst) 
            potential[i] <= 16'sd0;
        else if (picture_done) 
            potential[i] <= 16'sd0;
        else if (enable) begin
            // 1. Spike-triggered reset: if it crossed threshold last cycle, reset it
            if (potential[i] >= THRESHOLD) begin
                potential[i] <= RESET_VAL;
            end else begin
                // 2. LIF Accumulation: Subtract leak, add stimulus if connected
                potential[i] <= potential[i] - LEAK + (connection[i] ? stimuli : 16'sd0);
            end
        end else begin
            potential[i] <= potential[i];
        end
      end

      // 3. Combinational spike generation based on configurable threshold
      assign spike_o[i] = (potential[i] >= THRESHOLD);
    end
  endgenerate
endmodule
