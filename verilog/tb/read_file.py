import os
import sys
from pathlib import Path

def read_matrix_from_file(filename):
    matrix = []
    with open(filename, 'r') as file:
        for line in file:
            # Split the line by whitespace and convert each value to an integer
            row = [int(bit) for bit in line.strip()]
            matrix.append(row)
    return matrix

def list_to_binary(matrix):
    binary_str = ''.join(map(str, matrix))
    hex_number = int(binary_str, 2)
    return hex_number
    
def calculate_majority_class(matrix):
    majority_classes = []
    for row in matrix:
        votes =  [0 for _ in range(20)] 
        for i in range(240):
            if (row[i] == 1): 
                class_index = i % 20
                votes[class_index] += 1
        majority_class = votes.index(max(votes))
        majority_classes.append(majority_class)
    return majority_classes
