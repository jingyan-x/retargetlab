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
