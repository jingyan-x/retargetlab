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

### M0 continuation: narrow explicit normalize adapter

The first normalize path is intentionally limited to in-memory/JSON rows with
one position and one quaternion pose per declared stream. It requires position
unit `m`, the declared coordinate frame, and an explicit `wxyz` quaternion
order; unsupported fields are rejected rather than silently dropped. Numeric
values are checked for finiteness, quaternions are normalized, and only the
mathematically equivalent sign is continuity-corrected across frames. The
result is the existing CanonicalTrajectory v0.1 contract, with no source
column-order assumptions and no robot-specific transform.

`normalize <rows.json> --spec <mapping.json> --output <canonical.json>` now
writes the canonical artifact once. The structured stdout response contains
only status and shape metadata; an existing output path is rejected. This is a
synthetic pose-only adapter and deliberately does not support gripper channels,
Parquet/HDF5, or private/held-out data yet.

Remote verification:

- normalize and mapping tests: 10 passed, including quaternion sign
  continuity, missing fields, frame declarations, non-monotonic timestamps,
  and non-overwriting CLI output;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- the accidental duplicate test copy under `src/retargetlab/cli/` was removed
  before verification; no such file remains in the source package.

The next boundary is a synthetic solve command that consumes a canonical file
and an explicit RobotProfile/asset reference, or a separately reviewed real
container prober. Neither path should bypass the recipe hash and report layer.

### M0 continuation: recipe-bound solve CLI

The CLI now exposes an explicit `solve` path requiring a CanonicalTrajectory
JSON, RobotProfile JSON, Recipe JSON, named stream/group, full initial joint
seed, and a new output path. Before Pink runs, it validates the canonical input
file hash from the recipe and the recipe/profile robot identity. After backend
construction it also requires exact backend name and version agreement. The
full output stores per-frame `IKResult` values, including joint vectors for
the intended solve artifact; structured stdout remains a metadata-only
summary. Existing output files are rejected.

This is an M0 fixture-capable command, not a product claim for arbitrary
robots: it currently selects Pink, uses the existing profile-driven backend,
and leaves quality adjudication to `diagnose`. A mismatch in input hash,
robot identity, or backend version returns semantic exit code `3`; missing
solver runtime returns environment exit code `5`.

Remote verification:

- synthetic Pink solve CLI integration and CLI regression tests: 8 passed;
- full `pytest -q tests`: 33 passed and 1 Panda asset smoke skipped when the
  gitignored project asset path is not mounted;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- the solve output was verified to contain a result joint vector only in the
  explicitly requested artifact, not in the JSON stdout summary.

No private or held-out trajectory was used. The next step is to connect solve
and diagnose through a run workspace, so result files cannot exist without the
recipe/report lineage already recorded.

### M0 continuation: solve-to-run lineage

The solve path now has a reusable execution layer that connects the recipe-bound
solver to the run workspace. `solve --project <project> --run-id <id>` creates
the non-overwriting run directory, writes `recipe.json` and its digest, stores
the full `result/solutions.json`, runs the read-only episode diagnosis, and
materializes JSON/Markdown/CSV/JSONL reports plus `run-manifest.json`. The
manifest records both recipe and report hashes and includes the solution
artifact. A solver result with unknown collision verification therefore stays
visible as a completed run with quality `FAIL`; it is not silently upgraded to
pass.

The standalone `solve --output` mode remains available for fixture-level use.
The project mode requires `--run-id` and rejects incompatible output/project
argument combinations. The run layer validates the trajectory source hash and
robot/backend identity before execution; backend failures leave the recipe-only
partial directory as evidence rather than overwriting or fabricating a report.

Remote verification:

- solve-to-run integration, report artifact, and CLI regression tests: 4
  targeted tests passed;
- full `pytest -q tests`: 34 passed and 1 Panda asset smoke skipped when the
  gitignored project asset path is not mounted;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed.

This completes the first reproducible synthetic solve/diagnose loop. It still
does not read private data, open held-out episodes, or authorize export. The
next slice can add the M0 static numerical confirmation or improve the profile
loader before any real-data adapter is enabled.

### M0 continuation: profile asset hash enforcement

The Pinocchio profile loader now verifies the resolved URDF SHA-256 against
`RobotProfile.urdf_sha256` before model construction and validates every URDF
mesh reference against the declared asset root. This closes the path where a
profile could carry a syntactically valid but stale or placeholder hash. The
existing Panda manifest path keeps its earlier manifest verification, so the
runtime loader and the manifest loader now enforce the same asset boundary.

All solver and synthetic fixture profiles were updated to derive their hash
from the fixture bytes. A dedicated negative test mutates the hash and asserts
that model loading fails before FK is available. No production profile or
private asset was modified; the remote Panda asset integration remains skipped
because that gitignored target directory is not mounted in this checkout.

Remote verification:

- full `pytest -q tests`: 35 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- the registered solver environment and all synthetic solve/diagnose paths
  remain green after the stricter loader check.

The next boundary is either a static numerical confirmation utility or a
profile-loader contract for SRDF/mesh policy; real-data normalization remains
gated behind an explicit container prober and has not started.

### M0 continuation: collision asset-chain hash enforcement

The profile asset check is now shared by Pinocchio FK loading and the collision
model. Both paths verify the URDF digest and portable mesh references before
constructing runtime geometry. `CollisionProfile` can additionally carry an
explicit SRDF digest; when present, the collision loader verifies it before
applying the disabled-pair policy. This prevents direct collision-model use
from bypassing the same asset boundary enforced by the FK backend.

The synthetic fixtures now derive their URDF digests from the exact UTF-8
fixture bytes. Negative coverage includes mismatched URDF and SRDF hashes.
The real Panda profile path was not changed because its target asset directory
is currently absent from the remote mount; the integration test remains an
explicit skip rather than a synthetic substitute.

Remote verification:

- full `pytest -q tests`: 36 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no private data, held-out episode, or production asset was modified.

The next M0 boundary remains a static numerical confirmation/report utility;
the real-container prober and OpenArm formalization stay outside this slice.

### M0 continuation: optional static diagnostic plot

The report layer now includes a lazy `plot_dataset_report` helper. It plots
episode nominal/relaxed rates and invalid fractions from `DatasetReport` only;
it never reads or renders joint vectors, poses, private source rows, or held
out content. The output path is non-overwriting, and matplotlib is an optional
`viz` extra so the core/solver environment remains installable without a GUI
stack. The pure JSON/Markdown/CSV report remains the authoritative numerical
artifact.

The remote environment does not currently have matplotlib installed. The
optional-dependency negative test confirms that plotting reports a clear
runtime requirement and leaves no partial output. This is an environment
capability note, not a project blocker.

Remote verification:

- static-plot and diagnostic tests: 3 passed;
- full `pytest -q tests`: 37 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed.

No package installation, private data access, or held-out access was needed
for this slice. The next step can add a contract-level profile/SRDF review or
prepare the narrow prober interface for a separately authorized real container.

### M1a.1: read-only Parquet structure prober

The input boundary now has a Parquet schema prober and an `inspect` CLI path.
It reads only Parquet schema and footer metadata, records column names, Arrow
dtypes, conservative shapes, row count, and the source file SHA-256, and never
materializes or serializes row values. Variable-width list columns are kept as
`shape: null`; mapping validation rejects indexed references whose source width
is unknown instead of guessing from a storage encoding.

The remote private sample was probed at the metadata-only boundary. The main
data file reports 13,746 rows, the episode metadata file reports 20 rows, and
the task metadata file reports 1 row. The three source hashes are respectively
`379a36946b7f0d39705caa434c8630a65131d20d75626c731daa94f195ccb`,
`28c2e9afd5c4112af46337c9e781d85c13d36036e3dfdef040b6da795624c634`, and
`fabd9e744d6a2ca0d1034d5c383a5923815e99c39b9f6d76f591215023c03f40`.
The Parquet footer stores the vector-like feature columns as variable-width
lists, so this slice deliberately does not promote their widths into a
mapping. The declared feature shape in the metadata manifest remains a
separate next-step contract to cross-check explicitly.

Remote verification:

- targeted prober and CLI tests: 9 passed;
- full `pytest -q tests`: 39 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no row values, held-out episodes, videos, or production assets were read or
  modified.

The next boundary is an explicit metadata-manifest prober that can compare
declared feature shapes and dtypes with the value-free Parquet structure before
any mapping or normalization is enabled.

### M1a.2: explicit metadata/Parquet cross-check

The input boundary now probes the selected declarations from a LeRobot-style
`info.json` and compares them with the value-free Parquet manifest. Feature
dtype, shape, element names, dataset counts, and FPS remain metadata-only; the
video features are marked external and are not incorrectly expected to appear
as Parquet columns. Arrow's `float` is compared to the declared `float32`, and
the known `[1]` declaration versus scalar `()` storage representation is
reported as `shape_normalized` rather than a silent match. Variable-width list
storage remains `shape_unverified`.

For the remote private sample, the declaration and the main Parquet footer are
compatible: alias, revision, row count, field presence, and dtypes all agree.
The result is intentionally not fully verified: eight vector features have
unverified physical width, and seven scalar features use the explicit
singleton-to-scalar storage normalization. No feature mapping or normalization
was enabled as a consequence of this comparison.

Remote verification:

- metadata/comparison and CLI tests: 11 passed;
- full `pytest -q tests`: 42 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no row values, held-out episodes, videos, or production assets were read or
  modified.

The next boundary is to generate a reviewable, explicit mapping candidate from
the declared element names, while keeping frame, unit, quaternion order, and
source-to-target semantics unresolved until separately evidenced.

### M1a.3: review-only pose mapping candidate

The metadata boundary now produces a `MappingSpec` candidate from declared
element names, without opening data rows. It identifies position indices from
`epos_{slot}_{x,y,z}` and quaternion indices from
`epos_{slot}_{q{w,x,y,z}}`, records the declared `wxyz` ordering basis, and
keeps the two arms as `slot_0` and `slot_1`. It intentionally leaves the
coordinate frame and position unit unset, retains both state and command
roles, and records gripper indices as review metadata; the candidate status is
`REVIEW_REQUIRED` and is not executable by the pose normalizer.

For the remote private sample, the generated candidate contains four streams:
`observation.state.slot_0`, `observation.state.slot_1`, `action.slot_0`, and
`action.slot_1`. The review artifacts are stored under the gitignored project
review directory: `mapping-candidate.json` has SHA-256
`9b2067e39781e9dfe2949b8ae9900980a2a55b2a7b9a21fac64619a2bf4771d7`, and
`structure-comparison.json` has SHA-256
`f2c88269c7acf4e8c20d40255607e7f437599bc21e958526d3bf897a467d3e22`.
These artifacts contain declarations, mappings, schema metadata, and hashes;
they do not contain source row values or held-out content.

Remote verification:

- candidate and CLI tests: 11 passed;
- full `pytest -q tests`: 44 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real-data normalization, IK solving, or target-side semantic promotion
  was performed.

The next boundary is a human-review contract for frame/unit and slot-to-target
semantics, followed by a separate bounded calibration slice only after those
fields are explicitly supplied.

### M1a.4: explicit semantic review gate

The mapping layer now has a `MappingReview` contract and a promotion function.
An approved review must explicitly provide a non-placeholder coordinate frame,
metres for position, seconds for timestamps, `wxyz` quaternion order, unique
labels for `slot_0` and `slot_1`, a target group for each slot, reviewer
identity, and evidence. Without `approved=true`, promotion fails. Promotion
renames streams and fills frame/unit fields but keeps target groups as
traceable metadata; it does not run normalization or IK.

The real private-sample candidate remains `REVIEW_REQUIRED`; no guessed frame,
unit, left/right assignment, or target-group assignment was promoted. This
keeps the current evidence boundary intact while making the next human-owned
decision machine-checkable.

Remote verification:

- candidate, review-gate, and CLI tests: 12 passed;
- full `pytest -q tests`: 45 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real-data normalization, IK solving, or target-side semantic promotion
  was performed.

The next boundary is to supply or derive review evidence for frame/unit and
slot-to-target semantics, then run only a bounded calibration check before any
full trajectory conversion.

### M1a.5: require structure evidence during mapping promotion

The promotion path now requires the value-free `StructureComparison` artifact
in addition to the semantic review. It rejects incompatible alias/revision,
row-count, field, dtype, or shape results. When the comparison is compatible
but not fully verified, the review must explicitly set
`accept_unverified_shape=true`; the default remains rejection. The CLI accepts
either a bare comparison object or the archived inspect wrapper containing a
`comparison` member.

The remote private sample therefore still cannot be promoted automatically:
its comparison is compatible but not fully verified, and no approved review
was supplied. This preserves the distinction between declared feature shape,
physical storage shape, and human semantic approval.

Remote verification:

- full `pytest -q tests`: 46 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- the unapproved CLI path remains covered and no real-data normalization or IK
  solving was performed.

The next boundary is a bounded calibration executor that accepts only an
approved mapping plus its matching structure comparison, with no full-dataset
conversion until calibration evidence is recorded.

### M1a.6: bounded approval-gated calibration executor

The runtime now exposes a bounded calibration normalization function. It
rejects empty or oversized slices, unresolved/unapproved mappings, mismatched
structure comparisons, and approved mappings that have not explicitly accepted
unverified shape. The default slice limit is 60 frames and the hard limit is
600. On success it returns the canonical trajectory for the small slice plus a
value-free `CalibrationReport`; the report records counts and verification
status but never embeds pose or joint arrays.

The executor was closed over synthetic rows only. The real private-sample
candidate remains unapproved, so no real source rows were normalized and no IK
was run. This keeps the next real-data action limited to supplying an explicit
review and then selecting a bounded calibration slice.

Remote verification:

- bounded calibration tests: 3 passed;
- full `pytest -q tests`: 49 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no held-out content, videos, or production assets were modified.

The next boundary is to connect the approved-only calibration function to a
row-selection adapter, preserving episode boundaries and provenance without
adding an unbounded data-conversion path.

### M1a.7: bounded Parquet selector with preflight ordering

The selector now reads only requested episode range metadata, deterministically
chooses uniformly spaced frame positions within each requested episode, and
fetches only the corresponding source rows and explicitly requested columns.
It enforces a 60-frame selection ceiling, preserves episode boundaries, checks
the returned global index/episode/frame triplets, and emits data/episode file
hashes plus selected row indices in a value-free `CalibrationSelection`.

The combined Parquet calibration entrypoint performs the approval and structure
comparison preflight before opening either data file. Only after that gate does
it select rows and call bounded normalization. The real private-sample mapping
is still unapproved, so this combined path was exercised only with synthetic
Parquet data.

Remote verification:

- selector and combined calibration tests: 6 passed;
- full `pytest -q tests`: 52 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real source rows, held-out episodes, videos, or production assets were
  read or modified by the calibration path.

The next boundary is to expose a bounded review-run artifact that records the
selection and calibration report without serializing source rows by default.

### M1a.8: exclusive bounded calibration audit artifact

The run layer now writes an exclusive JSON audit artifact for a completed
bounded calibration. It records the approved mapping hash, structure-comparison
hash, reviewer/evidence, coordinate frame, selection provenance, and the
value-free calibration report. It validates alias/revision and selected-frame
lineage and refuses to overwrite an existing artifact. A canonical trajectory
is intentionally not an input to this writer, so pose/joint arrays cannot enter
the artifact through the normal API.

The artifact writer was exercised with synthetic approved calibration output;
the real private-sample candidate remains unapproved and produced no
calibration artifact. Real structure and candidate review artifacts remain
under the private-sample project review directory, with their hashes recorded
above.

Remote verification:

- review-artifact and calibration tests: 4 passed;
- full `pytest -q tests`: 53 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real source rows, held-out episodes, videos, or production assets were
  modified.

The next boundary is to add a narrow command-level wrapper for this artifact,
still requiring an explicit approved mapping and comparison before any real
calibration read.

### M1a.9: command-level bounded calibration wrapper

The CLI now exposes `calibrate` with required data/episode paths, candidate,
review, structure comparison, episode indices, per-episode frame count, total
frame budget, and exclusive audit output. It loads and promotes the mapping
before calling the Parquet selector; only the approved mapping and matching
comparison can reach source-row reads. The command writes the audit artifact
only, never a canonical trajectory file, and emits counts plus artifact hash.

A real-path negative smoke used the archived private-sample candidate and
comparison with an `approved=false` review. It returned the expected invalid
input before opening the data files, and the requested output artifact was not
created. A synthetic approved path completed successfully and produced an
audit-only artifact without pose arrays.

Remote verification:

- command-level calibration and selector tests: 7 passed;
- full `pytest -q tests`: 54 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real source rows were read by the negative smoke; no held-out content,
  videos, or production assets were modified.

The next boundary is to add an explicit calibration recipe/run manifest so a
future approved real run records parameters and hashes alongside the audit
artifact without changing the default bounded behavior.

### M1a.10: explicit calibration recipe and run manifest

The bounded calibration command now emits a complete, exclusive audit set:
the value-free calibration audit, a canonical `calibration-recipe.json`, its
SHA-256 sidecar, and a `calibration-run-manifest.json`. The recipe records the
dataset and source revision, data and episode hashes, mapping/structure/review
hashes, selected episode ids, frame budget, and exact Parquet columns. The
writer cross-checks these hashes and selection parameters before writing, and
refuses partial or overwriting artifact sets. The manifest records the recipe
and audit hashes plus the sibling artifact names; no trajectory arrays are
serialized.

The recipe/run writer and the CLI wrapper were exercised only with synthetic
approved calibration output. The archived real private-sample review remains
unapproved, so it still cannot create a calibration artifact or read source
rows through the CLI path.

Remote verification:

- recipe/run-manifest and command-level calibration tests: 8 passed;
- full `pytest -q tests`: 55 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real source rows, held-out content, videos, or production assets were
  read or modified by the calibration path.

The next boundary is a read-only verifier for the recipe, sidecar, manifest,
and audit lineage, so a future approved real run can be checked without
opening or rewriting its source rows.

### M1a.11: read-only calibration run verifier

The run layer now provides a read-only verifier and the CLI command
`verify-calibration`. It requires the manifest to name exactly one audit file
plus the recipe, recipe hash sidecar, and manifest; rejects unsafe or missing
artifact names; recomputes canonical recipe and audit hashes; and checks the
dataset, revision, mapping, structure, review, episode, frame-budget, and
selection lineage. Verification returns only value-free status and counts and
never opens the source Parquet files or rewrites the artifact set.

The success path and a tampered recipe-sidecar negative path were covered on
synthetic approved artifacts. The real private-sample review is still
unapproved and remains outside the calibration read path.

Remote verification:

- verifier and CLI success/negative assertions passed within the artifact and
  selector test suites;
- full `pytest -q tests`: 55 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real source rows, held-out content, videos, or production assets were
  read or modified by the verifier.

The next boundary is to add an explicit source-independent report renderer for
the verified calibration run, keeping review and provenance readable without
exposing source pose values.

### M1a.12: deterministic source-independent calibration summary

Each bounded calibration run now also writes `calibration-summary.md`. The
summary is generated deterministically from the recipe and value-free audit:
it presents status, dataset/revision, provenance hashes, selected episode and
frame counts, requested columns, coordinate-frame label, stream names,
structure status, and reviewer. It explicitly contains no source rows or
trajectory arrays. The manifest records the summary hash, and the read-only
verifier checks both that hash and the regenerated summary content.

The summary writer, manifest extension, verifier checks, and existing CLI
success path were exercised only with synthetic approved artifacts. The real
private-sample review remains unapproved and did not enter this path.

Remote verification:

- summary/manifest and verifier assertions passed in the artifact test suite;
- full `pytest -q tests`: 55 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no real source rows, held-out content, videos, or production assets were
  read or modified by summary generation or verification.

The next boundary is to add a bounded, read-only review-package inspector that
reports whether a real dataset has all evidence needed before an explicit
semantic approval, without treating inferred mappings as approved.

### M1a.13: bounded read-only review-package inspector

The input layer now exposes `inspect-review-package`. It reads only the
candidate mapping, explicit review, and structure comparison; reports
`PENDING_REVIEW`, `REVIEW_APPROVED`, or `BLOCKED`; and separates readiness for
semantic review from permission to apply the review. Alias/revision mismatches,
incompatible structure evidence, and an unaccepted unverified shape are
reported as blockers. A pending package is never promoted, and the command
returns a non-zero semantic exit only for a structurally blocked package.

The inspector was exercised on the real private-sample OpenArm review package
using its review-only candidate, structure comparison, and pending review
record. It returned `PENDING_REVIEW`, `can_apply_review=false`, and required a
shape decision; no data or episode Parquet file was opened.

Remote verification:

- review-package unit and CLI tests: 2 passed;
- full `pytest -q tests`: 57 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no source rows, held-out content, videos, or production assets were read or
  modified by the inspector.

The next boundary is to make the review-package output consumable as a stable
preflight record for later approved calibration runs, without auto-generating
or silently accepting semantic review decisions.

### M1a.14: archived review-package preflight record

The review-package inspector can now optionally write an exclusive,
value-free `review-package-preflight.json`. The record stores canonical hashes
of the candidate, explicit review, and structure comparison together with the
inspection status and next action. The default inspector remains read-only;
writing occurs only when an explicit output path is supplied, and a pending or
blocked package is never promoted by the writer.

The real private-sample OpenArm package was inspected and its pending preflight
record was written to a controlled temporary path for a smoke test. It
reported `PENDING_REVIEW`, `can_apply_review=false`, and an unresolved shape
decision without opening source data or episode Parquet.

Remote verification:

- preflight writer, exclusivity, value-free, and CLI output tests: 3 passed;
- full `pytest -q tests`: 58 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no source rows, held-out content, videos, or production assets were read or
  modified by the preflight path.

The next boundary is to add a review-package preflight verifier that accepts
only the saved package paths and checks the archived hash record before a
future approval or calibration step.

### M1a.15: read-only review-package preflight verifier

The run layer and CLI now expose `verify-review-package`. Given the saved
preflight artifact and the candidate, explicit review, and structure
comparison paths, it recomputes all three canonical input hashes and compares
the regenerated inspection result with the archived record. It returns only
value-free verification metadata and never reads dataset or episode files.

The real OpenArm package was used for the preceding preflight smoke; the
verifier success path and a tampered-candidate negative path were exercised on
synthetic package files. A changed candidate is rejected by hash mismatch, so
the saved preflight cannot silently drift from its reviewed inputs.

Remote verification:

- review-package preflight writer/verifier and CLI tests: 3 passed;
- full `pytest -q tests`: 58 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no source rows, held-out content, videos, or production assets were read or
  modified by the verifier.

The next boundary is to add an explicit review-package evidence checklist,
keeping structural readiness, semantic approval, and shape acceptance as
separate fields before any real calibration is allowed.

### M1a.16: explicit review evidence checklist

`MappingReview` now accepts an optional `ReviewEvidenceChecklist`. Pending
reviews remain parseable without a checklist, but an `approved=true` review
must explicitly confirm structure evidence, coordinate frame, position and
timestamp units, quaternion order, slot labels, and target groups. Shape
acceptance is a separate `NOT_REQUIRED`/`ACCEPTED`/`REJECTED` field; an
unverified structure can enter the executable path only when the review both
enables unverified-shape acceptance and marks the checklist shape as
`ACCEPTED`. The package inspector exposes checklist presence/completeness and
shape state without promoting the candidate.

The real private-sample OpenArm pending review was re-inspected after the
contract extension. It remains `PENDING_REVIEW`, with no checklist and an
explicit unresolved shape decision; no source rows were opened. Synthetic
approved fixtures were updated with complete checklists and continue to pass
the calibration gate.

Remote verification:

- checklist, review promotion, preflight, and calibration tests: 58 passed;
- full `pytest -q tests`: 58 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no source rows, held-out content, videos, or production assets were read or
  modified by the checklist path.

The next boundary is to add a stable, value-free review decision record that
binds the checklist and approved mapping hashes before any real calibration
run is created.
