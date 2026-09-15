"""Release-facing commands and config files work outside the checkout directory."""

import json
import os
import subprocess
import sys
from pathlib import Path

from retargetlab import __version__


def test_module_cli_reports_version_and_help():
    version = subprocess.run(
        [sys.executable, "-m", "retargetlab", "--version"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert version.stdout.strip() == f"retargetlab {__version__}"
    help_text = subprocess.run(
        [sys.executable, "-m", "retargetlab", "--help"], text=True, capture_output=True, check=True
    ).stdout
    for command in ("demo-init", "process", "training-export", "replay-build", "verify-reader"):
        assert command in help_text


def test_demo_rejects_unregistered_source_before_creating_output(tmp_path):
    import pytest

    from retargetlab.demo import create_demo

    with pytest.raises(ValueError, match="checkout"):
        create_demo(tmp_path / "missing-source", tmp_path / "demo")
    assert not (tmp_path / "demo").exists()


def test_public_demo_runs_real_processing_and_export(tmp_path):
    import pytest

    source = os.environ.get("RETARGETLAB_OPENARM_PUBLIC_SOURCE")
    if not source:
        pytest.skip("pinned public OpenArm checkout required")
    pq = pytest.importorskip("pyarrow.parquet")
    pytest.importorskip("pinocchio")
    pytest.importorskip("av")
    from retargetlab.demo import create_demo
    from retargetlab.run.process import process_dataset
    from retargetlab.run.training_dataset import valid_window_indices
    from retargetlab.run.training_export import export_training_dataset

    demo = tmp_path / "demo"
    create_demo(Path(source), demo)
    process_dataset(demo / "process-pink.json", demo / "processed")
    binding = json.loads((demo / "processed/input-binding.json").read_text())
    assert binding["source_joint_columns_read"] is False
    assert binding["held_out_read"] is False
    result = export_training_dataset(
        demo / "processed", demo / "quality-policy.json", demo / "dataset"
    )
    rows = pq.read_table(demo / "dataset/data").to_pydict()
    assert len(rows["valid.retarget"]) == 192
    assert 0 < result["eligible_paired_rows"] < 192
    windows = valid_window_indices(
        rows["episode_index"], rows["frame_index"], rows["valid.retarget"], 16
    )
    assert len(windows) > 2
    for i in windows:
        assert all(rows["valid.retarget"][i : i + 16])
        assert len(set(rows["episode_index"][i : i + 16])) == 1
    assert result["videos_copied"] == 6
    assert result["baseline_evidence"]["kind"] == "SYNTHETIC"
