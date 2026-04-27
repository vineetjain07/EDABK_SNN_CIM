"""
File I/O utilities for SNN hardware data files.

This module provides helper functions to read connection files (weights) 
and stimuli files (inputs) used by the RTL testbench. It ensures consistent 
packing and bit-ordering across Python and Verilog.

Connection files (connection_XXX.txt):
    - Each line represents a single axon row.
    - Characters '0'/'1' represent binary connectivity to each neuron in the core.
    - Format: MSB-first. The first character (index 0) maps to the highest-indexed 
      neuron (neuron 63).

Stimuli files (stimuli.txt):
    - 32-bit binary words, each packing two 16-bit axon values.
    - Upper 16 bits = even-indexed axon.
    - Lower 16 bits = odd-indexed axon.
    - Hardware MAC rule: Odd-indexed axons are treated as negative contributions.
"""

from snn_hw_utils import interleaved_vote, load_nvm_parameter


def read_matrix_from_file(filename):
    """Read a connection file into a 2-D list of ints.

    Each line becomes one row; each character ('0' or '1') becomes one element.
    Row order and bit order are preserved as-is (MSB-first within each row).

    Args:
        filename: Path to connection_XXX.txt file.

    Returns:
        List of lists of int (0 or 1).
    """
    matrix = []
    with open(filename, 'r') as file:
        for line in file:
            row = [int(bit) for bit in line.strip()]
            matrix.append(row)
    return matrix


def list_to_binary(matrix):
    """Concatenate all elements of a flat list into a binary integer.

    Used to pack a row of connection bits into a single integer for Wishbone
    writes. MSB-first: index 0 of the list becomes the most-significant bit.

    Args:
        matrix: Flat list of int (0 or 1).

    Returns:
        Integer with bits ordered MSB-first.
    """
    binary_str = ''.join(map(str, matrix))
    return int(binary_str, 2)


def calculate_majority_class(matrix, num_class=None):
    """Interleaved majority vote: neuron i votes for class (i % num_class).
    Default num_class read from nvm_parameter.NUM_CLASS (12).
    """
    if num_class is None:
        num_class = load_nvm_parameter().NUM_CLASS
    return [interleaved_vote(row, num_class) for row in matrix]
