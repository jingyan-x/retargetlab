# Usage workflow and verified interfaces

Use only the steps required for the requested deliverable. Installation is a separate entrance. Below, `PROCESS_PY` and `READER_PY` mean the actual interpreter paths in a complete `installation.json`, or explicitly verified existing environments. `SKILL_DIR` is the actual directory containing this skill. Resolve variables before running examples; do not assume a `python3.12` shell alias exists.

## Check without installing

During usage, check only the components the requested task actually needs: processing/replay uses the process interpreter; actual LeRobot reading uses the reader interpreter; reading a saved JSON report may need neither. Inspect the installation record for paths, then use the relevant `--version`, `--help` and scoped `doctor`. An unrelated component failure does not change this task's output or authorize installation. Do not claim the entire installation is healthy based on one component.

When the user requests a **complete installation check**, use the full read-only checker (also mandatory for installation acceptance):

```bash
"$PROCESS_PY" "$SKILL_DIR/scripts/install_full.py" --prefix "$INSTALL_DIR" --check
```

For existing separately configured interpreters, inspect the relevant actual version and CLI help/doctor. Reuse them when appropriate; do not require reinstall merely because they lack the helper's manifest. Only claim a complete installation if both environments and all runtime components were verified. Choose the relevant examples below; they are not a mandatory three-command sequence for every usage task.

```bash
"$PROCESS_PY" -m retargetlab --version
"$PROCESS_PY" -m retargetlab doctor --scope pipeline --json
"$READER_PY" -m retargetlab doctor --scope reader --json
```

An environment problem pauses that step and invokes the decision pattern; it never implicitly authorizes an installation command. No dataset task asks for GPU/CUDA by default.

## Inspect metadata or structure

Use the smallest authorized object. For LeRobot metadata or one Parquet file:

```bash
"$PROCESS_PY" -m retargetlab inspect /path/to/meta/info.json --dataset-alias NAME --source-revision REVISION --json
"$PROCESS_PY" -m retargetlab inspect /path/to/file.parquet --dataset-alias NAME --source-revision REVISION --json
```

`NAME` is a non-private task alias; derive revision identity from available provenance/content rather than asking the user to invent it. Inspect requires an actual supported file, not an arbitrary dataset-directory argument. Do not inspect held-out numerical data while diagnosing the development set. Structure inspection does not require a target robot, source URDF or video upload.

## Process EEF or prepare robot replay

Read [inputs](inputs.md) for the two supported routes. Reuse a matching configuration; if the user has no configuration, construct it from resolved inputs using the published example/usage schema. Required paths and episode scope come from the task, not a laboratory default.

```bash
"$PROCESS_PY" -m retargetlab process --config /path/to/process.json --output /path/to/new-run --json
```

This performs continuous IK and writes saved solutions, `report.json`, `report.md`, `trajectories.parquet`, bindings and a manifest. A completed process may contain failed frames. Keep the existing time/pose/limit/quality rules. Use the existing registered default backend/recipe when the user has not requested a comparison; do not automatically run both backends or tune them.

For a replay model not yet built, use the verified profile and a new output directory:

```bash
"$PROCESS_PY" -m retargetlab build-mujoco-model --profile /path/to/robot-profile.json --output /path/to/new-model --json
```

The published OpenArm synthetic example explicitly uses `--kinematic-inertia-repair` to compile its known model. Preserve that registered setting for that example only; do not silently apply it to an unknown model or present it as dynamics calibration. Mink processing requires its model beforehand; Pink processing does not.

## Diagnose a saved result

Identify the artifact layout first. Current `process` outputs store `report.json` and `trajectories.parquet` at the run root: read those public artifacts directly with available file/Parquet tools. Start with the summary and inspect only the relevant episode/frames when needed. Use actual per-frame quantities to distinguish pose, limits, speed, contact and missing checks.

The rc4 `diagnose --run` command instead expects the older `result/report.json` contract. Use it only for that layout. Do not rerun IK merely because the legacy command rejects a new process report.

## Build and serve replay

A replay configuration is a JSON list; paths are relative to the config file:

```json
[
  {"id": "chosen-run", "processing_run": "run", "model": "model", "label": "Selected result"}
]
```

Add `quality_dataset` only if a matching exported quality dataset already exists and the requested view needs it. Exporting training data is not a prerequisite for normal robot replay.

```bash
"$PROCESS_PY" -m retargetlab replay-build --config /path/to/replay.json --output /path/to/new-bundle --json
"$PROCESS_PY" -m retargetlab replay --bundle /path/to/bundle --port 8790
```

`replay` is a long-running loopback server, not a command that emits one completion JSON. Use the environment's supported background/session mechanism, verify the server is listening, and give the actual reachable URL. For a remote host, use an authorized SSH tunnel to the selected port; reuse an existing matching server/tunnel rather than opening duplicates. Do not close unrelated user sessions.

For an HTTP-only accessibility check, use these read-only interfaces on that server:

- `GET /api/catalog`: read the available `runs`, their IDs and episode IDs.
- `GET /api/scene?run=RUN_ID`: load the selected model scene.
- `GET /api/episode?run=RUN_ID&episode=EPISODE_ID`: load saved episode records.
- `GET /api/motion?run=RUN_ID&episode=EPISODE_ID&stream=observation.state` (or `action`): load geometry motion for the chosen stream.

Obtain IDs from the catalog and URL-encode query values. Verify the user-facing forwarded URL as well when running remotely. Successful HTTP/JSON reads establish service/data accessibility; they do not establish browser rendering or interaction. The legacy `/api/frame` native-image endpoint is not required by the WebGL UI.

The browser displays saved q with robot/backend/run/episode/stream selection, playback/frame stepping, timeline, camera controls, TCP/trajectory overlays, error curves and available quality/failure filters. Backend selection displays an existing result; it does not initiate IK. There is no GUI task submission, solver tuning/local rerun, dataset export, raw-video synchronization or dynamics control in rc4. Do not claim browser interaction passed based only on HTTP availability; if browser tools are unavailable, say which checks were actually performed.

## Export and actually read

Use a completed processing run and an existing reviewed policy matching the robot. Read the rc4 source-Joint dependency in [inputs](inputs.md) before promising this task. Do not generate new contact exceptions to improve the eligible count.

```bash
"$PROCESS_PY" -m retargetlab training-export --processing-run /path/to/run --policy /path/to/policy.json --output /path/to/new-dataset --json
"$READER_PY" -m retargetlab verify-reader --dataset /path/to/dataset --output /path/to/new-reader-report.json --horizon 16 --json
```

The reader uses actual LeRobot/PyAV and complete eligible windows. Use the user's horizon; if unspecified, report that the registered 16-step default was used for compatibility checking, not that the user's future training configuration was chosen. Never bypass the mask because there are too few windows. Single-window datasets are valid when the requested horizon fits.

## Published synthetic example

Use only when the user requests an example or installation validation warrants it. The public model is `enactic/openarm_description` commit `6148297241fb0402eafe2c6eed455ae4e90d4552`. Reuse a verified existing checkout or fetch this pinned public revision into a new location. Then:

```bash
"$PROCESS_PY" -m retargetlab demo-init --openarm-source /path/to/public-model --output /path/to/new-demo --json
```

It creates the registered process, model, replay and quality-policy inputs. Read generated config paths rather than assuming they point to your differently named run/model directories. Continue only through the steps included in the requested demonstration. No private data are needed.

## Exit codes and completion

0 means command completion; 2 usage error; 3 input/semantic error; 4 a legacy quality-gate failure; 5 dependency/environment error; 1 other runtime/validation failure. New `process` can return 0 with quality failures, so read its report. `replay` stays running until stopped. A file or stdout JSON alone is not evidence of a successful larger task.

Finish with the requested result, exact artifact path/URL, version and scope, actual checks, and any remaining requested work. A source/reference comparison, software reader check, kinematic replay and physical execution claim are different outcomes.
