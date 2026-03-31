from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class RRAMModelParams:
    """Two-timescale compact model for an RRAM cell embedded in a neuron readout.

    The model is intentionally compact and phenomenological so that it matches the
    user's observations directly:
      - fast relaxation over the first ~2000 s
      - a 2-3x change from the immediately programmed state to the relaxed state
      - retention controlled by pulse modulation (square vs ramp)

    Notes
    -----
    * HRS/LRS drift direction was not specified by the user, so this implementation
      assumes symmetric drift toward a neutral reference conductance.
    * Programming sets an overshoot in the fast state x_f and a smaller core state x_s.
      The conductance is exponential in x_f, which naturally produces the observed
      2-3x drift using a modest state excursion.
    """

    tau_relax_s: float = 600.0
    relax_window_s: float = 2000.0
    tau_ret_square_s: float = 1.0e3
    tau_ret_ramp_s: float = 1.0e5
    x_fast0: float = 1.0
    x_core0: float = 0.4
    g_ref: float = 1.0

    # beta is chosen so that exp(beta * (x_fast0 - x_core0)) ~= 2.5,
    # i.e. the fast relaxation changes the effective conductance by 2-3x.
    beta: float = math.log(2.5) / (1.0 - 0.4)

    # LIF readout parameters
    tau_m_s: float = 0.02
    v_rest: float = 0.0
    v_reset: float = 0.0
    v_th: float = 1.0
    refractory_s: float = 0.003
    readout_gain: float = 130.0

    # Input burst used in the example test cases
    burst_duration_s: float = 0.5
    pulse_start_s: float = 0.05
    pulse_width_s: float = 0.004
    pulse_period_s: float = 0.02
    pulse_count: int = 15


P = RRAMModelParams()

# --- Plot styling ----------------------------------------------------------

BG = "#0b0b0f"
FG = "#f8f9fa"
GRID = "#2b2d42"
ACCENT_BLUE = "#4cc9f0"
ACCENT_PINK = "#f72585"
ACCENT_GREEN = "#90be6d"
ACCENT_GOLD = "#f9c74f"
ACCENT_GRAY = "#adb5bd"


def apply_plot_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": BG,
            "axes.facecolor": BG,
            "savefig.facecolor": BG,
            "axes.edgecolor": FG,
            "axes.labelcolor": FG,
            "xtick.color": FG,
            "ytick.color": FG,
            "text.color": FG,
            "axes.titlecolor": FG,
            "grid.color": GRID,
            "legend.edgecolor": GRID,
            "legend.facecolor": BG,
            "font.size": 11,
            "font.family": "DejaVu Sans",
        }
    )


# --- Device model ----------------------------------------------------------


def tau_retention(modulation: str, params: RRAMModelParams = P) -> float:
    mod = modulation.lower()
    if mod == "square":
        return params.tau_ret_square_s
    if mod == "ramp":
        return params.tau_ret_ramp_s
    raise ValueError(f"Unknown modulation '{modulation}'. Use 'square' or 'ramp'.")


def simulate_rram_trajectory(
    age_max_s: float,
    dt_s: float = 1.0,
    state: str = "LRS",
    modulation: str = "ramp",
    params: RRAMModelParams = P,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Simulate fast/slow RRAM states and effective conductance over device age."""

    state_sign = 1.0 if state.upper() == "LRS" else -1.0
    tau_ret_s = tau_retention(modulation, params)

    n = int(age_max_s / dt_s) + 1
    age_s = np.linspace(0.0, age_max_s, n)
    x_fast = np.zeros(n, dtype=float)
    x_slow = np.zeros(n, dtype=float)

    # Immediately after programming: fast state overshoot + smaller stable core.
    x_fast[0] = state_sign * params.x_fast0
    x_slow[0] = state_sign * params.x_core0

    for i in range(1, n):
        t_prev = age_s[i - 1]

        # Separate the first 2000 s (relaxation) from long-term retention.
        if t_prev < params.relax_window_s:
            dx_slow = 0.0
        else:
            dx_slow = -(x_slow[i - 1]) / tau_ret_s

        x_slow[i] = x_slow[i - 1] + dt_s * dx_slow

        dx_fast = -(x_fast[i - 1] - x_slow[i - 1]) / params.tau_relax_s
        x_fast[i] = x_fast[i - 1] + dt_s * dx_fast

    conductance = params.g_ref * np.exp(params.beta * x_fast)
    return age_s, x_fast, x_slow, conductance


def conductance_at_age(
    age_s: float,
    state: str,
    modulation: str,
    params: RRAMModelParams = P,
    age_max_s: float | None = None,
    dt_s: float = 1.0,
) -> float:
    """Convenience interpolation helper for conductance at a specific device age."""

    sim_max = max(age_s, age_max_s or age_s)
    t, _, _, g = simulate_rram_trajectory(sim_max, dt_s=dt_s, state=state, modulation=modulation, params=params)
    return float(np.interp(age_s, t, g))


# --- Neuron readout --------------------------------------------------------


def make_pulse_train(
    total_s: float,
    dt_s: float,
    start_s: float,
    width_s: float,
    period_s: float,
    count: int,
    amplitude: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    t = np.arange(0.0, total_s + dt_s, dt_s)
    u = np.zeros_like(t)
    for k in range(count):
        pulse_start = start_s + k * period_s
        pulse_end = pulse_start + width_s
        u[(t >= pulse_start) & (t < pulse_end)] = amplitude
    return t, u


def lif_readout(
    g_age: float,
    dt_s: float = 1.0e-4,
    params: RRAMModelParams = P,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """LIF membrane response for a fixed RRAM conductance at a given age."""

    t, u = make_pulse_train(
        total_s=params.burst_duration_s,
        dt_s=dt_s,
        start_s=params.pulse_start_s,
        width_s=params.pulse_width_s,
        period_s=params.pulse_period_s,
        count=params.pulse_count,
        amplitude=1.0,
    )

    v = np.zeros_like(t)
    refractory_steps = max(1, int(params.refractory_s / dt_s))
    ref_count = 0
    spikes: list[float] = []

    for i in range(1, len(t)):
        if ref_count > 0:
            v[i] = params.v_reset
            ref_count -= 1
            continue

        dv = dt_s * (
            (params.v_rest - v[i - 1]) / params.tau_m_s
            + params.readout_gain * g_age * u[i - 1]
        )
        v[i] = v[i - 1] + dv

        if v[i] >= params.v_th:
            spikes.append(float(t[i]))
            v[i] = params.v_reset
            ref_count = refractory_steps

    return t, u, v, np.asarray(spikes, dtype=float)


def spike_rate_hz(spikes: np.ndarray, duration_s: float) -> float:
    return float(len(spikes) / duration_s)


# --- Figure generation -----------------------------------------------------


def plot_relaxation(out_file: Path, params: RRAMModelParams = P) -> None:
    apply_plot_style()
    age_max = 4000
    t_lrs, _, _, g_lrs = simulate_rram_trajectory(age_max_s=age_max, state="LRS", modulation="ramp", params=params)
    t_hrs, _, _, g_hrs = simulate_rram_trajectory(age_max_s=age_max, state="HRS", modulation="ramp", params=params)

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=200)
    ax.plot(t_lrs, g_lrs, lw=2.7, color=ACCENT_BLUE, label="LRS → relaxes downward")
    ax.plot(t_hrs, g_hrs, lw=2.7, color=ACCENT_PINK, label="HRS → relaxes upward")
    ax.axvline(params.relax_window_s, color=ACCENT_GRAY, lw=1.5, ls="--", alpha=0.85)
    ax.text(
        params.relax_window_s + 70,
        4.8,
        "~2000 s\nrelaxation window",
        color=ACCENT_GRAY,
        fontsize=10,
        va="top",
    )
    ax.set_xlim(0, age_max)
    ax.set_ylim(0, 5.0)
    ax.set_xlabel("Age after programming (s)")
    ax.set_ylabel("Normalized conductance $G/G_{ref}$")
    ax.set_title("Fast relaxation captured as a volatile state converging to a stable core")
    ax.grid(True, alpha=0.55)
    ax.legend(loc="upper right", fontsize=9)

    # Annotate the ~2.5x drift between the immediate and relaxed value.
    idx_relaxed = int(params.relax_window_s)
    ratio_lrs = g_lrs[0] / g_lrs[idx_relaxed]
    ratio_hrs = g_hrs[idx_relaxed] / g_hrs[0]
    ax.text(
        210,
        4.3,
        f"LRS change ≈ {ratio_lrs:.1f}×",
        color=ACCENT_BLUE,
        fontsize=10,
    )
    ax.text(
        210,
        0.82,
        f"HRS change ≈ {ratio_hrs:.1f}×",
        color=ACCENT_PINK,
        fontsize=10,
    )

    fig.tight_layout()
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)



def plot_retention(out_file: Path, params: RRAMModelParams = P) -> None:
    apply_plot_style()
    age_max = 100_000
    t_sq, _, _, g_sq = simulate_rram_trajectory(age_max_s=age_max, state="LRS", modulation="square", params=params)
    t_rm, _, _, g_rm = simulate_rram_trajectory(age_max_s=age_max, state="LRS", modulation="ramp", params=params)

    # Normalize contrast after the 2000 s relaxation window so retention is isolated.
    idx0 = int(params.relax_window_s)
    contrast_sq = np.abs(g_sq - params.g_ref) / np.abs(g_sq[idx0] - params.g_ref)
    contrast_rm = np.abs(g_rm - params.g_ref) / np.abs(g_rm[idx0] - params.g_ref)

    mask = t_sq >= params.relax_window_s

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=200)
    ax.plot(t_sq[mask], contrast_sq[mask], lw=2.7, color=ACCENT_GOLD, label="Square pulse: $\\tau_{ret} = 10^3$ s")
    ax.plot(t_rm[mask], contrast_rm[mask], lw=2.7, color=ACCENT_GREEN, label="Ramp pulse: $\\tau_{ret} = 10^5$ s")
    ax.set_xscale("log")
    ax.set_xlim(params.relax_window_s, age_max)
    ax.set_ylim(0, 1.08)
    ax.set_xlabel("Age after programming (s)")
    ax.set_ylabel("Retained contrast (normalized at 2000 s)")
    ax.set_title("Pulse modulation selects the long-term retention time")
    ax.grid(True, which="both", alpha=0.55)
    ax.legend(loc="upper right", fontsize=9)
    ax.axvline(1.0e3, color=ACCENT_GOLD, lw=1.0, ls=":", alpha=0.6)
    ax.axvline(1.0e5, color=ACCENT_GREEN, lw=1.0, ls=":", alpha=0.6)

    fig.tight_layout()
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)



def _format_trace_axes(axs: Iterable[plt.Axes]) -> None:
    for ax in axs:
        ax.grid(True, alpha=0.5)
        for spine in ax.spines.values():
            spine.set_alpha(0.85)



def plot_trace_hrs_vs_lrs(out_file: Path, age_s: float = 1500.0, params: RRAMModelParams = P) -> None:
    apply_plot_style()
    g_lrs = conductance_at_age(age_s, state="LRS", modulation="ramp", params=params, age_max_s=max(10_000, age_s))
    g_hrs = conductance_at_age(age_s, state="HRS", modulation="ramp", params=params, age_max_s=max(10_000, age_s))
    t, u, v_lrs, spikes_lrs = lif_readout(g_lrs, params=params)
    _, _, v_hrs, spikes_hrs = lif_readout(g_hrs, params=params)

    fig, axs = plt.subplots(2, 1, figsize=(7.0, 4.8), dpi=200, sharex=True, height_ratios=[1.0, 3.0])
    axs[0].plot(t * 1000.0, u, color=ACCENT_GRAY, lw=2.0)
    axs[0].set_ylabel("Input")
    axs[0].set_ylim(-0.05, 1.15)
    axs[0].set_title(f"Same burst read at age = {age_s:.0f} s (after fast relaxation, before long decay)")

    axs[1].plot(t * 1000.0, v_lrs, color=ACCENT_BLUE, lw=2.2, label=f"LRS  |  G={g_lrs:.2f}  |  {len(spikes_lrs)} spikes")
    axs[1].plot(t * 1000.0, v_hrs, color=ACCENT_PINK, lw=2.2, label=f"HRS  |  G={g_hrs:.2f}  |  {len(spikes_hrs)} spikes")
    axs[1].axhline(params.v_th, color=ACCENT_GRAY, lw=1.5, ls="--", label="threshold")
    axs[1].set_xlabel("Readout time within burst (ms)")
    axs[1].set_ylabel("Membrane voltage")
    axs[1].set_ylim(-0.02, 1.1)
    axs[1].legend(loc="upper right", fontsize=8)
    _format_trace_axes(axs)
    fig.tight_layout()
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)



def plot_trace_square_vs_ramp(out_file: Path, age_s: float = 50_000.0, params: RRAMModelParams = P) -> None:
    apply_plot_style()
    g_sq = conductance_at_age(age_s, state="LRS", modulation="square", params=params, age_max_s=max(100_000, age_s))
    g_rm = conductance_at_age(age_s, state="LRS", modulation="ramp", params=params, age_max_s=max(100_000, age_s))
    t, u, v_sq, spikes_sq = lif_readout(g_sq, params=params)
    _, _, v_rm, spikes_rm = lif_readout(g_rm, params=params)

    fig, axs = plt.subplots(2, 1, figsize=(7.0, 4.8), dpi=200, sharex=True, height_ratios=[1.0, 3.0])
    axs[0].plot(t * 1000.0, u, color=ACCENT_GRAY, lw=2.0)
    axs[0].set_ylabel("Input")
    axs[0].set_ylim(-0.05, 1.15)
    axs[0].set_title(f"Late-age readout at age = {age_s/1000.0:.0f} ks")

    axs[1].plot(t * 1000.0, v_sq, color=ACCENT_GOLD, lw=2.2, label=f"Square pulse  |  G={g_sq:.2f}  |  {len(spikes_sq)} spikes")
    axs[1].plot(t * 1000.0, v_rm, color=ACCENT_GREEN, lw=2.2, label=f"Ramp pulse    |  G={g_rm:.2f}  |  {len(spikes_rm)} spikes")
    axs[1].axhline(params.v_th, color=ACCENT_GRAY, lw=1.5, ls="--", label="threshold")
    axs[1].set_xlabel("Readout time within burst (ms)")
    axs[1].set_ylabel("Membrane voltage")
    axs[1].set_ylim(-0.02, 1.1)
    axs[1].legend(loc="upper right", fontsize=8)
    _format_trace_axes(axs)
    fig.tight_layout()
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)



def plot_firing_rate_vs_age(out_file: Path, params: RRAMModelParams = P) -> None:
    apply_plot_style()
    ages = np.logspace(0, 5, 36)
    rates: dict[str, list[float]] = {"square": [], "ramp": []}

    for modulation in rates.keys():
        age_sim_max = 100_000
        t_age, _, _, g = simulate_rram_trajectory(age_max_s=age_sim_max, state="LRS", modulation=modulation, params=params)
        for age in ages:
            g_age = float(np.interp(age, t_age, g))
            _, _, _, spikes = lif_readout(g_age, params=params)
            rates[modulation].append(spike_rate_hz(spikes, params.burst_duration_s))

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=200)
    ax.plot(ages, rates["square"], color=ACCENT_GOLD, lw=2.7, marker="o", ms=3.5, label="Square-programmed LRS")
    ax.plot(ages, rates["ramp"], color=ACCENT_GREEN, lw=2.7, marker="o", ms=3.5, label="Ramp-programmed LRS")
    ax.set_xscale("log")
    ax.set_xlim(1.0, 100_000.0)
    ax.set_ylim(-1.0, 32.0)
    ax.set_xlabel("Age after programming (s)")
    ax.set_ylabel("Output firing rate (Hz)")
    ax.set_title("Same burst, same neuron: only retention age and pulse modulation change")
    ax.grid(True, which="both", alpha=0.55)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)



def generate_all_figures(out_dir: Path, params: RRAMModelParams = P) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_relaxation(out_dir / "relaxation.png", params=params)
    plot_retention(out_dir / "retention.png", params=params)
    plot_trace_hrs_vs_lrs(out_dir / "trace_hrs_vs_lrs.png", params=params)
    plot_trace_square_vs_ramp(out_dir / "trace_square_vs_ramp.png", params=params)
    plot_firing_rate_vs_age(out_dir / "firing_rate_vs_age.png", params=params)


# --- CLI -------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact two-timescale RRAM neuron model and figure generator.")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("plots"),
        help="Directory where PNG figures will be written.",
    )
    args = parser.parse_args()
    generate_all_figures(args.outdir)
    print(f"Wrote figures to {args.outdir.resolve()}")


if __name__ == "__main__":
    main()
