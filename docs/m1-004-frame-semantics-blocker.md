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

Recipe `20260903-m1-005` then expanded T2 directionally from the previous boundary
candidate without changing the frame hypothesis or solver gate. Its one-frame
diagnostic prescreen covered 81 candidates and produced 10 nominal candidates,
15 relaxed candidates, 11 converged candidates, and 36 collision-free candidates.
The best gate-ratio candidate was `t2-072` (`x=0.20`, `y=0.00`, `z=-0.10` m,
`yaw=-20` deg), with 1.9997 mm position error and 1.2670 deg orientation error
on the diagnostic frame. The diagnostic report is
`runs/20260903-m1-005/prescreen-one-frame.json` (SHA-256
`bdd14c53679ca609f83e49ee0e4fa4cbeea22c3917f1cc407953fb7ac458288a`).

This is a calibration-only one-frame diagnostic, not the registered T2 prescreen
and not the M-1 exit result. The next gate is the registered 60-frame prescreen;
only its ranking may select the top 9 for the full evaluation over the 600
calibration single frames and 20 continuous segments.

## Registered OpenArm result

The registered `20260903-m1-005` 60-frame calibration prescreen was completed
without reading held-out values. Its best nominal rate was 30.0%, its best
relaxed rate was 35.0%, and no candidate was collision-free across all 60
frames. This is a formal red result. The one-frame diagnostic above is retained
as context only; it did not select or override the formal result.

Following the pre-registered red-light procedure, the next step was a separate
target-reselection spike. OpenArm remains blocked for M-1 and its results were
not reused as Panda candidate scores.

## Target-reselection spike: Panda

Recipe `20260904-m1-panda-002` evaluates an independent dual-Panda target. The
asset is explicitly `target_reselection_spike_only`, not a replacement for the
future Panda product profile. It was generated from the pinned official
`franka_ros` dual-arm example at revision
`ddd2fffd9de44b02ad15b4bbb2bfa2cec4d60d98`; the adapted MoveIt SRDF source is
pinned at `c55b102711fc0aebe80c6952d2ce97c38110abba`. The official dual-arm
example's side comments establish the mapping used here: dataset left maps to
`panda_2` and dataset right maps to `panda_1`. The earlier opposite-mapping
Panda run was discarded and is not part of this evidence.

The Panda asset and collision checks both passed: model `nq=nv=18`, 19
portable mesh files, 68 adapted SRDF entries, 88 selected coarse collision
objects, and the nine required cross-arm base pairs preserved after SRDF
filtering. The 81-candidate one-frame diagnostic was consistent with the
corrected mapping. The registered 60-frame prescreen had 81/81 candidates with
nominal rate above zero and 16/81 candidates with zero penetration over all
prescreen frames.

The top 9 from that frozen prescreen were evaluated on the full calibration
budget. Best candidate `t2-080` uses translation offset `[0.10, 0.10, 0.10] m`
and yaw offset `10 deg`. It achieved:

- full single-frame nominal rate `99.17%` (594/600), relaxed rate `100%`, and
  penetration fraction `0.83%`;
- 20/20 continuous segments nominal, with continuous penetration fraction `0`;
- no joint-limit or delta violations.

Under the pre-registered gate this is `YELLOW`, because the full single-frame
result contains a small penetration fraction and uses the relaxed orientation
tolerance on some frames. It is not `GREEN` and does not establish frame
identity. Per the build checklist, the yellow condition is recorded for M0 and
must be rechecked before M1; held-out episodes remain unopened.

The key remote evidence files are under
`projects/target-reselection-panda/runs/20260904-m1-panda-002/`: the recipe,
asset assertions, collision probe, 60-frame prescreen, merged full top-9
report, and the OpenArm harness regression smoke report. The merged report's
SHA-256 is
`124cacb1bf2e34c4de27c3b5ce5ceed9176fb4917a8f3dda02fd4bbf94d1fe82`.

## Next gate

Do not promote the identity mapping, the local Viser rotation, the `link7`
hypothesis, or the Panda side mapping into a physical frame claim. The current
Panda result is a conditional target-reselection checkpoint only. M0 may record
the yellow condition, but M1 must recheck it before any data export or held-out
evaluation. A source URDF or explicit mapping remains useful for later
cross-checking, but is not silently assumed as a prerequisite:

- the source URDF and source TCP/frame convention; or
- an authorized source-to-target pose mapping with its evidence and validation set.

Held-out episodes remain unread before M-1c, and no raw private poses or source paths belong in reports.

## 2026-09-04 follow-up: OpenArm-first semantic isolation

The user subsequently reaffirmed that OpenArm is the first adaptation target.
The Panda section above remains historical target-reselection evidence; it does
not change the active OpenArm-first order and does not authorize promoting the
Panda mapping into a source-frame claim.

The diagnostic harness now supports aggregate calibration-only comparisons for
the target frame (`hand_tcp` or `link7`), side mapping, orientation hypothesis,
and bounded solver budgets. On the new recipe
`20260904-m1-openarm-006`, candidate `t2-023` was held fixed and 60 calibration
frames were evaluated under four semantic combinations. With the same
120-iteration/1-seed diagnostic budget, identity/hand_tcp reached 1/60 nominal,
identity/link7 2/60, and viser-left-inverse/hand_tcp 3/60. The combined
viser-left-inverse/link7 hypothesis reached 25/60 nominal and 26/60 relaxed,
with 0.117 penetration fraction. This is a useful directional signal, not a
frame-identity proof.

The combined hypothesis was then rerun with the full recipe budget (300 outer
iterations and 4 target seeds). It reached 28/60 nominal, 29/60 relaxed, and
0.117 penetration fraction. It remains below the 0.80 yellow gate and is not a
candidate for formal recipe promotion. The evidence reports are retained under
the gitignored `20260904-openarm-recovery-002` run directory; the full-budget
report SHA-256 is
`5edb15f1ab6be0c9a7bd47df717fbdfcaad101173e4ed1686537bbcbab90e643`.

The source metadata provides an important constraint on interpretation: the
dataset declares source end links `Larm08_link`/`Rarm08_link` and records a
flange-to-TCP translation of `[0, 0, 0.22855]` with unchanged quaternion, but
the source URDF and coordinate-frame declaration are absent. The OpenArm
`link7`/`hand_tcp` relationship is therefore only a diagnostic hypothesis.
The next OpenArm gate is to obtain or reconstruct an authorized source-to-
target frame mapping and validate it on calibration data, then isolate
per-arm versus shared bimanual constraints. Do not rewrite the formal recipe,
open held-out episodes, or export data until that semantic evidence exists.

## 2026-09-04 follow-up: single-arm versus bimanual isolation

The repository now carries `harness/m_minus_1/diagnose_single_arm.py`, a
calibration-only diagnostic that removes the inactive EEF task and collision
pairs while preserving target limits, mimic constraints, and the registered
solver strategy. For candidate `t2-023` under the `link7 +
viser_left_inverse` hypothesis, 60 calibration frames gave 40/60 nominal for
the left arm and 34/60 for the right arm with a bounded 120-iteration/1-seed
budget; neither side had joint-limit violations.

A full-budget bimanual run with collision pairs removed gave 46/60 left-side,
41/60 right-side, and 29/60 both-side nominal. The same bimanual run with the
full collision model gave 28/60 both-side nominal and 0.117 penetration
fraction. Collision therefore accounts for only one additional failed frame;
the dominant issue is the conjunction of two imperfect single-arm semantic
fits, not a structural collision barrier failure.

This evidence does not authorize relaxing bimanual constraints or promoting
the candidate frame/orientation mapping. The next gate remains an authorized
source-to-target frame reconstruction, followed by independent per-arm
validation and only then a new bimanual recipe. Held-out episodes and export
data remain unopened.

## 2026-09-04 follow-up: frame-lineage preflight

`harness/m_minus_1/inspect_openarm_frame_lineage.py` now provides a
value-free, calibration-independent preflight for the semantic handoff. It
checks the target manifest/URDF hash, both candidate target frames, the fixed
TCP chain, and path portability, while recording only hashes and aggregate
booleans. It accepts optional source-URDF or authorized-mapping evidence for
the next handoff; neither input alone authorizes recipe promotion.

The current report confirms the OpenArm target asset is ready for semantic
validation: both fixed chains are explicit and total `0.1801 m` in z, with
relative mesh references and matching manifest hash. The review-only mapping
candidate still has unresolved source coordinate frame, position unit, and
slot labels, and no source URDF or authorized mapping is present. The report
therefore returns `BLOCKED_SEMANTICS` and
`OBTAIN_SOURCE_FRAME_EVIDENCE`. Its SHA-256 is
`e036231036252e4ee2b8c54576f5530854b5a1bf8e9d8ea06888f7bcfaecfcc7` under the
gitignored `20260904-openarm-recovery-004` run directory.

This is an evidence gate only. It does not change the formal recipe, open
held-out episodes, relax collision/IK constraints, or produce export data.

## Strict data-only axis candidate gate (2026-09-04)

The earlier preflight's `OBTAIN_SOURCE_FRAME_EVIDENCE` blocker is retired.
The tracked MappingSpec record now marks the schema facts and their evidence
levels separately from the three unresolved frame questions. The source URDF
is an optional cross-check and is not required for the product or for the
data-only calibration.

The new preflight returns
`READY_FOR_DATA_ONLY_CALIBRATION` and
`RESOLVE_FRAME_SEMANTICS_FROM_SCHEMA_OR_DATA_ONLY_CALIBRATION`. It still sets
`semantic_status=UNRESOLVED`, keeps `kinematic_status=RED`, and refuses formal
recipe promotion until a validated candidate exists.

The strict calibration-only screen evaluated 24 legal proper axis rotations,
both forward/inverse pose directions, both `link7` and `hand_tcp`, and direct
left/right mapping: 96 deterministic candidates in total, each arm on the
same 60-frame calibration prescreen and the same 120-iteration/1-seed IK
budget. No candidate reached 0.80 nominal on both independent arms. The best
`link7` rates were left `0.050` and right `0.550`; the best `hand_tcp` rates
were left `0.183` and right `0.067`. No joint-limit violations were observed
in these single-arm aggregates. Because the single-arm gate failed, the
bimanual shortlist remained empty and no bimanual run was performed.

This is the stop condition requested for the data-only rotation search. Do
not expand the axis set or open held-out data. The next gate is to resolve
pose direction, source base/world semantics, and source-tool-to-OpenArm
tool-frame alignment, then repeat the independent-arm gate with the corrected
semantic transform. The merged report is retained outside Git under the
calibration-only run workspace; its SHA-256 is
`165c17aec153150abce18b886f6889baabcfd4a38bb4a3467abf8cab0aa4cde0`.
