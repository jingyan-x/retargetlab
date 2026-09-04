import importlib.metadata
import inspect

import pytest


@pytest.mark.lerobot
def test_lerobot_061_dataset_loader_api() -> None:
    """Pin the optional acceptance test to the documented 0.6.1 API."""

    pytest.importorskip("lerobot")
    for dependency in ("torch", "datasets", "huggingface_hub"):
        pytest.importorskip(dependency)

    try:
        version = importlib.metadata.version("lerobot")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("lerobot is available only as an uninstalled source checkout")
    assert version == "0.6.1"

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    parameters = inspect.signature(LeRobotDataset).parameters
    for name in ("repo_id", "root", "episodes", "download_videos"):
        assert name in parameters
