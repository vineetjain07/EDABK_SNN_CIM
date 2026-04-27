"""
Pure-Python reference model for the SNN Neuromorphic Core.

Mimics hardware EXACTLY — same arithmetic, same data-flow, same indexing.
All constants are sourced from nvm_parameter.py (single source of truth).
No classes — only free functions operating on plain Python dicts.

Hardware facts modelled
-----------------------
- 16 physical potentials, time-multiplexed 4× via picture_done → 64 virtual neurons
- weight_type = col[0] (NOT axon[0]); odd cols negate the stimulus word
- LIF with 17-bit saturation (clamp), not wrapping  (RTL commit 33b58ab)
- Connection slicing: connection_data[axon][NUM_NEURON-(base+16) : NUM_NEURON-base], MSB-first
- ReRAM threshold: bit i of data16 → 1 if bit set  (Verilog: dat_i[i] ? MEM_HIGH : MEM_LOW)
- picture_done: latches 16 spikes into group slot, resets 16 potentials to 0

conn_matrices layout
--------------------
Flat list indexed 0 … (total_cores - 1):
  [0 : L0_cores]                 → Layer 0 cores
  [L0_cores : L0+L1_cores]       → Layer 1 cores
  [L0+L1_cores : total_cores]    → Layer 2 cores

Usage (standalone)
------------------
  python snn_reference_model.py \\
      --conn-dir   mem/connection \\
      --stimuli    mem/stimuli/stimuli.txt \\
      --labels     mem/testbench/tb_correct.txt \\
      --num-pics   100
"""

import sys
from pathlib import Path

# ── Allow imports from utils/ when run from this directory or root ───────────
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "utils"))

from snn_hw_utils import (
    interleaved_vote, interleaved_accuracy,
    load_nvm_parameter
)


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Load nvm_parameter.py  (single source of truth for all dimensions)
# ─────────────────────────────────────────────────────────────────────────────

_nvm = load_nvm_parameter()    # resolves to verilog/tb/nvm_parameter.py

# ── Core tile constants ────────────────────────────────────────────────────────
NUM_AXON    = _nvm.NUM_AXON                 # 256 — physical rows per crossbar tile
NUM_NEURON  = _nvm.NUM_NEURON               # 64  — physical columns per crossbar tile
NUM_MACROS  = _nvm.NUM_OF_MACRO             # 16  — Neuromorphic_X1 macros per core (from nvm_parameter.py / nvm_parameter.vh)
ROWS        = NUM_AXON  // NUM_MACROS       # 32  — rows per macro (256/16 = 16... wait, see note)
COLS        = NUM_NEURON // 2               # 32  — cols per macro
MEM_BASE_DIR = _nvm.MEM_BASE_DIR

# Note: the physical crossbar layout is 16 macros × 32 rows × 32 cols (= 256 × 32 per macro-pair).
# Canonical loop bounds match the RTL exactly: row in 0..31, col in 0..31.
_MACRO_ROWS = 32
_MACRO_COLS = 32

# ── Layer topology (all derived from nvm_parameter) ───────────────────────────
NUM_AXON_LAYER_0    = _nvm.NUM_AXON_LAYER_0     # 256  — input feature width
NUM_NEURONS_LAYER_0 = _nvm.NUM_NEURONS_LAYER_0  # 832
NUM_NEURONS_LAYER_1 = _nvm.NUM_NEURONS_LAYER_1  # 256
NUM_NEURONS_LAYER_2 = _nvm.NUM_NEURONS_LAYER_2  # 256

NUM_CORES_LAYER_0   = _nvm.NUM_CORES_LAYER_0    # 13
NUM_CORES_LAYER_1   = _nvm.NUM_CORES_LAYER_1    # 4
NUM_CORES_LAYER_2   = _nvm.NUM_CORES_LAYER_2    # 4

NUM_AXON_LAYER_1    = _nvm.NUM_AXON_LAYER_1     # 208  — L0_total / L1_cores (partitioned)
NUM_AXON_LAYER_2    = _nvm.NUM_AXON_LAYER_2     # 256  — L1_total (broadcast)

NUM_STIMULI_WORD    = _nvm.NUM_STIMULI_WORD      # 128  — 32-bit words per gesture
NUM_VOTES           = _nvm.NUM_VOTES             # 240  — active output spikes

# ── LIF parameters ────────────────────────────────────────────────────────────
NEURON_THRESHOLD    = _nvm.NEURON_THRESHOLD      # 8  (from nvm_parameter.py; overridden at runtime by validate_reference_model.py)
NEURON_LEAK_SHIFT   = _nvm.NEURON_LEAK_SHIFT     # 16 (from nvm_parameter.py; leak = potential >> 16 ≈ 0.0015% per injection)

# Saturation bounds: full signed 16-bit range.
# Inhibitory (odd-col) contributions drive potential negative — SW batch MAC and HW
# sequential accumulation are bit-accurate only when the floor never triggers.
# With scale=256 and 256 axons, |potential| ≤ ~16384 << 32768, so NEG_SAT=-32768
# is effectively never hit for typical inputs.
POS_SAT =  32767    # 0x7FFF
NEG_SAT = -32768    # 0x8000 as signed — full signed 16-bit floor

# ── Derived output shape ──────────────────────────────────────────────────────
_TOTAL_CORES         = NUM_CORES_LAYER_0 + NUM_CORES_LAYER_1 + NUM_CORES_LAYER_2  # 21
_L0_OFFSET           = 0
_L1_OFFSET           = NUM_CORES_LAYER_0                                           # 13
_L2_OFFSET           = NUM_CORES_LAYER_0 + NUM_CORES_LAYER_1                       # 17
_ACTIVE_PER_L2_CORE  = NUM_VOTES // NUM_CORES_LAYER_2   # 60  (240 / 4)


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Core state  (plain dict, no class)
# ─────────────────────────────────────────────────────────────────────────────

def make_core():
    """
    Allocate a fresh neuromorphic core state dict.

    Keys
    ----
    macros    : list[list[list[int]]] — macros[macro_i][row][col] ∈ {0,1}
                16 macros × 32 rows × 32 cols
    potential : list[int] — signed 16-bit potential for each of the 16 physical neurons
    spikes    : list[int] — 64 accumulated spike slots (4 groups × 16)
    """
    return {
        "macros":    [[[0] * _MACRO_COLS for _ in range(_MACRO_ROWS)]
                      for _ in range(NUM_MACROS)],
        "potential": [0] * NUM_MACROS,
        "spikes":    [0] * NUM_NEURON,
    }


def reset_core(core):
    """
    Full reset: clears potentials, spikes and all macro weights.
    Mutates core in-place.
    """
    for i in range(NUM_MACROS):
        core["potential"][i] = 0
        for r in range(_MACRO_ROWS):
            for c in range(_MACRO_COLS):
                core["macros"][i][r][c] = 0
    for i in range(NUM_NEURON):
        core["spikes"][i] = 0


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Bit-accurate arithmetic helpers
# ─────────────────────────────────────────────────────────────────────────────

def lif_saturate(potential, stimuli):
    """
    LIF integration with 17-bit saturation. Matches nvm_neuron_block.v exactly.

    next = potential - trunc(potential / 2^NEURON_LEAK_SHIFT) + stimuli
    Leak is truncated toward zero (not arithmetic shift): this preserves
    batch-MAC equivalence since |leak| < 1 ⇒ leak = 0 for both signs.
    Without this, Python/Verilog arithmetic shift gives pot>>16 = -1 for
    any negative 16-bit potential, injecting a +1 bias per step.

    Clamped to [NEG_SAT, POS_SAT].  Python int arithmetic is unbounded,
    so this is exact — no 16-bit wrapping.

    Parameters
    ----------
    potential : int  — current membrane potential (signed 16-bit)
    stimuli   : int  — signed stimulus contribution for this cycle

    Returns
    -------
    int — updated potential, saturated to 16-bit signed range
    """
    # Round toward zero (not -inf) to keep leak symmetric across signs.
    if potential >= 0:
        leak = potential >> NEURON_LEAK_SHIFT
    else:
        leak = -((-potential) >> NEURON_LEAK_SHIFT)
    nxt = potential - leak + stimuli
    if nxt > POS_SAT:
        return POS_SAT
    if nxt < NEG_SAT:
        return NEG_SAT
    return nxt


def stimuli_from_val_col(val, col):
    """
    Apply hardware sign encoding: weight_type = col[0] (LSB of column index).

    Hardware: stimuli = weight_type ? -wbs_dat_i[15:0] : wbs_dat_i[15:0]
    val is a 16-bit unsigned integer read from the stimulus bus.

    Parameters
    ----------
    val : int  — 16-bit unsigned stimulus word (0 … 65535)
    col : int  — column index within the 32-column macro (0 … 31)

    Returns
    -------
    int — signed stimulus value applied to neurons whose connection bit is set
    """
    if col & 1:                                         # odd column → negate
        neg = (-val) & 0xFFFF
        return neg if neg < 0x8000 else neg - 0x10000
    else:                                               # even column → pass through
        return val if val < 0x8000 else val - 0x10000


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Weight programming
# ─────────────────────────────────────────────────────────────────────────────

def program_core(core, connection_data):
    """
    Program one crossbar tile with binary weights from connection_data.

    Iterates the same 32×32 loop as program_layer_core() in test_full_network.py.
    connection_data[axon] is a list of NUM_NEURON bits in MSB-first order (as
    read by read_matrix_from_file / read_connection_file).

    Parameters
    ----------
    core            : dict — from make_core()
    connection_data : list[list[int]] — NUM_AXON rows × NUM_NEURON cols, each cell ∈ {0,1}
    """
    for row in range(_MACRO_ROWS):
        for col in range(_MACRO_COLS):
            axon        = (row & 0x07) * _MACRO_COLS + col           # 0 … 255
            neuron_base = ((row >> 3) & 0x03) * NUM_MACROS            # 0, 16, 32, 48
            # Slice of 16 bits for this macro group, MSB-first in the file
            val_slice = connection_data[axon][
                NUM_NEURON - (neuron_base + NUM_MACROS) : NUM_NEURON - neuron_base
            ]
            data16 = _list_to_int(val_slice)                          # pack 16 bits → int
            for i in range(NUM_MACROS):
                core["macros"][i][row][col] = (data16 >> i) & 1


def _list_to_int(bits):
    """Pack a list of bits (MSB-first) into an integer."""
    result = 0
    for b in bits:
        result = (result << 1) | int(b)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Single-cycle inject and picture_done
# ─────────────────────────────────────────────────────────────────────────────

def inject(core, row, col, val):
    """
    Inject one (row, col) bus read — equivalent to nvm_inject in hardware.

    Steps:
      1. Compute signed stimulus from val and col parity
      2. For each of the 16 macros: if connection bit is set, apply LIF update

    Parameters
    ----------
    core : dict — from make_core()
    row  : int  — row address (0 … 31)
    col  : int  — column address (0 … 31)
    val  : int  — 16-bit unsigned stimulus word
    """
    stimuli_signed = stimuli_from_val_col(val, col)
    for i in range(NUM_MACROS):
        if core["macros"][i][row][col]:
            core["potential"][i] = lif_saturate(core["potential"][i], stimuli_signed)


def picture_done(core, group):
    """
    Latch current 16 potentials → spikes, then reset potentials to 0.

    Matches nvm_neuron_spike_out: sram[addr] = spike_o, addr = wbs_adr_i[2:1]
    group ∈ {0, 1, 2, 3} → spike slots [base : base+16]

    Parameters
    ----------
    core  : dict — from make_core()
    group : int  — group index (0 … 3)
    """
    base = group * NUM_MACROS
    for i in range(NUM_MACROS):
        core["spikes"][base + i] = 1 if core["potential"][i] >= NEURON_THRESHOLD else 0
        core["potential"][i] = 0


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Single-core inference
# ─────────────────────────────────────────────────────────────────────────────

def run_core_inference(core, layer, core_idx, stimuli_in, pic=0,
                       pad_override=None,
                       verbose_inject=False, verbose_group=False):
    """
    Run inference for one crossbar tile. Mirrors run_core_inference() in
    test_full_network.py exactly.

    Parameters
    ----------
    core        : dict — from make_core(), already programmed
    layer       : int  — 0, 1, or 2
    core_idx    : int  — index of this core within its layer (used for L1 partitioned routing)
    stimuli_in  : varies by layer —
                    L0: list[int]  — 32-bit words from stimuli.txt
                    L1: list[list[int]] — spike vectors per pic (shape: [num_pics][832])
                    L2: list[list[int]] — spike vectors per pic (shape: [num_pics][256])
    pic         : int  — picture (gesture) index within stimuli_in
    pad_override: int | None — if set, forces axons ≥ NUM_AXON_LAYER_0 to this value (L0 only)
    verbose_inject: bool — print per-injection details
    verbose_group : bool — print per-group spike counts after picture_done

    Returns
    -------
    list[int] — 64-element spike vector for this core
    """
    # Reset only spike accumulator (potentials survive between pics if re-used,
    # but callers always reset_core() before programming — so this is defensive)
    for i in range(NUM_NEURON):
        core["spikes"][i] = 0

    for row in range(_MACRO_ROWS):
        for col in range(_MACRO_COLS):
            axon   = (row & 0x07) * _MACRO_COLS + col
            active = False
            val    = 0

            if layer == 0:
                # Padding: axons beyond NUM_AXON_LAYER_0 get pad_override
                if pad_override is not None and axon >= NUM_AXON_LAYER_0:
                    val    = pad_override
                    active = True
                else:
                    word_idx = pic * NUM_STIMULI_WORD + axon // 2
                    word_val = stimuli_in[word_idx] if word_idx < len(stimuli_in) else 0
                    val      = (word_val >> 16) & 0xFFFF if axon % 2 == 0 else word_val & 0xFFFF
                    active   = True

            elif layer == 1:
                # Partitioned routing: each L1 core sees a fixed slice of L0 output
                if axon < NUM_AXON_LAYER_1:
                    idx = core_idx * NUM_AXON_LAYER_1 + axon
                    if stimuli_in[pic][idx] == 1:
                        active = True
                        val    = 1

            elif layer == 2:
                # Broadcast: all L2 cores see the full L1 output
                if axon < NUM_AXON_LAYER_2:
                    if stimuli_in[pic][axon] == 1:
                        active = True
                        val    = 1

            if active:
                if verbose_inject:
                    pre = list(core["potential"])
                inject(core, row, col, val)
                if verbose_inject:
                    post    = list(core["potential"])
                    changed = [i for i in range(NUM_MACROS) if pre[i] != post[i]]
                    if changed:
                        sv = stimuli_from_val_col(val, col)
                        print(f"  inject row={row} col={col} axon={axon} val={val} "
                              f"stimuli={sv} changed={changed} "
                              f"post_pot={[post[i] for i in changed]}")

            # After the last column of each macro group, issue picture_done
            if col == _MACRO_COLS - 1:
                group = None
                if   row == 7:  group = 0
                elif row == 15: group = 1
                elif row == 23: group = 2
                elif row == 31: group = 3
                if group is not None:
                    picture_done(core, group)
                    if verbose_group:
                        sl = core["spikes"][group * NUM_MACROS : (group + 1) * NUM_MACROS]
                        print(f"  Group {group} picture_done: spikes={sum(sl)} mask={sl}")

    return list(core["spikes"])


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Full 3-layer network inference
# ─────────────────────────────────────────────────────────────────────────────

def run_full_network(conn_matrices, stimuli, num_pics=1,
                     pad_override=None,
                     verbose_core=False, verbose_group=False, verbose_inject=False):
    """
    Run full 3-layer SNN inference in Python, mirroring run_full_network() in
    test_full_network.py exactly.

    Parameters
    ----------
    conn_matrices : list[list[list[int]]]
        Flat list of connection matrices, length = total_cores (= 21 for 13-4-4).
        Index layout (derived from nvm_parameter):
          [0          : L0_cores]          → Layer 0 (13 cores)
          [L0_cores   : L0+L1_cores]       → Layer 1 ( 4 cores)
          [L0+L1_cores: L0+L1+L2_cores]    → Layer 2 ( 4 cores)
    stimuli   : list[int]  — all 32-bit stimulus words concatenated (num_pics × NUM_STIMULI_WORD)
    num_pics  : int        — number of gestures to infer
    pad_override : int | None — stimulus value for padding axons in L0 (None = zero, not injected)
    verbose_*    : bool   — debugging output flags

    Returns
    -------
    list[list[int]] — spike_l2[num_pics][NUM_VOTES]
        Output spike vectors (240 spikes = 4×60 active neurons, used for majority voting).
    """
    core = make_core()

    spike_l0 = [[0] * NUM_NEURONS_LAYER_0  for _ in range(num_pics)]   # [pics][832]
    spike_l1 = [[0] * NUM_NEURONS_LAYER_1  for _ in range(num_pics)]   # [pics][256]
    spike_l2 = [[0] * NUM_VOTES            for _ in range(num_pics)]   # [pics][240]

    # ── Layer 0 ── 13 cores × 64 spikes = 832 ────────────────────────────────
    for ci in range(NUM_CORES_LAYER_0):
        reset_core(core)
        program_core(core, conn_matrices[_L0_OFFSET + ci])
        if verbose_core:
            density = _weight_density(core)
            print(f"[L0 core {ci}] weight density={density:.3f}")
        for pic in range(num_pics):
            spikes = run_core_inference(
                core, layer=0, core_idx=ci, stimuli_in=stimuli, pic=pic,
                pad_override=pad_override,
                verbose_inject=verbose_inject, verbose_group=verbose_group,
            )
            for i in range(NUM_NEURON):
                spike_l0[pic][ci * NUM_NEURON + i] = spikes[i]
        if verbose_core:
            for pic in range(num_pics):
                cnt = sum(spike_l0[pic][ci * NUM_NEURON:(ci + 1) * NUM_NEURON])
                print(f"  pic={pic} L0 core {ci} spikes={cnt}/{NUM_NEURON}")

    # ── Layer 1 ── 4 cores × 64 spikes = 256 ─────────────────────────────────
    for ci in range(NUM_CORES_LAYER_1):
        reset_core(core)
        program_core(core, conn_matrices[_L1_OFFSET + ci])
        if verbose_core:
            density = _weight_density(core)
            print(f"[L1 core {ci}] weight density={density:.3f}")
        for pic in range(num_pics):
            spikes = run_core_inference(
                core, layer=1, core_idx=ci, stimuli_in=spike_l0, pic=pic,
                verbose_inject=verbose_inject, verbose_group=verbose_group,
            )
            for i in range(NUM_NEURON):
                spike_l1[pic][ci * NUM_NEURON + i] = spikes[i]
        if verbose_core:
            for pic in range(num_pics):
                cnt = sum(spike_l1[pic][ci * NUM_NEURON:(ci + 1) * NUM_NEURON])
                print(f"  pic={pic} L1 core {ci} spikes={cnt}/{NUM_NEURON}")

    # ── Layer 2 ── 4 cores × 60 active = 240 ─────────────────────────────────
    for ci in range(NUM_CORES_LAYER_2):
        reset_core(core)
        program_core(core, conn_matrices[_L2_OFFSET + ci])
        if verbose_core:
            density = _weight_density(core)
            print(f"[L2 core {ci}] weight density={density:.3f}")
        for pic in range(num_pics):
            spikes = run_core_inference(
                core, layer=2, core_idx=ci, stimuli_in=spike_l1, pic=pic,
                verbose_inject=verbose_inject, verbose_group=verbose_group,
            )
            # Only first _ACTIVE_PER_L2_CORE spikes per core are valid (60 of 64)
            for i in range(_ACTIVE_PER_L2_CORE):
                spike_l2[pic][ci * _ACTIVE_PER_L2_CORE + i] = spikes[i]
        if verbose_core:
            for pic in range(num_pics):
                cnt = sum(spike_l2[pic][ci * _ACTIVE_PER_L2_CORE:(ci + 1) * _ACTIVE_PER_L2_CORE])
                print(f"  pic={pic} L2 core {ci} spikes={cnt}/{_ACTIVE_PER_L2_CORE}")

    return spike_l2


# ─────────────────────────────────────────────────────────────────────────────
# 8.  Classification (majority voting)
# ─────────────────────────────────────────────────────────────────────────────

def classify(l2_spikes):
    """
    Majority-vote classifier — interleaved round-robin assignment.

    Neuron i votes for class (i % NUM_CLASS).  This is the hardware-native
    convention: the scheduler cycles through classes in lock-step with the
    physical neuron index.

    Delegates to snn_hw_utils.interleaved_vote — single source of truth
    shared with train_dvs128.py and test_full_network_debug.py.

    Parameters
    ----------
    l2_spikes : list[list[int]] — shape [num_pics][NUM_VOTES]

    Returns
    -------
    list[int] — predicted class index (0 … NUM_CLASS-1) for each gesture
    """
    num_class = _nvm.NUM_CLASS
    return [interleaved_vote(row, num_class) for row in l2_spikes]

def calculate_accuracy(preds, labels):
    """
    Calculate simple accuracy percentage.

    Parameters
    ----------
    preds  : list[int] — predicted class indices
    labels : list[int] — ground truth class indices

    Returns
    -------
    float — accuracy percentage (0.0 to 100.0)
    """
    return 100.0 * interleaved_accuracy(preds, labels)


def print_accuracy_report(preds, labels):
    """
    Print a detailed accuracy report including per-class breakdown.

    Parameters
    ----------
    preds  : list[int] — predicted class indices
    labels : list[int] — ground truth class indices
    """
    n = min(len(preds), len(labels))
    if n == 0:
        print("No samples to evaluate.")
        return

    num_class = _nvm.NUM_CLASS
    class_stats = {i: {"correct": 0, "total": 0} for i in range(num_class)}

    for p, l in zip(preds[:n], labels[:n]):
        class_stats[l]["total"] += 1
        if p == l:
            class_stats[l]["correct"] += 1

    overall_acc = calculate_accuracy(preds, labels)
    print("=" * 40)
    print(f" ACCURACY REPORT (N={n})")
    print("-" * 40)
    print(f" Overall Accuracy: {overall_acc:>6.2f}%")
    print("-" * 40)
    print(f" {'Class':<8} │ {'Accuracy':>10} │ {'Count':>6}")
    print(" ─────────┼────────────┼───────")

    for i in range(num_class):
        s = class_stats[i]
        if s["total"] > 0:
            acc = 100.0 * s["correct"] / s["total"]
            print(f" {i:<8d} │ {acc:>9.1f}% │ {s['total']:>6d}")
        else:
            print(f" {i:<8d} │ {'---':>10} │ {0:>6d}")
    print("=" * 40)


# ─────────────────────────────────────────────────────────────────────────────
# 9.  File I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def read_connection_file(path):
    """
    Read one connection_XXX.txt file.

    Each line is a string of '0'/'1' characters (NUM_NEURON chars = 64).
    Returns list[list[int]] — NUM_AXON rows × NUM_NEURON cols.

    Parameters
    ----------
    path : str | Path

    Returns
    -------
    list[list[int]]  shape (NUM_AXON, NUM_NEURON)
    """
    matrix = []
    with open(path) as fh:
        for line in fh:
            matrix.append([int(c) for c in line.strip()])
    return matrix


def load_connection_files(conn_dir):
    """
    Load all connection files for a 3-layer network into a flat list.

    Expected file names (sequential numbering):
      connection_000.txt ... connection_{total_cores-1:03d}.txt

    Parameters
    ----------
    conn_dir : str | Path — directory containing the connection_XXX.txt files

    Returns
    -------
    list[list[list[int]]] — flat list of matrices, length = total_cores (21)
    """
    conn_dir = Path(conn_dir)
    matrices = []

    for ci in range(_TOTAL_CORES):
        path = conn_dir / f"connection_{ci:03d}.txt"
        matrices.append(read_connection_file(path))

    expected = _TOTAL_CORES
    if len(matrices) != expected:
        raise RuntimeError(
            f"Expected {expected} connection files, loaded {len(matrices)}. "
            f"Check {conn_dir}."
        )
    return matrices


def load_stimuli_file(stimuli_path):
    """
    Load stimuli.txt into a flat list of 32-bit integers.

    Each line is a 32-bit binary string (from export_stimuli.py).
    The resulting list has length = num_gestures × NUM_STIMULI_WORD.

    Parameters
    ----------
    stimuli_path : str | Path

    Returns
    -------
    list[int]
    """
    words = []
    with open(stimuli_path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                words.append(int(line, 2))
    return words


def load_labels_file(labels_path):
    """
    Load tb_correct.txt ground-truth labels (8-bit binary strings, one per line).

    Parameters
    ----------
    labels_path : str | Path

    Returns
    -------
    list[int] — integer class indices
    """
    labels = []
    with open(labels_path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                labels.append(int(line, 2))
    return labels


# ─────────────────────────────────────────────────────────────────────────────
# 10.  Internal debug helper
# ─────────────────────────────────────────────────────────────────────────────

def _weight_density(core):
    """Return fraction of '1' bits across all macros (for debug / logging)."""
    total = NUM_MACROS * _MACRO_ROWS * _MACRO_COLS
    ones  = sum(
        core["macros"][i][r][c]
        for i in range(NUM_MACROS)
        for r in range(_MACRO_ROWS)
        for c in range(_MACRO_COLS)
    )
    return ones / total


# ─────────────────────────────────────────────────────────────────────────────
# 11.  CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="SNN Neuromorphic Core — Python Reference Model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  # Full inference, measure accuracy
  python snn_reference_model.py \\
      --conn-dir  mem/connection \\
      --stimuli   mem/stimuli/stimuli.txt \\
      --labels    mem/testbench/tb_correct.txt

  # Single gesture, verbose
  python snn_reference_model.py \\
      --conn-dir  mem/connection \\
      --stimuli   mem/stimuli/stimuli.txt \\
      --num-pics  1 --verbose-group

  # LIF self-test only
  python snn_reference_model.py --self-test
        """,
    )
    parser.add_argument("--conn-dir",  type=Path, default=MEM_BASE_DIR / "connection",
                        help=f"Directory with connection_XXX.txt files (default: {MEM_BASE_DIR}/connection)")
    parser.add_argument("--stimuli",   type=Path, default=MEM_BASE_DIR / "stimuli/stimuli.txt",
                        help=f"Stimuli file (default: {MEM_BASE_DIR}/stimuli/stimuli.txt)")
    parser.add_argument("--labels",    type=Path, default=MEM_BASE_DIR / "testbench/tb_correct.txt",
                        help=f"Ground-truth labels file (default: {MEM_BASE_DIR}/testbench/tb_correct.txt)")
    parser.add_argument("--num-pics",  type=int,  default=None,
                        help="Number of gestures to run (default: all in stimuli file)")
    parser.add_argument("--verbose-core",   action="store_true", help="Print per-core weight density & spikes")
    parser.add_argument("--verbose-group",  action="store_true", help="Print per-group spikes at picture_done")
    parser.add_argument("--verbose-inject", action="store_true", help="Print per-injection potential changes")
    parser.add_argument("--self-test",      action="store_true", help="Run arithmetic self-test and exit")
    args = parser.parse_args()

    # ── Self-test ─────────────────────────────────────────────────────────────
    if args.self_test:
        print("=== LIF saturation self-test ===")
        assert lif_saturate(32000,  5000) == POS_SAT,  "FAIL: positive saturation"
        assert lif_saturate(-32000, -5000) == NEG_SAT, "FAIL: negative saturation"
        p = lif_saturate(100, 50)
        assert 148 <= p <= 150, f"FAIL: normal integration = {p}"
        assert stimuli_from_val_col(0x0010, 0) == 16,  "FAIL: even col should be +16"
        assert stimuli_from_val_col(0x0010, 1) == -16, "FAIL: odd col should be -16"
        print("  lif_saturate(32000,  5000) =", lif_saturate(32000,  5000), " (expect 32767)")
        print("  lif_saturate(-32000,-5000) =", lif_saturate(-32000,-5000), " (expect -32768)")
        print("  lif_saturate(100, 50)      =", lif_saturate(100, 50),       " (expect ~149)")
        print("  stimuli col=0 val=0x10 →",    stimuli_from_val_col(0x10, 0), " (expect +16)")
        print("  stimuli col=1 val=0x10 →",    stimuli_from_val_col(0x10, 1), " (expect -16)")
        print("All assertions passed.")
        sys.exit(0)

    # ── Full inference run ────────────────────────────────────────────────────
    if not args.conn_dir.is_dir():
        print(f"ERROR: connection directory not found: {args.conn_dir}")
        print("  Run from verilog/tb/ or pass --conn-dir explicitly.")
        sys.exit(1)
    if not args.stimuli.exists():
        print(f"ERROR: stimuli file not found: {args.stimuli}")
        sys.exit(1)

    print("=== SNN Reference Model ===")
    print(f"  Layer 0 : {NUM_AXON_LAYER_0} axons → {NUM_CORES_LAYER_0}×{NUM_NEURON} = {NUM_NEURONS_LAYER_0} spikes")
    print(f"  Layer 1 : {NUM_AXON_LAYER_1}/core  → {NUM_CORES_LAYER_1}×{NUM_NEURON} = {NUM_NEURONS_LAYER_1} spikes  (partitioned)")
    print(f"  Layer 2 : {NUM_AXON_LAYER_2} axons → {NUM_CORES_LAYER_2}×{_ACTIVE_PER_L2_CORE} = {NUM_VOTES} votes")
    print(f"  Threshold={NEURON_THRESHOLD}  LeakShift={NEURON_LEAK_SHIFT}  StimWords/pic={NUM_STIMULI_WORD}")
    print()

    print("Loading connection files ...")
    conn_matrices = load_connection_files(args.conn_dir)
    print(f"  Loaded {len(conn_matrices)} cores from {args.conn_dir}")

    print("Loading stimuli ...")
    stimuli_words = load_stimuli_file(args.stimuli)
    total_pics    = len(stimuli_words) // NUM_STIMULI_WORD
    num_pics      = args.num_pics if args.num_pics is not None else total_pics
    num_pics      = min(num_pics, total_pics)
    print(f"  {len(stimuli_words)} words → {total_pics} gestures available → running {num_pics}")

    labels = None
    if args.labels is not None:
        if args.labels.exists():
            labels = load_labels_file(args.labels)
            print(f"  Labels loaded: {len(labels)} entries")
        else:
            print(f"  WARNING: labels file not found: {args.labels} — skipping accuracy")
    print()

    print(f"Running inference on {num_pics} gesture(s) ...")
    spike_l2 = run_full_network(
        conn_matrices, stimuli_words, num_pics=num_pics,
        verbose_core=args.verbose_core,
        verbose_group=args.verbose_group,
        verbose_inject=args.verbose_inject,
    )

    preds = classify(spike_l2)

    if labels is not None:
        print_accuracy_report(preds, labels[:num_pics])
        if num_pics <= 20:
            print("\nDetailed Predictions:")
            for i, (p, l) in enumerate(zip(preds, labels[:num_pics])):
                mark = "✓" if p == l else "✗"
                print(f"  pic {i:3d}: pred={p:2d}  true={l:2d}  {mark}")
    else:
        print("\nPredictions (no labels loaded):")
        for i, p in enumerate(preds):
            print(f"  pic {i:3d}: pred={p}")
