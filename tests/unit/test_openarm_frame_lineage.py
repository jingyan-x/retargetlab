from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[2]
    / "harness"
    / "m_minus_1"
    / "inspect_openarm_frame_lineage.py"
)
SPEC = importlib.util.spec_from_file_location("inspect_openarm_frame_lineage", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_schema_presence_is_distinguished_from_mapping_missing(tmp_path: Path) -> None:
    info_path = tmp_path / "info.json"
    info_path.write_text(
        json.dumps(
            {
                "features": {
                    "observation.state": {
                        "shape": [16],
                        "names": [
                            "gripper_0",
                            "epos_0_qw",
                            "epos_0_qx",
                            "epos_0_qy",
                            "epos_0_qz",
                            "epos_0_x",
                            "epos_0_y",
                            "epos_0_z",
                            "gripper_1",
                            "epos_1_qw",
                            "epos_1_qx",
                            "epos_1_qy",
                            "epos_1_qz",
                            "epos_1_x",
                            "epos_1_y",
                            "epos_1_z",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    mapping = {
        "coordinate_frame": "UNRESOLVED",
        "streams": [],
        "metadata": {"slot_semantics": "slot_0/slot_1; unresolved"},
    }
    mapping_checks = MODULE.inspect_mapping(mapping)
    info = MODULE.inspect_dataset_info(info_path)
    evidence = MODULE.build_evidence_map(
        mapping_checks,
        info,
        {"fields": {}},
    )
    assert info["present"] is True
    assert info["observation_state_layout_explicit"] is True
    assert mapping_checks["mapping_position_unit_present"] is False
    assert evidence["observation_state_layout"]["evidence"] == "EXPLICIT"
    assert evidence["position_unit"]["evidence"] == "UNRESOLVED"
    assert evidence["source_world_axes"]["evidence"] == "UNRESOLVED"


def test_value_free_mapping_record_preserves_evidence_levels(tmp_path: Path) -> None:
    record_path = tmp_path / "mapping.json"
    record_path.write_text(
        json.dumps(
            {
                "known": {
                    "position_unit": {
                        "value": "m",
                        "evidence": "DATA_DERIVED",
                        "evidence_scope": "synthetic fixture",
                    }
                },
                "unresolved": {
                    "source_pose_direction": {
                        "value": None,
                        "evidence": "UNRESOLVED",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    record = MODULE.inspect_semantics_record(record_path)
    assert record["parseable"] is True
    assert record["fields"]["position_unit"]["evidence"] == "DATA_DERIVED"
    assert record["fields"]["source_pose_direction"]["evidence"] == "UNRESOLVED"
    assert MODULE.inspect_optional_source(None)["provided"] is False
