"""Reproducible run workspace and report helpers."""

from .calibration_report import render_calibration_summary
from .coverage import write_dataset_coverage
from .decision import verify_review_decision_artifact, write_review_decision_artifact
from .execute import SolveRunResult, execute_solve_run, solve_canonical_stream
from .export_gate import build_export_input_gate, write_export_input_gate
from .export_profile import write_export_profile
from .export_table import (
    build_synthetic_table_write_preflight,
    build_synthetic_table_write_report,
    verify_synthetic_table_write_preflight,
    verify_synthetic_table_write_report,
    write_synthetic_table_write_preflight,
    write_synthetic_table_write_report,
)
from .fingerprint import canonical_json_bytes, recipe_sha256
from .gripper import map_target_grippers, write_target_gripper_trajectory
from .preflight import verify_review_package_preflight, write_review_package_preflight
from .profile import load_executable_data_profile, verify_data_profile, write_data_profile
from .replay import (
    build_target_replay_bundle,
    build_target_replay_manifest,
    build_target_replay_trajectory,
    verify_target_replay_bundle,
    verify_target_replay_manifest,
    verify_target_replay_trajectory,
    write_target_replay_bundle,
    write_target_replay_manifest,
    write_target_replay_trajectory,
)
from .report import write_dataset_report
from .review import write_calibration_run, write_review_run_artifact
from .robot_profile import write_robot_profile
from .verify import verify_calibration_run
from .workspace import RunWorkspace, create_run_workspace

__all__ = [
    "RunWorkspace",
    "SolveRunResult",
    "canonical_json_bytes",
    "create_run_workspace",
    "execute_solve_run",
    "recipe_sha256",
    "render_calibration_summary",
    "write_review_decision_artifact",
    "verify_review_decision_artifact",
    "solve_canonical_stream",
    "write_dataset_report",
    "write_calibration_run",
    "write_review_package_preflight",
    "verify_review_package_preflight",
    "write_data_profile",
    "write_robot_profile",
    "write_export_profile",
    "build_export_input_gate",
    "write_export_input_gate",
    "build_synthetic_table_write_preflight",
    "build_synthetic_table_write_report",
    "write_synthetic_table_write_preflight",
    "write_synthetic_table_write_report",
    "verify_synthetic_table_write_preflight",
    "verify_synthetic_table_write_report",
    "map_target_grippers",
    "write_target_gripper_trajectory",
    "build_target_replay_manifest",
    "build_target_replay_bundle",
    "build_target_replay_trajectory",
    "write_target_replay_manifest",
    "write_target_replay_trajectory",
    "write_target_replay_bundle",
    "verify_target_replay_trajectory",
    "verify_target_replay_bundle",
    "verify_target_replay_manifest",
    "write_dataset_coverage",
    "verify_data_profile",
    "load_executable_data_profile",
    "write_review_run_artifact",
    "verify_calibration_run",
]
