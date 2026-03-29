from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

try:
    from .reram_snn_32x32 import make_prototype_weights, make_temporal_pattern
    from .reram_snn_32x32_1t1r import (
        MixedSignalNeuronConfig,
        OneTOneRArrayConfig,
        ReRAMSNN32x32OneTOneR,
    )
except ImportError:  # pragma: no cover
    from reram_snn_32x32 import make_prototype_weights, make_temporal_pattern
    from reram_snn_32x32_1t1r import (
        MixedSignalNeuronConfig,
        OneTOneRArrayConfig,
        ReRAMSNN32x32OneTOneR,
    )


def make_model(gate_drive: str, seed: int, outputs: int) -> ReRAMSNN32x32OneTOneR:
    model = ReRAMSNN32x32OneTOneR(
        seed=seed,
        enable_faults=False,
        n_outputs=outputs,
        array=OneTOneRArrayConfig(
            source_connection="dsc",
            gate_drive=gate_drive,
            include_gate_dynamics=True,
            include_dynamic_settling=True,
            r_access_on_ohm=1.5e3,
        ),
        neuron=MixedSignalNeuronConfig(
            activation="tdc_nonlinear",
            output_mode="lif",
            use_activation_before_lif=False,
        ),
    )
    model.program_weights(make_prototype_weights(num_outputs=outputs, rows=32))
    return model


def make_pattern(rows: int, steps: int) -> np.ndarray:
    groups = np.array_split(np.arange(rows), 4)
    pat = np.zeros((steps, rows), dtype=float)
    for k, g in enumerate(groups):
        onset = 2 + 2 * k
        width = 2
        pat += make_temporal_pattern(rows, g, steps=steps, onset=onset, width=width)
    return np.clip(pat, 0.0, 1.0)


def save_trace(path: Path, data: np.ndarray, title: str, ylabel: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.2))
    for i in range(data.shape[1]):
        ax.plot(data[:, i], label=f"out{i}")
    ax.set_title(title)
    ax.set_xlabel("Time step")
    ax.set_ylabel(ylabel)
    ax.legend(ncol=min(4, data.shape[1]), fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_single_trace(path: Path, data: np.ndarray, title: str, ylabel: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.plot(data)
    ax.set_title(title)
    ax.set_xlabel("Time step")
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_heatmap(path: Path, data: np.ndarray, title: str) -> None:
    fig, ax = plt.subplots(figsize=(6, 4.5))
    im = ax.imshow(data, aspect="auto", interpolation="nearest")
    ax.set_title(title)
    ax.set_xlabel("Column")
    ax.set_ylabel("Row")
    fig.colorbar(im, ax=ax, shrink=0.82)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def summarize_run(model: ReRAMSNN32x32OneTOneR, pattern: np.ndarray) -> dict[str, np.ndarray | int]:
    out = model.run(pattern, reset_state=True)
    spikes = out["output_spikes"]
    spike_count = spikes.sum(axis=0)
    if np.all(spike_count == 0):
        winner = int(np.argmax(out["signed_currents_a"].sum(axis=0)))
    else:
        winner = int(np.argmax(spike_count))

    static = model.step(np.ones(model.rows), input_mode="spike")
    return {
        "winner": winner,
        "spike_count": spike_count,
        "signed_currents_a": out["signed_currents_a"],
        "tdc_delays_ns": out["tdc_delays_ns"],
        "membrane": out["membrane"],
        "gate_state": out["gate_state"],
        "read_margin_static": static["read_margin"],
        "tau_cols_ns": static["tau_cols_ns"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo for the generic ReRAM 1T1R 32x32 SNN/CIM model.")
    parser.add_argument("--save-dir", type=Path, default=Path("reram_1t1r_demo_out"))
    parser.add_argument("--outputs", type=int, default=4)
    parser.add_argument("--steps", type=int, default=14)
    parser.add_argument("--seed", type=int, default=5)
    args = parser.parse_args()

    args.save_dir.mkdir(parents=True, exist_ok=True)
    pattern = make_pattern(32, args.steps)

    model_always = make_model("always_on", args.seed, args.outputs)
    model_gated = make_model("input_gated", args.seed, args.outputs)

    always = summarize_run(model_always, pattern)
    gated = summarize_run(model_gated, pattern)

    save_trace(
        args.save_dir / "always_on_signed_currents.png",
        np.asarray(always["signed_currents_a"]),
        "1T1R always-on gates: signed output currents",
        "Current (A)",
    )
    save_trace(
        args.save_dir / "input_gated_signed_currents.png",
        np.asarray(gated["signed_currents_a"]),
        "1T1R input-gated WLs: signed output currents",
        "Current (A)",
    )
    save_trace(
        args.save_dir / "always_on_tdc_delays.png",
        np.asarray(always["tdc_delays_ns"]),
        "1T1R always-on gates: TDC delays",
        "Delay (ns)",
    )
    save_trace(
        args.save_dir / "input_gated_tdc_delays.png",
        np.asarray(gated["tdc_delays_ns"]),
        "1T1R input-gated WLs: TDC delays",
        "Delay (ns)",
    )

    gate_hist = np.asarray(gated["gate_state"])
    save_single_trace(
        args.save_dir / "input_gated_gate_row0.png",
        gate_hist[:, 0],
        "1T1R input-gated WL dynamics (row 0)",
        "Gate state",
    )
    save_heatmap(
        args.save_dir / "always_on_read_margin_static.png",
        np.asarray(always["read_margin_static"]),
        "1T1R always-on gates: read margin for dense active input",
    )
    save_heatmap(
        args.save_dir / "input_gated_read_margin_static.png",
        np.asarray(gated["read_margin_static"]),
        "1T1R input-gated WLs: read margin for dense active input",
    )

    tau_always = np.asarray(always["tau_cols_ns"])
    tau_gated = np.asarray(gated["tau_cols_ns"])
    summary = [
        "1T1R ReRAM SNN 32x32 demo",
        f"pattern_steps={args.steps}",
        f"outputs={args.outputs}",
        f"always_on_winner={always['winner']}",
        f"always_on_spike_count={np.asarray(always['spike_count']).tolist()}",
        f"input_gated_winner={gated['winner']}",
        f"input_gated_spike_count={np.asarray(gated['spike_count']).tolist()}",
        f"always_on_mean_tau_ns={float(np.mean(tau_always)):.4f}",
        f"input_gated_mean_tau_ns={float(np.mean(tau_gated)):.4f}",
        f"always_on_mean_read_margin={float(np.mean(np.asarray(always['read_margin_static']))):.4f}",
        f"input_gated_mean_read_margin={float(np.mean(np.asarray(gated['read_margin_static']))):.4f}",
    ]
    (args.save_dir / "summary.txt").write_text("\n".join(summary), encoding="utf-8")

    print("\n".join(summary))
    print(f"Saved results to: {args.save_dir}")


if __name__ == "__main__":
    main()
