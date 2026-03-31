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
  
  parameter signed [15:0] THRESHOLD = 16'sd100;
  parameter signed [15:0] LEAK = 16'sd1;

  generate
    genvar i;
    for (i = 0; i < NUM_OF_MACRO; i=i+1) begin
      always @(posedge clk or posedge rst) begin
        if (rst) 
            potential[i] <= 16'b0;
        else if (picture_done) 
            potential[i] <= 16'b0;
        else if (enable) begin
            // 1. RESET TRIGGER: If it spiked last cycle, drop back to 0
            if (potential[i] >= THRESHOLD) begin
                potential[i] <= 16'b0; 
            end 
            // 2. INTEGRATE & LEAK: Add input, subtract leak
            else if (connection[i]) begin
                potential[i] <= potential[i] + stimuli - LEAK;
            end 
            // 3. JUST LEAK: No input, so decay towards zero
            else if (potential[i] > LEAK) begin
                potential[i] <= potential[i] - LEAK;
            end 
            // 4. CLAMP: Don't let it leak into negative numbers
            else if (potential[i] > 0) begin
                potential[i] <= 16'b0;
            end
        end
      end

      // The spike fires exactly when the threshold is crossed
      assign spike_o[i] = (potential[i] >= THRESHOLD); 
    end
  endgenerate

  // --- WAVEFORM RECORDING FOR COCOTB ---
  
  initial begin
      $dumpfile("waveform.vcd");
      $dumpvars(0, nvm_neuron_block);
  end
  

endmodule