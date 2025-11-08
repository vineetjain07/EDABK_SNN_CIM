module user_project_wrapper (user_clock2,
    wb_clk_i,
    wb_rst_i,
    wbs_ack_o,
    wbs_cyc_i,
    wbs_stb_i,
    wbs_we_i,
    vssa2,
    vdda2,
    vssa1,
    vdda1,
    vssd2,
    vccd2,
    vssd1,
    vccd1,
    analog_io,
    io_in,
    io_oeb,
    io_out,
    la_data_in,
    la_data_out,
    la_oenb,
    user_irq,
    wbs_adr_i,
    wbs_dat_i,
    wbs_dat_o,
    wbs_sel_i);
 input user_clock2;
 input wb_clk_i;
 input wb_rst_i;
 output wbs_ack_o;
 input wbs_cyc_i;
 input wbs_stb_i;
 input wbs_we_i;
 inout vssa2;
 inout vdda2;
 inout vssa1;
 inout vdda1;
 inout vssd2;
 inout vccd2;
 inout vssd1;
 inout vccd1;
 inout [28:0] analog_io;
 input [37:0] io_in;
 output [37:0] io_oeb;
 output [37:0] io_out;
 input [127:0] la_data_in;
 output [127:0] la_data_out;
 input [127:0] la_oenb;
 output [2:0] user_irq;
 input [31:0] wbs_adr_i;
 input [31:0] wbs_dat_i;
 output [31:0] wbs_dat_o;
 input [3:0] wbs_sel_i;

 wire \slave_0_dat_i[0] ;
 wire \slave_0_dat_i[10] ;
 wire \slave_0_dat_i[11] ;
 wire \slave_0_dat_i[12] ;
 wire \slave_0_dat_i[13] ;
 wire \slave_0_dat_i[14] ;
 wire \slave_0_dat_i[15] ;
 wire \slave_0_dat_i[16] ;
 wire \slave_0_dat_i[17] ;
 wire \slave_0_dat_i[18] ;
 wire \slave_0_dat_i[19] ;
 wire \slave_0_dat_i[1] ;
 wire \slave_0_dat_i[20] ;
 wire \slave_0_dat_i[21] ;
 wire \slave_0_dat_i[22] ;
 wire \slave_0_dat_i[23] ;
 wire \slave_0_dat_i[24] ;
 wire \slave_0_dat_i[25] ;
 wire \slave_0_dat_i[26] ;
 wire \slave_0_dat_i[27] ;
 wire \slave_0_dat_i[28] ;
 wire \slave_0_dat_i[29] ;
 wire \slave_0_dat_i[2] ;
 wire \slave_0_dat_i[30] ;
 wire \slave_0_dat_i[31] ;
 wire \slave_0_dat_i[3] ;
 wire \slave_0_dat_i[4] ;
 wire \slave_0_dat_i[5] ;
 wire \slave_0_dat_i[6] ;
 wire \slave_0_dat_i[7] ;
 wire \slave_0_dat_i[8] ;
 wire \slave_0_dat_i[9] ;
 wire \slave_0_dat_o[0] ;
 wire \slave_0_dat_o[10] ;
 wire \slave_0_dat_o[11] ;
 wire \slave_0_dat_o[12] ;
 wire \slave_0_dat_o[13] ;
 wire \slave_0_dat_o[14] ;
 wire \slave_0_dat_o[15] ;
 wire \slave_0_dat_o[16] ;
 wire \slave_0_dat_o[17] ;
 wire \slave_0_dat_o[18] ;
 wire \slave_0_dat_o[19] ;
 wire \slave_0_dat_o[1] ;
 wire \slave_0_dat_o[20] ;
 wire \slave_0_dat_o[21] ;
 wire \slave_0_dat_o[22] ;
 wire \slave_0_dat_o[23] ;
 wire \slave_0_dat_o[24] ;
 wire \slave_0_dat_o[25] ;
 wire \slave_0_dat_o[26] ;
 wire \slave_0_dat_o[27] ;
 wire \slave_0_dat_o[28] ;
 wire \slave_0_dat_o[29] ;
 wire \slave_0_dat_o[2] ;
 wire \slave_0_dat_o[30] ;
 wire \slave_0_dat_o[31] ;
 wire \slave_0_dat_o[3] ;
 wire \slave_0_dat_o[4] ;
 wire \slave_0_dat_o[5] ;
 wire \slave_0_dat_o[6] ;
 wire \slave_0_dat_o[7] ;
 wire \slave_0_dat_o[8] ;
 wire \slave_0_dat_o[9] ;
 wire \slave_1_dat_i[0] ;
 wire \slave_1_dat_i[10] ;
 wire \slave_1_dat_i[11] ;
 wire \slave_1_dat_i[12] ;
 wire \slave_1_dat_i[13] ;
 wire \slave_1_dat_i[14] ;
 wire \slave_1_dat_i[15] ;
 wire \slave_1_dat_i[16] ;
 wire \slave_1_dat_i[17] ;
 wire \slave_1_dat_i[18] ;
 wire \slave_1_dat_i[19] ;
 wire \slave_1_dat_i[1] ;
 wire \slave_1_dat_i[20] ;
 wire \slave_1_dat_i[21] ;
 wire \slave_1_dat_i[22] ;
 wire \slave_1_dat_i[23] ;
 wire \slave_1_dat_i[24] ;
 wire \slave_1_dat_i[25] ;
 wire \slave_1_dat_i[26] ;
 wire \slave_1_dat_i[27] ;
 wire \slave_1_dat_i[28] ;
 wire \slave_1_dat_i[29] ;
 wire \slave_1_dat_i[2] ;
 wire \slave_1_dat_i[30] ;
 wire \slave_1_dat_i[31] ;
 wire \slave_1_dat_i[3] ;
 wire \slave_1_dat_i[4] ;
 wire \slave_1_dat_i[5] ;
 wire \slave_1_dat_i[6] ;
 wire \slave_1_dat_i[7] ;
 wire \slave_1_dat_i[8] ;
 wire \slave_1_dat_i[9] ;
 wire \slave_1_dat_o[0] ;
 wire \slave_1_dat_o[10] ;
 wire \slave_1_dat_o[11] ;
 wire \slave_1_dat_o[12] ;
 wire \slave_1_dat_o[13] ;
 wire \slave_1_dat_o[14] ;
 wire \slave_1_dat_o[15] ;
 wire \slave_1_dat_o[16] ;
 wire \slave_1_dat_o[17] ;
 wire \slave_1_dat_o[18] ;
 wire \slave_1_dat_o[19] ;
 wire \slave_1_dat_o[1] ;
 wire \slave_1_dat_o[20] ;
 wire \slave_1_dat_o[21] ;
 wire \slave_1_dat_o[22] ;
 wire \slave_1_dat_o[23] ;
 wire \slave_1_dat_o[24] ;
 wire \slave_1_dat_o[25] ;
 wire \slave_1_dat_o[26] ;
 wire \slave_1_dat_o[27] ;
 wire \slave_1_dat_o[28] ;
 wire \slave_1_dat_o[29] ;
 wire \slave_1_dat_o[2] ;
 wire \slave_1_dat_o[30] ;
 wire \slave_1_dat_o[31] ;
 wire \slave_1_dat_o[3] ;
 wire \slave_1_dat_o[4] ;
 wire \slave_1_dat_o[5] ;
 wire \slave_1_dat_o[6] ;
 wire \slave_1_dat_o[7] ;
 wire \slave_1_dat_o[8] ;
 wire \slave_1_dat_o[9] ;
 wire \slave_2_dat_i[0] ;
 wire \slave_2_dat_i[10] ;
 wire \slave_2_dat_i[11] ;
 wire \slave_2_dat_i[12] ;
 wire \slave_2_dat_i[13] ;
 wire \slave_2_dat_i[14] ;
 wire \slave_2_dat_i[15] ;
 wire \slave_2_dat_i[16] ;
 wire \slave_2_dat_i[17] ;
 wire \slave_2_dat_i[18] ;
 wire \slave_2_dat_i[19] ;
 wire \slave_2_dat_i[1] ;
 wire \slave_2_dat_i[20] ;
 wire \slave_2_dat_i[21] ;
 wire \slave_2_dat_i[22] ;
 wire \slave_2_dat_i[23] ;
 wire \slave_2_dat_i[24] ;
 wire \slave_2_dat_i[25] ;
 wire \slave_2_dat_i[26] ;
 wire \slave_2_dat_i[27] ;
 wire \slave_2_dat_i[28] ;
 wire \slave_2_dat_i[29] ;
 wire \slave_2_dat_i[2] ;
 wire \slave_2_dat_i[30] ;
 wire \slave_2_dat_i[31] ;
 wire \slave_2_dat_i[3] ;
 wire \slave_2_dat_i[4] ;
 wire \slave_2_dat_i[5] ;
 wire \slave_2_dat_i[6] ;
 wire \slave_2_dat_i[7] ;
 wire \slave_2_dat_i[8] ;
 wire \slave_2_dat_i[9] ;
 wire \slave_2_dat_o[0] ;
 wire \slave_2_dat_o[10] ;
 wire \slave_2_dat_o[11] ;
 wire \slave_2_dat_o[12] ;
 wire \slave_2_dat_o[13] ;
 wire \slave_2_dat_o[14] ;
 wire \slave_2_dat_o[15] ;
 wire \slave_2_dat_o[16] ;
 wire \slave_2_dat_o[17] ;
 wire \slave_2_dat_o[18] ;
 wire \slave_2_dat_o[19] ;
 wire \slave_2_dat_o[1] ;
 wire \slave_2_dat_o[20] ;
 wire \slave_2_dat_o[21] ;
 wire \slave_2_dat_o[22] ;
 wire \slave_2_dat_o[23] ;
 wire \slave_2_dat_o[24] ;
 wire \slave_2_dat_o[25] ;
 wire \slave_2_dat_o[26] ;
 wire \slave_2_dat_o[27] ;
 wire \slave_2_dat_o[28] ;
 wire \slave_2_dat_o[29] ;
 wire \slave_2_dat_o[2] ;
 wire \slave_2_dat_o[30] ;
 wire \slave_2_dat_o[31] ;
 wire \slave_2_dat_o[3] ;
 wire \slave_2_dat_o[4] ;
 wire \slave_2_dat_o[5] ;
 wire \slave_2_dat_o[6] ;
 wire \slave_2_dat_o[7] ;
 wire \slave_2_dat_o[8] ;
 wire \slave_2_dat_o[9] ;
 wire \slave_3_dat_i[0] ;
 wire \slave_3_dat_i[10] ;
 wire \slave_3_dat_i[11] ;
 wire \slave_3_dat_i[12] ;
 wire \slave_3_dat_i[13] ;
 wire \slave_3_dat_i[14] ;
 wire \slave_3_dat_i[15] ;
 wire \slave_3_dat_i[16] ;
 wire \slave_3_dat_i[17] ;
 wire \slave_3_dat_i[18] ;
 wire \slave_3_dat_i[19] ;
 wire \slave_3_dat_i[1] ;
 wire \slave_3_dat_i[20] ;
 wire \slave_3_dat_i[21] ;
 wire \slave_3_dat_i[22] ;
 wire \slave_3_dat_i[23] ;
 wire \slave_3_dat_i[24] ;
 wire \slave_3_dat_i[25] ;
 wire \slave_3_dat_i[26] ;
 wire \slave_3_dat_i[27] ;
 wire \slave_3_dat_i[28] ;
 wire \slave_3_dat_i[29] ;
 wire \slave_3_dat_i[2] ;
 wire \slave_3_dat_i[30] ;
 wire \slave_3_dat_i[31] ;
 wire \slave_3_dat_i[3] ;
 wire \slave_3_dat_i[4] ;
 wire \slave_3_dat_i[5] ;
 wire \slave_3_dat_i[6] ;
 wire \slave_3_dat_i[7] ;
 wire \slave_3_dat_i[8] ;
 wire \slave_3_dat_i[9] ;
 wire \slave_3_dat_o[0] ;
 wire \slave_3_dat_o[10] ;
 wire \slave_3_dat_o[11] ;
 wire \slave_3_dat_o[12] ;
 wire \slave_3_dat_o[13] ;
 wire \slave_3_dat_o[14] ;
 wire \slave_3_dat_o[15] ;
 wire \slave_3_dat_o[16] ;
 wire \slave_3_dat_o[17] ;
 wire \slave_3_dat_o[18] ;
 wire \slave_3_dat_o[19] ;
 wire \slave_3_dat_o[1] ;
 wire \slave_3_dat_o[20] ;
 wire \slave_3_dat_o[21] ;
 wire \slave_3_dat_o[22] ;
 wire \slave_3_dat_o[23] ;
 wire \slave_3_dat_o[24] ;
 wire \slave_3_dat_o[25] ;
 wire \slave_3_dat_o[26] ;
 wire \slave_3_dat_o[27] ;
 wire \slave_3_dat_o[28] ;
 wire \slave_3_dat_o[29] ;
 wire \slave_3_dat_o[2] ;
 wire \slave_3_dat_o[30] ;
 wire \slave_3_dat_o[31] ;
 wire \slave_3_dat_o[3] ;
 wire \slave_3_dat_o[4] ;
 wire \slave_3_dat_o[5] ;
 wire \slave_3_dat_o[6] ;
 wire \slave_3_dat_o[7] ;
 wire \slave_3_dat_o[8] ;
 wire \slave_3_dat_o[9] ;
 wire \slave_ack_i[0] ;
 wire \slave_ack_i[1] ;
 wire \slave_ack_i[2] ;
 wire \slave_ack_i[3] ;
 wire slave_cyc_o;
 wire slave_stb_o;
 wire slave_we_o;

 neuron_core core (.VGND(vssd1),
    .VPWR(vccd1),
    .slave_cyc_o(slave_cyc_o),
    .slave_stb_o(slave_stb_o),
    .slave_we_o(slave_we_o),
    .wb_clk_i(wb_clk_i),
    .wb_rst_i(wb_rst_i),
    .wbs_ack_o(wbs_ack_o),
    .wbs_cyc_i(wbs_cyc_i),
    .wbs_stb_i(wbs_stb_i),
    .wbs_we_i(wbs_we_i),
    .slave_0_dat_i({\slave_0_dat_i[31] ,
    \slave_0_dat_i[30] ,
    \slave_0_dat_i[29] ,
    \slave_0_dat_i[28] ,
    \slave_0_dat_i[27] ,
    \slave_0_dat_i[26] ,
    \slave_0_dat_i[25] ,
    \slave_0_dat_i[24] ,
    \slave_0_dat_i[23] ,
    \slave_0_dat_i[22] ,
    \slave_0_dat_i[21] ,
    \slave_0_dat_i[20] ,
    \slave_0_dat_i[19] ,
    \slave_0_dat_i[18] ,
    \slave_0_dat_i[17] ,
    \slave_0_dat_i[16] ,
    \slave_0_dat_i[15] ,
    \slave_0_dat_i[14] ,
    \slave_0_dat_i[13] ,
    \slave_0_dat_i[12] ,
    \slave_0_dat_i[11] ,
    \slave_0_dat_i[10] ,
    \slave_0_dat_i[9] ,
    \slave_0_dat_i[8] ,
    \slave_0_dat_i[7] ,
    \slave_0_dat_i[6] ,
    \slave_0_dat_i[5] ,
    \slave_0_dat_i[4] ,
    \slave_0_dat_i[3] ,
    \slave_0_dat_i[2] ,
    \slave_0_dat_i[1] ,
    \slave_0_dat_i[0] }),
    .slave_0_dat_o({\slave_0_dat_o[31] ,
    \slave_0_dat_o[30] ,
    \slave_0_dat_o[29] ,
    \slave_0_dat_o[28] ,
    \slave_0_dat_o[27] ,
    \slave_0_dat_o[26] ,
    \slave_0_dat_o[25] ,
    \slave_0_dat_o[24] ,
    \slave_0_dat_o[23] ,
    \slave_0_dat_o[22] ,
    \slave_0_dat_o[21] ,
    \slave_0_dat_o[20] ,
    \slave_0_dat_o[19] ,
    \slave_0_dat_o[18] ,
    \slave_0_dat_o[17] ,
    \slave_0_dat_o[16] ,
    \slave_0_dat_o[15] ,
    \slave_0_dat_o[14] ,
    \slave_0_dat_o[13] ,
    \slave_0_dat_o[12] ,
    \slave_0_dat_o[11] ,
    \slave_0_dat_o[10] ,
    \slave_0_dat_o[9] ,
    \slave_0_dat_o[8] ,
    \slave_0_dat_o[7] ,
    \slave_0_dat_o[6] ,
    \slave_0_dat_o[5] ,
    \slave_0_dat_o[4] ,
    \slave_0_dat_o[3] ,
    \slave_0_dat_o[2] ,
    \slave_0_dat_o[1] ,
    \slave_0_dat_o[0] }),
    .slave_1_dat_i({\slave_1_dat_i[31] ,
    \slave_1_dat_i[30] ,
    \slave_1_dat_i[29] ,
    \slave_1_dat_i[28] ,
    \slave_1_dat_i[27] ,
    \slave_1_dat_i[26] ,
    \slave_1_dat_i[25] ,
    \slave_1_dat_i[24] ,
    \slave_1_dat_i[23] ,
    \slave_1_dat_i[22] ,
    \slave_1_dat_i[21] ,
    \slave_1_dat_i[20] ,
    \slave_1_dat_i[19] ,
    \slave_1_dat_i[18] ,
    \slave_1_dat_i[17] ,
    \slave_1_dat_i[16] ,
    \slave_1_dat_i[15] ,
    \slave_1_dat_i[14] ,
    \slave_1_dat_i[13] ,
    \slave_1_dat_i[12] ,
    \slave_1_dat_i[11] ,
    \slave_1_dat_i[10] ,
    \slave_1_dat_i[9] ,
    \slave_1_dat_i[8] ,
    \slave_1_dat_i[7] ,
    \slave_1_dat_i[6] ,
    \slave_1_dat_i[5] ,
    \slave_1_dat_i[4] ,
    \slave_1_dat_i[3] ,
    \slave_1_dat_i[2] ,
    \slave_1_dat_i[1] ,
    \slave_1_dat_i[0] }),
    .slave_1_dat_o({\slave_1_dat_o[31] ,
    \slave_1_dat_o[30] ,
    \slave_1_dat_o[29] ,
    \slave_1_dat_o[28] ,
    \slave_1_dat_o[27] ,
    \slave_1_dat_o[26] ,
    \slave_1_dat_o[25] ,
    \slave_1_dat_o[24] ,
    \slave_1_dat_o[23] ,
    \slave_1_dat_o[22] ,
    \slave_1_dat_o[21] ,
    \slave_1_dat_o[20] ,
    \slave_1_dat_o[19] ,
    \slave_1_dat_o[18] ,
    \slave_1_dat_o[17] ,
    \slave_1_dat_o[16] ,
    \slave_1_dat_o[15] ,
    \slave_1_dat_o[14] ,
    \slave_1_dat_o[13] ,
    \slave_1_dat_o[12] ,
    \slave_1_dat_o[11] ,
    \slave_1_dat_o[10] ,
    \slave_1_dat_o[9] ,
    \slave_1_dat_o[8] ,
    \slave_1_dat_o[7] ,
    \slave_1_dat_o[6] ,
    \slave_1_dat_o[5] ,
    \slave_1_dat_o[4] ,
    \slave_1_dat_o[3] ,
    \slave_1_dat_o[2] ,
    \slave_1_dat_o[1] ,
    \slave_1_dat_o[0] }),
    .slave_2_dat_i({\slave_2_dat_i[31] ,
    \slave_2_dat_i[30] ,
    \slave_2_dat_i[29] ,
    \slave_2_dat_i[28] ,
    \slave_2_dat_i[27] ,
    \slave_2_dat_i[26] ,
    \slave_2_dat_i[25] ,
    \slave_2_dat_i[24] ,
    \slave_2_dat_i[23] ,
    \slave_2_dat_i[22] ,
    \slave_2_dat_i[21] ,
    \slave_2_dat_i[20] ,
    \slave_2_dat_i[19] ,
    \slave_2_dat_i[18] ,
    \slave_2_dat_i[17] ,
    \slave_2_dat_i[16] ,
    \slave_2_dat_i[15] ,
    \slave_2_dat_i[14] ,
    \slave_2_dat_i[13] ,
    \slave_2_dat_i[12] ,
    \slave_2_dat_i[11] ,
    \slave_2_dat_i[10] ,
    \slave_2_dat_i[9] ,
    \slave_2_dat_i[8] ,
    \slave_2_dat_i[7] ,
    \slave_2_dat_i[6] ,
    \slave_2_dat_i[5] ,
    \slave_2_dat_i[4] ,
    \slave_2_dat_i[3] ,
    \slave_2_dat_i[2] ,
    \slave_2_dat_i[1] ,
    \slave_2_dat_i[0] }),
    .slave_2_dat_o({\slave_2_dat_o[31] ,
    \slave_2_dat_o[30] ,
    \slave_2_dat_o[29] ,
    \slave_2_dat_o[28] ,
    \slave_2_dat_o[27] ,
    \slave_2_dat_o[26] ,
    \slave_2_dat_o[25] ,
    \slave_2_dat_o[24] ,
    \slave_2_dat_o[23] ,
    \slave_2_dat_o[22] ,
    \slave_2_dat_o[21] ,
    \slave_2_dat_o[20] ,
    \slave_2_dat_o[19] ,
    \slave_2_dat_o[18] ,
    \slave_2_dat_o[17] ,
    \slave_2_dat_o[16] ,
    \slave_2_dat_o[15] ,
    \slave_2_dat_o[14] ,
    \slave_2_dat_o[13] ,
    \slave_2_dat_o[12] ,
    \slave_2_dat_o[11] ,
    \slave_2_dat_o[10] ,
    \slave_2_dat_o[9] ,
    \slave_2_dat_o[8] ,
    \slave_2_dat_o[7] ,
    \slave_2_dat_o[6] ,
    \slave_2_dat_o[5] ,
    \slave_2_dat_o[4] ,
    \slave_2_dat_o[3] ,
    \slave_2_dat_o[2] ,
    \slave_2_dat_o[1] ,
    \slave_2_dat_o[0] }),
    .slave_3_dat_i({\slave_3_dat_i[31] ,
    \slave_3_dat_i[30] ,
    \slave_3_dat_i[29] ,
    \slave_3_dat_i[28] ,
    \slave_3_dat_i[27] ,
    \slave_3_dat_i[26] ,
    \slave_3_dat_i[25] ,
    \slave_3_dat_i[24] ,
    \slave_3_dat_i[23] ,
    \slave_3_dat_i[22] ,
    \slave_3_dat_i[21] ,
    \slave_3_dat_i[20] ,
    \slave_3_dat_i[19] ,
    \slave_3_dat_i[18] ,
    \slave_3_dat_i[17] ,
    \slave_3_dat_i[16] ,
    \slave_3_dat_i[15] ,
    \slave_3_dat_i[14] ,
    \slave_3_dat_i[13] ,
    \slave_3_dat_i[12] ,
    \slave_3_dat_i[11] ,
    \slave_3_dat_i[10] ,
    \slave_3_dat_i[9] ,
    \slave_3_dat_i[8] ,
    \slave_3_dat_i[7] ,
    \slave_3_dat_i[6] ,
    \slave_3_dat_i[5] ,
    \slave_3_dat_i[4] ,
    \slave_3_dat_i[3] ,
    \slave_3_dat_i[2] ,
    \slave_3_dat_i[1] ,
    \slave_3_dat_i[0] }),
    .slave_3_dat_o({\slave_3_dat_o[31] ,
    \slave_3_dat_o[30] ,
    \slave_3_dat_o[29] ,
    \slave_3_dat_o[28] ,
    \slave_3_dat_o[27] ,
    \slave_3_dat_o[26] ,
    \slave_3_dat_o[25] ,
    \slave_3_dat_o[24] ,
    \slave_3_dat_o[23] ,
    \slave_3_dat_o[22] ,
    \slave_3_dat_o[21] ,
    \slave_3_dat_o[20] ,
    \slave_3_dat_o[19] ,
    \slave_3_dat_o[18] ,
    \slave_3_dat_o[17] ,
    \slave_3_dat_o[16] ,
    \slave_3_dat_o[15] ,
    \slave_3_dat_o[14] ,
    \slave_3_dat_o[13] ,
    \slave_3_dat_o[12] ,
    \slave_3_dat_o[11] ,
    \slave_3_dat_o[10] ,
    \slave_3_dat_o[9] ,
    \slave_3_dat_o[8] ,
    \slave_3_dat_o[7] ,
    \slave_3_dat_o[6] ,
    \slave_3_dat_o[5] ,
    \slave_3_dat_o[4] ,
    \slave_3_dat_o[3] ,
    \slave_3_dat_o[2] ,
    \slave_3_dat_o[1] ,
    \slave_3_dat_o[0] }),
    .slave_ack_i({\slave_ack_i[3] ,
    \slave_ack_i[2] ,
    \slave_ack_i[1] ,
    \slave_ack_i[0] }),
    .wbs_adr_i({wbs_adr_i[31],
    wbs_adr_i[30],
    wbs_adr_i[29],
    wbs_adr_i[28],
    wbs_adr_i[27],
    wbs_adr_i[26],
    wbs_adr_i[25],
    wbs_adr_i[24],
    wbs_adr_i[23],
    wbs_adr_i[22],
    wbs_adr_i[21],
    wbs_adr_i[20],
    wbs_adr_i[19],
    wbs_adr_i[18],
    wbs_adr_i[17],
    wbs_adr_i[16],
    wbs_adr_i[15],
    wbs_adr_i[14],
    wbs_adr_i[13],
    wbs_adr_i[12],
    wbs_adr_i[11],
    wbs_adr_i[10],
    wbs_adr_i[9],
    wbs_adr_i[8],
    wbs_adr_i[7],
    wbs_adr_i[6],
    wbs_adr_i[5],
    wbs_adr_i[4],
    wbs_adr_i[3],
    wbs_adr_i[2],
    wbs_adr_i[1],
    wbs_adr_i[0]}),
    .wbs_dat_i({wbs_dat_i[31],
    wbs_dat_i[30],
    wbs_dat_i[29],
    wbs_dat_i[28],
    wbs_dat_i[27],
    wbs_dat_i[26],
    wbs_dat_i[25],
    wbs_dat_i[24],
    wbs_dat_i[23],
    wbs_dat_i[22],
    wbs_dat_i[21],
    wbs_dat_i[20],
    wbs_dat_i[19],
    wbs_dat_i[18],
    wbs_dat_i[17],
    wbs_dat_i[16],
    wbs_dat_i[15],
    wbs_dat_i[14],
    wbs_dat_i[13],
    wbs_dat_i[12],
    wbs_dat_i[11],
    wbs_dat_i[10],
    wbs_dat_i[9],
    wbs_dat_i[8],
    wbs_dat_i[7],
    wbs_dat_i[6],
    wbs_dat_i[5],
    wbs_dat_i[4],
    wbs_dat_i[3],
    wbs_dat_i[2],
    wbs_dat_i[1],
    wbs_dat_i[0]}),
    .wbs_dat_o({wbs_dat_o[31],
    wbs_dat_o[30],
    wbs_dat_o[29],
    wbs_dat_o[28],
    wbs_dat_o[27],
    wbs_dat_o[26],
    wbs_dat_o[25],
    wbs_dat_o[24],
    wbs_dat_o[23],
    wbs_dat_o[22],
    wbs_dat_o[21],
    wbs_dat_o[20],
    wbs_dat_o[19],
    wbs_dat_o[18],
    wbs_dat_o[17],
    wbs_dat_o[16],
    wbs_dat_o[15],
    wbs_dat_o[14],
    wbs_dat_o[13],
    wbs_dat_o[12],
    wbs_dat_o[11],
    wbs_dat_o[10],
    wbs_dat_o[9],
    wbs_dat_o[8],
    wbs_dat_o[7],
    wbs_dat_o[6],
    wbs_dat_o[5],
    wbs_dat_o[4],
    wbs_dat_o[3],
    wbs_dat_o[2],
    wbs_dat_o[1],
    wbs_dat_o[0]}),
    .wbs_sel_i({wbs_sel_i[3],
    wbs_sel_i[2],
    wbs_sel_i[1],
    wbs_sel_i[0]}));
 Neuromorphic_X1_wb mprj (.wbs_we_i(slave_we_o),
    .user_clk(wb_clk_i),
    .wbs_ack_o(\slave_ack_i[0] ),
    .user_rst(wb_rst_i),
    .wb_rst_i(wb_rst_i),
    .wb_clk_i(wb_clk_i),
    .TM(io_in[5]),
    .wbs_stb_i(slave_stb_o),
    .ScanInCC(io_in[4]),
    .ScanInDL(io_in[1]),
    .ScanInDR(io_in[2]),
    .ScanOutCC(io_out[0]),
    .Iref(analog_io[0]),
    .Vbias(analog_io[6]),
    .Vcomp(analog_io[2]),
    .Bias_comp2(analog_io[3]),
    .Vcc_L(analog_io[10]),
    .Vcc_Body(analog_io[11]),
    .Vcc_reset(analog_io[9]),
    .Vcc_set(analog_io[8]),
    .Vcc_wl_reset(analog_io[7]),
    .Vcc_wl_set(analog_io[5]),
    .Vcc_wl_read(analog_io[12]),
    .Vcc_read(analog_io[1]),
    .VSS(vssd1),
    .VDDC(vccd1),
    .VDDA(vdda1),
    .wbs_cyc_i(slave_cyc_o),
    .wbs_adr_i({wbs_adr_i[31],
    wbs_adr_i[30],
    wbs_adr_i[29],
    wbs_adr_i[28],
    wbs_adr_i[27],
    wbs_adr_i[26],
    wbs_adr_i[25],
    wbs_adr_i[24],
    wbs_adr_i[23],
    wbs_adr_i[22],
    wbs_adr_i[21],
    wbs_adr_i[20],
    wbs_adr_i[19],
    wbs_adr_i[18],
    wbs_adr_i[17],
    wbs_adr_i[16],
    wbs_adr_i[15],
    wbs_adr_i[14],
    wbs_adr_i[13],
    wbs_adr_i[12],
    wbs_adr_i[11],
    wbs_adr_i[10],
    wbs_adr_i[9],
    wbs_adr_i[8],
    wbs_adr_i[7],
    wbs_adr_i[6],
    wbs_adr_i[5],
    wbs_adr_i[4],
    wbs_adr_i[3],
    wbs_adr_i[2],
    wbs_adr_i[1],
    wbs_adr_i[0]}),
    .wbs_dat_i({wbs_dat_i[31],
    wbs_dat_i[30],
    wbs_dat_i[29],
    wbs_dat_i[28],
    wbs_dat_i[27],
    wbs_dat_i[26],
    wbs_dat_i[25],
    wbs_dat_i[24],
    wbs_dat_i[23],
    wbs_dat_i[22],
    wbs_dat_i[21],
    wbs_dat_i[20],
    wbs_dat_i[19],
    wbs_dat_i[18],
    wbs_dat_i[17],
    wbs_dat_i[16],
    wbs_dat_i[15],
    wbs_dat_i[14],
    wbs_dat_i[13],
    wbs_dat_i[12],
    wbs_dat_i[11],
    wbs_dat_i[10],
    wbs_dat_i[9],
    wbs_dat_i[8],
    wbs_dat_i[7],
    wbs_dat_i[6],
    wbs_dat_i[5],
    wbs_dat_i[4],
    wbs_dat_i[3],
    wbs_dat_i[2],
    wbs_dat_i[1],
    wbs_dat_i[0]}),
    .wbs_dat_o({\slave_0_dat_i[31] ,
    \slave_0_dat_i[30] ,
    \slave_0_dat_i[29] ,
    \slave_0_dat_i[28] ,
    \slave_0_dat_i[27] ,
    \slave_0_dat_i[26] ,
    \slave_0_dat_i[25] ,
    \slave_0_dat_i[24] ,
    \slave_0_dat_i[23] ,
    \slave_0_dat_i[22] ,
    \slave_0_dat_i[21] ,
    \slave_0_dat_i[20] ,
    \slave_0_dat_i[19] ,
    \slave_0_dat_i[18] ,
    \slave_0_dat_i[17] ,
    \slave_0_dat_i[16] ,
    \slave_0_dat_i[15] ,
    \slave_0_dat_i[14] ,
    \slave_0_dat_i[13] ,
    \slave_0_dat_i[12] ,
    \slave_0_dat_i[11] ,
    \slave_0_dat_i[10] ,
    \slave_0_dat_i[9] ,
    \slave_0_dat_i[8] ,
    \slave_0_dat_i[7] ,
    \slave_0_dat_i[6] ,
    \slave_0_dat_i[5] ,
    \slave_0_dat_i[4] ,
    \slave_0_dat_i[3] ,
    \slave_0_dat_i[2] ,
    \slave_0_dat_i[1] ,
    \slave_0_dat_i[0] }),
    .wbs_sel_i({wbs_sel_i[3],
    wbs_sel_i[2],
    wbs_sel_i[1],
    wbs_sel_i[0]}));
 Neuromorphic_X1_wb mprj1 (.wbs_we_i(slave_we_o),
    .user_clk(wb_clk_i),
    .wbs_ack_o(\slave_ack_i[1] ),
    .user_rst(wb_rst_i),
    .wb_rst_i(wb_rst_i),
    .wb_clk_i(wb_clk_i),
    .TM(io_in[5]),
    .wbs_stb_i(slave_stb_o),
    .ScanInCC(io_in[4]),
    .ScanInDL(io_in[1]),
    .ScanInDR(io_in[2]),
    .ScanOutCC(io_out[1]),
    .Iref(analog_io[0]),
    .Vbias(analog_io[6]),
    .Vcomp(analog_io[2]),
    .Bias_comp2(analog_io[3]),
    .Vcc_L(analog_io[10]),
    .Vcc_Body(analog_io[11]),
    .Vcc_reset(analog_io[9]),
    .Vcc_set(analog_io[8]),
    .Vcc_wl_reset(analog_io[7]),
    .Vcc_wl_set(analog_io[5]),
    .Vcc_wl_read(analog_io[12]),
    .Vcc_read(analog_io[1]),
    .VSS(vssd1),
    .VDDC(vccd1),
    .VDDA(vdda1),
    .wbs_cyc_i(slave_cyc_o),
    .wbs_adr_i({wbs_adr_i[31],
    wbs_adr_i[30],
    wbs_adr_i[29],
    wbs_adr_i[28],
    wbs_adr_i[27],
    wbs_adr_i[26],
    wbs_adr_i[25],
    wbs_adr_i[24],
    wbs_adr_i[23],
    wbs_adr_i[22],
    wbs_adr_i[21],
    wbs_adr_i[20],
    wbs_adr_i[19],
    wbs_adr_i[18],
    wbs_adr_i[17],
    wbs_adr_i[16],
    wbs_adr_i[15],
    wbs_adr_i[14],
    wbs_adr_i[13],
    wbs_adr_i[12],
    wbs_adr_i[11],
    wbs_adr_i[10],
    wbs_adr_i[9],
    wbs_adr_i[8],
    wbs_adr_i[7],
    wbs_adr_i[6],
    wbs_adr_i[5],
    wbs_adr_i[4],
    wbs_adr_i[3],
    wbs_adr_i[2],
    wbs_adr_i[1],
    wbs_adr_i[0]}),
    .wbs_dat_i({wbs_dat_i[31],
    wbs_dat_i[30],
    wbs_dat_i[29],
    wbs_dat_i[28],
    wbs_dat_i[27],
    wbs_dat_i[26],
    wbs_dat_i[25],
    wbs_dat_i[24],
    wbs_dat_i[23],
    wbs_dat_i[22],
    wbs_dat_i[21],
    wbs_dat_i[20],
    wbs_dat_i[19],
    wbs_dat_i[18],
    wbs_dat_i[17],
    wbs_dat_i[16],
    wbs_dat_i[15],
    wbs_dat_i[14],
    wbs_dat_i[13],
    wbs_dat_i[12],
    wbs_dat_i[11],
    wbs_dat_i[10],
    wbs_dat_i[9],
    wbs_dat_i[8],
    wbs_dat_i[7],
    wbs_dat_i[6],
    wbs_dat_i[5],
    wbs_dat_i[4],
    wbs_dat_i[3],
    wbs_dat_i[2],
    wbs_dat_i[1],
    wbs_dat_i[0]}),
    .wbs_dat_o({\slave_1_dat_i[31] ,
    \slave_1_dat_i[30] ,
    \slave_1_dat_i[29] ,
    \slave_1_dat_i[28] ,
    \slave_1_dat_i[27] ,
    \slave_1_dat_i[26] ,
    \slave_1_dat_i[25] ,
    \slave_1_dat_i[24] ,
    \slave_1_dat_i[23] ,
    \slave_1_dat_i[22] ,
    \slave_1_dat_i[21] ,
    \slave_1_dat_i[20] ,
    \slave_1_dat_i[19] ,
    \slave_1_dat_i[18] ,
    \slave_1_dat_i[17] ,
    \slave_1_dat_i[16] ,
    \slave_1_dat_i[15] ,
    \slave_1_dat_i[14] ,
    \slave_1_dat_i[13] ,
    \slave_1_dat_i[12] ,
    \slave_1_dat_i[11] ,
    \slave_1_dat_i[10] ,
    \slave_1_dat_i[9] ,
    \slave_1_dat_i[8] ,
    \slave_1_dat_i[7] ,
    \slave_1_dat_i[6] ,
    \slave_1_dat_i[5] ,
    \slave_1_dat_i[4] ,
    \slave_1_dat_i[3] ,
    \slave_1_dat_i[2] ,
    \slave_1_dat_i[1] ,
    \slave_1_dat_i[0] }),
    .wbs_sel_i({wbs_sel_i[3],
    wbs_sel_i[2],
    wbs_sel_i[1],
    wbs_sel_i[0]}));
endmodule
