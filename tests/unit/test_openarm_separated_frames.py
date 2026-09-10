"""Regression checks for TCP semantics and the single-arm gate."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness/m_minus_1"))
from diagnose_openarm_separated_frames import audit_tcp, check_fingerprint, gate


def target_urdf(tmp_path):
    root = ET.Element("robot")
    for side in ("left", "right"):
        for name, parent, child, xyz in (
            (
                f"{side}_openarm_hand_joint",
                f"openarm_{side}_link7",
                f"openarm_{side}_hand",
                "0 0 0.1001",
            ),
            (
                f"openarm_{side}_hand_tcp_joint",
                f"openarm_{side}_hand",
                f"openarm_{side}_hand_tcp",
                "0 0 0.08",
            ),
        ):
            joint = ET.SubElement(root, "joint", name=name, type="fixed")
            ET.SubElement(joint, "parent", link=parent)
            ET.SubElement(joint, "child", link=child)
            ET.SubElement(joint, "origin", xyz=xyz, rpy="0 0 0")
        for number, axis in ((1, "0 -1 0"), (2, "0 1 0")):
            joint = ET.SubElement(
                root, "joint", name=f"openarm_{side}_finger_joint{number}", type="prismatic"
            )
            ET.SubElement(joint, "parent", link=f"openarm_{side}_hand")
            ET.SubElement(joint, "axis", xyz=axis)
    path = tmp_path / "robot.urdf"
    ET.ElementTree(root).write(path)
    return path


def test_tcp_local_convention_matches_both_sides(tmp_path):
    result = audit_tcp(target_urdf(tmp_path))
    assert result["sides"]["left"] == result["sides"]["right"]
    assert result["sides"]["left"]["link7_to_tcp_translation_m"] == [0, 0, 0.1801]
    assert result["source_to_target_axis_pairing"] == "INFERRED_CANDIDATE"


@pytest.mark.parametrize("change", ["offset", "rotation", "finger_axis", "parent"])
def test_audit_rejects_changed_target_convention(tmp_path, change):
    path = target_urdf(tmp_path)
    tree = ET.parse(path)
    joint = tree.find("./joint[@name='openarm_right_hand_tcp_joint']")
    if change == "offset":
        joint.find("origin").set("xyz", "0 0 0.09")
    elif change == "rotation":
        joint.find("origin").set("rpy", "0 0 3.14159")
    elif change == "parent":
        joint.find("parent").set("link", "openarm_left_hand")
    else:
        tree.find("./joint[@name='openarm_right_finger_joint1']/axis").set("xyz", "1 0 0")
    tree.write(path)
    with pytest.raises(ValueError):
        audit_tcp(path)


def result(side, rate=0.8, violations=0):
    return {
        "arm": side,
        "aggregate": {
            "frame_count": 60,
            "nominal_rate": rate,
            "joint_limit_violation_fraction": violations,
        },
    }


def test_gate_requires_two_full_nominal_arms_without_limit_violations():
    assert gate([result("left"), result("right")], 60)
    assert not gate([result("left"), result("right", 0.79)], 60)
    assert not gate([result("left"), result("right", violations=0.01)], 60)
    assert not gate([result("left"), result("left")], 60)
    assert not gate([result("left"), result("right")], 12)


def test_changed_input_cannot_reuse_frozen_recipe(tmp_path):
    import hashlib

    path = tmp_path / "private-input"
    path.write_bytes(b"frozen")
    expected = hashlib.sha256(b"frozen").hexdigest()
    assert check_fingerprint(path, expected, "dataset") == expected
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="dataset differs from frozen recipe") as error:
        check_fingerprint(path, expected, "dataset")
    assert str(tmp_path) not in str(error.value)


def test_absent_input_cannot_match_missing_fingerprint(tmp_path):
    with pytest.raises(ValueError, match="dataset differs from frozen recipe"):
        check_fingerprint(tmp_path / "missing", None, "dataset")


def test_bimanual_gate_cannot_borrow_a_pass_from_changed_recipe():
    from copy import deepcopy

    from diagnose_openarm_separated_frames import validate_bimanual_prerequisite

    candidate = {"candidate_id": "same-id", "translation_offset_m": [0.25, -0.15, -0.15]}
    recipe = {
        "frame_mapping": {"tool": "data-derived"},
        "solve_options": {"max_iterations": 300},
        "reachability": {"position_tolerance": 0.005},
        "dataset": {"revision": "frozen"},
        "robot": {"manifest_hash": "frozen"},
        "t2": {
            "separated_candidates": [candidate],
            "anchor": {"seed": 1},
            "budget": {"fractions": [0, 0.25, 0.5, 0.75, 1]},
        },
    }
    report = {
        "candidate": candidate,
        "single_arm_results": [result("left"), result("right")],
        "sampling": {"split": "calibration", "frame_count": 60, "held_out_read": False},
    }
    validate_bimanual_prerequisite(report, recipe, recipe)
    changed = deepcopy(recipe)
    changed["t2"]["separated_candidates"][0]["translation_offset_m"][0] = 0.30
    with pytest.raises(ValueError, match="candidate differs"):
        validate_bimanual_prerequisite(report, recipe, changed)
    changed = deepcopy(recipe)
    changed["reachability"]["position_tolerance"] = 0.01
    with pytest.raises(ValueError, match="reachability differs"):
        validate_bimanual_prerequisite(report, recipe, changed)
    report["single_arm_results"][0]["aggregate"]["nominal_rate"] = 0.79
    with pytest.raises(ValueError, match="must pass"):
        validate_bimanual_prerequisite(report, recipe, recipe)
