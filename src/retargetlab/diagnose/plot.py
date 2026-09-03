"""Optional static plots derived only from diagnostic report metrics."""

from __future__ import annotations

from pathlib import Path

from retargetlab.contracts import DatasetReport


def plot_dataset_report(report: DatasetReport, output_path: Path) -> Path:
    """Save a report-rate plot once; no joint or pose values are plotted."""

    if output_path.exists():
        raise FileExistsError(f"plot output already exists: {output_path}")
    try:
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("matplotlib is required for static report plots") from exc

    episodes = [episode.episode_index for episode in report.episodes]
    nominal = [episode.nominal_rate for episode in report.episodes]
    relaxed = [episode.relaxed_rate for episode in report.episodes]
    collision = [episode.collision_fraction for episode in report.episodes]
    limit = [episode.joint_limit_violation_fraction for episode in report.episodes]
    delta = [episode.delta_violation_fraction for episode in report.episodes]

    figure, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    axes[0].plot(episodes, nominal, marker="o", label="nominal rate")
    axes[0].plot(episodes, relaxed, marker="o", label="relaxed rate")
    axes[0].set_ylabel("rate")
    axes[0].set_ylim(0.0, 1.0)
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(episodes, collision, marker="o", label="collision invalid")
    axes[1].plot(episodes, limit, marker="o", label="limit invalid")
    axes[1].plot(episodes, delta, marker="o", label="delta invalid")
    axes[1].set_xlabel("episode index")
    axes[1].set_ylabel("fraction")
    axes[1].set_ylim(0.0, 1.0)
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    figure.suptitle(f"RetargetLab diagnostic status: {report.status}")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)
    return output_path
