# RetargetLab development log

This is an append-only engineering record for the remote-first development
workflow. It records decisions, evidence, discarded attempts, and stopping
points. It must not contain raw private poses, private dataset values, source
credentials, or held-out episode contents.

## 2026-09-04 · remote M-1 target-reselection checkpoint

### Working location and scope

- Remote parent: `/data_ssda/xyh/retargetlab`
- Remote canonical repository: `/data_ssda/xyh/retargetlab/repo`
- Remote Python environment: `/root/miniconda3/envs/retargetlab`
- Scope: finish the registered OpenArm M-1 run, then execute the
  pre-registered target-reselection spike with an independent dual-Panda
  asset. The `held_out` split remains unopened.
- The generated Panda asset is a spike-only target. It is not yet a formal
  Panda `RobotProfile`, product asset, or export authorization.

### Work sequence

1. Confirmed the remote directory layout requested for development: `xyh` is
   the parent and `retargetlab` is below it. The canonical worktree is the
   repository path above; Windows is used as the Remote-SSH client.
2. Rechecked the local and remote OpenArm asset chain, including URDF, SRDF,
   portable collision meshes, dynamic fingers, and the required body-to-link0
   collision pairs. The OpenArm harness was kept disposable and separate from
   the future formal pipeline.
3. Completed the registered OpenArm T2 expansion recipe
   `20260903-m1-005`. The 60-frame calibration prescreen reached at most
   30.0% nominal and 35.0% relaxed, with no candidate collision-free across
   all prescreen frames. The formal OpenArm result is RED.
4. Followed the registered red-light route and built a separate Panda
   target-reselection spike from the official dual-Panda description. The
   target asset was built with relative mesh paths, no bundled environment
   table geometry, dynamic finger joints, and an adapted SRDF policy.
5. The first Panda recipe used the opposite side mapping and produced a
   penetration-dominated result. Inspection of the official dual-arm example
   comments and the observed dataset-side placement showed the correct
   mapping is dataset left -> `panda_2` and dataset right -> `panda_1`.
   Recipe `20260903-m1-panda-001` is therefore historical/discarded evidence;
   its scores were not reused.
6. Created recipe `20260904-m1-panda-002` with the corrected mapping and a
   fresh 81-candidate T2 grid. The one-frame diagnostic and the registered
   60-frame prescreen were rerun from scratch; no OpenArm candidate result was
   reused.
7. Selected the top 9 only from the frozen 60-frame Panda prescreen, then ran
   the complete calibration budget: 600 single frames and 20 continuous
   segments of 60 frames each.
8. During merge review, found that `merge_full_evaluations.py` copied the
   gate from the first lexicographic input instead of the best candidate. The
   merger now carries each input's candidate-local gate and assigns the gate
   belonging to the selected best candidate. The merged report was regenerated
   after this fix.
9. Corrected the Panda collision-probe labels from `neutral` to `ready_seed`,
   because the probe deliberately uses the registered Panda ready seed rather
   than Pinocchio's neutral configuration. The collision metrics did not
   change; the report was regenerated to keep the names semantically exact.

### Asset and harness evidence

The Panda target directory is
`projects/target-reselection-panda/robots/panda_bimanual/`. Its tracked
harness entry points are:

- `harness/m_minus_1/build_panda_assets.py`
- `harness/m_minus_1/assert_panda_assets.py`
- `harness/m_minus_1/probe_panda_collisions.py`
- `harness/m_minus_1/probe_panda_reselection.py`
- `harness/m_minus_1/merge_full_evaluations.py`

The official dual-Panda source revision is
`frankarobotics/franka_ros@ddd2fffd9de44b02ad15b4bbb2bfa2cec4d60d98`. The
adapted SRDF policy records
`moveit/moveit_resources@c55b102711fc0aebe80c6952d2ce97c38110abba`.

Asset assertions passed with model `nq=nv=18`, 19 portable mesh files, 106
full collision objects, and 68 SRDF entries. The collision probe passed with
88 selected coarse collision objects, 2,680 post-SRDF collision pairs, and
the nine required cross-arm base pairs preserved. A one-frame OpenArm
regression smoke also passed after the generic target-seed adapter change.

### Panda M-1 evidence

Run directory:
`projects/target-reselection-panda/runs/20260904-m1-panda-002/`

- Recipe: `recipe.yaml`; recipe SHA-256
  `40d149739a89881a2ca27666d76dba790fd13e3bf6ece21e0bffcd5b94416a65`.
- Registered 60-frame prescreen: `prescreen-calibration-60.json`; SHA-256
  `9cf1d7a3407dbd1fff5e69918759bbb84f339378208e4af2c2010a6b431a2700`.
- Full top-9 merge: `full-top9.json`; SHA-256
  `124cacb1bf2e34c4de27c3b5ce5ceed9176fb4917a8f3dda02fd4bbf94d1fe82`.
- Asset assertions: `panda-asset-assertions.json`.
- Collision probe: `panda-collision-probe.json`.
- OpenArm compatibility smoke: `openarm-harness-regression-smoke.json`.

The regenerated collision-probe report SHA-256 is
`fe64dfd107ea2641e201551d752fd2d30f1dcf58592d74e8b6bfc93f01fa309a`.

The corrected-mapping 60-frame prescreen had 81/81 candidates with a
nonzero nominal rate and 16/81 candidates with zero penetration over all
prescreen frames. The full top-9 ranking selected `t2-080`, with offset
`[0.10, 0.10, 0.10] m` and yaw `10 deg`:

- 594/600 single frames nominal (`99.17%`), relaxed rate `100%`, penetration
  fraction `0.83%`;
- 20/20 continuous segments nominal, continuous penetration fraction `0`;
- no joint-limit or delta violations.

The registered gate is `YELLOW`. The yellow causes are explicit: a small
single-frame penetration fraction and use of the relaxed orientation
tolerance on some single frames. This is a conditional M-1 checkpoint, not a
frame-identity proof and not a held-out or export result.

### Current stopping point and next action

At this checkpoint, record the yellow condition and keep frame semantics
`unconfirmed`. M0 may proceed with the condition recorded; M1 must recheck
the target before data export or opening held-out episodes. Any future change
to the Panda mapping, T2 grid, solver options, collision policy, or tolerance
requires a new recipe and a new report rather than rewriting this evidence.

## 2026-09-04 · M0 Panda foundation slice

After recording the yellow M-1 condition, the first M0 slice was implemented
in the repository rather than in the disposable harness:

- `pyproject.toml` and the `src/retargetlab/` package skeleton;
- backend-independent contracts for evidence, canonical trajectories, robot
  profiles, thresholds, solve options, and observable IK statuses;
- one transform boundary in `kinematics/transforms.py`, with explicit wxyz
  quaternion order, SE(3) validation, sign-invariant geodesic angle, and
  quaternion sign continuity;
- `PinocchioBackend` for profile-driven FK and Jacobians;
- `PinocchioCollisionModel` for manifest-controlled geometry selection,
  explicit SRDF filtering, and allowed-contact reporting;
- a runtime dual-Panda profile factory that verifies the manifest URDF hash and
  all referenced mesh paths before loading.

The first integration attempt exposed two implementation issues and both were
resolved before commit: the Panda smoke initially used the full fine-mesh
geometry instead of the manifest's coarse policy, and Pinocchio's copied
`GeometryModel` binding was unsafe to iterate while removing objects. The
loader now applies the named coarse policy and removes objects using names
collected from the original model.

Verification on the remote environment:

- `pytest`: 10 passed, including the remote Panda asset integration smoke;
- `ruff check src tests` and `ruff format --check src tests`: passed;
- `mypy src`: passed with the Pinocchio third-party import explicitly marked
  as untyped.

This slice stops before Pink IK, sequence solving, data normalization, CLI,
and export. Those remain subsequent M0 work and must preserve the current
yellow-gate condition.

### M0 continuation: Pink single-group IK

The next M0 slice adds `kinematics/pink_backend.py`. It implements the
observable Pink loop `task target -> solve_ik -> integrate -> recompute
residual`, maps backend exceptions to the declared `IKStatus` values, enforces
the formal position/orientation tolerances, and uses the previous result as
the warm start for `solve_sequence`. It deliberately solves one named profile
group; dual-group coupling remains a later `solve/coupling.py` task.

The synthetic two-joint fixture converges for both a single pose and a
two-frame warm-started sequence. After adding this slice, remote verification
was `pytest: 11 passed`, `ruff: passed`, and `mypy: passed`. The only test
warnings are upstream qpsolvers/OSQP sparse-conversion and deprecation
warnings. No private dataset or held-out value was read.

### M0 continuation: sequence and coupling boundary

`solve/sequence.py` now owns fixed-seed retry selection and delegates warm
starts to the backend; it does not branch on a concrete backend name.
`solve/coupling.py` declares the four registered modes. Independent and
warm-started streams use the generic sequence path, `joint_solve` is rejected
unless the backend declares `multi_group_joint_solve`, and the previously
invalid `interleaved_sequence` timing assumption is rejected explicitly.
Synthetic tests cover the accepted path and both capability/semantic guards.
The remote suite remains green at 12 passed, with ruff and mypy passing.

### M0 continuation: collision-barrier budget

A real Panda perturbation smoke initially failed at the first Pink step because
all 2,680 post-SRDF collision pairs were passed to one OSQP barrier. A direct
barrier-off comparison converged, confirming a QP-size bottleneck rather than
an FK or target-frame error. The fix keeps the full geometry for the final
collision postcheck but exposes `self_collision_min_distance_m` and
`collision_barrier_pair_budget` in `SolveOptions`. The collision model now
constructs a deterministic barrier subset while retaining profile-declared
required pairs; Panda's nine cross-arm link0 geometry pairs are retained in the
16-pair budget.

The real Panda perturbation (panda_1 joint1 +0.1 rad from the registered ready
seed) then converged in 63 Pink iterations with collision-free postcheck. The
integration test covers this path, and the remote suite is `12 passed`; ruff
and mypy remain green. The solver output contains only upstream qpsolvers/OSQP
warnings. No private or held-out data was read.

### M0 continuation: read-only frame and episode diagnostics

The next slice adds a backend-independent diagnostic layer without changing
solver outputs or repairing trajectories. `FrameDiagnostics` records solver
status, residuals, collision verification, joint-limit violation, and a
separate continuous-jump flag; it intentionally contains no joint values.
`ThresholdSet` makes the M0 nominal position/orientation thresholds and the
relaxed orientation threshold explicit, each with source and provenance.
`diagnose_episode` aggregates frame predicates into `PASS`, `WARN`, or `FAIL`:
all nominal frames pass, all relaxed-but-not-nominal frames warn, and any
other condition fails. An unknown collision result is not treated as safe.

Verification on the remote repository:

- `pytest -q tests`: 13 passed and 1 Panda integration test skipped because
  the ignored project asset directory was unavailable to this checkout;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- focused diagnostic tests: 2 passed.

This layer remains read-only and does not claim frame-identity confirmation,
real-robot safety, or held-out validation. The next slice can connect it to a
trajectory runner once the input adapter supplies explicit per-frame collision,
limit, and delta checks.

### M0 continuation: synthetic bounded round-trip and negative cases

The synthetic test support now generates a deterministic joint-space reference
with a seeded low-pass velocity process, explicit lower/upper limits, and a
per-joint step bound. It derives each canonical pose through the supplied
`KinematicsBackend.fk` implementation, so the fixture does not duplicate robot
kinematics. The reference joint configurations are kept in the test result
object only; they are not part of the canonical input contract or any private
dataset.

The synthetic suite verifies both directions of the CPU loop: bounded smooth
configurations produce FK-backed canonical targets, and those targets return
through the Pink sequence solver with observable `CONVERGED` results. It also
exercises 10+ negative conditions covering invalid poses, stream/timestamp/frame
alignment, empty trajectories, malformed generator bounds, and unknown backend
groups. These tests are contract guards, not accuracy claims about the Panda
M-1 target.

Remote verification after this slice:

- `pytest -q tests`: 17 passed and 1 Panda asset smoke skipped when the
  gitignored project asset path is not mounted in the checkout;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- only the existing upstream qpsolvers/OSQP conversion and deprecation
  warnings remain.

The synthetic generator is deliberately not an input adapter and does not open
the private or held-out split. The next implementation boundary remains the
run/recipe/report layer before any real-data normalization is attempted.

### M0 continuation: reproducible run workspace and reports

The M0 run layer now records the computation boundary before execution. A
`Recipe` captures the dataset alias and input hash, target asset hash, backend
identity, solve coupling, full `SolveOptions`, random seed, split hash, and
provenance-bearing thresholds. Canonical JSON hashing makes the recipe digest
independent of dictionary insertion order and formatting. `create_run_workspace`
creates `runs/<run_id>/result` and `runs/<run_id>/export` exactly once, writes
`recipe.json` plus `recipe.sha256`, and rejects an existing run id rather than
overwriting historical evidence.

`write_dataset_report` persists the read-only diagnostic report as JSON,
Markdown, CSV, and JSONL episode summaries, then writes a completion manifest
containing recipe/report hashes and the artifact list. Reports contain solver
and quality facts only; they do not serialize joint arrays or private poses.
Repeated report writes are rejected as well. The current M0 format uses JSON
as the canonical core representation; a future CLI may add YAML as a
presentation adapter without changing the hash contract.

Verification on the remote repository:

- `pytest -q tests`: 19 passed and 1 Panda asset smoke skipped when the
  gitignored project asset path is not mounted;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- run tests confirm stable/sensitive recipe hashes, non-overwriting workspace
  creation, report materialization, and absence of joint data in metrics.

This slice establishes the run evidence boundary but does not execute a real
dataset, normalize fields, or authorize export. The next slice can add a
minimal CLI/doctor surface over these contracts while preserving the same
recipe and report hashes.

### M0 continuation: structured CLI doctor and canonical inspect

The first CLI surface is now installed through the `retargetlab` project
entrypoint and can also run as `python -m retargetlab.cli`. `doctor --json`
reports the RetargetLab version, Python version, and core/solver dependency
availability with exit code `5` when a required runtime dependency is missing.
`inspect <canonical.json> --json` validates and summarizes only the current
CanonicalTrajectory v0.1 contract; it does not infer a source schema or echo
input values. Invalid structure returns semantic-validation exit code `3` and
the human-readable path reports a concise error without a traceback.

The CLI keeps structured payloads on stdout and human-readable diagnostics on
stderr. The package currently exposes only these two useful commands; future
normalize/solve/diagnose/export commands will be added behind the same exit
code contract instead of being registered as misleading no-op stubs.

Remote verification:

- `doctor --json`: `READY`; Python `3.12.14`, Pinocchio `4.1.0`, Pink `4.3.0`,
  qpsolvers `4.13.0`, OSQP `1.1.3` and core dependencies were detected;
- `pytest -q tests`: 23 passed and 1 Panda asset smoke skipped when the
  gitignored project asset path is not mounted;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed.

This slice is still metadata-only: no private data, held-out split, IK result,
or export artifact is read or generated by the CLI.

### M0 continuation: read-only run diagnosis command

The CLI now also exposes `diagnose --run <run-dir>`. It validates the completed
`result/report.json`, emits only episode-level quality summaries, and maps a
report with any failing episode to exit code `4`; malformed or missing report
data remains semantic exit code `3`. A warning report remains a successful
command because it is a completed computation whose quality condition is
visible in the structured result.

The human-readable invalid-input path was tested separately so a malformed
report does not cause a traceback or an accidental success summary. The CLI
still has no real-data adapter and cannot open the private or held-out split.

Remote verification:

- CLI unit tests: 5 passed, including PASS/FAIL exit behavior and the
  no-joint-array output guard;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed after removing one accidentally copied test file from the source
  package directory;
- the full suite remains green at 23 passed and 1 skipped when the ignored
  Panda asset path is not mounted.

The next boundary is input/schema inspection and validation, still synthetic or
explicitly mapped only; no real-data normalization is authorized by this
slice.

### M0 continuation: explicit mapping and structure validation

The input boundary now has value-free contracts for `MappingSpec`,
`StructureManifest`, and `MappingValidation`. A mapping declares the dataset
alias, source revision, coordinate frame, timestamp reference, stream role,
source paths, expected shapes, indices, units, and frames. The validator checks
alias/revision, missing paths, shape mismatches, and out-of-range indices
without reading sample values. This keeps container layout separate from
trajectory semantics and makes an implicit column-order mapping impossible.

The CLI exposes `validate-input <manifest.json> --spec <mapping.json>` using
those contracts. It returns exit code `0` for a valid explicit mapping and
exit code `3` for a structurally invalid mapping or malformed contract. The
current fixtures are synthetic JSON manifests only; no Parquet/HDF5 reader and
no private-data path were added in this slice.

Remote verification:

- mapping and CLI tests: 9 passed;
- `doctor --json`: still `READY` with the registered solver environment;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed.

The next implementation step can add a narrow synthetic normalize adapter over
these mappings, followed by a real-container prober only when its dependency
and private-data boundary are explicitly registered.
