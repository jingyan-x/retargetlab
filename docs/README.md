# 规划文档索引

本目录只保留一个现行规划基线，其余文件用于追溯讨论和技术调研。

| 文件 | 状态 | 用途 |
|---|---|---|
| [`product-plan-v2.md`](./product-plan-v2.md) | **现行、唯一基线（2026-08-27 生效）** | 产品范围、工作流、架构、导出契约、机器人、里程碑、决策记录 |
| [`build-checklist.md`](./build-checklist.md) | **施工用** | 一页可勾选的任务与闸门清单，从基线派生；只回答「现在做什么」 |
| [`current-product-plan.md`](./current-product-plan.md) | 历史归档（2026-08-27 卸任） | 前基线。含五机器人、完整前端、Agent 自动修复等已被移出首版的范围；**不得作为实现依据** |
| [`planning-discussion-archive.md`](./planning-discussion-archive.md) | 历史归档 | 各轮议题、候选方案、被覆盖的决定及 2026-08-14 闭合记录 |
| [`eef-trajectory-tool-architecture-review.md`](./eef-trajectory-tool-architecture-review.md) | 历史技术评审 | 早期技术调查与对比；不得作为当前实现需求 |
| [`weekly-meeting-plan-brief-2026-08-26.md`](./weekly-meeting-plan-brief-2026-08-26.md) | 历史会议记录 | **早于四轮修订，已被取代。** 作为 08-26 当时状态的记录保留，未回填修订；需要新的汇报版应另建日期文件 |

## 阅读规则

1. 开发、拆任务和验收只以 `product-plan-v2.md` 为产品范围依据；日常照 `build-checklist.md` 推进。
2. 需要理解决策原因时再查讨论归档或早期评审。
3. 历史文件与现行规划冲突时，以现行规划为准。
4. 新的架构决定先讨论确认，再写入现行规划，并在该文 §14.1 追加决策记录。

## 基线切换记录（2026-08-27）

`product-plan-v2.md` 经四轮外部评审修订后取代 `current-product-plan.md`，并于 2026-08-31 完成开工前一致性清理。四轮各修了什么，见该文 §14.1：

| 轮次 | 修的是 | 代表性结论 |
|---|---|---|
| 一 | 设计缺口 | 新增导出契约；审计/训练视图分离；认证粒度下沉到数据集 revision；碰撞球改为封装 CuRobo；**新增跨流 IK 分支耦合**（评审未提出，自查发现） |
| 二 | 上一轮引入的语义问题 | `command_timing` 缺失；夹爪 observation 泄漏；白名单验收未走训练路径；`joint_solve` 数学上不成立 |
| 三 | 用实测替换推测 | 全量 20 ep / 13,746 帧实测：`action[t] ≈ state[t+4~5]`；`state_gripper ≈ 5·action − 3`；**`interleaved_sequence` 被实测否掉** |
| 四 | 可施工性 | 消除 M-1/M0 循环依赖；M-1 补量化闸门；训练承诺降级为「候选训练数据集」；标定/验收集划开；M0「跨后端一致性」正名；M1 拆为 M1a/b/c |

2026-08-31 的一致性清理没有扩大范围：OpenArm 资产核实统一归入 M-1；阈值统一为 M3 全量后冻结；Panda 双臂仅保留为需重新过闸门的备用候选；交付顺序不再绑定“暑假”日期。

## 开工状态

**规划允许开始 M-1，但实施尚未自动开始。** 先按 `build-checklist.md` 写入 M-1 recipe、固定 `calibration`/`held_out` 划分并钉住 `lerobot` commit，再执行两项 M-1 工作（OpenArm 建模、双臂可达性预检）。

源机器人 URDF 与 `command_timing` 的源码确认**不阻塞**——两者都有 `DATA_DERIVED` 路径可走，回复到手时用于把证据等级升为 `USER_CONFIRMED`。

**待实施期按证据决定的项**见基线 §14.3，其中 §6.3 各项阈值**须待 M3 全量跑完才允许冻结**：现有 20 个 episode 是上游按规则从 1682 条筛出的，本身偏向质量好的样本。
