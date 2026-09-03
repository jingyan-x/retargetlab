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
