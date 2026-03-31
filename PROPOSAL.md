# Proposal: Hardware-Aware Leaky Integrate-and-Fire (LIF) Neurosynaptic Core for Edge Gesture Recognition

**Designer:** Nikunj Bhatt  
**Target Platform:** ChipFoundry Caravel SoC + BM Labs Neuromorphic X1 ReRAM NVM  

## 1. Project Overview
This project proposes an architectural enhancement to the `EDABK_SNN_CIM` reference design, upgrading the digital neuron array to enable true temporal processing for edge-based gesture recognition. By replacing the static accumulation neuron model with a hardware-efficient Leaky Integrate-and-Fire (LIF) neuron, this design allows the system to accurately process time-series IMU data without saturation, leveraging the full potential of the BM Labs ReRAM In-Memory Computing (IMC) macro.

## 2. The Core Problem
The current EDABK_SNN_CIM architecture utilizes the ReRAM crossbar for efficient Vector-Matrix Multiplication (VMM), but the digital neuron block (`nvm_neuron_block.v`) acts as a static accumulator with a fixed zero-threshold. For time-series data like human gestures (captured via IMU):
* **No Temporal Decay:** Old inputs never fade, treating past and present movements equally.
* **Saturation Risk:** Continuous positive stimuli cause the membrane potential to saturate, leading to permanent firing states.
* **Loss of SNN Advantage:** True Spiking Neural Networks rely on the *timing* of spikes. Without leakage and dynamic reset, the network acts as a binary classifier rather than a temporal processor.

## 3. Key Innovation Points
This proposal introduces a modified digital neuron block that bridges the gap between biological realism and silicon efficiency:
* **Controlled Leakage Dynamics:** Introduces a clock-cycle decay to the membrane potential, ensuring that only correlated, recent movements trigger a spike. 
* **Configurable Firing Threshold:** Replaces the hardcoded sign-bit check with a parameter-driven threshold, preventing noisy or weak IMU signals from causing false positive spikes.
* **Spike-Triggered Reset:** Resets the membrane potential locally upon firing, allowing the neuron to recover and represent subsequent gesture phases accurately.
* **Zero-Multiplier Overhead:** The LIF dynamics are implemented using simple shifts and additions, maintaining the ultra-low-area footprint required for Caravel integration.

## 4. System Architecture & Data Flow
1. **Stimulus Input:** Encoded IMU data (acceleration, angular velocity) enters via the Wishbone bus.
2. **In-Memory Compute:** The Neuromorphic X1 ReRAM macro performs analog VMM, outputting connection states.
3. **LIF Processing (Core Contribution):** The custom digital neuron array integrates the stimuli, applies the leakage penalty, and checks the configurable threshold.
4. **Classification:** Spikes are generated and latched into the Spike-out buffer only when temporal gesture patterns cross the confidence threshold.

## 5. Application Scenarios
By introducing reliable temporal dynamics, this neurosynaptic core becomes viable for ultra-low-power, real-world edge applications:
* **Industrial IoT (Predictive Maintenance):** Adapting the temporal gesture core to monitor time-series vibration data on factory floors to detect motor anomalies.
* **Touchless Medical Interfaces:** Sterile gesture control for surgeons or clinical staff, running entirely on-device without cloud latency.
* **AR/VR Wearables:** Ultra-low-power continuous hand tracking that operates within strict thermal and battery limits.

## 6. Current Status & Next Steps
* **Phase 1 (Completed):** Architectural analysis of `nvm_neuron_block.v` and implementation of RTL modifications for thresholding, leakage, and reset logic. (Available in the `lif_neuron_upgrade` branch).
* **Phase 2 (Immediate):** Local simulation and validation of the LIF dynamics against the baseline accumulation model using Cocotb to prove saturation prevention.
* **Phase 3 (Target):** Integration with the complete Caravel + Neuromorphic X1 SoC flow for OpenLane synthesis and timing verification.
