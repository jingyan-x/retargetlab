from retargetlab.contracts import DatasetReport, EpisodeReport, FrameDiagnostics, IKStatus
from retargetlab.diagnose.plot import plot_dataset_report


def make_report() -> DatasetReport:
    frame = FrameDiagnostics(
        frame_index=0,
        solver_status=IKStatus.CONVERGED,
        position_error_m=0.001,
        orientation_error_rad=0.01,
        collision_free=True,
        nominal=True,
        relaxed=True,
    )
    episodes = tuple(
        EpisodeReport(
            episode_index=index,
            frame_count=1,
            nominal_rate=1.0 if index == 0 else 0.0,
            relaxed_rate=1.0,
            collision_fraction=0.0,
            joint_limit_violation_fraction=0.0,
            delta_violation_fraction=0.0,
            status="PASS" if index == 0 else "WARN",
            frames=(frame,),
        )
        for index in range(2)
    )
    return DatasetReport(episode_count=2, episodes=episodes, status="WARN")


def test_static_plot_requires_optional_matplotlib_without_touching_report(
    tmp_path, monkeypatch
) -> None:
    import builtins

    original_import = builtins.__import__

    def reject_matplotlib(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("fixture hides optional matplotlib")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_matplotlib)
    output_path = tmp_path / "report.png"
    try:
        plot_dataset_report(make_report(), output_path)
    except RuntimeError as exc:
        assert "matplotlib" in str(exc)
    else:
        raise AssertionError("matplotlib unexpectedly available under the import guard")
    assert not output_path.exists()
