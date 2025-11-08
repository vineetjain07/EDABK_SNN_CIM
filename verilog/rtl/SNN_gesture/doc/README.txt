Dũng 05/11/2025
################################
RTL CỦA 1 user_project_wrapper

Module cần layout tên là nvm_neuron_core_64x64. Tức là 64 axon x 64 neuron
- Core Decoder: giải mã địa chỉ

- Synapse Matrix không còn nữa, mà đưa ra khỏi core, Hình thành bởi 4 IP Neuromorphic X1 32x32. Mỗi lần ghi vào và đọc ra cùng lúc chỉ được 1 bit cho mỗi IP. Quy tác đọc/ghi đơn giản: wbs_adr_i trỏ đến 1 địa chỉ cố định, wbs_data_i chia ra làm các trường MODE, ROW, COL, DATA. Cụ thể hơn thì xem link của thằng tác giả gốc bên trên.
  IP 0 lưu synap giữa mọi axon với neuron 0,4,8,...,60 (2 hàng đầu của neuron 0, 2 hàng sau của neuron 4,...). Tương tự từ IP 1 (các axon x neuron 1,5,..,61) đến IP 3 (các axon x neuron 3,7,..,63).
  Ví dụ vị trí của các cell trong IP 0 ứng với connection giữa axon nào và neuron nào:
  Row Col Axon Neuron
  0   0   0    0
  0   1   1    0
  1   0   32   0
  1   31  63   0
  3   31  63   4
  5   31  63   8
  31  31  63   60

             MODE   ROW    COL    NONE  DATA 
 wbs_dat_i: [31:30][29:25][24:20][19:4][3:0]

- Neuron Block: Tính toán potential + kích hoạt. Tạm thời đang để weight mặc định là +1 (với axon 0,2,4,...) và -1 (với axon 1,3,5,...). Threshold mặc định là 0. Không dùng bias.
  Thực hiện tính toán mỗi lần đưa kích thích (stimuli, 16 bit = 9 bit phần thực + 7 bit phần thập phân) vào, bằng cách đọc từ địa chỉ synapse cố định (như trên) ra kèm theo wbs_data_i trỏ đến tọa độ hàng/cột của connection 
             MODE   ROW    COL    NONE   STIMULI
 wbs_dat_i: [31:30][29:25][24:20][19:16][15:0]

- Neuron Spikeout: Lưu spike out
Done pic, viết spike từ Neuron Block vào Neuron Spikeout: viết vào một trong 4 địa chỉ sau, mỗi lần viết chỉ được 4 bit thôi (vì chỉ có 4 IP nên thành ra có 4 neuron block) 
  Địa chỉ     Neuron
  0x3000_2000 0-3
  0x3000_2001 4-7
  0x3000_2002 8-11
  0x3000_200F 60-63

Khi muốn đọc spike out ra thì đọc từ một trong địa chỉ này ra, được 32bit mỗi lần đọc.
  Địa chỉ     Neuron
  0x3000_1000 0-31
  0x3000_1008 32-63