---
name: retargetlab
description: Install the complete RetargetLab runtime or operate its EEF processing, robot replay, diagnosis, dataset export and reader-validation workflows. Use for RetargetLab tasks and explicitly supported OpenArm or MQ03 EEF workflows.
---

# RetargetLab

Use the user's language. This skill is validated against **RetargetLab 0.1.0rc4** on Linux x86_64/Python 3.12. It operates the existing tool; it does not make missing adapters, physical validation or task management capabilities exist.

## Choose one entrance

- **Install or repair installation:** read [installation](references/install.md). Default to the complete supported runtime, in separate processing/replay and reader environments. Do not ask for a dataset or a future usage task. End after installation and its checks.
- **Use an existing installation:** read [usage](references/usage.md). Check the components required by this task without changing them. An unrelated reader fault does not block replay; this does not make the full installation healthy. Do not implicitly install, update or remove dependencies.
- If the user explicitly asks to install **and then** perform a task, complete the two workflows separately, retaining the requested task and its scope.

An existing environment fault does not authorize entering installation. Offer repair installation, an existing compatible environment, or pausing the affected step; act on the user's selection. Reuse prior authorization and decisions instead of asking again.

## Establish the requested result

When the goal is ambiguous, ask: “这次完成后，你希望得到什么结果？” When it is clear, state the operation and deliverable briefly and proceed. Do not turn a clear instruction into another approval request.

Select the minimum complete workflow:

| User task | Included work | Stop after |
|---|---|---|
| Inspect input structure | Read metadata/structure within the requested scope | Structure and concrete missing/unsupported fields |
| Replay EEF on a specified robot | Resolve required semantics/model, continuous IK if no valid saved solution exists, build and serve replay | Robot replay and actual processing/quality limitations |
| Replay saved results | Verify/reuse the result and matching model/bundle; serve replay | Accessible replay; no new IK |
| Diagnose an existing run | Read its actual report, locate requested failures; replay only if requested/useful to that diagnosis | Evidence-based findings; no automatic repair experiments |
| Export and/or verify a dataset | Check the chosen input/policy, export only when requested, run the actual reader when requested or needed for the agreed usable-data deliverable | Requested files and reader evidence |

“EEF robot replay” already includes the necessary IK; do not ask for separate permission to solve. It does **not** include training export, parameter searches, dynamics, or real-robot execution. Pure EEF-only 3D replay is not a standalone rc4 interface; do not invent a robot requirement to make that different task fit.

For new data or models, read [inputs](references/inputs.md). Use existing configuration and explicit metadata before asking for information. Necessary information need not be manually supplied. Do not infer unknown units, pose direction, TCP, stream meaning or gripper physics just to make the command run.

## Decisions during execution

Use [decision patterns](references/decisions.md) only at actual decision points. Explain the observed fact and its effect, then offer 2–3 feasible actions when a user choice is needed. A recommendation is not consent. Skip only a separable part and explicitly update the resulting deliverable.

Perform normal operations and clear, scope-preserving corrections autonomously. Do not expand the dataset, change a quality threshold, shift labels, run additional searches, or substitute a smaller task without a clear instruction/selection. Do not repeatedly retry an unchanged failure.

## Execute and deliver

- Read `--version` and relevant `--help`; use the actual environment interpreter. For another release, report that this skill has not validated that release and inspect compatibility before relying on these instructions. Never silently downgrade or upgrade.
- Use structured command output and the saved report together. Exit 0 or `COMPLETED` does not mean every frame meets the policy. Report missing capability, missing material, runtime failure and quality failure separately.
- Preserve input data, saved solutions and their hashes. Use new output directories. Source joints may be post-check evidence; they are not IK seeds or replacements for failed solutions.
- Use only the capabilities listed in [usage](references/usage.md). rc4's source-URDF/source-Joint requirements are specific interface constraints, not universal requirements for all EEF data.
- At the agreed endpoint, give the artifact/URL, input/version/scope, checks actually run and remaining requested work. Do not automatically proceed to the next workflow or claim an unsupported check passed.

Model files, user data, host addresses and experiment paths come from the current task or installation record; this skill contains no laboratory-specific defaults.
