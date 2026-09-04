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

### M1a.17: explicit semantic review decision artifact

The run layer now writes an exclusive `semantic_review_decision` artifact for
an approved mapping review. It applies the review through the existing gate,
then records canonical hashes for the review-only candidate, review,
checklist, structure comparison, and promoted mapping, together with reviewer,
evidence, coordinate frame, shape acceptance, and target-group metadata. The
`review-mapping` CLI accepts an optional `--output` to archive this record;
without it, the command remains an in-memory promotion report.

The writer cannot run for a pending review, and approved reviews without a
complete checklist are rejected by the contract. Synthetic approved fixtures
covered the writer and CLI path; the real private-sample review remains
pending and did not create a decision artifact.

Remote verification:

- decision-artifact, checklist, promotion-gate, and CLI tests: 60 passed;
- full `pytest -q tests`: 60 passed and 1 Panda asset smoke skipped;
- `ruff check src tests`, `ruff format --check src tests`, and `mypy src`:
  passed;
- no source rows, held-out content, videos, or production assets were read or
  modified by the decision-record path.

The next boundary is to make an approved decision artifact consumable by the
bounded calibration command, while rechecking its hashes and preserving the
existing explicit review inputs as the source of truth.

### M1a.18: consume the semantic decision artifact in calibration

The bounded `calibrate` command now accepts an optional `--decision` path. When
provided, it loads the candidate, review, and structure comparison, applies the
existing approval gate, and verifies that the saved decision artifact exactly
matches those explicit inputs before invoking any Parquet selection. The
calibration recipe records the canonical decision hash, and the run writer
checks that the recipe and call-site agree so the lineage cannot be silently
omitted or substituted.

The verifier rebuilds the decision artifact from the value-free review inputs;
it does not trust a hash copied from the decision file and it does not read
dataset rows. The CLI calibration fixture now exercises the full decision-aware
path, while a tampered-comparison test confirms that drift is rejected.

Remote verification:

- full `pytest -q`: 61 passed and 1 Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no source rows, held-out content, videos, or production assets were read or
  modified by decision verification tests.

The next boundary is to expose the optional decision hash from the read-only
calibration-run verifier, so downstream review tooling can distinguish legacy
runs from runs carrying an archived semantic decision without reopening source
data.

### M1a.19: expose decision lineage from calibration verification

The read-only `verify-calibration` result now includes the optional
`decision_sha256` carried by the calibration recipe. The deterministic Markdown
summary also records this field, using `none` for legacy runs that predate the
decision artifact. This keeps the verifier and summary aligned with the recipe
without requiring source data or the original decision JSON to be reopened.

Remote verification:

- decision-aware CLI calibration and verification test: passed;
- legacy calibration-artifact verification still reports a null decision hash;
- full `pytest -q`: 61 passed and 1 Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed.

The next boundary is to add an explicit read-only lineage check for the
decision artifact itself, so a completed run can optionally prove that its
recorded decision hash still resolves to the supplied decision file without
making calibration depend on source-row access.

### M1a.20: optionally recheck the decision file from a completed run

`verify-calibration` now accepts an optional `--decision` path. For a
decision-aware run, the verifier parses the value-free semantic decision
artifact, recomputes its canonical hash, and checks dataset/source lineage
against the recipe. The result reports both the recorded `decision_sha256` and
whether the supplied file was verified. Legacy runs remain valid and report a
null hash with `decision_verified=false`.

The calibration verification fixture covers the success path and a tampered
decision file. The latter is rejected before a verified result is emitted;
verification remains read-only and does not access source rows or held-out
data.

Remote verification:

- full `pytest -q`: 61 passed and 1 Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no source rows, held-out content, videos, or production assets were read or
  modified by the lineage check.

The next boundary is to keep the real private-sample approval gate pending:
there is still no approved decision artifact for production calibration, so no
real calibration or retargeting run should be started automatically.

### M1a.21: explicit pure joint-space command timing verification

The repository now provides a read-only `analyze-timing` command and contracts
for ranking `action.position[t]` against `observation.state.position[t+k]`
within an explicit episode allowlist. The report records only input hash,
episode and joint indices, pair counts, aggregate/per-joint RMSE, and the
expected shift window; it never emits source rows or held-out values.

The implementation requires explicit `joint_indices` instead of silently
aggregating heterogeneous channels. It also supports an explicit affine action
transform for channels whose command and state units differ. On the
calibration subset, the 14 arm joints use identity and produce best shift `4`
within the registered `4..5` window. The two gripper joints use the separately
declared `5*x-3` transform and produce best shift `6` within their registered
`5..6` window. The earlier all-16-dimension diagnostic was retained only as a
debug artifact; it is not used as the timing conclusion because it mixed
normalized gripper commands with radian joint states.

This timing result is a physical tracking-delay diagnostic only. It does not
change the training pairing rule: source `observation[t]` remains paired with
`action[t]`, with no row shift.

Remote verification:

- calibration timing reports for arm and gripper groups: both `SUPPORTED`;
- full `pytest -q`: 63 passed and 1 Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no held-out data, video, or production export was read or modified.

The next boundary is to formalize the reviewed dataset profile and its explicit
source-side gripper/timing declarations; the semantic review gate remains
pending for the unresolved EEF frame mapping.

### M1a.22: separate arm/gripper timing units and rerun calibration evidence

The first timing implementation exposed an important unit boundary: aggregating
all 16 source joint dimensions directly made the two normalized gripper command
channels dominate the RMSE against radian state channels. The report contract
was tightened to require explicit `joint_indices` and to record an optional
per-selected-joint affine action transform; no heterogeneous dimensions are
silently mixed.

The final calibration reports therefore use two explicit slices. The 14 arm
joints use identity and return `SUPPORTED` with best shift `4` in the
registered `4..5` window. The two gripper joints use the declared `5*x-3`
state-unit transform and return `SUPPORTED` with best shift `6` in the
registered `5..6` window. This matches the separate channel semantics already
documented for the dataset. The initial mixed-unit report remains only as a
debug artifact and is not treated as evidence.

The implementation and synthetic tests also cover a non-identity transform,
explicit index validation, value-free JSON output, and the quality exit code
for a conflicting expected range. The physical timing result remains a
diagnostic of tracking delay; it does not authorize shifting training rows.

Remote verification:

- final calibration timing reports: arm and gripper both `SUPPORTED`;
- full `pytest -q`: 63 passed and 1 Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no held-out data, video, or production export was read or modified.

The next boundary is the DataProfile contract: capture the dataset revision,
stream-specific pose/gripper semantics, timing evidence scope, and the
explicit mapping formula as one reviewable value-free input to M1a.

### M1a.23: bind the private dataset revision into a pending DataProfile

The repository now has a value-free `DataProfile` contract and an exclusive
writer. It binds the five source revision hashes (`info`, `data`, `episodes`,
`tasks`, and `stats`) to the current review-only `MappingSpec`, records the two
stream families for both grippers, and makes the observation/action aperture
affine maps explicit. It also binds each timing report by canonical report
hash, selected joint indices, action transform, same-step pairing, and
`shift_policy=none`.

The private `private-sample-20` builder produced:

- `projects/private-sample-openarm/runs/20260903-m1-005/data-profile-review-required.json`;
- profile status `REVIEW_REQUIRED`, with `coordinate_frame=UNRESOLVED`;
- source revision `info.json@sha256:5447be7ef21b29fb03e04871ee6b908e3013051217b757fd9a3f30c8d3555a40`;
- arm and gripper timing evidence bound to the same data hash, with observed
  best shifts `4` and `6` respectively, both `SUPPORTED`;
- no trajectory rows, held-out values, video, or production export in the
  profile; the unresolved EEF frame and absent source robot identity remain
  explicit limitations.

The profile cannot be certified: no approved review-decision hash exists and
the EEF frame mapping is still unresolved. This artifact is therefore a
review input only and does not authorize calibration or retargeting.

Remote verification:

- profile unit tests: 2 passed;
- full `pytest -q`: 65 passed and 1 Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- the broader legacy `harness/m_minus_1` lint scope still has pre-existing
  style findings and was not modified by this slice.

The next boundary is to add an explicit profile/review-decision cross-check,
then keep the production gate closed until the semantic frame decision is
actually approved.

### M1a.24: verify DataProfile to semantic-decision lineage

The repository now exposes a read-only `verify_data_profile` helper and a
`verify-profile` CLI command. Structural profile validation and decision
lineage validation are intentionally separate. A pending profile can verify
successfully while reporting `decision_verified=false`; a certified profile
must be checked with its decision artifact. When a decision is supplied, the
verifier checks its canonical hash, dataset alias, source revision, approved
mapping hash, and coordinate frame against the profile.

The real private profile verifies as:

- profile status `REVIEW_REQUIRED`;
- profile SHA-256
  `aae5432a5fbacb6cce43a3a25b135f28e06988daa9376c604f5bfb70c1b83746`;
- decision verification `false`, because no approved semantic decision was
  supplied or exists for this review-pending mapping.

Remote verification:

- profile and CLI lineage tests: 4 passed in the focused profile/CLI run;
- full `pytest -q`: 67 passed and 1 Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- verifier reads only the profile and optional decision artifact, never source
  rows, held-out data, video, or production exports.

The production gate remains closed. The next implementation boundary is to
make downstream calibration/normalization consume a verified DataProfile
without allowing a pending profile to enter an executable path.

### M1a.25: gate executable calibration and normalization on certified profiles

The executable path now has an explicit profile gate. `calibrate --profile`
and `normalize --profile` first require a `CERTIFIED` DataProfile and a
matching verified semantic decision. Calibration then checks the approved
mapping hash plus the data and episode file hashes before reading source rows;
the resulting calibration recipe and deterministic summary record the profile
hash. Normalization uses the certified profile mapping and records the profile
hash in canonical trajectory metadata. The existing explicit `--spec` and
review-approved calibration paths remain backward-compatible when no profile
is supplied.

The real pending private profile was deliberately exercised through the
calibration CLI with review-package paths that do not exist. It was rejected
at the profile gate with `executable data profile must be CERTIFIED`, proving
that a pending profile cannot fall through to review-package or source-row
access. The same pre-row gate is covered for normalization by a unit test.

Remote verification:

- focused profile/review/calibration tests: 21 passed;
- full `pytest -q`: 69 passed and 1 Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private source rows or held-out data were changed; only the previously
  generated value-free pending profile was read.

The next boundary is to use the certified profile as the single source of
mapping and channel semantics in any future executable retargeting command;
the current private profile remains intentionally non-executable until the
semantic EEF frame decision is approved.

### M1a.26: execute source-side gripper semantics in canonical normalization

The canonical frame contract now carries optional per-stream gripper aperture
values, constrained to finite `[0, 1]` and aligned with the pose streams. The
normalizer accepts the explicit `GripperProfile` declarations and selects the
correct source channel independently for each stream: observation state uses
the measured joint-angle affine map, while action uses its normalized-open
map. Reference joint streams are supported by the same explicit channel
selection. Out-of-range mapped aperture values are rejected rather than
silently clipped.

`normalize --profile` now uses the certified profile mapping and gripper
declarations, and records the profile hash in canonical metadata. The legacy
pose-only `normalize --spec` path remains unchanged. The current private
profile was not used for normalization because its frame semantics are still
unresolved and its status is `REVIEW_REQUIRED`.

Remote verification:

- pose-only, profile-gripper, range, and canonical alignment tests passed;
- full `pytest -q`: 71 passed and 1 Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private trajectory rows were written or exported; only synthetic rows
  were used to test the new value transformation.

The next boundary is to carry the same certified profile semantics into the
future target-side gripper mapping, while preserving the rule that grippers
do not enter arm IK and that unresolved EEF frame semantics keep the private
profile non-executable.

### M1a.27: bind complete private-dataset coverage into the profile evidence

The repository now has a value-free `DatasetCoverage` contract and a
`scan-coverage` CLI for the fixed private LeRobot source set. The scanner reads
only the source metadata and Parquet schema/episode index columns, records the
five source revision hashes, checks episode interval contiguity and declared
counts, and writes through an exclusive artifact writer. It never copies raw
trajectory values, held-out rows, video, or export data into the evidence
artifact.

The actual private dataset scan completed successfully:

- 20 episodes and 13,746 data rows were observed;
- episode intervals were contiguous from row 0 through row 13,746;
- one task and the declared metadata structure were observed;
- schema compatibility is true, while vector shape remains explicitly
  unverified because Parquet schema alone cannot prove the list lengths;
- the coverage artifact is `COMPLETE` and its SHA-256 is
  `2ce452d67db872fa4413234be13d8cba3a1ce0a3af7a3e8a5c5ffcb56f7968a4`.

The profile builder can now bind that coverage hash and expand the validation
scope to all accessible episodes. The resulting profile verifies internally
with profile SHA-256
`95d2e5fe392ea874409e5d7748f82fdb6801a7502e0ee8979c354526f538423a`, but
remains `REVIEW_REQUIRED` with an unresolved EEF coordinate frame and no
approved semantic decision. Therefore it is still not executable.

Remote verification:

- coverage, profile, and full regression tests: 73 passed and 1 Panda asset
  smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- coverage and profile focused tests: 8 passed;
- no private trajectory values were materialized in the coverage or profile
  artifacts.

The next implementation boundary is target-side OpenArm gripper semantics and
an explicit target robot profile, while keeping arm IK independent of gripper
channels and preserving the certified-profile gate.

### M1a.28: formalize target-side OpenArm gripper semantics and profile loading

The target robot contract now distinguishes source-side `GripperProfile` from
target-side `TargetGripperProfile`. A target gripper declares one driver joint,
its ordered mimic joints, metre units, driver limits, and the canonical
`aperture_fraction` meaning. Its pure mapping is explicit:
`0=closed` and `1=open` linearly map to the driver joint, then apply the URDF
mimic multiplier and offset to dependent joints. Invalid or non-finite aperture
values are rejected. `KinematicGroup` requires the declared target gripper
joint order to match its gripper joint list, so a mimic joint cannot silently
be treated as an independent command dimension.

The formal OpenArm loader now consumes the versioned asset bundle and verifies
the generated URDF hash, SRDF hash, required arm/TCP/finger links, prismatic
finger limits `[0, 0.044] m`, and `finger_joint2 -> finger_joint1` mimic
relation before constructing the profile. The two groups are
`openarm_left` and `openarm_right`, both target `hand_tcp` in the `world` root.
The profile preserves the 16 SRDF disabled pairs, allows only the expected
closed-finger contacts, and retains body-to-arm-base barrier pairs for the
collision backend. Gripper mapping remains a target-side post-processing
contract and is not injected into arm IK.

Remote verification against the real staged OpenArm asset:

- formal profile, Pinocchio load, SRDF policy, and real-finger endpoint smoke:
  passed;
- full regression tests with `RETARGETLAB_OPENARM_ASSET_DIR` set: 77 passed
  and 1 Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or export data were accessed or changed.

The next implementation boundary is to make this formal target profile
materializable as an exclusive, hash-bound JSON artifact for solve/export
inputs, before adding any target-specific execution behavior.

### M1a.29: materialize and verify the OpenArm target profile artifact

The target profile is now materializable through the `build-robot-profile`
command. It currently accepts the explicit `openarm_bimanual` adapter, reruns
the URDF/SRDF and gripper-structure checks, and writes exactly one JSON profile
through an exclusive writer. The command reports a canonical profile SHA-256 so
future solve/export recipes can bind the exact target asset contract.

The remote artifact is:

- `projects/private-sample-openarm/robots/openarm_bimanual/robot-profile-v0.1.json`;
- robot id `openarm_bimanual`, root `world`;
- groups `openarm_left` and `openarm_right`, each targeting its `hand_tcp`;
- target gripper mapping `aperture_fraction -> finger_joint1` in metres, with
  `finger_joint2` represented only through the declared mimic relation;
- canonical profile SHA-256
  `1aa65d1241838b7fd29ed79d2a485488aec187b946ccb8fc654d4bfb71bc0194`.

Reloading the written JSON reproduced the same hash and the expected two group
bindings. A second write to the same path is rejected, so a changed URDF or
semantic declaration must create a new artifact rather than silently replacing
the old one.

Remote verification:

- target gripper, OpenArm asset, writer, and CLI tests: 6 passed;
- full regression with the real OpenArm asset profile smoke enabled: 79 passed
  and 1 Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- the generated profile contains only robot metadata and hashes; no private
  dataset values, video, or export commands were run.

The next implementation boundary is to bind this target profile hash into a
target-side aperture mapping/replay artifact, keeping that transformation
separate from arm IK and refusing a missing or mismatched target profile.

### M1a.30: bind target aperture replay to the OpenArm profile

The target-side transformation now has its own `TargetGripperTrajectory`
contract. It contains only timestamps and target joint positions, never arm
poses or IK results, and records the canonical hash of the target
`RobotProfile`. `map_target_grippers` requires an exact one-to-one binding
between canonical gripper streams and all target robot groups; missing,
unbound, duplicate, or gripper-less groups are rejected. The mapping then uses
the target profile's driver/mimic semantics, so OpenArm emits
`finger_joint1` in metres and `finger_joint2` only as its declared mimic.

The `map-grippers` CLI materializes this replay artifact through an exclusive
writer. A profile or stream binding cannot be silently substituted, and a
second write to the same output path fails. The real target profile artifact
hash is carried into the replay artifact and revalidated by the contract.

Remote verification:

- target gripper contract, mapping, writer, CLI, and real OpenArm profile
  smoke: 9 focused tests passed;
- synthetic mapping confirmed that the output contains no `poses` field and
  maps closed/open/mid aperture values to the expected driver and mimic
  positions;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, arm IK output, or export bundle were read or
  changed.

The next implementation boundary is to bind the target gripper replay into a
full canonical-to-target replay manifest, including explicit arm-solve
provenance, without making the gripper path part of the arm IK objective.

### M1a.31: bind canonical-to-target replay provenance

The replay layer now has a value-free `TargetReplayManifest` containing exactly
five immutable references: canonical trajectory, target robot profile, recipe,
arm solve artifact, and target gripper replay. It records each file/hash,
robot/backend/coupling identity, arm group, target groups, and frame count.
The builder revalidates the canonical/profile/recipe contracts, requires the
target gripper artifact to carry the same profile hash and robot id, checks the
arm solve recipe/backend/group/frame metadata, and refuses any count or
coupling mismatch. The manifest contains no pose arrays, joint solutions, or
gripper values.

The `build-replay-manifest` CLI writes the manifest exclusively, so changing
any upstream input requires a new replay id/output instead of replacement.
Synthetic CLI and cross-check tests passed, including the invariant that the
target gripper path remains separate from arm IK provenance rather than being
silently folded into the solver input.

Remote verification:

- replay manifest contract and CLI tests: 2 passed;
- full regression with real OpenArm profile smoke enabled: 84 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, arm solve, or export bundle were read or
  changed while building the synthetic manifest.

The next implementation boundary is a read-only replay-manifest verifier that
recomputes all five hashes and rechecks their cross-artifact lineage before
any future export or execution step.

### M1a.32: verify replay manifest lineage before downstream use

The replay layer now includes a read-only verifier and
`verify-replay-manifest` CLI. It re-parses the canonical trajectory, target
robot profile, recipe, target gripper replay, and arm solve metadata, then
rebuilds the expected manifest and compares all five artifact hashes, robot
identity, backend identity, coupling, group, profile binding, and frame counts.
The returned `TargetReplayVerification` is value-free and reports only the
verified replay id, profile hash, frame count, manifest hash, and artifact
roles.

The verifier rejects a modified arm-solve frame count even when the manifest
file itself is unchanged. This establishes the downstream gate needed before
any future export or execution step; it does not run IK, touch private data,
or infer missing semantics.

Remote verification:

- replay builder/verifier and CLI tests: 2 passed;
- tamper case: modified solve metadata was rejected with a semantic error;
- full regression with real OpenArm profile smoke enabled: 84 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed.

The next implementation boundary is an explicit multi-group arm-solve binding
for the replay manifest, so a bimanual target cannot be represented by one
arm result while still being called complete.

### M1a.33: require complete multi-group arm-solve binding

The replay manifest schema is now `0.2` and supports repeated `arm_solve`
artifact references, each carrying its target group. The builder and verifier
require the arm-solve group set to equal the target robot group set, require
one frame-count/backend/recipe check per group, and preserve deterministic
profile-order hashing in the manifest. The CLI accepts `--arm-solve` once per
target group and reports all bound groups. A bimanual OpenArm profile therefore
cannot be labeled `READY` from only one arm result.

The single-group fixture remains supported as the smallest valid case, while a
dual-group fixture now exercises two solve artifacts and rejects a missing
second group. This keeps the first stable Panda/OpenArm loop composable without
silently weakening the bimanual completeness rule.

Remote verification:

- multi-group replay builder, CLI, and missing-group rejection tests: 3 passed;
- full regression with real OpenArm profile smoke enabled: 85 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or real solve/export artifact was read or
  changed.

The next implementation boundary is to add a target-profile asset verifier to
the replay gate, so the recorded URDF/SRDF hashes are checked again before a
replay is accepted as ready.

### M1a.34: verify target profile assets before replay acceptance

The replay gate now performs a read-only `verify_robot_profile_asset` check
before accepting a target robot profile. It revalidates the profile URDF hash
and portable mesh references, confirms the declared root and end-effector
frames plus every arm/gripper joint exist, and checks target gripper driver
limits and mimic relations against the URDF. When a profile declares an SRDF,
the verifier also checks its path, optional hash, and XML root. This keeps the
profile artifact's recorded semantics tied to the actual target assets rather
than treating the JSON metadata as sufficient evidence.

Replay unit fixtures now include minimal self-contained URDFs and exact hashes,
including a dual-group fixture. This exercises the new asset gate without
reading private dataset rows or requiring a real arm-solve artifact. The
multi-group replay schema and completeness checks remain unchanged.

Remote verification:

- replay asset-gate and multi-group tests: 3 passed;
- full regression with real OpenArm profile smoke enabled: 85 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- target asset verification remains read-only and no private dataset rows,
  video, or real solve/export artifact was read or changed.

The next implementation boundary is to use the verified profile and replay
lineage as the prerequisite for a deterministic target-side execution/export
artifact, while preserving the separation between arm IK results and gripper
aperture replay.

### M1b.1: freeze the target vector layout contract

The export layer now materializes an explicit `TargetVectorLayout` and
`ExportProfile` bound to the canonical hash of the verified target
`RobotProfile`. The layout is deterministic in profile group order: each arm's
declared joints come first in `rad`, followed by that group's physical gripper
driver in `m`; URDF mimic joints are deliberately not independent output
dimensions. The contract records `float32`, the one-dimensional shape, ordered
names, units, robot identity, and normalization exclusions, so downstream
writers do not infer meaning from numeric positions.

`build-export-profile` verifies the target assets before writing the profile
exclusively. A real OpenArm artifact was materialized at
`projects/private-sample-openarm/runs/20260904-m1b1-001/export-profile.json`
with SHA-256
`db37586f85bd3e64a216a21fcb46d546654ccae42eebcb0f595401ed43d54cdf`; its
layout is shape `[16]` with the expected left-arm/left-gripper/right-arm/right-
gripper order from the target profile.

Remote verification:

- export-layout contract and CLI tests: 5 passed;
- full regression with real OpenArm profile smoke enabled: 90 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- the artifact contains layout metadata only; no private dataset rows, video,
  or solve values were read or exported.

The next implementation boundary is to bind value-bearing arm-solve and
gripper frames into this verified layout as a separate deterministic replay
command artifact, without presenting it as a LeRobot dataset export or as a
real-robot safety guarantee.

### M1b.1a: materialize a deterministic target replay command artifact

The replay run layer now materializes a value-bearing
`TargetReplayTrajectory` only after re-verifying the value-free replay
manifest and checking the supplied `ExportProfile` against the target
`RobotProfile` layout. It consumes each group's arm-solve `q` values and the
target gripper artifact, requires every arm result to be `CONVERGED`, checks q
dimensions and finiteness, checks gripper driver limits and mimic relations,
checks timestamps, and emits one ordered float32-layout vector per frame.
Mimic joints remain represented by the driver-derived target semantics and do
not become duplicate output dimensions. The exclusive writer and
`materialize-replay` CLI keep the value artifact separate from the provenance
manifest and emit metadata-only stdout summaries.

The artifact is deliberately not a LeRobot dataset export and does not claim
controller compatibility or real-robot safety. A non-converged arm frame is
rejected before any command artifact is written; the serialized artifact
contains layout-bound values but no source poses or raw solve result objects.

Remote verification:

- target replay materialization, CLI rejection, and provenance tests: 5
  replay tests passed;
- full regression with real OpenArm profile smoke enabled: 92 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- only synthetic arm q values were used for this materialization test; no
  private dataset rows, video, or real solve/export artifact was read or
  changed.

The next implementation boundary is a read-only verifier for this
value-bearing command artifact, so a dataset writer cannot consume a modified
vector file merely because its provenance manifest is still valid.

### M1b.1b: verify materialized target replay values before downstream use

The target replay layer now exposes a value-free verifier for
`TargetReplayTrajectory`. It re-reads the bound replay manifest and export
profile, regenerates the expected target vectors from the hashed arm-solve and
gripper inputs, and compares the complete artifact rather than trusting the
artifact's own metadata. A changed joint value therefore fails even when the
provenance manifest itself remains untouched. The CLI command
`verify-target-replay` returns the normal semantic-invalid status for such a
tamper case and emits no joint values in its summary.

Remote verification:

- materialization/verifier and CLI tamper tests: 6 replay tests passed;
- full regression with real OpenArm profile smoke enabled: 93 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- verification is read-only; no private dataset rows, video, or real solve
  artifact was read or changed.

The next implementation boundary is to define the dataset-writer input gate
around this verified command artifact, keeping the current work limited to
layout/provenance/value correctness and not yet copying or rewriting private
LeRobot data.

### M1b.1c: add the value-free dataset-export input gate

The export preflight now binds the source and target sides without opening
source rows or videos. `build_export_input_gate` requires a `CERTIFIED`
DataProfile with a verified semantic decision, `COMPLETE` coverage with fully
verified source structure and no unverified shapes, exact dataset revision and
coverage hash lineage, an explicit training episode allowlist contained in the
covered episodes, a verified target replay artifact, and a matching
ExportProfile. It emits an exclusive value-free `ExportInputGate` artifact;
the `verify-export-inputs` CLI reports metadata only and does not write an
artifact when the gate fails.

The current real private-sample profile is intentionally rejected at the first
gate because it is still `REVIEW_REQUIRED`; the current coverage also records
unverified vector shapes. This is the correct pre-export state and does not
authorize a dataset rewrite. Synthetic tests cover a passing gate, pending
profile rejection, unverified-shape rejection, and CLI behavior.

Remote verification:

- export-input gate and CLI tests: 4 passed;
- full regression with real OpenArm profile smoke enabled: 97 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is the dataset writer itself, beginning with
synthetic/public parquet metadata only and requiring this gate before any
private source materialization is considered.

### M1b.1d: require distinct state/action replay inputs at the export gate

Before touching a dataset writer, the target replay contract now makes the
stream role explicit (`observation.state` or `action`) and adds a value-free
`TargetReplayBundle` that binds one verified artifact for each role. The
bundle checks shared replay identity, target layout, profile hash, frame count,
and timestamps, while preserving the two value artifacts as separate files.
The export input gate now consumes and hashes this bundle, so a single action
trajectory can no longer be presented as both observation state and action.
The gate schema is `0.2` to make this stronger requirement visible to old
consumers.

Remote verification:

- state/action bundle construction, verification, same-stream rejection, and
  export-gate migration tests passed;
- full regression with real OpenArm profile smoke enabled: 97 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- the current real data profile remains blocked at `REVIEW_REQUIRED`; no
  private rows, video, or dataset rewrite was performed.

The next implementation boundary remains a synthetic/public-only dataset
writer prototype, but it must consume the verified state/action bundle and
must not collapse the two streams or infer missing source semantics.

### M1b.2a: add the synthetic/public single-trajectory table writer

The first table-writer slice now materializes one explicitly scoped
`synthetic_public_only` Parquet trajectory from a verified state/action replay
bundle. Before opening the source table it re-verifies the bundle and both
value-bearing replay artifacts. It then requires the source row count and
timestamps to match the target replay, accepts exactly one contiguous episode,
preserves all source columns other than `observation.state` and `action`,
rewrites those two columns in the target layout as fixed-size `float32`
vectors, and appends `valid.retarget=True` for every row. The output metadata
records the synthetic scope, replay id, robot id, and bundle hash, and output
creation is exclusive so an existing file is never silently overwritten.

This is intentionally not a complete LeRobot dataset writer: it does not copy
videos, create `info.json`/episode/task metadata, or infer private source
semantics. The CLI is named `write-synthetic-table` to keep that boundary
visible.

Remote verification:

- synthetic writer and CLI tests: 3 passed;
- full regression with the real OpenArm asset smoke enabled: 100 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is a value-free writer preflight that can
bind this table rewrite to the certified source/export gate without claiming
that this prototype is already a complete LeRobot dataset export.

### M1b.2b: bind the synthetic writer to a value-free preflight

The synthetic table prototype now has an explicit
`synthetic_table_write_preflight` artifact. It binds the source table path and
hash, output path, existing `ExportInputGate` path and hash, verified replay
bundle path and hash, dataset revision, robot/replay identity, gated source
frame count, target frame count, and training episode allowlist. Building and
verifying this record does not parse source rows; it rechecks only the gate,
file hashes, and replay-bundle lineage. The preflight also requires the gate's
robot, target frame count, target bundle hash, and export-profile hash to agree
with the verified bundle.

The table writer accepts the preflight as an optional explicit input. When it
is supplied, the writer verifies the preflight before reading the source table
and checks that its source, bundle, and output paths match the write request.
The resulting value-free write summary records the preflight path and hash.
The preflight and writer remain visibly synthetic/public-only and do not
authorize private-data materialization or imply a complete LeRobot export.

Remote verification:

- preflight build/verify, tamper detection, writer linkage, and CLI tests: 5
  passed;
- full regression with the real OpenArm asset smoke enabled: 102 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is to make the preflight's episode/frame
selection executable for a deliberately small synthetic multi-row fixture,
before considering any real dataset materialization.

### M1b.2c: execute the preflight episode selection on a synthetic multi-episode table

When a verified synthetic-table preflight is supplied, the writer now requires
one allowlisted episode for one flat replay and filters the source table to
that episode before checking row count, contiguous `frame_index`, and replay
timestamps. The output therefore cannot accidentally include an adjacent
episode whose local frame indices or timestamps happen to look valid. The
selected episode id is recorded in the value-free write summary and Parquet
metadata. The no-preflight path remains deliberately single-episode and
rejects multi-episode input rather than guessing a selection.

Remote verification:

- synthetic single- and multi-episode selection tests: 6 passed;
- full regression with the real OpenArm asset smoke enabled: 103 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is a value-aware synthetic-output verifier
that rechecks the written Parquet vectors and preserved row alignment against
the verified replay and preflight, before any real dataset materialization.

### M1b.2d: verify the synthetic target table after writing

The synthetic writer now has a value-aware `verify-synthetic-table` path. It
rebuilds the selected source view from the verified bundle/preflight, confirms
the output column order and row count, compares every preserved source column,
checks both fixed-size `float32` target vectors against their corresponding
state/action replay artifacts, requires all `valid.retarget` values to be
true, and validates the output metadata plus bundle/replay identity. It
returns only hashes and structural metadata; it does not persist target vector
values in the verification summary. Tampering with a target vector is now a
deterministic verification failure.

Remote verification:

- synthetic write/verify, CLI, preflight linkage, multi-episode selection, and
  tamper tests: 7 passed;
- full regression with the real OpenArm asset smoke enabled: 104 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is to persist a value-free write/verify
report and make the synthetic CLI round trip consume it, before designing a
full multi-episode LeRobot metadata writer.

### M1b.2e: persist and consume the synthetic write/verify report

The synthetic CLI now supports an optional value-free
`synthetic_table_write_report`. With `--report`, a successful table write is
immediately verified and the report archives both the write summary and the
verification summary, including paths, hashes, layout/column metadata, and
selected episode ids but no trajectory vector values. The verification CLI
can consume `--report`; it reruns the output verifier from the report's bound
inputs and requires the result to match the report and the explicit CLI
inputs. This makes a completed synthetic experiment reproducible from one
small audit file.

Remote verification:

- synthetic write/verify/report CLI round-trip, preflight linkage,
  multi-episode selection, and tamper tests: 7 passed;
- full regression with the real OpenArm asset smoke enabled: 104 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is to validate report persistence under
report/output tampering and then decide the minimal metadata needed for a
complete multi-episode LeRobot writer.

### M1b.2f: close report tamper coverage

The archived synthetic write report now has a negative test for an altered
output hash. Even when both the write and verification JSON fields are
changed together, report verification reruns the actual Parquet verifier and
rejects the mismatch. This keeps the report an audit pointer rather than a
self-authenticating claim.

Remote verification:

- synthetic write/verify/report, preflight, selection, CLI, and report-tamper
  tests: 8 passed;
- full regression with the real OpenArm asset smoke enabled: 105 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is a metadata-only design/contract slice
for a complete multi-episode LeRobot export. It will first bind episode
ranges, tasks, fps, and feature declarations without writing real dataset
rows or videos.

### M1b.3a: define a metadata-only LeRobot v3 export plan

The project now has a value-free `lerobot_metadata_plan` contract and builder
for a future multi-episode export. The plan binds the existing export gate and
target profile hashes, target vector layout, fps, required frame features
(`timestamp`, `frame_index`, `episode_index`, `index`, `task_index`), target
state/action plus `valid.retarget`, sequential task declarations, episode
lengths, contiguous shared-data index ranges, and the explicit
`preserve_source` episode-index policy. It also records the v3 data/episode,
tasks, info, and stats path templates and makes the no-video boundary
explicit. Validators reject unknown task references, gaps/overlaps in data
ranges, mismatched target shapes/names/dtypes, and allowlist drift.

The field choices were checked against the current upstream LeRobot v3
metadata organization, but this slice remains a project contract and does
not write `info.json`, `stats.json`, `tasks.parquet`, episode parquet, data
shards, or videos.

Remote verification:

- metadata-plan contract, gate/profile binding, target-shape rejection, and
  CLI round-trip tests: 3 passed;
- full regression with the real OpenArm asset smoke enabled: 108 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is a metadata-plan tamper/negative-test
expansion, followed by a synthetic writer that emits the planned metadata
files only after the plan is verified.

### M1b.3b: expand LeRobot metadata-plan negative coverage

The metadata-only plan now has explicit failure coverage for non-contiguous
episode data ranges, missing v3 required frame features, unknown task
references, and episode allowlist drift. These checks keep a structurally
plausible JSON plan from being promoted into a training-ready dataset claim.
The plan remains bound to the existing gate/profile hashes and still emits no
dataset rows, statistics values, or video files.

Remote verification:

- metadata-plan happy path, CLI round-trip, shape mismatch, range gap, missing
  feature, unknown task, and allowlist-drift tests: 7 passed;
- full regression with the real OpenArm asset smoke enabled: 112 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests harness/m1a` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is a synthetic-only metadata skeleton writer
that materializes the plan's `info`, tasks, and episode metadata files only
after re-verifying the plan; it will leave data/video/statistics values
explicitly incomplete.

### M1b.3c: materialize and verify a partial LeRobot metadata skeleton

The project now has a synthetic/public-only metadata skeleton writer. It
re-verifies the bound metadata plan before creating an output root, writes
plan-derived `meta/info.json`, `meta/tasks.parquet`, and grouped episode
metadata parquet files, and uses exclusive file creation. The generated info
records the source-preserving episode-index policy and the exact training
allowlist. The result is explicitly `PARTIAL`; data shards, video shards, and
`meta/stats.json` are omitted and listed in the write manifest. A verifier
rejects missing, extra, or tampered files and rechecks the task/episode table
values against the verified plan. The CLI exposes separate write and verify
commands, with an optional write manifest kept outside the dataset root.

Remote verification:

- metadata skeleton writer, grouped episode metadata, CLI round-trip, and
  info tamper detection: 9 passed;
- full regression with the real OpenArm asset smoke enabled: 114 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, data shard, or statistics value was read or
  written.

The next implementation boundary is to bind the skeleton's metadata contract
to actual synthetic target-table shards, while retaining an explicit
incomplete status until statistics and all declared data paths are verified.

### M1b.3d: bind one verified synthetic target table to a LeRobot data shard

The partial dataset writer now consumes only a verified synthetic table write
report and an already verified metadata skeleton. For the current prototype it
requires exactly one planned episode, checks robot/layout/frame/episode/task
identity, casts every declared Parquet feature to the plan's physical Arrow
type, writes the plan's `data/chunk-*/file-*.parquet` path exclusively, and
updates `meta/info.json` through an explicit partial-dataset state transition.
The partial verifier checks metadata, physical data values and types, lineage
metadata, exact output-file inventory, and rejects extra files. It records the
remaining omissions (`video_shards` and `meta/stats.json`) and refuses to
claim multi-episode materialization before that path is implemented.

Remote verification:

- metadata plan/skeleton/partial-dataset writer, CLI, and tamper tests: 11
  passed;
- full regression with the real OpenArm asset smoke enabled: 116 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or statistics value was read or written.

The next implementation boundary is multi-episode synthetic shard
materialization, which must first introduce a value-free mapping from each
episode's verified replay artifact to its declared data interval.

### M1b.3e: add the multi-episode replay binding manifest

The project now has a value-free `lerobot_replay_binding_manifest`. It maps
each planned episode index and contiguous dataset interval to one independently
verified target replay bundle, preserving the bundle path/hash, replay id,
robot id, export-profile hash, target layout, and frame count. The builder
requires exact coverage of the metadata plan's episode allowlist and rechecks
every bundle before recording the binding. The verifier rebuilds the manifest
from those bound files, so changing a bundle or mapping cannot be hidden by
editing the JSON summary. CLI build/verify commands accept an explicit JSON
episode-to-bundle map.

Remote verification:

- replay binding contract, gate/profile/layout/frame checks, CLI round-trip,
  and allowlist mismatch tests: 12 passed;
- full regression with the real OpenArm asset smoke enabled: pending for this
  slice;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is a multi-episode target-table binding
manifest and grouped data-shard writer that consumes one verified synthetic
target-table report per episode.

### M1b.3f: bind per-episode target-table reports

The project now has a value-free `lerobot_target_table_binding_manifest` that
chains the metadata plan, the per-episode replay binding manifest, and one
verified synthetic target-table write report per episode. The builder rechecks
each report, matches its bundle path/hash and replay id to the replay binding,
and matches robot, layout, frame count, and selected episode to the plan. The
manifest preserves each episode's data interval and report hash; its verifier
rebuilds the full chain, so report or replay changes cannot be hidden by
editing the binding JSON. CLI build/verify commands accept an explicit
episode-to-report map.

Remote verification:

- replay binding, target-table binding, metadata skeleton/partial writer, CLI,
  and tamper tests: 13 passed;
- full regression with the real OpenArm asset smoke enabled: 118 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is grouped multi-episode data-shard writing
from this verified target-table binding manifest; it must preserve the
declared episode intervals and keep video/statistics omissions explicit.

### M1b.3g: chain target-table reports to replay bindings

The project now has a value-free
`lerobot_target_table_binding_manifest`. It binds each planned episode's
verified synthetic target-table report to the exact replay bundle path/hash
and replay id already recorded by the per-episode replay binding manifest,
while retaining the plan's dataset interval and report hash. Builder checks
re-run the report verifier and compare robot, layout, frame count, and selected
episode; the manifest verifier rebuilds the entire plan -> replay bundle ->
target-table-report chain. This provides the explicit input map required by a
future grouped multi-episode data writer without inferring order from filenames.

Remote verification:

- replay binding, target-table binding, metadata skeleton/partial writer, CLI,
  and mismatch tests: 13 passed;
- full regression with the real OpenArm asset smoke enabled: 118 passed and 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed.

The next implementation boundary is grouped multi-episode data-shard writing
from this verified target-table binding manifest; it must preserve the
declared episode intervals and keep video/statistics omissions explicit.

### M1b.3h: write grouped multi-episode data shards

The project now materializes a grouped, video-free partial LeRobot dataset
from the verified target-table binding manifest. The writer re-verifies the
metadata skeleton, replay bindings, every target-table report, and each
episode's declared interval before reading any table rows. It normalizes the
declared state/action feature types to the plan, groups contiguous episode
tables by the plan's data chunk/file coordinates, writes exact Parquet shard
paths, and updates `info.json` with the written data inventory. The verifier
checks the exact file inventory, metadata, episode ranges, row values,
feature types, and Parquet metadata; report, binding, table, and output-root
tampering are covered by tests. The result remains explicitly `PARTIAL`:
videos and statistics are still omitted, so this is not yet a claim of a
training-ready public dataset.

Remote verification:

- focused LeRobot export tests: 14 passed;
- full regression with the real OpenArm asset smoke enabled: 119 passed, 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or
  changed; all writer coverage uses synthetic fixtures.

The next implementation boundary is statistics handling or an explicit
statistics preflight. It must retain the current partial-export boundary and
must not silently imply compatibility with the upstream training loader.

### M1b.3i: write and verify numeric statistics

The partial grouped dataset can now receive a separate, exclusive
`meta/stats.json` stage. After re-verifying the plan, target-table binding
chain, metadata, and every grouped data shard, the writer computes exact
population statistics for the declared scalar/one-dimensional numeric
features using the explicit `numpy_exact_v0.1` algorithm. It writes the
LeRobot basic statistics plus q01/q10/q50/q90/q99 and updates `info.json` to
record `stats` as written while retaining `video_shards` as the only omitted
component. The verifier recomputes statistics from the materialized data
shards and rejects changed values, types, metadata, lineage, or file inventory.
The dataset remains `PARTIAL` because no video shards are synthesized.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with the real OpenArm asset smoke enabled: 120 passed, 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- statistics coverage is synthetic/public only; no private dataset rows or
  video output was read or changed.

The next implementation boundary is a loader-compatibility preflight for the
video-free numeric dataset, while preserving the explicit partial status and
not claiming upstream training compatibility without direct loader evidence.

### M1b.3j: align tasks parquet with the current LeRobot loader

The current LeRobot `load_tasks` path reads `meta/tasks.parquet` through
pandas and uses the task string as the named index, with `task_index` as the
data column. The exporter previously wrote the task string as an ordinary
`task` column, which could make a loader see a RangeIndex and lose task-name
lookup. The tasks writer now emits the pandas-compatible index field
`__index_level_0__`, records the named `task` index in the Parquet pandas
metadata, and retains `task_index` as the physical data column. Skeleton,
partial, grouped, and statistics verifiers compare schema metadata as well as
values, so index metadata drift is now detected.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with the real OpenArm asset smoke enabled: 120 passed, 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows or video output was read or changed.

The next implementation boundary is a local loader-contract preflight that
checks the emitted info, tasks, episode metadata, data, and stats assumptions
against the current public LeRobot file contract without silently claiming
that the optional upstream training dependencies are installed.

### M1b.3k: make video-free info fields explicit

The emitted `meta/info.json` now records `video_path: null` for the
video-free plan and includes the current LeRobot default data/video file-size
fields instead of relying on loader-side defaults. This keeps the output
self-describing while preserving the deliberate `PARTIAL` status and the
absence of video shards.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with the real OpenArm asset smoke enabled: 120 passed, 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed.

### M1b.3l: record the local loader-contract preflight

The partial numeric LeRobot v3 output now has an explicit loader-contract
preflight. It rechecks the current `info.json`, the named task index and
`task_index` metadata, episode data-link columns, grouped data feature
schemas, numeric statistics, and the video-free file inventory. The result is
persisted as a separate, exclusive preflight artifact and exposes
`upstream_training_compatibility: NOT_CLAIMED` so structural compatibility is
not confused with a successful upstream training run.

The current metadata plan deliberately preserves source episode identifiers.
For the synthetic plan these are `(3, 4)`, while the current explicit
LeRobot loader selection contract requires zero-based contiguous episode
indices. The preflight therefore reports `BLOCKED` with the explicit reason
`preserve_source_episode_indices_are_not_zero_based_for_explicit_loader_selection`.
This is a recorded compatibility boundary, not a writer failure or a reason
to stop the development chain; the default preserve-source policy remains
unchanged and no silent reindexing is introduced.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with the real OpenArm asset smoke enabled: 120 passed, 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- preflight CLI build/verify behavior is covered, including the expected
  quality-status exit for the explicit blocked boundary;
- all coverage remains synthetic/public only; no private dataset rows, video,
  or target dataset output was read or changed.

### M1b.3m: materialize the direct dataset-loader configuration

The verified loader preflight now feeds an exclusive training-dataset config
artifact. It records the exact local `repo_id`, dataset `root`, and episode
allowlist needed by the LeRobot loading path, pins the intended runtime
dependency as `lerobot==0.6.1`, and binds the config to the preflight hash.
The artifact explicitly remains `upstream_training_compatibility: NOT_CLAIMED`;
it is a reproducible loader configuration, not evidence that a training run
has succeeded.

When the preflight is `BLOCKED`, the config preserves that status and the
blocking reason and the CLI returns `EXIT_QUALITY`. A `READY` config is only
valid when its episode selection is zero-based and contiguous, so the new
artifact cannot silently turn a non-compatible source-index selection into a
training-ready claim.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with the real OpenArm asset smoke enabled: 120 passed, 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- config build/verify CLI coverage preserves the expected BLOCKED quality
  status for the current `(3, 4)` synthetic source-index fixture;
- all coverage remains synthetic/public only; no private dataset rows, video,
  or target dataset output was read or changed.

### M1b.3n: keep split metadata positional and source-index metadata separate

The LeRobot `splits` field is now emitted as the physical dataset range
`0:<total_episodes>`, matching the upstream writer convention. It no longer
uses the minimum and maximum source episode identifiers, which could describe
an interval containing episodes that are not materialized when a selected
source subset has identifiers such as `(3, 4)`. The original source IDs remain
explicitly recorded in `retargetlab.training_episode_allowlist`, and the
loader preflight still blocks the non-zero-based partial fixture.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with the real OpenArm asset smoke enabled: 120 passed, 1
  Panda asset smoke skipped;
- `ruff check src tests` and `mypy src`: passed;
- metadata, grouped data, statistics, loader preflight, and loader-config
  verifiers continue to reject schema/value drift;
- all coverage remains synthetic/public only; no private dataset rows, video,
  or target dataset output was read or changed.

### M1b.3o: run the complete dual-morphology regression

The full remote regression was rerun with both versioned target asset bundles
enabled: the real OpenArm bimanual asset and the staged Panda bimanual asset.
All 121 tests passed with no asset-related skip. The existing solver warnings
remain limited to qpsolvers sparse-matrix conversion and the upstream OSQP
deprecation notices; they do not change the pass/fail result.

This verifies that the LeRobot metadata/export additions did not regress either
target morphology's URDF/SRDF loading, collision policy, FK, or Pink solve
smokes. It still does not authorize private source-row export or claim an
upstream LeRobot training run.

### M1b.3p: expose optional LeRobot runtime readiness

The `doctor --json` report now distinguishes the core retargetlab runtime from
the optional upstream LeRobot loader stack. It reports `lerobot`, `torch`,
`datasets`, and `huggingface_hub` explicitly and exposes `optional_missing`
without turning their absence into a failure of the core solver/export
environment.

On this remote host the core environment is `READY`, while those four loader
dependencies are missing. `/root/lerobot` is present as a read-only source
checkout at revision `64b23178d5348609c266250d3e1f511eba4c33ff`, whose package
version is `0.6.2`; it is not silently substituted for the pinned
`lerobot==0.6.1` runtime in the generated config. No environment installation
or upstream training/loader claim was made.

Remote verification:

- `doctor --json` reports the optional runtime boundary explicitly;
- focused CLI tests: 9 passed;
- full regression with both OpenArm and Panda assets enabled: 121 passed;
- `ruff check src tests` and `mypy src`: passed.

### M1b.3q: remove an unverified pandas producer-version claim

The tasks Parquet writer keeps the pandas-compatible named-index metadata
required by the LeRobot task loader, but no longer inserts a hard-coded
`pandas_version`. This project writes the table through PyArrow rather than
pandas, so the previous value was not evidence-backed and could misdescribe
the producer. The actual index field, index name, and `task_index` metadata
remain schema-verified.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with both OpenArm and Panda assets enabled: 121 passed;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or changed.

### M1b.3r: enforce external audit-artifact placement

Loader preflight and training-dataset config writers now reject output paths
inside the dataset root. These artifacts are audit/config references, not
dataset members; placing either one under `data/` or `meta/` would invalidate
the file inventory bound by the preflight and could make a later verifier
report a false mismatch. The negative case is covered for the training config
writer.

Remote verification:

- focused LeRobot export tests: 15 passed;
- full regression with both OpenArm and Panda assets enabled: 121 passed;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or changed.

### M1b.3s: pin the optional loader extra without polluting the core env

The package metadata now exposes `lerobot==0.6.1` as an explicit optional
`lerobot` extra, and `env/constraints.txt` records the same exact pin under
the M1b acceptance-only section. The core package still has no LeRobot import,
so M-1/M0 users do not pull in the upstream loader's large torch/vision stack.

The remote retargetlab environment was not modified or installed from this
extra. Its `doctor` result remains core `READY` with the optional loader stack
reported as missing; the pin is now reproducible for a separately provisioned
acceptance environment.

Remote verification:

- `pyproject.toml` parses and exposes `['lerobot==0.6.1']`;
- constraints contain the exact same pin;
- `ruff check src tests` and `mypy src`: passed;
- full dual-morphology regression remains green at 121 passed;
- no private dataset rows, video, or target dataset output was read or changed.

### M1b.3t: register the optional upstream loader smoke boundary

The test suite now registers a dedicated `lerobot` marker and adds an
acceptance-only API smoke test pinned to `lerobot==0.6.1`. When that optional
runtime is available, the smoke checks the documented `LeRobotDataset`
constructor surface (`repo_id`, `root`, `episodes`, and `download_videos`). It
does not turn the optional stack into a core dependency, does not claim local
dataset loading or training compatibility, and skips cleanly when the optional
runtime is absent.

On this remote host the smoke test skipped because `lerobot` is not installed;
the read-only `/root/lerobot` source checkout at version 0.6.2 was not silently
substituted for the pinned 0.6.1 acceptance runtime.

Remote verification:

- `pytest -m lerobot -q`: 1 skipped, 121 deselected;
- full dual-morphology regression: 121 passed, 1 skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or changed.

### M1b.4: keep failed rows, bind the training whitelist, and filter stats

The synthetic/public LeRobot path now has an explicit retarget-mask artifact.
Each episode records a boolean frame mask, derived `PASS`/`WARN`/`FAIL`
status, the first valid frame, and the valid-frame count. The materializer
keeps every physical row and writes `retarget.status` into
`meta/episodes/*`. For a partial episode, leading invalid frames take the
first valid target value and later invalid frames take the most recent valid
target value. An all-invalid episode is retained as `FAIL` with its candidate
values unchanged because there is no valid value from which to fill it.

The effective training episode allowlist is derived as the intersection of the
plan allowlist and `PASS` episodes. `valid.retarget` is registered as a formal
feature and is explicitly excluded from normalization. Numeric statistics now
use only rows that are both in that training allowlist and marked valid; they
fail clearly when that view contains no valid rows. The mask hash and policy
are carried into `info.json`, dataset/statistics manifests, loader preflight,
and the direct training config. CLI build/verify commands are available, and
dataset/statistics/loader-preflight commands accept the same external mask.

This slice remains synthetic/public-only. It does not delete or rewrite any
private source rows or videos, and it does not claim that the custom mask is
automatically consumed by an upstream training loop.

Remote verification:

- focused LeRobot export tests: 16 passed;
- focused CLI/contracts tests: 12 passed;
- full dual-morphology regression: 122 passed, 1 skipped;
- `ruff check src tests` and `mypy src`: passed;
- no private dataset rows, video, or target dataset output was read or changed.

### M1b.7: add the optional five-check LeRobot acceptance report

The project now has an explicit loader-backed acceptance boundary with five
named checks: configuration binding, episode allowlist, temporal windows,
normalization of a small batch, and FK semantic recheck. The first four checks
use the exact `LeRobotDataset` configuration and keep the optional runtime
imports inside the acceptance function. Missing `lerobot`, `torch`,
`datasets`, or `huggingface_hub` produces an archived
`ENVIRONMENT_UNAVAILABLE` report rather than a false compatibility claim.

The FK semantic check is deliberately recorded as `BLOCKED` for the current
config contract: the direct training config does not yet bind a
`RobotProfile` and source EEF reference artifact. The report verifier checks
the config hash, identity, five-check structure, and current config binding
without silently rerunning an unavailable optional environment. CLI build and
verify commands are available, and audit reports remain outside the dataset
root.

On this remote host the optional loader stack remains uninstalled, so the
loader-backed path was not falsely reported as passed. No private dataset
rows, video, or target dataset output was read or changed.

Remote verification:

- acceptance/CLI/contracts focused tests: 14 passed;
- full dual-morphology regression with both assets enabled: 124 passed, 1 skipped;
- `ruff check` on changed files and `mypy src`: passed;
- CLI help exposes `run-lerobot-acceptance` and `verify-lerobot-acceptance`.

### M1b.8: bind and execute the LeRobot FK semantic recheck

The direct training dataset configuration now carries the verified
target-table binding manifest path and file hash. The acceptance runner follows
that binding through each selected replay bundle, both materialized streams,
the replay manifest, RobotProfile, ExportProfile, and the canonical EEF
trajectory. It rechecks the loader values against the bound state/action
artifacts before expanding the exported arm-plus-gripper-driver layout into
the complete Pinocchio model q order; mimic joints are reconstructed from the
declared gripper semantics.

Both `observation.state` and `action` are independently FK-checked against the
same-frame canonical EEF poses, with position/orientation limits taken from
the replay recipe thresholds and falling back to its solve options. The first
supported mapping is intentionally narrow: the recipe must explicitly record
`identity_dataset_native_hypothesis`; absent or unsupported frame mapping
remains a blocking semantic result rather than an inferred pass. The report
can now become `PASSED` only after all five checks, including this two-stream
recheck, pass.

This slice remains synthetic/public-only and does not read or modify private
dataset rows, videos, or target dataset output. The remote environment still
does not install the optional LeRobot runtime, so the loader-backed end-to-end
acceptance remains environment-gated; the FK lineage resolver and Pinocchio
two-stream check are covered independently with the fixture artifacts.

Remote verification:

- focused LeRobot export/replay/acceptance tests: 26 passed;
- `ruff check src tests` and `mypy src`: passed;
- verified the complete fixture binding chain resolves one FK context for a
  selected episode;
- no private dataset rows, video, or target dataset output was read or changed.

### M1b.9: add an explicit zero-based LeRobot loader view

The source-preserving export remains the audit source of truth, while a new
opt-in compatibility materializer creates an independent loader view only from
an already verified numeric/video-free dataset and its loader preflight. The
view maps source episode ids to `0..N-1` in plan order, rewrites only the
`episode_index` columns in data and episode metadata, and updates the
`info.retargetlab` namespace with both id spaces, the source plan/preflight
hashes, and the mapped training allowlist. Task metadata and statistics are
copied unchanged and every source/output file is recorded with a SHA-256 hash
in the external compatibility receipt.

The output is built in a private staging root and published only after the
file set is materialized; source and output roots must be disjoint and the
source-preserving plan/binding/mask artifacts are not duplicated or rewritten.
A compatibility preflight consumes the receipt, removes only the known
source-index blocker, and exposes loader physical episode ids to the training
config. FK acceptance maps those loader ids back to source ids before resolving
replay/binding lineage, so the two namespaces cannot be silently conflated.

CLI commands now cover compatibility write/verify and compatible-preflight
creation. The default preserve-source path is unchanged, and this view still
records `upstream_training_compatibility: NOT_CLAIMED`; the pinned
`lerobot==0.6.1` runtime remains uninstalled on the remote host, so no real
loader or training pass is claimed.

Remote verification:

- focused LeRobot export/acceptance tests: 20 passed;
- full dual-morphology regression: 122 passed, 5 skipped;
- `ruff check` and `mypy src`: passed;
- compatibility receipt verification binds source/output hashes and mapped
  Parquet values; no private dataset rows, video, or target dataset output was
  read or changed.

### 2026-09-04 · resume the OpenArm-first route after user confirmation

The user explicitly reaffirmed that OpenArm is the first adaptation target.
The earlier Panda target-reselection spike remains diagnostic evidence only;
it does not change the active delivery order. Panda remains a future
regression fixture after the OpenArm loop is resolved.

The M-1 diagnostic harness was corrected and hardened before this run. T2
candidates are now derived from the recipe grid rather than a hidden default
grid; the report supports aggregate prescreen mode, direct/swapped side
hypotheses, `hand_tcp`/`link7` frame hypotheses, failure-status counts, bounded
retry/iteration budgets, and an exclusive output path. Reports explicitly
assert that held-out values, private values, and source paths were not emitted.

Recipe `20260904-m1-openarm-006` isolated an x/y directional expansion from
the prior boundary candidate `t2-059`. It preserved z, yaw, the identity
dataset-native pose hypothesis, the OpenArm solver, and the registered gate.
The 81-candidate grid was x `[0.20, 0.30, 0.40]` m, y `[-0.40, -0.30,
-0.20]` m, z `[-0.10, 0.00, 0.10]` m, and yaw `[-20, -10, 0]` degrees. The
recipe sidecar hash is `0865eadfc8c8155c73f87d9f333c2b47039c7694a3f386cfc6f6d02a9b953573`.

The complete calibration prescreen merged 27/27 disjoint reports (81/81
candidates, 60 frames each) into
`projects/private-sample-openarm/runs/20260904-m1-openarm-006/prescreen-calibration-60.json`.
Its best candidate reached 0.30 nominal and 0.35 relaxed reachability, with
0.15 penetration fraction; zero candidates reached the 0.80 yellow gate.
The best result is the old boundary point in the new grid's overlap, so the
isolated x/y expansion did not recover feasibility. The OpenArm M-1 result
therefore remains RED, and the top-9 full evaluation is intentionally not
authorized by the gate.

The aggregate workspace check did not show an inherently impossible arm-span
constraint: source inter-EEF distances remained inside the OpenArm random
reachability cloud, with only a small tail outside its p01-p99 range. The next
OpenArm action is therefore semantic/constraint diagnosis (T2 anchor and
coordinate/frame mapping, then one-arm/bimanual constraint isolation), not a
larger blind T2 grid. The long tail runtime of the two hardest shards is also
recorded as follow-up work: add candidate-level checkpoints or timeouts before
the next broad sweep. No held-out split was read.

Remote verification:

- 27/27 prescreen reports passed merge validation with unique candidate ids;
- merged report contains 81 candidates and preserves the private-data output
  policy flags as false;
- no held-out values, private pose values, source paths, video, or target
  dataset output were read or changed.

### 2026-09-04 · isolate OpenArm frame and orientation semantics

The next OpenArm-first slice held candidate `t2-023` fixed and compared the
unconfirmed target frame and orientation hypotheses on the same 60 calibration
frames. Under an identical diagnostic budget (120 outer iterations, one target
seed), the four combinations were:

- identity + `hand_tcp`: 1/60 nominal, 0.583 penetration fraction;
- identity + `link7`: 2/60 nominal, 0.450 penetration fraction;
- `viser_left_inverse` + `hand_tcp`: 3/60 nominal, 0.750 penetration fraction;
- `viser_left_inverse` + `link7`: 25/60 nominal, 26/60 relaxed, 0.117
  penetration fraction.

The combined hypothesis was rerun with the complete recipe solver budget (300
outer iterations, four target seeds). It reached 28/60 nominal, 29/60 relaxed,
and 0.117 penetration fraction. The full-budget report is
`projects/private-sample-openarm/runs/20260904-openarm-recovery-002/viser-left-inverse-link7-t2-023-full-budget.json`
with SHA-256
`5edb15f1ab6be0c9a7bd47df717fbdfcaad101173e4ed1686537bbcbab90e643`.

This is strong evidence that the identity pose hypothesis is a poor diagnostic
fit, and that frame/orientation choices interact; it is not enough to promote
`viser_left_inverse` or `link7` into the formal recipe. The best result remains
below the 0.80 yellow gate and retains penetration. The source metadata says
the original EEF values came from `Larm08_link`/`Rarm08_link` with a recorded
flange-to-TCP translation of `[0, 0, 0.22855]` and unchanged quaternion, while
the source URDF and coordinate-frame declaration are unavailable. The next
OpenArm action is therefore to obtain or reconstruct an authorized source-
to-target frame mapping and validate it, followed by per-arm versus shared
bimanual constraint isolation. No formal recipe or held-out access was changed.
