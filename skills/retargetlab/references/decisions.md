# Decision patterns

These are response patterns, not a checklist to present every time. Use the user's language. Fill only facts supported by the actual request, files and command results.

| Situation | Wording and feasible actions |
|---|---|
| Ambiguous task | “这次完成后，你希望得到什么结果？” If the task is already clear, briefly restate its scope and act. |
| Missing required material | “完成【当前任务】还缺【材料】，用于【具体步骤】。” Offer supplement / skip the entire affected part with a changed deliverable / pause, only where feasible. |
| Missing optional evidence | “【材料】可增加【检查】；不提供仍能完成【原定结果】。” Offer continue without that check or provide the evidence. Do not hold the whole task hostage. |
| Conflicting semantics | “【来源A】是【X】，而【来源B】是【Y】，影响【步骤】。” Request an authoritative explanation or pause that step. A user who does not know must not be pushed into guessing. |
| Environment problem during usage | “当前环境缺少/不兼容【组件】，影响【步骤】。” Offer independent repair installation / another existing compatible environment / pause. Do not run pip before that choice. |
| Existing output directory | “【目录】已存在，工具不会覆盖。” Reuse valid results when they satisfy the requested task, choose a new output for an explicitly requested rerun, or pause if neither is authorized. No new decision is needed just to choose a fresh directory within an already authorized rerun. |
| Runtime failure | “【步骤】因【observed cause】失败。” Correct an obvious scope-preserving problem and retry; for unresolved causes, state what remains unknown and propose a specific next check. Do not call an IK quality failure an environment error. |
| Partial quality failure | “本次处理完成；【范围】未通过【policy/check】。” Offer inspect failures, use the original-policy eligible subset if that deliverable was requested, or a separately agreed rerun. Do not relax thresholds automatically. |
| Extra work or budget | “进一步确定【问题】需要增加【具体操作/范围/预算】，超出本次【任务】。” Offer include it, record for later, or end at the original scope. |
| Unsupported feature | “当前版本不支持【能力】。” Offer only actual supported outcomes or a separately selected development task. Do not request unnecessary robot/material data to make a different workflow seem applicable. |

Usually present 2–3 relevant options, with an evidence-based recommendation if useful. State what changes in the deliverable, scope or cost. Allow free-text correction. No answer is not consent to a recommended option.

A skipped part remains skipped in the final report; do not report the original larger request complete. Retain prior decisions throughout the task. Routine commands are not repeated approval checkpoints.
