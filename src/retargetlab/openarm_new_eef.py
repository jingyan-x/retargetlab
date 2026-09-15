"""Explicit OpenArm sidecar adapter and independent bounded pose IK.

Source joint columns are deliberately outside this module's interface.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def validate_manifest(root: Path, target_urdf: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text())
    expected = {
        "format": "openarm_eef_sidecar.v1",
        "pose_columns": [
            f"{side}.{part}"
            for side in ("left", "right")
            for part in ("x_m", "y_m", "z_m", "qw", "qx", "qy", "qz", "gripper_raw")
        ],
        "root_frame": "world (URDF model root; no external lab-world calibration applied)",
        "quaternion_order": "wxyz",
        "pose_direction": "T_world_tcp maps TCP-local coordinates into URDF world",
        "tcp_frames": ["openarm_left_hand_tcp", "openarm_right_hand_tcp"],
        "link7_to_tcp_translation_m": [0, 0, 0.1801],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"incompatible sidecar semantics: {key}")
    expected_hash = manifest["fingerprints"]["urdf"]
    for path in (root / "assets/source_openarm.urdf", target_urdf):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("identity mapping requires identical source and target URDF")
    return manifest


def decode_targets(vector):
    """Decode meters/wxyz into two world-to-hand-TCP SE3 targets."""
    import pinocchio as pin

    values = np.asarray(vector, dtype=float)
    if values.shape != (16,) or not np.isfinite(values).all():
        raise ValueError("EEF vector must have 16 finite values")
    targets = []
    for offset in (0, 8):
        wxyz = values[offset + 3 : offset + 7]
        if abs(np.linalg.norm(wxyz) - 1) > 1e-6:
            raise ValueError("EEF quaternion must be unit wxyz")
        rotation = pin.Quaternion(*wxyz).matrix()
        targets.append(pin.SE3(rotation, values[offset : offset + 3]))
    return targets


class IndependentPoseIK:
    """Solve each disjoint arm with analytic SE3 Jacobian and joint bounds.

    First frame uses the URDF joint-limit midpoint; subsequent frames use the
    previous IK output. Deterministic random restarts never read source joints.
    Grippers are fixed to mid-aperture as an explicit collision assumption.
    """

    def __init__(self, model, retries=3, max_nfev=100):
        import pinocchio as pin

        self.model = model
        self.data = model.createData()
        self.retries = retries
        self.max_nfev = max_nfev
        self.rng = np.random.default_rng(20260911)
        self.seed = pin.neutral(model)
        self.indices = []
        self.frames = []
        for side in ("left", "right"):
            indices = [
                model.joints[model.getJointId(f"openarm_{side}_joint{i}")].idx_q
                for i in range(1, 8)
            ]
            self.indices.append(np.array(indices))
            self.frames.append(model.getFrameId(f"openarm_{side}_hand_tcp"))
        self.active = np.concatenate(self.indices)
        self.seed[:] = (model.lowerPositionLimit + model.upperPositionLimit) / 2

    def solve(self, targets, seed=None):
        import pinocchio as pin
        from scipy.optimize import least_squares

        q = self.seed.copy() if seed is None else np.asarray(seed).copy()
        evaluations = 0
        for frame, indices, target in zip(self.frames, self.indices, targets, strict=True):
            lower = self.model.lowerPositionLimit[indices]
            upper = self.model.upperPositionLimit[indices]

            def residual(x):
                q[indices] = x
                pin.forwardKinematics(self.model, self.data, q)
                pin.updateFramePlacements(self.model, self.data)
                delta = self.data.oMf[frame].actInv(target)
                return pin.log6(delta).vector

            def jacobian(x):
                residual(x)
                delta = self.data.oMf[frame].actInv(target)
                jac = pin.computeFrameJacobian(
                    self.model, self.data, q, frame, pin.ReferenceFrame.LOCAL
                )
                return (-pin.Jlog6(delta.inverse()) @ jac)[:, indices]

            initial = np.clip(q[indices], lower + 1e-9, upper - 1e-9)
            best = None
            for attempt in range(self.retries):
                start = initial if attempt == 0 else self.rng.uniform(lower, upper)
                result = least_squares(
                    residual,
                    start,
                    jac=jacobian,
                    bounds=(lower, upper),
                    max_nfev=self.max_nfev,
                    ftol=1e-9,
                    xtol=1e-9,
                    gtol=1e-9,
                )
                evaluations += result.nfev
                error = float(np.linalg.norm(result.fun))
                if best is None or error < best[0]:
                    best = (error, result.x.copy())
                if error < 1e-4:
                    break
            q[indices] = best[1]
        pin.forwardKinematics(self.model, self.data, q)
        pin.updateFramePlacements(self.model, self.data)
        errors = []
        for frame, target in zip(self.frames, targets, strict=True):
            current = self.data.oMf[frame]
            errors.append(
                (
                    float(np.linalg.norm(current.translation - target.translation)),
                    float(np.linalg.norm(pin.log3(current.rotation.T @ target.rotation))),
                )
            )
        return q.copy(), np.asarray(errors), evaluations
