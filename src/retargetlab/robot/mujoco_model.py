"""Derive a named MuJoCo kinematic model from a verified robot profile."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from retargetlab.contracts import RobotProfile
from retargetlab.robot.assets import _mesh_path, sha256_file, verify_robot_profile_asset
from retargetlab.robot.collision import parse_srdf_disabled_pairs


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def build_mujoco_model(
    profile: RobotProfile, output: Path, *, kinematic_inertia_repair: bool = False
) -> dict:
    """Copy source geometry, preserve the tree, and add explicit TCP sites.

    The result is a kinematic artifact. Native MuJoCo mesh contacts and inertias
    are not certified equivalent to the source collision/dynamics model.
    """
    import importlib.metadata

    import mujoco
    import trimesh

    urdf = verify_robot_profile_asset(profile)
    output = output.resolve()
    if output.exists() or output.is_relative_to(Path(profile.asset_dir).resolve()):
        raise ValueError("MuJoCo output must be a new directory outside source assets")
    tree = ET.parse(urdf)
    root = tree.getroot()
    inertia_repairs = []
    for link in root.findall("link"):
        inertia = link.find("inertial/inertia")
        if inertia is None:
            continue
        values = {k: float(inertia.get(k, "0")) for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")}
        matrix = np.array(
            [
                [values["ixx"], values["ixy"], values["ixz"]],
                [values["ixy"], values["iyy"], values["iyz"]],
                [values["ixz"], values["iyz"], values["izz"]],
            ]
        )
        eigenvalues = np.linalg.eigvalsh(matrix)
        if eigenvalues.min() <= 0:
            raise ValueError(
                f"nonpositive source inertia requires separate review: {link.get('name')}"
            )
        if eigenvalues[0] + eigenvalues[1] < eigenvalues[2]:
            if not kinematic_inertia_repair:
                raise ValueError(
                    "invalid source inertia; use explicit kinematic inertia repair"
                )
            mean = float(np.trace(matrix) / 3)
            replacement = {key: mean if key in ("ixx", "iyy", "izz") else 0.0 for key in values}
            inertia.attrib.update({k: repr(v) for k, v in replacement.items()})
            inertia_repairs.append(
                {
                    "link": link.get("name"),
                    "source": values,
                    "replacement": replacement,
                    "reason": "isotropic trace-preserving inertia for kinematic compilation only",
                }
            )
    if root.find("mujoco") is not None:
        raise ValueError("source has MuJoCo extensions; explicit reconciliation is required")
    movable = [j for j in root.findall("joint") if j.get("type") != "fixed"]
    if any(j.get("type") not in ("revolute", "prismatic") for j in movable):
        raise ValueError("this adapter supports fixed-body scalar bounded joints")
    declared = {n for g in profile.groups for n in g.joint_names + g.gripper_joint_names}
    if {j.get("name") for j in movable} != declared:
        raise ValueError("profile must declare every movable joint")
    output.mkdir(parents=True)
    (output / "meshes").mkdir()
    _write_json(output / "source-profile.json", profile.model_dump(mode="json"))
    shutil.copy2(urdf, output / "source.urdf")
    mesh_records, mesh_cache, geometry = [], {}, []
    for link in root.findall("link"):
        for kind in ("visual", "collision"):
            for index, element in enumerate(link.findall(kind)):
                name = f"{kind}__{link.get('name')}__{index}"
                element.set("name", name)
                geometry.append({"name": name, "link": link.get("name"), "kind": kind})
                mesh = element.find("geometry/mesh")
                if mesh is None:
                    continue
                source = _mesh_path(Path(profile.asset_dir), mesh.get("filename"))
                source_hash = sha256_file(source)
                scale = tuple(float(x) for x in mesh.get("scale", "1 1 1").split())
                if len(scale) != 3 or not np.isfinite(scale).all() or 0 in scale:
                    raise ValueError("mesh scale must have three finite nonzero values")
                cache_key = (source_hash, scale)
                if cache_key not in mesh_cache:
                    shape = trimesh.load_scene(source, process=False).to_mesh()
                    if not len(shape.vertices) or not len(shape.faces):
                        raise ValueError("source mesh is empty")
                    shape.apply_scale(scale)
                    if len(shape.faces) > 200000:
                        relative = f"meshes/mesh_{len(mesh_cache):03d}.obj"
                        shape.merge_vertices(digits_vertex=14)
                        shape.export(
                            output / relative,
                            file_type="obj",
                            digits=17,
                            include_normals=False,
                            include_color=False,
                            include_texture=False,
                        )
                    else:
                        relative = f"meshes/mesh_{len(mesh_cache):03d}.stl"
                        shape.export(output / relative, file_type="stl")
                    record = {
                        "source_reference": mesh.get("filename"),
                        "source_sha256": source_hash,
                        "source_scale": scale,
                        "generated_path": relative,
                        "generated_sha256": sha256_file(output / relative),
                        "scaled_bounds_m": shape.bounds.tolist(),
                        "vertices": len(shape.vertices),
                        "faces": len(shape.faces),
                    }
                    mesh_records.append(record)
                    mesh_cache[cache_key] = relative
                mesh.set("filename", mesh_cache[cache_key])
                mesh.set("scale", "1 1 1")
    mimic = []
    joint_specs = {}
    for joint in movable:
        name = joint.get("name")
        limit = joint.find("limit")
        joint_specs[name] = {
            "type": joint.get("type"),
            "lower": float(limit.get("lower")),
            "upper": float(limit.get("upper")),
            "velocity": float(limit.get("velocity")),
        }
        relation = joint.find("mimic")
        if relation is not None:
            mimic.append(
                {
                    "follower": name,
                    "driver": relation.get("joint"),
                    "multiplier": float(relation.get("multiplier", "1")),
                    "offset": float(relation.get("offset", "0")),
                }
            )
            joint.remove(relation)
    extension = ET.SubElement(root, "mujoco")
    ET.SubElement(
        extension,
        "compiler",
        {
            "fusestatic": "false",
            "discardvisual": "false",
            "strippath": "false",
            "inertiafromgeom": "false",
            "balanceinertia": "false",
        },
    )
    import_path = output / "import.urdf"
    tree.write(import_path, encoding="utf-8", xml_declaration=True)
    spec = mujoco.MjSpec.from_file(str(import_path))
    sites = {}
    for group in profile.groups:
        body = spec.body(group.end_effector_frame)
        if body is None:
            raise ValueError("TCP link was lost during URDF import")
        name = f"retarget_tcp__{group.name}"
        body.add_site(name=name, size=[0.008] * 3)
        sites[group.name] = {"site": name, "source_frame": group.end_effector_frame}
    reference_model = spec.compile()
    xml = ET.fromstring(spec.to_xml())

    # The default MJCF writer rounds to six significant digits. Restore the
    # compiled tree and scalar joint values before reloading the saved artifact.
    def numbers(values):
        return " ".join(format(float(v), ".17g") for v in np.atleast_1d(values))

    for body in xml.findall(".//body"):
        index = reference_model.body(body.get("name")).id
        body.set("pos", numbers(reference_model.body_pos[index]))
        body.set("quat", numbers(reference_model.body_quat[index]))
        inertial = body.find("inertial")
        if inertial is not None:
            inertial.set("pos", numbers(reference_model.body_ipos[index]))
            inertial.set("quat", numbers(reference_model.body_iquat[index]))
            inertial.set("mass", numbers(reference_model.body_mass[index]))
            inertial.set("diaginertia", numbers(reference_model.body_inertia[index]))
    for joint in xml.findall(".//joint"):
        if joint.get("name") not in joint_specs:
            continue
        index = reference_model.joint(joint.get("name")).id
        joint.set("pos", numbers(reference_model.jnt_pos[index]))
        joint.set("axis", numbers(reference_model.jnt_axis[index]))
        joint.set("range", numbers(reference_model.jnt_range[index]))
    compiler = xml.find("compiler")
    compiler.set("fusestatic", "false")
    compiler.set("discardvisual", "false")
    compiler.set("inertiafromgeom", "false")
    compiler.set("balanceinertia", "false")
    option = xml.find("option")
    if option is None:
        option = ET.SubElement(xml, "option")
    flag = option.find("flag")
    if flag is None:
        flag = ET.SubElement(option, "flag")
    flag.set("filterparent", "disable")
    disabled = set()
    if profile.collision is not None and profile.collision.srdf_path:
        srdf = Path(profile.asset_dir) / profile.collision.srdf_path
        disabled = parse_srdf_disabled_pairs(srdf)
        shutil.copy2(srdf, output / "source.srdf")
    if disabled:
        contact = ET.SubElement(xml, "contact")
        for first, second in sorted(disabled):
            ET.SubElement(contact, "exclude", body1=first, body2=second)
    if mimic:
        equality = ET.SubElement(xml, "equality")
        for item in mimic:
            ET.SubElement(
                equality,
                "joint",
                joint1=item["follower"],
                joint2=item["driver"],
                polycoef=f"{item['offset']} {item['multiplier']} 0 0 0",
            )
    for geom in xml.findall(".//geom"):
        name = geom.get("name", "")
        if "__openarm_left_" in name or "__Larm" in name:
            geom.set("rgba", "0.15 0.55 0.90 1")
        elif "__openarm_right_" in name or "__Rarm" in name:
            geom.set("rgba", "0.95 0.50 0.15 1")
    model_path = output / "model.xml"
    ET.ElementTree(xml).write(model_path, encoding="utf-8", xml_declaration=True)
    model = mujoco.MjModel.from_xml_path(str(model_path))
    joints = {}
    for name, reference in joint_specs.items():
        joint = model.joint(name)
        expected_type = (
            mujoco.mjtJoint.mjJNT_HINGE
            if reference["type"] == "revolute"
            else mujoco.mjtJoint.mjJNT_SLIDE
        )
        if joint.type[0] != expected_type or not joint.limited[0]:
            raise ValueError(f"joint type or limit changed: {name}")
        if not np.allclose(
            joint.range, [reference["lower"], reference["upper"]], atol=1e-8, rtol=0
        ):
            raise ValueError(f"joint range changed: {name}")
        joints[name] = {
            **reference,
            "qpos_address": int(joint.qposadr[0]),
            "qvel_address": int(joint.dofadr[0]),
        }
    if model.nq != len(joints) or model.nv != len(joints):
        raise ValueError("MuJoCo introduced or removed a movable degree of freedom")
    missing_geoms = [
        g["name"]
        for g in geometry
        if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, g["name"]) < 0
    ]
    if missing_geoms:
        raise ValueError(f"geometry lost during model import: {missing_geoms}")
    report = {
        "schema_version": "mujoco_model.0.1",
        "status": "COMPLETED",
        "robot_id": profile.robot_id,
        "root_frame": profile.root_frame,
        "model_path": "model.xml",
        "nq": model.nq,
        "nv": model.nv,
        "bodies": model.nbody,
        "geometries": model.ngeom,
        "tcp_sites": sites,
        "joints": joints,
        "mimic": mimic,
        "geometry_mapping": geometry,
        "mesh_conversion": mesh_records,
        "source_profile_sha256": sha256_file(output / "source-profile.json"),
        "source_urdf_sha256": profile.urdf_sha256,
        "srdf_exclusions": sorted(disabled),
        "inertia_policy": "explicit repair only; compiler balancing and inertia inference disabled",
        "inertia_repairs": inertia_repairs,
        "collision_status": "NATIVE_CONVEX_MESH_CONTACTS_NOT_VALIDATED_AGAINST_PINOCCHIO",
        "dynamics_status": "NOT_VALIDATED_NO_ACTUATORS",
        "visual_materials": "uniform arm colors; source texture materials not migrated",
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("mujoco", "mink", "trimesh", "pycollada")
        },
    }
    _write_json(output / "mujoco-model.json", report)
    _write_json(
        output / "manifest.json",
        {
            "status": "COMPLETED",
            "files": {
                p.relative_to(output).as_posix(): sha256_file(p)
                for p in output.rglob("*")
                if p.is_file() and p.name != "manifest.json"
            },
        },
    )
    return report


class MujocoKinematics:
    """Load a derived artifact and set scalar configurations by joint name."""

    def __init__(self, asset_dir: Path):
        import mujoco

        self.asset_dir = Path(asset_dir)
        manifest = json.loads((self.asset_dir / "manifest.json").read_text())
        for name, digest in manifest["files"].items():
            if sha256_file(self.asset_dir / name) != digest:
                raise ValueError(f"MuJoCo asset fingerprint changed: {name}")
        self.metadata = json.loads((self.asset_dir / "mujoco-model.json").read_text())
        self.model = mujoco.MjModel.from_xml_path(str(self.asset_dir / self.metadata["model_path"]))
        self.data = mujoco.MjData(self.model)

    def set_configuration(self, joint_names, values) -> None:
        import mujoco

        names, q = list(joint_names), np.asarray(values, dtype=float)
        if q.shape != (len(names),) or not np.isfinite(q).all():
            raise ValueError("configuration must be finite and match joint names")
        if len(set(names)) != len(names) or set(names) != set(self.metadata["joints"]):
            raise ValueError("configuration must name every scalar joint exactly once")
        positions = dict(zip(names, q, strict=True))
        for relation in self.metadata["mimic"]:
            expected = positions[relation["driver"]] * relation["multiplier"] + relation["offset"]
            if not np.isclose(positions[relation["follower"]], expected, atol=1e-9, rtol=0):
                raise ValueError("configuration violates the declared gripper mimic relation")
        for name, value in positions.items():
            self.data.qpos[self.metadata["joints"][name]["qpos_address"]] = value
        mujoco.mj_kinematics(self.model, self.data)

    def frame_pose(self, group: str) -> tuple[np.ndarray, np.ndarray]:
        """Return TCP position and rotation matrix relative to the declared root."""
        root = self.model.body(self.metadata["root_frame"]).id
        root_rotation = self.data.xmat[root].reshape(3, 3)
        site = self.model.site(self.metadata["tcp_sites"][group]["site"]).id
        p = root_rotation.T @ (self.data.site_xpos[site] - self.data.xpos[root])
        r = root_rotation.T @ self.data.site_xmat[site].reshape(3, 3)
        return p.copy(), r.copy()
