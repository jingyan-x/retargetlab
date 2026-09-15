"""MQ03 fixed-body target adapter; source joints never enter inverse kinematics."""

import hashlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from retargetlab.contracts import KinematicGroup, Pose, RobotProfile

ARMS = {
    s: tuple(f"{p}arm{i}_Joint" for i in range(1, 8)) for s, p in [("left", "L"), ("right", "R")]
}
LOCKS = {"Waist1_Joint": 0.23, "Waist2_Joint": math.radians(19.48), "Waist3_Joint": 0.0}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_profile(source, output):
    source, output = Path(source), Path(output)
    root = ET.parse(source).getroot()
    joints = {j.get("name"): j for j in root.findall("joint")}
    expected = set(sum(ARMS.values(), ()))
    if not expected <= joints.keys() or not LOCKS.keys() <= joints.keys():
        raise ValueError("MQ03 arm or waist joints missing")
    if any(joints[n].get("type") != "revolute" for n in expected):
        raise ValueError("MQ03 arm joints must be revolute")
    locked = {}
    for name, joint in joints.items():
        if name in expected or joint.get("type") == "fixed":
            continue
        value = LOCKS.get(name, 0.0)
        kind = joint.get("type")
        if kind not in ("prismatic", "revolute", "continuous"):
            raise ValueError("unsupported locked joint type")
        origin = joint.find("origin")
        if origin is None:
            origin = ET.SubElement(joint, "origin", xyz="0 0 0", rpy="0 0 0")
        xyz = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ")
        rotation = Rotation.from_euler("xyz", np.fromstring(origin.get("rpy", "0 0 0"), sep=" "))
        axis = np.fromstring(joint.find("axis").get("xyz"), sep=" ")
        if kind == "prismatic":
            xyz += rotation.apply(axis * value)
        else:
            rotation = rotation * Rotation.from_rotvec(axis * value)
        origin.set("xyz", " ".join(map(str, xyz)))
        origin.set("rpy", " ".join(map(str, rotation.as_euler("xyz"))))
        joint.set("type", "fixed")
        for tag in ("axis", "limit", "dynamics", "mimic"):
            for child in joint.findall(tag):
                joint.remove(child)
        locked[name] = value
    for side, prefix in [("left", "L"), ("right", "R")]:
        ET.SubElement(root, "link", name=f"{side}_tcp")
        j = ET.SubElement(root, "joint", name=f"{side}_tcp_fixed", type="fixed")
        ET.SubElement(j, "parent", link=f"{prefix}arm08_link")
        ET.SubElement(j, "child", link=f"{side}_tcp")
        ET.SubElement(j, "origin", xyz="0 0 0.22855", rpy="0 0 0")
    # Explicit kinematics-only artifact: unavailable meshes are not fabricated.
    for link in root.findall("link"):
        for tag in ("visual", "collision"):
            for element in link.findall(tag):
                link.remove(element)
    output.mkdir(parents=True, exist_ok=False)
    urdf = output / "mq03_fixed_body.urdf"
    ET.ElementTree(root).write(urdf, encoding="utf-8", xml_declaration=True)
    profile = RobotProfile(
        robot_id="moqi_mq03_fixed_body",
        asset_dir=str(output.resolve()),
        urdf_path=urdf.name,
        urdf_sha256=sha(urdf),
        root_frame="base_link",
        groups=tuple(
            KinematicGroup(name=s, joint_names=names, end_effector_frame=f"{s}_tcp")
            for s, names in ARMS.items()
        ),
        metadata={
            "source_urdf_sha256": sha(source),
            "collision": "NOT_EVALUATED_missing_mesh_assets",
            "gripper": "fixed_geometry_only",
            "tcp_offset_m": "0.22855",
        },
    )
    return profile, locked


def eef_poses(values):
    a = np.asarray(values, dtype=float)
    if a.shape != (16,) or not np.isfinite(a).all():
        raise ValueError("EEF layout must be finite 16-vector")
    return {
        s: Pose(
            position_m=tuple(a[b + 5 : b + 8]),
            quaternion_wxyz=tuple(a[b + 1 : b + 5]),
            frame="base_link",
        )
        for s, b in [("left", 0), ("right", 8)]
    }
