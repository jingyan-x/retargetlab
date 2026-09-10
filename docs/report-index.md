# 报告与运行索引

整理日期：2026-09-10。当前状态见 [current-status.md](current-status.md)。包含整理记录及用户授权恢复后的新增实验。

本次覆盖远端仓库 projects/*/runs 的 **28 个 run、377 个文件**。完整相对路径、大小和 SHA-256 见 [文件级清单](evidence/run-report-inventory-20260910.json)。

## 当前采用的证据

| ID | 完整仓库相对路径 | SHA-256 |
|---|---|---|
| OA-POS-OLD | `projects/private-sample-openarm/runs/20260909-openarm-source-semantics-003/position-t2-prescreen.json` | `94c79b223e660ce326f679f154acb0c138542e0d410edd4c69601546a2a46a41` |
| OA-POS-BEST | `projects/private-sample-openarm/runs/20260909-openarm-source-semantics-008/refined-position-t2.json` | `759a473211dc2a139d9e405ad9514c63d1befdce3ba2616ceaedb0b2b14d30ff` |
| OA-POSE-BASE | `projects/private-sample-openarm/runs/20260909-openarm-source-semantics-005/per-side-tool-full-budget.json` | `28891b328d79255afe888e790b991490e5fdcd7b6fb3002278a2db152e7b61eb` |
| OA-POSE-REPRO | `projects/private-sample-openarm/runs/20260910-openarm-separated-frames-004/results/restored-t2-047.json` | `522d1a7055878edc736d9b0d3ced2de8b1b04ed4c12dec43e88f8de246279ef9` |
| OA-LEGACY-M1 | `projects/private-sample-openarm/runs/20260904-m1-openarm-006/prescreen-calibration-60.json` | `aafd9e212ad12b1165dd4cfcc6b22c886493a514c498625f6bbbfc93665939f3` |
| PA-HISTORICAL | `projects/target-reselection-panda/runs/20260904-m1-panda-002/full-top9.json` | `124cacb1bf2e34c4de27c3b5ce5ceed9176fb4917a8f3dda02fd4bbf94d1fe82` |

| OA-POSE-PASS | `projects/private-sample-openarm/runs/20260910-openarm-separated-frames-005/results/refined-t2-020.json` | `2181fd1f24c6bcbab6367fca1ed34ddba8a453f871cfd63f316a2838a8b53a42` |
| OA-BIMANUAL | `projects/private-sample-openarm/runs/20260910-openarm-separated-frames-006/results/refined-t2-020.json` | `29b08b9cec7bc978004c702e206e69980c9bf5ffc0c235d9188e639fab04cda2` |

85% 是 OA-POS-BEST 的 **position-only、未检查碰撞、同帧两侧分别求解成功**；完整位姿基线是 OA-POSE-BASE 的 78.33% / 88.33%，且已由 OA-POSE-REPRO 复现。两种口径不得互相替代。恢复后OA-POSE-PASS达到81.67%/83.33%；OA-BIMANUAL联合成功40/60（66.67%），碰撞0、越界0，仍未过双臂门槛。

## 全部运行目录

OpenArm 行的路径前缀为 projects/private-sample-openarm/runs/，Panda 行为 projects/target-reselection-panda/runs/。

| Run ID | 目标 / 用途 | 完成程度与当前解释 | 独立 recipe | 日志数 / 文件数 |
|---|---|---|---|---|
| `20260902-m1-001` | OpenArm / 初期 recipe / calibration 抽样材料 | 历史冻结材料；目录无完整预筛报告 | 有 | 0 / 3 |
| `20260902-m1-002` | OpenArm / calibration 600 帧抽样登记 | 抽样材料；不等于 IK 已通过 | 有 | 0 / 2 |
| `20260902-m1-003` | OpenArm / smoke / 单帧 prescreen | 仅诊断帧，不是注册 60 帧或 M-1 出口 | 有 | 0 / 4 |
| `20260902-m1-004` | OpenArm / 旧 identity + position-first 诊断 | 单帧报告存在；历史完整尺度运行曾中断 | 有 | 0 / 4 |
| `20260903-m1-005` | OpenArm / 注册 60 帧、timing、coverage、DataProfile | 注册预筛 RED；DataProfile 仍 REVIEW_REQUIRED | 有 | 29 / 70 |
| `20260904-m1-openarm-006` | OpenArm / 旧 identity 映射 81 候选注册预筛 | 完整合并；最佳 nominal 30%，不能覆盖后续新映射 | 有 | 0 / 31 |
| `20260904-m1b1-001` | OpenArm / ExportProfile 契约 | 仅 profile，不是私有数据集导出完成 | 无，见报告 basis/override | 0 / 1 |
| `20260904-openarm-recovery-001` | OpenArm / 旧 frame / side / rotation 诊断 | 历史假设比较，不作当前最佳 | 无，见报告 basis/override | 0 / 6 |
| `20260904-openarm-recovery-002` | OpenArm / 旧 Viser-left-inverse / link7 对照 | 历史完整双臂诊断 28/60；参考点/语义限制保留 | 无，见报告 basis/override | 0 / 5 |
| `20260904-openarm-recovery-003` | OpenArm / 旧假设单臂隔离 | 60 帧左 40/60、右 34/60；不是当前基线 | 无，见报告 basis/override | 0 / 4 |
| `20260904-openarm-recovery-004` | OpenArm / 早期 frame-lineage | 源语义未知的旧 blocker，已被后续证据覆盖 | 无，见报告 basis/override | 0 / 1 |
| `20260904-openarm-recovery-005` | OpenArm / 严格 world 轴旋转 96 候选 | 完整 legacy 候选族；没有独立 tool 右乘，不能作新模型的全局否定 | 无，见报告 basis/override | 0 / 4 |
| `20260909-openarm-source-semantics-001` | OpenArm / MQ03 语义加入后的共用 tool 初探 | 已完成；旧 t2-023 下 hand_tcp/link7 比较，非当前最佳 | 无，见报告 basis/override | 0 / 1 |
| `20260909-openarm-source-semantics-002` | OpenArm / 旧 t2-023，24 个 tool 右乘 | 已完成；hand_tcp 两侧分别最佳 46.67% / 70%，不同工具候选 | 无，见报告 basis/override | 0 / 1 |
| `20260909-openarm-source-semantics-003` | OpenArm / 旧网格 position-only | 已完成；93.33% / 90%，同帧独立两侧 83.33% | 无，见报告 basis/override | 0 / 1 |
| `20260909-openarm-source-semantics-004` | OpenArm / 旧 t2-047，24 个 tool 右乘 | 已完成；两侧不同工具候选 78.33% / 88.33% | 无，见报告 basis/override | 0 / 1 |
| `20260909-openarm-source-semantics-005` | OpenArm / per-side tool，300 次/4 初值复核 | 当前 full-pose 对照基线；78.33% / 88.33%，左侧未达标 | 无，见报告 basis/override | 0 / 1 |
| `20260909-openarm-source-semantics-006` | OpenArm / per-side tool，10 个 T2 shortlist | 已完成；无同一 T2 的两侧同时过 80% | 无，见报告 basis/override | 0 / 1 |
| `20260909-openarm-source-semantics-007` | OpenArm / 三个指定侧/点位的定向工具搜索 | 已完成；未恢复双侧 full-pose gate | 无，见报告 basis/override | 0 / 1 |
| `20260909-openarm-source-semantics-008` | OpenArm / 81 点局部细化 position-only | 当前位置基线；95% / 90%，同帧独立两侧 85% | 无，见报告 basis/override | 0 / 1 |
| `20260910-openarm-separated-frames-001` | OpenArm / 错误接续后居中七点 / 共用工具对照 | 7/7 完成；旁路诊断，不替代 9 月 9 日最佳 | 有 | 6 / 15 |
| `20260910-openarm-separated-frames-002` | OpenArm / 居中 full-budget + target-only FK 对照 | 已完成；私有 full-pose 15% / 15%；FK 对照 11/12、12/12 | 有 | 0 / 5 |
| `20260910-openarm-separated-frames-003` | OpenArm / 旧 t2-023 共用工具 full-budget | 已完成；63.33% / 38.33%；旁路诊断，不作当前最佳 | 有 | 0 / 3 |
| `20260910-openarm-separated-frames-004` | OpenArm / 恢复旧最佳与细化点 full-pose | 用户暂停，1/2 完成；旧最佳复现 78.33% / 88.33%，细化点无完整报告 | 有 | 0 / 4 |
| `20260910-openarm-separated-frames-005` | OpenArm / 续跑细化full-pose单臂 | 完成；49/60、50/60，首次双侧过80%；独立相交40/60 | 有 | 1 / 5 |
| `20260910-openarm-separated-frames-006` | OpenArm / 联合full-pose与碰撞后检 | 完成；40/60，碰撞0、越界0，20帧残差失败；双臂RED | 有 | 1 / 6 |
| `20260903-m1-panda-001` | Panda / 早期反向 side mapping | 已废弃方向，不能选作 Panda 或 OpenArm 基线 | 有 | 27 / 59 |
| `20260904-m1-panda-002` | Panda / 修正 side mapping 的独立目标重选 | 历史 YELLOW；600 帧 nominal 99.17%，不代表 OpenArm | 有 | 65 / 137 |

## 9 月 9 日遗漏归档的接续关系

source-semantics-001 共用工具初探 → 002 在旧点位枚举 tool 右乘 → 003 找到位置覆盖较好的旧网格 t2-047 → 004 在该点分别筛左右工具 → 005 用 300 次/4 初值复核 → 006 比较十个位置候选 → 007 做定向工具检查 → 008 将 position-only 局部细化至 95% / 90% / 85%。

002–008 的报告在远端存在，但此前未进入 development-log / MappingSpec 的后续结论。008之后当时计划的工具搜索未形成完整报告；本轮固定既有per-side工具的细化点复核已在run005完成，不能将两种实验混称。

这些诊断没有各自独立冻结的 recipe.yaml；报告中的 recipe_basis 指向旧 recipe，实际目标、工具矩阵、网格或预算由报告及原执行记录补充。它们是已完成的诊断证据，不伪装成注册 M-1。恢复执行时应使用新的完整 recipe；本轮004只完成一个候选后中断；005以新recipe完成剩余细化候选，006完成后续双臂诊断。

## 中断、旁路与状态含义

- separated-frames-004：stop-receipt.json 是本次整理时补写的审计回执，明确源于实际 SIGINT / KeyboardInterrupt；它不是伪造的原始 solver 日志。restored-t2-047完成，refined-t2-020当时中断；后续新run005续跑成功，不改写004回执。
- separated-frames-001–003：从过时基线启动的旁路对照，保留用于追溯，不取代已经存在的更好结果。
- 旧 source-semantics-006 的 joint_nominal_rate 字段取两臂 nominal rate 的较小值，并非同帧双臂成功率。
- PASS 表示报告生成成功，RED/YELLOW 表示相应 recipe 的闸门，REVIEW_REQUIRED 表示语义/Profile 待审核；不可混成一个“项目已通过”。
- 个别早期目录只有 recipe、抽样或单帧报告，目录存在不意味着完整运行结束。没有原始日志的运行不补造日志；缺失项保留为证据缺口。
- source-semantics-008 的独立两侧相交率是 51/60；没有真实碰撞或连续片段验收，不能据此开放后续导出。

## 不在 runs 清单内的相关材料

| 类别 | 位置 / 记录 | 当前用途 |
|---|---|---|
| 源语义 | docs/openarm-mapping-spec.json、历史源 FK 执行记录 | 源端解释；不存在独立源 FK 数值报告，保留此缺口 |
| 结构/映射 review | projects/private-sample-openarm/reviews/private-sample-20/ | 结构比较与 review-only mapping candidate，不是认证出口 |
| 目标资产 | projects/private-sample-openarm/robots/openarm_bimanual/ | manifest、URDF、SRDF、Profile；与轨迹通过率分开 |
| 私有 DataProfile | 20260903-m1-005/data-profile-review-required-with-coverage.json | 落盘版本仍为 REVIEW_REQUIRED，未自动升级 |
| 历史工程记录 | development-log.md | 已合并为里程碑主线；代码切片不等于阶段验收 |
| 本轮诊断实现 | harness/m_minus_1/diagnose_openarm_separated_frames.py；tests/unit/test_openarm_separated_frames.py | 已提交d51cc8c/a96085a；含输入指纹与双臂前置gate，代码哈希在清单中 |

## 证据缺口与下一次接续规则

1. 源 FK 独立报告缺失、部分诊断独立 recipe / 原始日志缺失，均已明确记录，不重新读原始数据来填补。
2. 早期全 20 ep 数值分析与后设 12/8 split 的关系需审计。各 run 的 held_out=false 只覆盖该次运行，不证明历史完全未见过。
3. 接续从current-status、OA-POSE-PASS / OA-BIMANUAL开始，历史对照为OA-POSE-REPRO / OA-POS-BEST；候选必须附 run ID 与参数，不能仅说 t2-020。
4. 改映射、目标帧、位置网格或 solver budget 时新建 recipe；完成、失败、中断都记录，不能只保存高分。
