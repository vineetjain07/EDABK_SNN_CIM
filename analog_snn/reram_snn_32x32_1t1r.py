from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from scipy import sparse
from scipy.sparse import linalg as spla

try:
    from .reram_snn_32x32 import ReRAMCrossbarParameters, ReRAMSNN32x32
except ImportError:  # pragma: no cover
    from reram_snn_32x32 import ReRAMCrossbarParameters, ReRAMSNN32x32


@dataclass
class ReRAMOneTOneRParameters(ReRAMCrossbarParameters):
    """
    Default behavioral parameters for a generic 32x32 ReRAM 1T1R tile.

    Design assumptions used by this behavioral model:
      - same 32x32 array size and 3-bit conductance programming
      - differential-pair weight mapping with TDC-style signed readout
      - 1T1R access-path abstraction with explicit source, bitline and gate behavior
      - low-voltage readout defaults suitable for fast mixed-signal evaluation
      - nanosecond-class device and sensing placeholders

    Not directly captured by this model:
      - extracted transistor model, threshold voltage, on/off resistance, or a demonstrated
        32x32 1T1R array using this exact ReRAM stack

    Consequently, this dataclass is a generic behavioral proxy for 1T1R operation.
    """

    # Keep the same ReRAM weight window and 3-bit programming capability.
    g_hrs_s: float = 6.67e-6
    g_lrs_s: float = 50.0e-6
    n_levels: int = 8

    # 1T1R proxy timing / operating point for a low-voltage mixed-signal case.
    read_voltage_v: float = 0.1
    switch_time_ns: float = 1.0
    read_time_ns: float = 2.5

    # 1R/1T1R low-voltage programming proxy based on the fast 1R pulse result.
    set_v_initial: float = -0.80
    set_v_max: float = -1.00
    reset_v_initial: float = 0.80
    reset_v_max: float = 1.00
    program_step_v: float = 0.01

    # Default TDC-style sensing proxy for the 1T1R path.
    tdc_ref_current_a: float = 55.0e-6
    tdc_ref_time_ns: float = 2.5

    # This was measured for the 1S1R array, not a demonstrated 1T1R array,
    # so keep fault modeling disabled by default and do not reuse 89% as a default fact.
    yield_fraction: float = 1.0

    # No direct 1T1R TDC energy number was reported; this field is left as a placeholder.
    tdc_energy_pj: float = np.nan

    # Convenience metadata for reporting.
    estimated_energy_efficiency_topsw: float = 1309.1


@dataclass
class OneTOneRArrayConfig:
    """
    Array/peripheral assumptions for the 1T1R conversion.

    The topology assumes a conventional 1T1R organization:
      - WL connects gate terminals
      - BL connects memristor top electrodes
      - SL connects source terminals
      - transistor drain connects to the memristor bottom electrode

    The values below are heuristic unless explicitly noted in the reference comments.
    They are exposed so you can retune them for a target CMOS node or PDK.
    """

    # Interconnect resistance per cell pitch segment.
    source_wire_res_ohm: float = 4.0
    bitline_wire_res_ohm: float = 4.0
    gate_wire_res_ohm: float = 4.0

    # Driver and sensing terminations.
    source_driver_impedance_ohm: float = 5.0
    gate_driver_impedance_ohm: float = 5.0
    tia_clamp_ohm: float = 1.0

    # Conventional 1T1R uses a source line in addition to WL and BL.
    source_connection: str = "dsc"  # 'ssc' or 'dsc'

    # Access-transistor conductance proxy.
    r_access_on_ohm: float = 1.5e3
    r_access_off_ohm: float = 1.0e9
    access_r_on_sigma_frac: float = 0.05

    # Gate-drive behavior.
    gate_drive: str = "always_on"  # 'always_on' or 'input_gated'
    gate_enable_threshold: float = 0.0
    include_gate_dynamics: bool = True

    # Distributed parasitics.  The review motivates including adjacent-line,
    # top-bottom intersection, and line-to-ground capacitances.  The 1T1R
    # the model also includes explicit BL/SL and BL/WL overlap terms.
    c_source_adj_f: float = 8e-15
    c_bitline_adj_f: float = 8e-15
    c_gate_adj_f: float = 8e-15
    c_intersection_f: float = 4e-15
    c_source_ground_f: float = 6e-15
    c_bitline_ground_f: float = 6e-15
    c_gate_ground_f: float = 4e-15
    c_bl_sl_overlap_f: float = 6e-15
    c_bl_wl_overlap_f: float = 6e-15
    c_gate_cell_f: float = 1e-15

    # PCB/sensing side errors inherited from the original hardware discussion.
    distributed_c_error_sigma_frac: float = 0.008
    discrete_component_sigma_frac: float = 0.010

    # Dynamic settling of the bitline current.
    include_dynamic_settling: bool = True


@dataclass
class MixedSignalNeuronConfig:
    activation: str = "tdc_nonlinear"  # 'none', 'relu', 'sigmoid', 'tdc_nonlinear'
    output_mode: str = "lif"  # 'lif' or 'wta'

    relu_gain: float = 1.0
    relu_max: float = 1.0
    sigmoid_gain: float = 6.0
    tdc_gamma: float = 1.25

    wta_threshold: float = 0.55
    lateral_inhibition: float = 0.30

    use_activation_before_lif: bool = False


class ReRAMSNN32x32OneTOneR(ReRAMSNN32x32):
    """
    Parasitic-aware 1T1R proxy of the reference's 32x32 ReRAM CIM/SNN tile.

    Relative to the earlier 1S1R model, the main architectural changes are:
      1. the selector diode is replaced by a gated access transistor model
      2. the array now uses source lines (SL) instead of driving the memristor rows directly
      3. the access path is modeled as memristor-in-series-with-transistor, so the effective
         cell conductance is G_eff = 1 / (1/G_mem + R_access)
      4. overlap-parasitic terms specific to conventional 1T1R arrays (BL/SL and BL/WL)
         are included in the RC latency estimates

    Important caveat:
      The reference demonstrates a 32x32 1S1R array, not a 32x32 1T1R array with this exact
      stack.  This class is therefore a *reference-constrained what-if model* that preserves the
      ReRAM device data and the differential TDC readout while swapping the access device.
    """

    def __init__(
        self,
        params: Optional[ReRAMOneTOneRParameters] = None,
        *,
        array: Optional[OneTOneRArrayConfig] = None,
        neuron: Optional[MixedSignalNeuronConfig] = None,
        n_outputs: Optional[int] = None,
        seed: Optional[int] = None,
        enable_faults: bool = False,
    ) -> None:
        super().__init__(
            params=params or ReRAMOneTOneRParameters(),
            n_outputs=n_outputs,
            seed=seed,
            enable_faults=enable_faults,
        )
        self.p = self.p  # type: ignore[assignment]
        self.array_cfg = array or OneTOneRArrayConfig()
        self.neuron_cfg = neuron or MixedSignalNeuronConfig()

        # Access-device mismatch proxy.
        on_scale = np.clip(
            self.rng.normal(
                1.0,
                self.array_cfg.access_r_on_sigma_frac,
                size=(self.rows, self.cols),
            ),
            0.60,
            1.40,
        )
        self.r_access_on_cell = self.array_cfg.r_access_on_ohm * on_scale
        self.g_access_on_cell = 1.0 / np.maximum(self.r_access_on_cell, 1e-12)
        self.g_access_off = 1.0 / max(self.array_cfg.r_access_off_ohm, 1e-12)

        self.gate_state = np.zeros(self.rows, dtype=float)
        self._dynamic_col_currents = np.zeros(self.cols, dtype=float)

        # Cache keyed by the gate-state vector rounded to 3 decimals.
        self._cached_key: Optional[Tuple[float, ...]] = None
        self._cached_solver = None
        self._cached_B = None
        self._cached_g_tia = 1.0 / max(self.array_cfg.tia_clamp_ohm, 1e-12)
        self._cached_g_eff = np.zeros((self.rows, self.cols), dtype=float)

    # ------------------------------------------------------------------
    # Dynamic-state helpers
    # ------------------------------------------------------------------
    def reset_array_state(self) -> None:
        self._dynamic_col_currents.fill(0.0)
        if self.array_cfg.gate_drive == "always_on":
            self.gate_state.fill(1.0)
        else:
            self.gate_state.fill(0.0)
        self._cached_key = None

    def reset_neuron_state(self) -> None:
        super().reset_neuron_state()
        self.reset_array_state()

    def program_weights(self, weights: np.ndarray, *, assume_normalized: bool = False) -> Dict[str, float]:
        info = super().program_weights(weights, assume_normalized=assume_normalized)
        self._cached_key = None
        return info

    # ------------------------------------------------------------------
    # 1T1R access device / input mapping
    # ------------------------------------------------------------------
    def _source_voltages_from_input(self, x: np.ndarray, input_mode: str) -> np.ndarray:
        x = np.asarray(x, dtype=float).reshape(-1)
        if x.shape != (self.rows,):
            raise ValueError(f"input vector must have shape {(self.rows,)}, got {x.shape}.")

        if input_mode == "spike":
            return self.p.read_voltage_v * (x > 0.0).astype(float)
        if input_mode == "analog":
            return self.p.read_voltage_v * np.clip(x, 0.0, 1.0)
        raise ValueError("input_mode must be 'spike' or 'analog'.")

    def _gate_targets_from_input(self, x: np.ndarray, input_mode: str) -> np.ndarray:
        x = np.asarray(x, dtype=float).reshape(-1)
        if self.array_cfg.gate_drive == "always_on":
            return np.ones(self.rows, dtype=float)
        if input_mode == "spike":
            return (x > self.array_cfg.gate_enable_threshold).astype(float)
        return (np.clip(x, 0.0, 1.0) > self.array_cfg.gate_enable_threshold).astype(float)

    def _source_tau_rows_ns(self) -> np.ndarray:
        c_eff = self.cols * (
            self.array_cfg.c_source_ground_f
            + 2.0 * self.array_cfg.c_source_adj_f
            + self.array_cfg.c_bl_sl_overlap_f
            + 0.25 * self.array_cfg.c_intersection_f
        )
        r_eff = (
            self.array_cfg.source_driver_impedance_ohm
            + 0.5 * max(self.cols - 1, 0) * self.array_cfg.source_wire_res_ohm
        )
        return np.full(self.rows, 1e9 * r_eff * c_eff, dtype=float)

    def _gate_tau_rows_ns(self) -> np.ndarray:
        c_eff = self.cols * (
            self.array_cfg.c_gate_ground_f
            + 2.0 * self.array_cfg.c_gate_adj_f
            + self.array_cfg.c_bl_wl_overlap_f
            + self.array_cfg.c_gate_cell_f
        )
        r_eff = (
            self.array_cfg.gate_driver_impedance_ohm
            + 0.5 * max(self.cols - 1, 0) * self.array_cfg.gate_wire_res_ohm
        )
        return np.full(self.rows, 1e9 * r_eff * c_eff, dtype=float)

    def _update_gate_state(self, x: np.ndarray, input_mode: str) -> np.ndarray:
        target = self._gate_targets_from_input(x, input_mode)
        if not self.array_cfg.include_gate_dynamics:
            self.gate_state = target
            return self.gate_state.copy()

        tau = self._gate_tau_rows_ns()
        alpha = 1.0 - np.exp(-self.p.dt_ns / np.maximum(tau, 1e-6))
        self.gate_state = self.gate_state + alpha * (target - self.gate_state)
        return self.gate_state.copy()

    def _effective_cell_conductance(self, gate_state: np.ndarray) -> np.ndarray:
        gate_state = np.asarray(gate_state, dtype=float).reshape(self.rows, 1)
        g_access = self.g_access_off + gate_state * (self.g_access_on_cell - self.g_access_off)
        r_access = 1.0 / np.maximum(g_access, 1e-15)
        return 1.0 / (1.0 / np.maximum(self.G, 1e-15) + r_access)

    # ------------------------------------------------------------------
    # Sparse solve for SL/BL network
    # ------------------------------------------------------------------
    def _source_node_idx(self, r: int, c: int) -> int:
        return r * self.cols + c

    def _bitline_node_idx(self, r: int, c: int) -> int:
        return self.rows * self.cols + r * self.cols + c

    def _build_solver_for_g_eff(self, g_eff: np.ndarray) -> None:
        ns = self.rows * self.cols
        nb = self.rows * self.cols
        n = ns + nb

        g_sw = 1.0 / max(self.array_cfg.source_wire_res_ohm, 1e-12)
        g_bw = 1.0 / max(self.array_cfg.bitline_wire_res_ohm, 1e-12)
        g_src = 1.0 / max(self.array_cfg.source_driver_impedance_ohm, 1e-12)
        g_tia = 1.0 / max(self.array_cfg.tia_clamp_ohm, 1e-12)

        left_drive = True
        right_drive = self.array_cfg.source_connection.lower() == "dsc"

        rows_idx: list[int] = []
        cols_idx: list[int] = []
        data: list[float] = []
        B = np.zeros((n, self.rows), dtype=float)

        def add(i: int, j: int, value: float) -> None:
            rows_idx.append(i)
            cols_idx.append(j)
            data.append(value)

        for r in range(self.rows):
            for c in range(self.cols):
                i_s = self._source_node_idx(r, c)
                i_b = self._bitline_node_idx(r, c)
                g_cell = float(g_eff[r, c])

                diag_s = g_cell
                diag_b = g_cell

                # Local 1T1R current path represented as a series-reduced conductance.
                add(i_s, i_b, -g_cell)
                add(i_b, i_s, -g_cell)

                # Horizontal source-line segments.
                if c > 0:
                    j = self._source_node_idx(r, c - 1)
                    add(i_s, j, -g_sw)
                    diag_s += g_sw
                if c < self.cols - 1:
                    j = self._source_node_idx(r, c + 1)
                    add(i_s, j, -g_sw)
                    diag_s += g_sw

                # Vertical bitline segments.
                if r > 0:
                    j = self._bitline_node_idx(r - 1, c)
                    add(i_b, j, -g_bw)
                    diag_b += g_bw
                if r < self.rows - 1:
                    j = self._bitline_node_idx(r + 1, c)
                    add(i_b, j, -g_bw)
                    diag_b += g_bw

                # Source-line drive from one or both ends.
                if c == 0 and left_drive:
                    diag_s += g_src
                    B[i_s, r] += g_src
                if c == self.cols - 1 and right_drive:
                    diag_s += g_src
                    B[i_s, r] += g_src

                # TIA / virtual-ground clamp at the bottom of each bitline.
                if r == self.rows - 1:
                    diag_b += g_tia

                add(i_s, i_s, diag_s)
                add(i_b, i_b, diag_b)

        A = sparse.coo_matrix((data, (rows_idx, cols_idx)), shape=(n, n)).tocsc()
        self._cached_solver = spla.factorized(A)
        self._cached_B = B
        self._cached_g_tia = g_tia
        self._cached_g_eff = np.asarray(g_eff, dtype=float).copy()

    def _maybe_refresh_solver(self, g_eff: np.ndarray) -> None:
        key = tuple(np.round(self.gate_state, 3).tolist())
        if self._cached_solver is not None and self._cached_key == key:
            return
        self._build_solver_for_g_eff(g_eff)
        self._cached_key = key

    def _solve_crossbar_nodes(
        self,
        x: np.ndarray,
        input_mode: str,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        v_source = self._source_voltages_from_input(x, input_mode)
        gate_state = self._update_gate_state(x, input_mode)
        g_eff = self._effective_cell_conductance(gate_state)
        self._maybe_refresh_solver(g_eff)

        assert self._cached_solver is not None
        assert self._cached_B is not None

        b = self._cached_B @ v_source
        v = self._cached_solver(b)

        vs = v[: self.rows * self.cols].reshape(self.rows, self.cols)
        vb = v[self.rows * self.cols :].reshape(self.rows, self.cols)

        i_cell = g_eff * (vs - vb)
        i_cols_static = self._cached_g_tia * vb[-1, :]

        active = v_source > 0
        if np.any(active):
            denom = np.maximum(v_source[:, None], 1e-12)
            read_margin = np.zeros_like(i_cell)
            read_margin[active, :] = np.clip(np.abs(vs[active, :] - vb[active, :]) / denom[active, :], 0.0, 1.0)
        else:
            read_margin = np.zeros_like(i_cell)

        return v_source, gate_state, vs, vb, i_cell, i_cols_static, read_margin

    # ------------------------------------------------------------------
    # Dynamic RC / TDC / activation
    # ------------------------------------------------------------------
    def _column_settling_tau_ns(self) -> np.ndarray:
        c_eff = self.rows * (
            self.array_cfg.c_bitline_ground_f
            + 2.0 * self.array_cfg.c_bitline_adj_f
            + self.array_cfg.c_intersection_f
            + self.array_cfg.c_bl_sl_overlap_f
            + self.array_cfg.c_bl_wl_overlap_f
            + 0.25 * self.array_cfg.c_source_adj_f
            + 0.25 * self.array_cfg.c_gate_adj_f
        )
        c_eff = np.full(self.cols, c_eff, dtype=float)

        g_col = np.maximum(self._cached_g_eff.sum(axis=0), 1e-12)
        r_eff = (
            self.array_cfg.tia_clamp_ohm
            + 0.5 * max(self.rows - 1, 0) * self.array_cfg.bitline_wire_res_ohm
            + 1.0 / g_col
        )
        return 1e9 * r_eff * c_eff

    def _combined_column_tau_ns(self) -> np.ndarray:
        tau_col = self._column_settling_tau_ns()
        tau_source = float(np.mean(self._source_tau_rows_ns()))
        tau_gate = float(np.mean(self._gate_tau_rows_ns())) if self.array_cfg.include_gate_dynamics else 0.0
        return tau_col + tau_source + tau_gate

    def crossbar_mac(self, x: np.ndarray, *, input_mode: str = "spike") -> Tuple[np.ndarray, np.ndarray, Dict[str, np.ndarray]]:
        v_source, gate_state, vs, vb, i_cell, i_cols_static, read_margin = self._solve_crossbar_nodes(x, input_mode)
        tau_ns = self._combined_column_tau_ns()

        if self.array_cfg.include_dynamic_settling:
            alpha = 1.0 - np.exp(-self.p.dt_ns / np.maximum(tau_ns, 1e-6))
            self._dynamic_col_currents = self._dynamic_col_currents + alpha * (i_cols_static - self._dynamic_col_currents)
            i_cols = self._dynamic_col_currents.copy()
        else:
            i_cols = i_cols_static.copy()

        if self.p.read_noise_sigma_frac > 0:
            i_cols = i_cols * (1.0 + self.rng.normal(0.0, self.p.read_noise_sigma_frac, size=i_cols.shape))

        i_plus = i_cols[0 : 2 * self.n_outputs : 2]
        i_minus = i_cols[1 : 2 * self.n_outputs : 2]
        i_diff = i_plus - i_minus

        if self.p.subtractor_noise_sigma_frac > 0:
            i_diff = i_diff * (
                1.0 + self.rng.normal(0.0, self.p.subtractor_noise_sigma_frac, size=i_diff.shape)
            )

        aux = {
            "input_source_voltages_v": v_source,
            "gate_state": gate_state,
            "source_node_voltages_v": vs,
            "bitline_node_voltages_v": vb,
            "cell_currents_a": i_cell,
            "cell_conductance_eff_s": self._cached_g_eff.copy(),
            "read_margin": read_margin,
            "tau_cols_ns": tau_ns,
            "static_column_currents_a": i_cols_static,
            "tau_gate_rows_ns": self._gate_tau_rows_ns(),
            "tau_source_rows_ns": self._source_tau_rows_ns(),
        }
        return i_cols, i_diff, aux

    def tdc_encode(self, i_diff: np.ndarray, aux: Optional[Dict[str, np.ndarray]] = None) -> Tuple[np.ndarray, np.ndarray]:
        i_diff = np.asarray(i_diff, dtype=float)
        i_tdc = self.tdc_bias_current_a + self.tdc_gain * i_diff

        if aux is not None:
            tau_cols = np.asarray(aux.get("tau_cols_ns", np.zeros(self.cols)))
            pair_tau = 0.5 * (tau_cols[0 : 2 * self.n_outputs : 2] + tau_cols[1 : 2 * self.n_outputs : 2])
            load_norm = pair_tau / max(np.max(pair_tau), 1e-12)
            err = self.rng.normal(0.0, self.array_cfg.distributed_c_error_sigma_frac, size=self.n_outputs) * load_norm
            i_tdc = i_tdc * (1.0 + err)

        if self.array_cfg.discrete_component_sigma_frac > 0:
            i_tdc = i_tdc * (
                1.0 + self.rng.normal(0.0, self.array_cfg.discrete_component_sigma_frac, size=self.n_outputs)
            )

        i_tdc = np.clip(i_tdc, 1e-9, None)
        delay_ns = 1e9 * self.p.tdc_discharge_charge_c / i_tdc
        return delay_ns, i_tdc

    def _apply_activation(self, i_diff: np.ndarray, delay_ns: np.ndarray) -> np.ndarray:
        cfg = self.neuron_cfg
        x = np.asarray(i_diff, dtype=float) / max(self.p.full_scale_signed_current_a, 1e-15)
        x = np.clip(x, -2.0, 2.0)

        if cfg.activation == "none":
            return x
        if cfg.activation == "relu":
            return np.clip(cfg.relu_gain * np.maximum(x, 0.0), 0.0, cfg.relu_max)
        if cfg.activation == "sigmoid":
            return 1.0 / (1.0 + np.exp(-cfg.sigmoid_gain * x))
        if cfg.activation == "tdc_nonlinear":
            delay_ns = np.asarray(delay_ns, dtype=float)
            d_min = 1e9 * self.p.tdc_discharge_charge_c / (self.tdc_bias_current_a + 0.5 * self.p.tdc_ref_current_a)
            d_max = 1e9 * self.p.tdc_discharge_charge_c / max(
                self.tdc_bias_current_a - 0.5 * self.p.tdc_ref_current_a,
                1e-9,
            )
            z = np.clip((d_max - delay_ns) / max(d_max - d_min, 1e-12), 0.0, 1.0)
            return np.clip(z ** cfg.tdc_gamma, 0.0, 1.0)
        raise ValueError(f"Unsupported activation: {cfg.activation}")

    def _lif_drive(self, i_diff: np.ndarray, activated: np.ndarray) -> np.ndarray:
        if not self.neuron_cfg.use_activation_before_lif:
            return np.asarray(i_diff, dtype=float)

        a = np.asarray(activated, dtype=float)
        if self.neuron_cfg.activation == "sigmoid":
            return (a - 0.5) * 2.0 * self.p.full_scale_signed_current_a
        return a * self.p.full_scale_signed_current_a

    def _wta_update(self, activated: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        activated = np.asarray(activated, dtype=float)
        self.v_mem *= self._mem_decay
        self.v_mem += activated

        spikes = np.zeros(self.n_outputs, dtype=np.int8)
        winner = int(np.argmax(activated)) if activated.size else -1
        if winner >= 0 and activated[winner] >= self.neuron_cfg.wta_threshold:
            spikes[winner] = 1
            inhibit = self.neuron_cfg.lateral_inhibition * activated[winner]
            self.v_mem -= inhibit
            self.v_mem[winner] = self.p.v_reset
        self.v_mem = np.maximum(self.v_mem, self.p.v_floor)
        return spikes, self.v_mem.copy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def step(
        self,
        x: np.ndarray,
        *,
        input_mode: str = "spike",
        apply_stdp: bool = False,
    ) -> Dict[str, np.ndarray]:
        i_cols, i_diff, aux = self.crossbar_mac(x, input_mode=input_mode)
        delay_ns, i_tdc = self.tdc_encode(i_diff, aux=aux)
        activated = self._apply_activation(i_diff, delay_ns)

        if self.neuron_cfg.output_mode == "wta":
            spikes, v_mem = self._wta_update(activated)
        else:
            lif_drive = self._lif_drive(i_diff, activated)
            spikes, v_mem = self._lif_update(lif_drive)

        if apply_stdp:
            pre_spikes = (np.asarray(x).reshape(-1) > 0).astype(np.int8)
            self._apply_stdp(pre_spikes, spikes)

        return {
            "column_currents_a": i_cols,
            "signed_currents_a": i_diff,
            "tdc_currents_a": i_tdc,
            "tdc_delays_ns": delay_ns,
            "activated": activated,
            "membrane": v_mem,
            "output_spikes": spikes,
            "input_source_voltages_v": aux["input_source_voltages_v"],
            "gate_state": aux["gate_state"],
            "source_node_voltages_v": aux["source_node_voltages_v"],
            "bitline_node_voltages_v": aux["bitline_node_voltages_v"],
            "cell_currents_a": aux["cell_currents_a"],
            "cell_conductance_eff_s": aux["cell_conductance_eff_s"],
            "read_margin": aux["read_margin"],
            "tau_cols_ns": aux["tau_cols_ns"],
            "tau_gate_rows_ns": aux["tau_gate_rows_ns"],
            "tau_source_rows_ns": aux["tau_source_rows_ns"],
            "static_column_currents_a": aux["static_column_currents_a"],
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
        act_hist = np.zeros((T, self.n_outputs), dtype=float)
        mem_hist = np.zeros((T, self.n_outputs), dtype=float)
        spike_hist = np.zeros((T, self.n_outputs), dtype=np.int8)
        gate_hist = np.zeros((T, self.rows), dtype=float)
        tau_hist = np.zeros((T, self.cols), dtype=float)
        rm_hist = np.zeros((T, self.rows, self.cols), dtype=float)

        for t in range(T):
            out = self.step(X[t], input_mode=input_mode, apply_stdp=apply_stdp)
            i_cols_hist[t] = out["column_currents_a"]
            i_diff_hist[t] = out["signed_currents_a"]
            i_tdc_hist[t] = out["tdc_currents_a"]
            delay_hist[t] = out["tdc_delays_ns"]
            act_hist[t] = out["activated"]
            mem_hist[t] = out["membrane"]
            spike_hist[t] = out["output_spikes"]
            gate_hist[t] = out["gate_state"]
            tau_hist[t] = out["tau_cols_ns"]
            rm_hist[t] = out["read_margin"]

        return {
            "input": X,
            "column_currents_a": i_cols_hist,
            "signed_currents_a": i_diff_hist,
            "tdc_currents_a": i_tdc_hist,
            "tdc_delays_ns": delay_hist,
            "activated": act_hist,
            "membrane": mem_hist,
            "output_spikes": spike_hist,
            "gate_state": gate_hist,
            "tau_cols_ns": tau_hist,
            "read_margin": rm_hist,
            "dt_ns": np.array(self.p.dt_ns),
        }

    def info(self) -> Dict[str, float]:
        base = {
            "rows": float(self.rows),
            "cols": float(self.cols),
            "signed_outputs": float(self.n_outputs),
            "g_hrs_uS": 1e6 * self.p.g_hrs_s,
            "g_lrs_uS": 1e6 * self.p.g_lrs_s,
            "levels": float(self.p.n_levels),
            "read_voltage_v": float(self.p.read_voltage_v),
            "switch_time_ns": float(self.p.switch_time_ns),
            "read_time_ns": float(self.p.read_time_ns),
            "tdc_ref_current_uA": 1e6 * self.p.tdc_ref_current_a,
            "estimated_energy_efficiency_topsw": float(self.p.estimated_energy_efficiency_topsw),
            "r_access_on_ohm_nominal": float(self.array_cfg.r_access_on_ohm),
            "source_wire_res_ohm_per_seg": float(self.array_cfg.source_wire_res_ohm),
            "bitline_wire_res_ohm_per_seg": float(self.array_cfg.bitline_wire_res_ohm),
            "gate_wire_res_ohm_per_seg": float(self.array_cfg.gate_wire_res_ohm),
            "source_connection_dsc": float(self.array_cfg.source_connection.lower() == "dsc"),
        }
        return base


def make_reram_1t1r_demo_model(seed: int = 1) -> ReRAMSNN32x32OneTOneR:
    model = ReRAMSNN32x32OneTOneR(
        seed=seed,
        enable_faults=False,
        n_outputs=8,
        array=OneTOneRArrayConfig(
            source_connection="dsc",
            gate_drive="always_on",
            r_access_on_ohm=1.5e3,
        ),
        neuron=MixedSignalNeuronConfig(
            activation="tdc_nonlinear",
            output_mode="lif",
            use_activation_before_lif=False,
        ),
    )
    return model
