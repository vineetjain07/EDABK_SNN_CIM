import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

ROWS = 32
N_NEURONS = 16
THRESHOLD = 24
LEAK_SHIFT = 2
MEM_RESET = 0
MEM_FLOOR = -64
MEM_BITS = 16


class RefNeuron:
    def __init__(self):
        self.g_pos = [0] * ROWS
        self.g_neg = [0] * ROWS
        self.membrane = MEM_RESET

    def program(self, row: int, sign: int, level: int) -> None:
        if sign:
            self.g_neg[row] = level
        else:
            self.g_pos[row] = level

    def step(self, spikes):
        pos_sum = sum(self.g_pos[i] for i in range(ROWS) if spikes[i])
        neg_sum = sum(self.g_neg[i] for i in range(ROWS) if spikes[i])
        syn_sum = pos_sum - neg_sum
        leak = self.membrane >> LEAK_SHIFT
        mem_next = self.membrane - leak + syn_sum
        spike = 0
        if mem_next >= THRESHOLD:
            self.membrane = MEM_RESET
            spike = 1
        elif mem_next <= MEM_FLOOR:
            self.membrane = MEM_FLOOR
        else:
            self.membrane = mem_next
        return spike, self.membrane, syn_sum


class RefArray:
    def __init__(self):
        self.neurons = [RefNeuron() for _ in range(N_NEURONS)]

    def program(self, neuron: int, row: int, sign: int, level: int) -> None:
        self.neurons[neuron].program(row, sign, level)

    def step(self, spike_mask: int):
        spikes = [(spike_mask >> i) & 1 for i in range(ROWS)]
        out_spikes = []
        membranes = []
        syn_sums = []
        for neuron in self.neurons:
            spike, membrane, syn_sum = neuron.step(spikes)
            out_spikes.append(spike)
            membranes.append(membrane)
            syn_sums.append(syn_sum)
        return out_spikes, membranes, syn_sums


def decode_signed(value: int, bits: int = MEM_BITS) -> int:
    if value & (1 << (bits - 1)):
        return value - (1 << bits)
    return value


async def reset_dut(dut):
    dut.rst_ni.value = 0
    dut.en_i.value = 0
    dut.cfg_we_i.value = 0
    dut.cfg_neuron_i.value = 0
    dut.cfg_sign_i.value = 0
    dut.cfg_row_i.value = 0
    dut.cfg_level_i.value = 0
    dut.spike_i.value = 0
    await Timer(5, units="ns")
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


async def program_weight(dut, neuron: int, row: int, sign: int, level: int):
    dut.cfg_neuron_i.value = neuron
    dut.cfg_row_i.value = row
    dut.cfg_sign_i.value = sign
    dut.cfg_level_i.value = level
    dut.cfg_we_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.cfg_we_i.value = 0
    dut.cfg_level_i.value = 0
    await RisingEdge(dut.clk_i)


@cocotb.test()
async def test_reram_1t1r_array(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset_dut(dut)

    ref = RefArray()

    # Configure a small set of weights.
    weight_cfg = [
        (0, 0, 0, 7),
        (0, 1, 0, 7),
        (0, 2, 0, 7),
        (0, 3, 1, 2),
        (1, 4, 0, 5),
        (1, 5, 0, 5),
        (1, 6, 1, 1),
        (2, 0, 0, 3),
        (2, 4, 0, 3),
        (2, 1, 1, 1),
        (2, 5, 1, 1),
    ]
    for neuron, row, sign, level in weight_cfg:
        await program_weight(dut, neuron, row, sign, level)
        ref.program(neuron, row, sign, level)

    # Drive input patterns and compare against the software reference model.
    patterns = [
        (1 << 0) | (1 << 1) | (1 << 2),
        (1 << 0) | (1 << 1) | (1 << 2),
        (1 << 4) | (1 << 5),
        (1 << 4) | (1 << 5),
        (1 << 4) | (1 << 5),
        (1 << 0) | (1 << 4),
        (1 << 0) | (1 << 4),
        (1 << 3) | (1 << 6),
        0,
    ]

    dut.en_i.value = 1
    for cycle, pattern in enumerate(patterns):
        expected_spikes, expected_mem, expected_syn = ref.step(pattern)
        dut.spike_i.value = pattern
        await RisingEdge(dut.clk_i)
        await Timer(1, units="ns")

        got_spikes = int(dut.spike_o.value)
        exp_spikes_mask = sum((bit & 1) << idx for idx, bit in enumerate(expected_spikes))
        assert got_spikes == exp_spikes_mask, (
            f"cycle={cycle}: spike mismatch got=0x{got_spikes:x} exp=0x{exp_spikes_mask:x}"
        )

        mem_bus = int(dut.membrane_o.value)
        syn_bus = int(dut.syn_sum_o.value)
        for idx in range(N_NEURONS):
            got_mem = decode_signed((mem_bus >> (idx * MEM_BITS)) & ((1 << MEM_BITS) - 1))
            got_syn = decode_signed((syn_bus >> (idx * MEM_BITS)) & ((1 << MEM_BITS) - 1))
            assert got_mem == expected_mem[idx], (
                f"cycle={cycle} neuron={idx}: membrane mismatch got={got_mem} exp={expected_mem[idx]}"
            )
            assert got_syn == expected_syn[idx], (
                f"cycle={cycle} neuron={idx}: syn mismatch got={got_syn} exp={expected_syn[idx]}"
            )

    dut.en_i.value = 0
    dut.spike_i.value = 0
    await RisingEdge(dut.clk_i)
