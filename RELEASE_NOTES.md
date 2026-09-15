# RetargetLab v0.1.0rc4

A reproducible EEF processing workflow for the registered OpenArm and MQ03 layouts: process both streams, inspect quality, replay saved joints, export masked LeRobot datasets and verify actual loading.

## Included

- Config-driven Pink/Pinocchio and Mink/MuJoCo processing with unchanged pose, joint-limit and timestamp-based velocity checks.
- A pinned public OpenArm model and synthetic EEF/video generator; no private datasets are distributed.
- A local WebGL replay with sequential playback, gray grid, orbit/pan/zoom and failure navigation. Low camera angles remain visible; backend menus reflect the bundle contents.
- Explicit training policies and complete-window masking, plus actual LeRobot/PyAV reader validation in a separate environment.
- Optional `native_clearance` export policy: recheck final float32 joints against a fingerprint-bound MuJoCo model before marking rows eligible.
- A wheel, source kit, install kit, dependency constraints and SHA256 checksums.
- Public-model release validation scripts and a GitHub Actions workflow. Tagged publication requires a project LICENSE and passing validation.

## Validation scope

Linux x86_64 / Python 3.12. Public smoke data contains 192 timestamps, three synthetic camera streams and intentional target jumps. Both backends retain 190 paired timestamps and 130 intact 16-step windows. This demonstrates software behavior, not task success or independent robot performance.

The development regression completed 218 tests with one LeRobot test skipped in the solver environment; actual LeRobot loading was checked separately. Private MQ03 exports are not release assets.

Dynamic gripper calibration, exact physical collision certification, held-out robot evaluation, dynamics, training and real hardware execution remain outside v0.1 scope.

Project code is released under the MIT License. Third-party components retain their own licenses.
