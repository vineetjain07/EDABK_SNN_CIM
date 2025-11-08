`timescale 1ns / 1ps

module user_project_wrapper_tb();
  reg         wb_clk_i; 
  reg         wb_rst_i; 
  reg         wbs_stb_i;
  reg         wbs_cyc_i;
  reg         wbs_we_i; 
  reg  [3:0]  wbs_sel_i;
  reg  [31:0] wbs_dat_i;
  reg  [31:0] wbs_adr_i;
  wire [31:0] wbs_dat_o;
  wire        wbs_ack_o;

  parameter  [1:0] MODE_PROGRAM = 2'b11;
  parameter  [1:0] MODE_READ    = 2'b01;
  parameter  [7:0] MEM_HIGH     = 8'hFF;
  parameter  [7:0] MEM_LOW      = 8'h00;

  parameter        WR_Dly       = 200;  //Write delay (simulate ~1K cycles for real chip)
  parameter        RD_Dly       = 44;   //Clock cycles delay before read data becomes valid

  parameter        NUM_AXON     = 256;
  parameter        NUM_NEURON   = 64;

  function [3:0] reverse_bits;
    input [3:0] in;
    integer q;
    begin
      for (q = 0; q < 4; q = q + 1) begin
        reverse_bits[q] = in[3 - q];
      end
    end
  endfunction
  
  task wishbone_write;
    input [31:0] addr;
    input [31:0] data;
    begin
      @(posedge wb_clk_i) begin
        wbs_cyc_i <= 1'b1;
        wbs_stb_i <= 1'b1;
        wbs_we_i  <= 1'b1;
        wbs_sel_i <= 4'hF;
        wbs_adr_i <= addr;
        wbs_dat_i <= data;
      end
      @(posedge wb_clk_i) begin
        wbs_cyc_i <= 1'b0;
        wbs_stb_i <= 1'b0;
        wbs_we_i  <= 1'b0;
        wbs_sel_i <= 4'b0000;
      end
       // @(negedge wb_clk_i) if (!wbs_ack_o) $display("%t: Not receive writing command ack", $time);
    end
  endtask

  task nvm_write;
    input [31:0] addr;
    input [31:0] data;
    fork
      begin
        @(posedge wb_clk_i) begin
          wbs_cyc_i <= 1'b1;
          wbs_stb_i <= 1'b1;
          wbs_we_i  <= 1'b1;
          wbs_sel_i <= 4'hF;
          wbs_adr_i <= addr;
          wbs_dat_i <= data;
        end
        @(posedge wb_clk_i) begin
          wbs_cyc_i <= 1'b0;
          wbs_stb_i <= 1'b0;
          wbs_we_i  <= 1'b0;
          wbs_sel_i <= 4'b0000;
        end
         // @(negedge wb_clk_i) if (!wbs_ack_o) $display("%t: Not receive writing command ack", $time);
      end
      begin
        repeat (2*WR_Dly+1) begin
          @(posedge wb_clk_i);
        end
      end
    join
  endtask

  task wishbone_read;
    input [31:0] addr;
    begin
      @(posedge wb_clk_i) begin
        wbs_cyc_i <= 1'b1;
        wbs_stb_i <= 1'b1;
        wbs_we_i  <= 1'b0;
        wbs_sel_i <= 4'b1111;
        wbs_adr_i <= addr;
        wbs_dat_i <= 0;
      end
      @(posedge wb_clk_i) begin
        wbs_cyc_i <= 1'b0;
        wbs_stb_i <= 1'b0;
        wbs_sel_i <= 4'b0000;
      end
      @(negedge wb_clk_i) $display("%t: Read at addr %h: value = %b", $time, addr, wbs_dat_o);
    end
  endtask

  task nvm_read;
    input [31:0] addr;
    input [31:0] data;
    fork
      begin
        @(posedge wb_clk_i) begin
          wbs_cyc_i <= 1'b1;
          wbs_stb_i <= 1'b1;
          wbs_we_i  <= 1'b1;
          wbs_sel_i <= 4'hF;
          wbs_adr_i <= addr;
          wbs_dat_i <= data;
        end
        @(posedge wb_clk_i) begin
          wbs_cyc_i <= 1'b0;
          wbs_stb_i <= 1'b0;
          wbs_we_i  <= 1'b0;
          wbs_sel_i <= 4'b0000;
        end
         // @(negedge wb_clk_i) if (!wbs_ack_o) $display("%t: Not receive read command ack", $time);
      end
      begin
        repeat (RD_Dly+2) begin
           @(posedge wb_clk_i);
        end
        @(posedge wb_clk_i) begin
          wbs_cyc_i <= 1'b1;
          wbs_stb_i <= 1'b1;
          wbs_we_i  <= 1'b0;
          wbs_sel_i <= 4'hF;
          wbs_adr_i <= addr;
        end
        @(posedge wb_clk_i) begin
          wbs_cyc_i <= 1'b0;
          wbs_stb_i <= 1'b0;
          wbs_sel_i <= 4'b0000;
        end
        // @(negedge wb_clk_i) $display("%t: Read value = %b", $time, wbs_dat_o);
      end
    join
  endtask

  user_project_wrapper DUT (
    .wb_clk_i (wb_clk_i),
    .wb_rst_i (wb_rst_i),
    .wbs_stb_i(wbs_stb_i),
    .wbs_cyc_i(wbs_cyc_i),
    .wbs_we_i (wbs_we_i),
    .wbs_sel_i(wbs_sel_i),
    .wbs_dat_i(wbs_dat_i),
    .wbs_adr_i(wbs_adr_i),
    .wbs_dat_o(wbs_dat_o),
    .wbs_ack_o(wbs_ack_o)
  );

  initial begin
    wb_clk_i = 0;
    wb_rst_i = 1;
    wbs_stb_i = 0;
    wbs_cyc_i = 0;
    wbs_we_i = 0;
    wbs_sel_i = 0;
    wbs_dat_i = 0;
    wbs_adr_i = 0;
  end
  always #0.5 wb_clk_i = ~wb_clk_i;

  reg [NUM_NEURON-1:0] connection [0:NUM_AXON-1];
  initial $readmemb("./mem/connection/connection_000.txt",connection);

  reg [31:0] stimuli [0:NUM_AXON/2-1];
  initial $readmemb("./mem/stimuli/stimuli.txt", stimuli);

  integer row_i,col_i, phase_i;
  reg [4:0] row;
  reg [4:0] col; 
  reg [1:0] phase; // phase 0 (axon 0-63), phase 1 (axon 64-127), phase 2 (axon 128-191), phase 3 (axon 192-255),
  reg [7:0] axon;  // 0 to 255
  reg [5:0] neuron;// 0 to 63

  initial begin
    #2 wb_rst_i=0;

    for (phase_i = 0; phase_i < 4; phase_i = phase_i + 1) begin
      // SYNAP MATRIX
      for (row_i = 0; row_i < 32; row_i = row_i + 1) begin 
        for (col_i = 0; col_i < 32; col_i = col_i + 1) begin
          row = row_i;
          col = col_i;
          phase = phase_i;
          axon = phase * 64 + row[0] * 32 + col;
          neuron = row[4:1] * 4;
          nvm_write(32'h3000_0000,{MODE_PROGRAM,
            row,
            col,
            16'b0,
            reverse_bits(connection[axon][63-neuron-:4])});
        end
      end

      // SEND INPUT STIMULI
      for (row_i = 0; row_i < 32; row_i = row_i + 1) begin
        for (col_i = 0; col_i < 32; col_i = col_i + 1) begin
          row = row_i;
          col = col_i;
          phase = phase_i;
          axon = phase * 64 + row[0] * 32 + col;
          neuron = row[4:1] * 4;
          nvm_read(32'h3000_0000,{MODE_READ,
            row,
            col,
            4'b0,
            stimuli[axon/2][31-16*(axon%2)-:16]});

          // DONE PIC
          if (col==31) begin
            if (row[0]) wishbone_write ({28'h3000_200,row[4:1]},32'h0);
          end
        end
      end
      // READ SPIKE-OUT
      wishbone_read(32'h3000_1000);
      wishbone_read(32'h3000_1008);
    end

    #20 $display("Test Completed."); 
    $stop;
  end

  // initial begin
  //   #4 wb_rst_i=0;

  //   // Load synapse matrix
  //   #2 nvm_write(32'h3000_0000,{MODE_PROGRAM,5'd1,5'd0,4'b0,16'h0F0F});
  //   // #2 nvm_write(32'h3000_0000,{MODE_PROGRAM,5'd0,5'd1,4'b0,16'h0F0F});

  //   // Send input stimuli
  //   #2 nvm_read (32'h3000_0000,{MODE_READ,   5'd1,5'd0,4'b0,16'h1111});
  //   // #2 nvm_read (32'h3000_0000,{MODE_READ,   5'd0,5'd1,4'b0,16'hAAAA});

  //   // Done pic
  //   // #2 wishbone_write (32'h3000_2000,32'h0);

  //   // Read spike-out
  //   // #2 
  //   // wishbone_read  (32'h3000_1000);
  //   // wishbone_read  (32'h3000_1004);

  //   #20 $display("Test Completed."); 
  //   $stop;
  // end

endmodule

