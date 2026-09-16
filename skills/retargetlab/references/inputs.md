# Task-specific inputs

Read this for new input/model binding or missing-material questions. Do not request every item below for every task.

| Information/material | Required when | Obtain it from / handling |
|---|---|---|
| Task result, data/run location and scope | Every usage task | User request or existing configuration; clarify only genuine ambiguity |
| Target robot/profile | Robot solving/replay | Existing registered assets/profile; not needed merely to inspect EEF metadata |
| Field layout, absolute/delta semantics, units, rotation convention and pose direction | Interpreting EEF values | Explicit metadata/registered mapping; unresolved or contradictory values require evidence/clarification |
| Coordinate relation, TCP and arm/group correspondence | Robot solving | Existing binding; do not assume identity, repeat a TCP offset or swap arms |
| Timestamp and episode/frame meaning | Continuous solving and time-quality claims | Input metadata/columns; do not invent a sampling rate or silently shift action labels |
| Observation/action definitions | Dual-stream processing/export | Each stream's own declared meaning; one stream is not a substitute for the other |
| Source URDF, acquisition/FK code, source joints | Optional cross-checks in the general product; some rc4 interfaces specifically require them | Explain the precise interface requirement below, not a universal EEF requirement; no source-joint IK seeds |
| Gripper physical mapping | Physical gripper commands or dynamic gripper checks | Verified mapping/model only. Raw preservation does not certify physical aperture |
| Videos and their time/episode metadata | A requested video-containing deliverable | Verify existing files/metadata; do not silently turn it into a numeric-only delivery |
| Scene/objects, controllers, inertias | Physics/task validation | Those workflows are not supported by this skill; do not request these for kinematic replay |

## Verified rc4 routes

**OpenArm EEF sidecar:** `source_format=openarm_eef_sidecar`, explicit `episode_indices`, `robot_asset`. The sidecar has `manifest.json`, `data/eef.parquet` and `assets/source_openarm.urdf`. Both EEF fields use `[x,y,z,qw,qx,qy,qz,gripper_raw]` per arm, left then right. Metres, wxyz, forward URDF-world-to-hand-TCP semantics and the registered model fingerprint must match. The current adapter requires identical declared source and target URDF hashes for its identity binding.

**MQ03 EEF:** `source_format=mq03_eef`, registered `robot_profile` and `split`. Features use `[gripper_raw,qw,qx,qy,qz,x,y,z]` per arm with exact registered feature names. Fixed-body profile has 14 controlled arm joints and the declared base/TCP. The CLI is calibration-only; the split contains calibration and held-out episode indices. Do not use an all-data request to bypass that split or manufacture a new split.

The `process` CLI is not a generic CSV/HDF5/Zarr or arbitrary single-stream/robot entrypoint. A user request for an unsupported route must receive a scoped capability explanation and feasible options, not guessed conversion.

## rc4 export dependencies

`training-export` requires a complete processing run and a matching policy. Its current implementation also reads the original selected source Joint data and LeRobot metadata and checks their layout/binding, even for strict policies. OpenArm locates the original dataset through the sidecar manifest; MQ03 uses the `.position` reference columns. Declared video files must be present when that source declares video features.

If source Joint data are unavailable, explain: “源Joint不是EEF求解的必要输入，但当前rc4的训练导出入口依赖它做后置对照。这个入口暂时不能完成无源Joint导出。” Offer a supported alternative only if it actually meets a user-selected revised goal; dependency removal is a separate development task, not a Skill fallback.

Existing processing runs/bundles carry their configuration and model references. For replay/diagnosis, inspect those first instead of asking the user to resend all original materials. `replay-build` rechecks its referenced input/model bindings, whereas serving an already built bundle uses the saved bundle and referenced model.

## EEF-only path request

If the user only wants to see a raw EEF path, do not request a robot or turn it into IK replay. Explain that rc4 lacks a standalone raw-EEF 3D viewer. Offer a supported structure inspection or a separately chosen visualization-development task; structure inspection does not deliver the requested path image.

Only after the user selects a feasible task, request its minimum input: “请提供文件或可访问路径，以及已有字段说明；我先读取元数据，再补问缺失信息。” A static xyz path does not itself require a sample rate, full robot model or physical gripper calibration. Orientation display and timed playback introduce their own input requirements, only if requested. Do not ask for those additional materials merely because a future viewer could use them.
