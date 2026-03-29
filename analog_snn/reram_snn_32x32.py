
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np


@dataclass
class ReRAMCrossbarParameters:
    """
    Default parameters for a 32x32 ReRAM crossbar SNN/CIM model.

    Core hardware-style defaults used directly:
      - 32x32 1S1R array
      - array-level HRS/LRS conductances: 6.67 uS and 50 uS
      - 8 conductance states (~3 bits)
      - read voltage: 0.7 V
      - integrated 1S1R switch/read times: 45 ns / 60 ns
      - TDC operating point: 50 uA average discharge current, 60 ns sensing time, 3.12 pJ

    Behavioral extensions used to expose an SNN-friendly API:
      - LIF neuron dynamics
      - STDP update rule
      - fault model for the 89% array yield
      - TDC gain from crossbar current to subtractor current
    """

    rows: int = 32
    cols: int = 32
    n_levels: int = 8  # 3-bit capability

    # Nominal array-level conductance window
    g_hrs_s: float = 6.67e-6
    g_lrs_s: float = 50.0e-6

    # Device variation (array-level D2D)
    d2d_hrs_sigma_frac: float = 0.0519
    d2d_lrs_sigma_frac: float = 0.0228

    # Read / program defaults
    read_voltage_v: float = 0.7
    switch_time_ns: float = 45.0
    read_time_ns: float = 60.0

    # Programming ramp defaults
    set_v_initial: float = -2.56
    set_v_max: float = -3.55
    reset_v_initial: float = 1.33
    reset_v_max: float = 3.50
    program_step_v: float = 0.01

    # Example endurance / retention placeholders
    integrated_endurance_cycles: int = 26_500
    retention_s_85c: float = 1.0e4

    # Optional fault-yield model
    yield_fraction: float = 0.89

    # TDC-style readout defaults
    tdc_ref_current_a: float = 50.0e-6
    tdc_ref_time_ns: float = 60.0
    tdc_energy_pj: float = 3.12
    tdc_power_uw: float = 52.0

    # Small analog noise terms used in the simulator
    read_noise_sigma_frac: float = 0.02
    subtractor_noise_sigma_frac: float = 0.005

    # SNN-only knobs (not reported in the reference design)
    tau_mem_ns: float = 240.0
    refractory_ns: float = 120.0
    v_threshold: float = 0.7
    v_reset: float = 0.0
    v_floor: float = -1.0

    stdp_tau_pre_ns: float = 600.0
    stdp_tau_post_ns: float = 600.0
    stdp_a_plus: float = 0.020
    stdp_a_minus: float = 0.022

    def conductance_levels(self) -> np.ndarray:
        return np.linspace(self.g_hrs_s, self.g_lrs_s, self.n_levels)

    @property
    def tdc_discharge_charge_c(self) -> float:
        # q = I * t = 50 uA * 60 ns = 3e-12 C
        return self.tdc_ref_current_a * self.tdc_ref_time_ns * 1e-9

    @property
    def dt_ns(self) -> float:
        return self.read_time_ns

    @property
    def n_signed_outputs(self) -> int:
        return self.cols // 2

    @property
    def full_scale_unsigned_col_current_a(self) -> float:
        return self.rows * self.read_voltage_v * self.g_lrs_s

    @property
    def full_scale_signed_current_a(self) -> float:
        # Differential-pair signed range around common mode
        return self.rows * self.read_voltage_v * 0.5 * (self.g_lrs_s - self.g_hrs_s)


class ReRAMSNN32x32:
    """
    32x32 ReRAM crossbar model adapted to an SNN-friendly interface.

    Hardware mapping used here:
      - each 1S1R crosspoint = programmable synapse
      - each adjacent column pair = signed output channel (16 total for a 32-column array)
      - TDC delay = current-domain readout
      - a digital / mixed-signal LIF state machine sits after each differential pair

    This model maps each crosspoint to a programmable synapse and each adjacent column pair to one signed output channel.
    It is intended for mixed-signal SNN exploration and compute-in-memory evaluation.
    """

    def __init__(
        self,
        params: Optional[ReRAMCrossbarParameters] = None,
        *,
        n_outputs: Optional[int] = None,
        seed: Optional[int] = None,
        enable_faults: bool = True,
    ) -> None:
        self.p = params or ReRAMCrossbarParameters()
        self.rng = np.random.default_rng(seed)
        self.rows = self.p.rows
        self.cols = self.p.cols
        self.n_outputs = n_outputs if n_outputs is not None else self.p.n_signed_outputs
        if self.n_outputs < 1 or self.n_outputs > self.p.n_signed_outputs:
            raise ValueError(
                f"n_outputs must be between 1 and {self.p.n_signed_outputs}, got {self.n_outputs}."
            )

        # Sample per-cell device variation.
        self.g_hrs_cell, self.g_lrs_cell, self.g_levels = self._sample_cell_conductance_levels()

        # Device fault model used to represent the reported 89% array yield.
        self.enable_faults = enable_faults
        self.fault_type = self._sample_faults() if enable_faults else np.full((self.rows, self.cols), 0, dtype=np.int8)

        # State index: 0 = HRS, n_levels-1 = LRS
        self.state_idx = np.zeros((self.rows, self.cols), dtype=np.int16)
        self.G = self._effective_conductance_matrix()

        # Signed weight view seen by the user.
        self.weights_norm = np.zeros((self.rows, self.n_outputs), dtype=float)
        self.user_weight_scale = 1.0

        # Neuron / SNN state
        self.v_mem = np.zeros(self.n_outputs, dtype=float)
        self.refrac_steps_remaining = np.zeros(self.n_outputs, dtype=np.int32)
        self.pre_trace = np.zeros(self.rows, dtype=float)
        self.post_trace = np.zeros(self.n_outputs, dtype=float)

        self._pre_decay = float(np.exp(-self.p.dt_ns / self.p.stdp_tau_pre_ns))
        self._post_decay = float(np.exp(-self.p.dt_ns / self.p.stdp_tau_post_ns))
        self._mem_decay = float(np.exp(-self.p.dt_ns / self.p.tau_mem_ns))
        self._refractory_steps = max(1, int(np.round(self.p.refractory_ns / self.p.dt_ns)))

        # Scale differential current to a TDC-style operating point.
        # The subtractor is centered around the reference current and allows a moderate signed current swing.
        self.tdc_bias_current_a = self.p.tdc_ref_current_a
        self.tdc_gain = 0.5 * self.p.tdc_ref_current_a / max(self.p.full_scale_signed_current_a, 1e-15)

        # Map signed synaptic current to unitless membrane voltage increments.
        self.synaptic_gain = 1.0 / max(self.p.full_scale_signed_current_a, 1e-15)

    # ------------------------------------------------------------------
    # Hardware-aware initialization
    # ------------------------------------------------------------------
    def _sample_cell_conductance_levels(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        hrs = self.p.g_hrs_s * np.clip(
            self.rng.normal(1.0, self.p.d2d_hrs_sigma_frac, size=(self.rows, self.cols)),
            0.50,
            1.50,
        )
        lrs = self.p.g_lrs_s * np.clip(
            self.rng.normal(1.0, self.p.d2d_lrs_sigma_frac, size=(self.rows, self.cols)),
            0.50,
            1.50,
        )
        lrs = np.maximum(lrs, 1.2 * hrs)  # keep a usable switching window
        alphas = np.linspace(0.0, 1.0, self.p.n_levels, dtype=float)[None, None, :]
        levels = hrs[..., None] + (lrs - hrs)[..., None] * alphas
        return hrs, lrs, levels

    def _sample_faults(self) -> np.ndarray:
        """
        Fault codes:
            0 -> healthy
            1 -> open / missing current path
            2 -> stuck near HRS
            3 -> stuck near LRS
        """
        fault = np.zeros((self.rows, self.cols), dtype=np.int8)
        defective = self.rng.random((self.rows, self.cols)) > self.p.yield_fraction
        if not np.any(defective):
            return fault

        kind = self.rng.random((self.rows, self.cols))
        fault[defective & (kind < 0.40)] = 1
        fault[defective & (kind >= 0.40) & (kind < 0.70)] = 2
        fault[defective & (kind >= 0.70)] = 3
        return fault

    def _effective_conductance_matrix(self) -> np.ndarray:
        G = np.take_along_axis(self.g_levels, self.state_idx[..., None], axis=2)[..., 0].copy()
        if not self.enable_faults:
            return G

        open_mask = self.fault_type == 1
        stuck_hrs_mask = self.fault_type == 2
        stuck_lrs_mask = self.fault_type == 3

        G[open_mask] = 0.0
        G[stuck_hrs_mask] = self.g_hrs_cell[stuck_hrs_mask]
        G[stuck_lrs_mask] = self.g_lrs_cell[stuck_lrs_mask]
        return G

    # ------------------------------------------------------------------
    # Programming / mapping
    # ------------------------------------------------------------------
    def reset_crossbar_to_hrs(self) -> None:
        self.state_idx.fill(0)
        self.G = self._effective_conductance_matrix()

    def _quantize_targets_for_column(self, col: int, targets: np.ndarray) -> np.ndarray:
        levels = self.g_levels[:, col, :]  # [rows, n_levels]
        # argmin over conductance level distance for each row
        idx = np.argmin(np.abs(levels - targets[:, None]), axis=1)
        return idx.astype(np.int16)

    def program_weights(self, weights: np.ndarray, *, assume_normalized: bool = False) -> Dict[str, float]:
        """
        Program a [32, n_outputs] software weight matrix into the 32x32 crossbar.

        Signed weights are stored using adjacent column pairs:
            W[:, j] -> (col 2j = G+, col 2j+1 = G-)

        The mapping follows the reference design's differential-pair scheme.
        """
        W = np.asarray(weights, dtype=float)
        if W.shape != (self.rows, self.n_outputs):
            raise ValueError(f"weights must have shape {(self.rows, self.n_outputs)}, got {W.shape}.")

        if assume_normalized:
            Wn = np.clip(W, -1.0, 1.0)
            scale = 1.0
        else:
            scale = float(np.max(np.abs(W))) if np.any(W) else 1.0
            Wn = np.clip(W / scale, -1.0, 1.0)

        self.weights_norm = Wn.copy()
        self.user_weight_scale = scale

        # Unused columns remain at HRS.
        self.state_idx.fill(0)

        total_state_hops = 0.0
        for j in range(self.n_outputs):
            col_p = 2 * j
            col_m = 2 * j + 1

            # Cell-specific differential mapping.
            gmid_p = 0.5 * (self.g_hrs_cell[:, col_p] + self.g_lrs_cell[:, col_p])
            gmid_m = 0.5 * (self.g_hrs_cell[:, col_m] + self.g_lrs_cell[:, col_m])
            gamp_p = 0.5 * (self.g_lrs_cell[:, col_p] - self.g_hrs_cell[:, col_p])
            gamp_m = 0.5 * (self.g_lrs_cell[:, col_m] - self.g_hrs_cell[:, col_m])

            target_p = np.clip(gmid_p + gamp_p * Wn[:, j], self.g_hrs_cell[:, col_p], self.g_lrs_cell[:, col_p])
            target_m = np.clip(gmid_m - gamp_m * Wn[:, j], self.g_hrs_cell[:, col_m], self.g_lrs_cell[:, col_m])

            new_idx_p = self._quantize_targets_for_column(col_p, target_p)
            new_idx_m = self._quantize_targets_for_column(col_m, target_m)

            total_state_hops += float(np.abs(self.state_idx[:, col_p] - new_idx_p).sum())
            total_state_hops += float(np.abs(self.state_idx[:, col_m] - new_idx_m).sum())

            self.state_idx[:, col_p] = new_idx_p
            self.state_idx[:, col_m] = new_idx_m

        self.G = self._effective_conductance_matrix()

        avg_state_hops = total_state_hops / max(2 * self.rows * self.n_outputs, 1)
        # Rough, explicitly heuristic programming-time estimate.
        est_program_time_ns = avg_state_hops * self.p.switch_time_ns
        return {
            "weight_scale": self.user_weight_scale,
            "average_state_hops": avg_state_hops,
            "estimated_program_time_ns_per_cell": est_program_time_ns,
        }

    def export_programmed_conductance_map(self) -> np.ndarray:
        return self.G.copy()

    def export_signed_weight_view(self) -> np.ndarray:
        Gp = self.G[:, 0 : 2 * self.n_outputs : 2]
        Gm = self.G[:, 1 : 2 * self.n_outputs : 2]
        # Normalize back to [-1, 1] using the nominal conductance span.
        denom = max(0.5 * (self.p.g_lrs_s - self.p.g_hrs_s), 1e-15)
        return np.clip((Gp - Gm) / (2.0 * denom), -1.0, 1.0)

    # ------------------------------------------------------------------
    # Readout / TDC / neuron dynamics
    # ------------------------------------------------------------------
    def _row_voltages_from_input(self, x: np.ndarray, input_mode: str) -> np.ndarray:
        x = np.asarray(x, dtype=float).reshape(-1)
        if x.shape != (self.rows,):
            raise ValueError(f"input vector must have shape {(self.rows,)}, got {x.shape}.")

        if input_mode == "spike":
            v_rows = self.p.read_voltage_v * (x > 0.0).astype(float)
        elif input_mode == "analog":
            v_rows = self.p.read_voltage_v * np.clip(x, 0.0, 1.0)
        else:
            raise ValueError("input_mode must be 'spike' or 'analog'.")
        return v_rows

    def crossbar_mac(self, x: np.ndarray, *, input_mode: str = "spike") -> Tuple[np.ndarray, np.ndarray]:
        """
        Returns:
            i_cols  : raw unsigned column currents, shape [32]
            i_diff  : signed differential currents, shape [n_outputs]
        """
        v_rows = self._row_voltages_from_input(x, input_mode)
        i_cols = v_rows @ self.G  # [cols]

        # Column current noise
        if self.p.read_noise_sigma_frac > 0:
            i_cols = i_cols * (1.0 + self.rng.normal(0.0, self.p.read_noise_sigma_frac, size=i_cols.shape))

        i_plus = i_cols[0 : 2 * self.n_outputs : 2]
        i_minus = i_cols[1 : 2 * self.n_outputs : 2]
        i_diff = i_plus - i_minus

        # Differential subtractor noise
        if self.p.subtractor_noise_sigma_frac > 0:
            i_diff = i_diff * (
                1.0 + self.rng.normal(0.0, self.p.subtractor_noise_sigma_frac, size=i_diff.shape)
            )
        return i_cols, i_diff

    def tdc_encode(self, i_diff: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Convert signed differential current to a positive TDC current and then to delay.

        Assumption:
            The subtractor + current mirror scales the raw crossbar differential current
            down to a 50 uA-centered operating point consistent with the TDC-style readout model.
        """
        i_tdc = self.tdc_bias_current_a + self.tdc_gain * np.asarray(i_diff, dtype=float)
        i_tdc = np.clip(i_tdc, 1e-9, None)
        delay_ns = 1e9 * self.p.tdc_discharge_charge_c / i_tdc
        return delay_ns, i_tdc

    def reset_neuron_state(self) -> None:
        self.v_mem.fill(0.0)
        self.refrac_steps_remaining.fill(0)
        self.pre_trace.fill(0.0)
        self.post_trace.fill(0.0)

    def _lif_update(self, i_diff: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        self.v_mem *= self._mem_decay
        self.v_mem = np.maximum(self.v_mem, self.p.v_floor)

        active = self.refrac_steps_remaining <= 0
        self.refrac_steps_remaining[~active] -= 1

        self.v_mem[active] += self.synaptic_gain * i_diff[active]

        spikes = active & (self.v_mem >= self.p.v_threshold)
        self.v_mem[spikes] = self.p.v_reset
        self.refrac_steps_remaining[spikes] = self._refractory_steps
        return spikes.astype(np.int8), self.v_mem.copy()

    # ------------------------------------------------------------------
    # STDP (optional online learning)
    # ------------------------------------------------------------------
    def _apply_stdp(self, pre_spikes: np.ndarray, post_spikes: np.ndarray) -> None:
        pre = (np.asarray(pre_spikes).reshape(-1) > 0).astype(float)
        post = (np.asarray(post_spikes).reshape(-1) > 0).astype(float)

        if pre.shape != (self.rows,):
            raise ValueError(f"pre spike vector must have shape {(self.rows,)}, got {pre.shape}.")
        if post.shape != (self.n_outputs,):
            raise ValueError(f"post spike vector must have shape {(self.n_outputs,)}, got {post.shape}.")

        self.pre_trace *= self._pre_decay
        self.post_trace *= self._post_decay
        self.pre_trace += pre
        self.post_trace += post

        dw = np.zeros_like(self.weights_norm)
        if np.any(post):
            dw += self.p.stdp_a_plus * np.outer(self.pre_trace, post)
        if np.any(pre):
            dw -= self.p.stdp_a_minus * np.outer(pre, self.post_trace)

        if np.any(dw):
            self.weights_norm = np.clip(self.weights_norm + dw, -1.0, 1.0)
            self.program_weights(self.weights_norm, assume_normalized=True)

    # ------------------------------------------------------------------
    # Public simulation API
    # ------------------------------------------------------------------
    def step(
        self,
        x: np.ndarray,
        *,
        input_mode: str = "spike",
        apply_stdp: bool = False,
    ) -> Dict[str, np.ndarray]:
        i_cols, i_diff = self.crossbar_mac(x, input_mode=input_mode)
        delay_ns, i_tdc = self.tdc_encode(i_diff)
        spikes, v_mem = self._lif_update(i_diff)

        if apply_stdp:
            pre_spikes = (np.asarray(x).reshape(-1) > 0).astype(np.int8)
            self._apply_stdp(pre_spikes, spikes)

        return {
            "column_currents_a": i_cols,
            "signed_currents_a": i_diff,
            "tdc_currents_a": i_tdc,
            "tdc_delays_ns": delay_ns,
            "membrane": v_mem,
            "output_spikes": spikes,
        }

    def run(
        self,
        spike_train: np.ndarray,
        *,
        input_mode: str = "spike",
        apply_stdp: bool = False,
        reset_state: bool = True,
    ) -> Dict[str, np.ndarray]:
        X = np.asarray(spike_train, dtype=float)
        if X.ndim != 2 or X.shape[1] != self.rows:
            raise ValueError(f"spike_train must have shape [T, {self.rows}], got {X.shape}.")

        if reset_state:
            self.reset_neuron_state()

        T = X.shape[0]
        i_cols_hist = np.zeros((T, self.cols), dtype=float)
        i_diff_hist = np.zeros((T, self.n_outputs), dtype=float)
        i_tdc_hist = np.zeros((T, self.n_outputs), dtype=float)
        delay_hist = np.zeros((T, self.n_outputs), dtype=float)
        mem_hist = np.zeros((T, self.n_outputs), dtype=float)
        spike_hist = np.zeros((T, self.n_outputs), dtype=np.int8)

        for t in range(T):
            out = self.step(X[t], input_mode=input_mode, apply_stdp=apply_stdp)
            i_cols_hist[t] = out["column_currents_a"]
            i_diff_hist[t] = out["signed_currents_a"]
            i_tdc_hist[t] = out["tdc_currents_a"]
            delay_hist[t] = out["tdc_delays_ns"]
            mem_hist[t] = out["membrane"]
            spike_hist[t] = out["output_spikes"]

        return {
            "input": X,
            "column_currents_a": i_cols_hist,
            "signed_currents_a": i_diff_hist,
            "tdc_currents_a": i_tdc_hist,
            "tdc_delays_ns": delay_hist,
            "membrane": mem_hist,
            "output_spikes": spike_hist,
            "dt_ns": np.array(self.p.dt_ns),
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def poisson_encode(self, rates_hz: np.ndarray, steps: int) -> np.ndarray:
        rates = np.asarray(rates_hz, dtype=float).reshape(-1)
        if rates.shape != (self.rows,):
            raise ValueError(f"rates_hz must have shape {(self.rows,)}, got {rates.shape}.")
        p = np.clip(rates * (self.p.dt_ns * 1e-9), 0.0, 1.0)
        return (self.rng.random((steps, self.rows)) < p[None, :]).astype(np.int8)

    def info(self) -> Dict[str, float]:
        return {
            "rows": float(self.rows),
            "cols": float(self.cols),
            "signed_outputs": float(self.n_outputs),
            "yield_fraction": float(self.p.yield_fraction),
            "g_hrs_uS": 1e6 * self.p.g_hrs_s,
            "g_lrs_uS": 1e6 * self.p.g_lrs_s,
            "levels": float(self.p.n_levels),
            "read_voltage_v": float(self.p.read_voltage_v),
            "switch_time_ns": float(self.p.switch_time_ns),
            "read_time_ns": float(self.p.read_time_ns),
            "tdc_energy_pj": float(self.p.tdc_energy_pj),
            "tdc_ref_current_uA": 1e6 * self.p.tdc_ref_current_a,
        }


def make_prototype_weights(num_outputs: int = 4, rows: int = 32) -> np.ndarray:
    """
    Small helper used by the demo:
    create four prototype receptive fields over 32 input axons.
    """
    if num_outputs > 16:
        raise ValueError("A 32x32 signed crossbar exposes at most 16 differential outputs.")
    W = -0.15 * np.ones((rows, num_outputs), dtype=float)
    groups = np.array_split(np.arange(rows), num_outputs)
    for j, g in enumerate(groups):
        W[g, j] = 1.0
    return W


def make_temporal_pattern(rows: int, active_rows: np.ndarray, steps: int, onset: int, width: int) -> np.ndarray:
    X = np.zeros((steps, rows), dtype=np.int8)
    end = min(steps, onset + width)
    X[onset:end, active_rows] = 1
    return X


def add_bitflip_noise(x: np.ndarray, rng: np.random.Generator, flip_prob: float = 0.03) -> np.ndarray:
    y = np.asarray(x, dtype=np.int8).copy()
    flips = rng.random(y.shape) < flip_prob
    y[flips] = 1 - y[flips]
    return y


if __name__ == "__main__":
    # Quick self-test / demo
    model = ReRAMSNN32x32(seed=7, enable_faults=False, n_outputs=4)
    weights = make_prototype_weights(num_outputs=4, rows=32)
    info = model.program_weights(weights)
    print("Program info:", info)
    print("Model info:", model.info())

    steps = 16
    patterns = []
    groups = np.array_split(np.arange(32), 4)
    for i, g in enumerate(groups):
        pat = make_temporal_pattern(32, g, steps=steps, onset=3 + i, width=3)
        patterns.append(add_bitflip_noise(pat, model.rng, flip_prob=0.02))

    for idx, pat in enumerate(patterns):
        out = model.run(pat, reset_state=True)
        spike_count = out["output_spikes"].sum(axis=0)
        winner = int(np.argmax(spike_count))
        print(f"Pattern {idx}: spike_count={spike_count.tolist()} winner={winner}")
