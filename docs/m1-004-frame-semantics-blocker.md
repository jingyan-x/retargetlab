# M-1.7 frame-semantics checkpoint

## Confirmed

- The OpenArm target URDF and SRDF are available locally and remotely. The SRDF hash is the same in the local OpenArm workspace and the bundled remote target asset.
- The private sample exposes dual EEF poses in `wxyz` order and records provenance for anonymous source end links named `Larm08_link` and `Rarm08_link`.
- The corresponding source URDF is not present in the checked local materials. The anonymous source joint state therefore remains provenance-only; it must not seed target OpenArm FK or be treated as target OpenArm qpos.
- The local OpenArm teleoperation recorder uses `openarm_left_link7` and `openarm_right_link7`, but that is a diagnostic hypothesis for this dataset, not proof of the private sample's generation path.

## Solver checkpoint

Recipe `20260902-m1-004` tests only the frozen dataset-native identity-pose hypothesis. It adds a deterministic target-only seed set, position-first continuation, and tolerance-normalized task costs. The completed 81-candidate single-frame prescreen is written to `runs/20260902-m1-004/prescreen-one-frame.json`; a later final-scale rerun was intentionally interrupted at the user's shutdown checkpoint.

The diagnostic result separates the two questions:

1. Position-only target IK can reach the selected calibration frame within the millimetre scale.
2. Full pose IK does not satisfy the 5 mm / 2 degree gate under the identity hypothesis; strict position preservation still leaves a large orientation residual, and some better orientation branches are collision-blocked.

Therefore the current result is a red identity-hypothesis prescreen, not evidence that the OpenArm target is intrinsically unreachable. The missing source URDF is an optional cross-check limitation, not an M-1 prerequisite.

## Next gate

Do not promote the identity mapping, the local Viser rotation, or the `link7` hypothesis into the formal recipe. Following the pre-registered red-light procedure, the next formal recipe expands T2 outward from the observed boundary candidate. If that remains red, the route moves to the target-reselection spike. A source URDF or explicit mapping remains useful for later cross-checking, but is not silently assumed as a prerequisite:

- the source URDF and source TCP/frame convention; or
- an authorized source-to-target pose mapping with its evidence and validation set.

Held-out episodes remain unread before M-1c, and no raw private poses or source paths belong in reports.
