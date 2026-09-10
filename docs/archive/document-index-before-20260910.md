> 历史索引快照：已由 [当前入口](../README.md) 替代。

# 规划文档索引

本目录只保留一个现行规划基线，其余文件用于追溯讨论和技术调研。

| 文件 | 状态 | 用途 |
|---|---|---|
| [`product-plan-v2.md`](../product-plan-v2.md) | **现行、唯一产品基线（2026-09-02 第七轮）** | 产品范围、工作流、架构、导出契约、机器人、里程碑、决策记录 |
| [`engineering-plan-v1.md`](../engineering-plan-v1.md) | **现行、唯一工程基线（v1.2，2026-09-02）** | M-1 到 M1c 的远端环境、仓库骨架、数据契约、模块接口、CLI 契约、任务分解与验收 |
| [`build-checklist.md`](../build-checklist.md) | **施工用** | 一页可勾选的任务与闸门清单，从上面两份派生；只回答「现在做什么」 |
| [`current-product-plan.md`](../current-product-plan.md) | 历史归档（2026-08-27 卸任） | 前基线。含五机器人、完整前端、Agent 自动修复等已被移出首版的范围；**不得作为实现依据** |
| [`planning-discussion-archive.md`](../planning-discussion-archive.md) | 历史归档 | 各轮议题、候选方案、被覆盖的决定及 2026-08-14 闭合记录 |
| [`eef-trajectory-tool-architecture-review.md`](../eef-trajectory-tool-architecture-review.md) | 历史技术评审 | 早期技术调查与对比；不得作为当前实现需求 |
| [`weekly-meeting-plan-brief-2026-08-26.md`](../weekly-meeting-plan-brief-2026-08-26.md) | 历史会议记录 | **早于五轮修订，已被取代。** 作为 08-26 当时状态的记录保留，未回填修订；需要新的汇报版应另建日期文件 |

## 阅读规则

1. **产品范围**（做什么、为什么、边界在哪）只以 `product-plan-v2.md` 为准。
2. **代码结构与任务**（怎么写、写在哪、算不算过）以 `engineering-plan-v1.md` v1.2 为准；它不改变产品范围。若两份现行文档真有冲突，先修文档再编码。
3. 日常照 `build-checklist.md` 推进。
4. 需要理解决策原因时再查讨论归档或早期评审。历史文件与现行规划冲突时，以现行规划为准。
5. 新的架构决定先讨论确认，再写入现行规划，并在 `product-plan-v2.md` §14.1 追加决策记录。

## 当前执行顺序（2026-09-04）

用户已再次确认 **OpenArm-first**。因此本工作区当前按
`M-1 OpenArm 语义/约束闸门 → OpenArm 正式数值闭环 → M1a/b/c` 推进；
Panda 仅保留为历史目标重选证据和后续回归夹具，不是当前交付目标，也
不能复用其映射或可达结论。详细证据与停止点见
[`development-log.md`](../development-log.md) 和
[`m1-004-frame-semantics-blocker.md`](../m1-004-frame-semantics-blocker.md)。

## 基线切换记录

`product-plan-v2.md` 经多轮评审后取代 `current-product-plan.md`，2026-09-02 完成第七轮 remote-first 与首轮预检闭合。各轮修了什么，见该文 §14.1：

| 轮次 | 修的是 | 代表性结论 |
|---|---|---|
| 一 | 设计缺口 | 新增导出契约；审计/训练视图分离；认证粒度下沉到数据集 revision；碰撞球改为封装 CuRobo；**新增跨流 IK 分支耦合**（评审未提出，自查发现） |
| 二 | 上一轮引入的语义问题 | `command_timing` 缺失；夹爪 observation 泄漏；白名单验收未走训练路径；`joint_solve` 数学上不成立 |
| 三 | 用实测替换推测 | 全量 20 ep / 13,746 帧实测：`action[t] ≈ state[t+4~5]`；`state_gripper ≈ 5·action − 3`；**`interleaved_sequence` 被实测否掉** |
| 四 | 可施工性 | 消除 M-1/M0 循环依赖；M-1 补量化闸门；训练承诺降级为「候选训练数据集」；标定/验收集划开；M0「跨后端一致性」正名；M1 拆为 M1a/b/c |
| 五 | 上游与本地事实 | `lerobot` v3 已进稳定版（改钉 `0.6.1`）；`DatasetConfig` 无 `exclude_episodes`；**那 20 条是均匀抽样不是质量筛选**，全量为 1667 ep；M-1 抽样撞 `held_out`，改为 12 ep × 50 帧；OpenArm URDF 有 **collision 占位球**与绝对 mesh 路径两个坑；`action_lookahead=5` 死参数是 §2.3 结论的未排除替代假设 |
| 六 | 代码冻结前收口 | 公司全量退出范围；私有样本只用别名与本地配置；固定 12/8 精确索引；OpenArm 恢复真实 collision + 动态 finger；recorder 本地旁证；Pink/OSQP/夹爪/T2/视频契约补齐；阈值改为 `sample_validated` 范围化认证 |
| 七 | Remote-first 与首轮闭合 | 主开发现场改为已实测连通的实验室 Linux；Windows 只作 Remote-SSH 客户端；补齐 M-1 可达定义、SolveOptions、T2 81→9 预算与 harness 文件落点 |

第六、七轮都没有扩大产品范围，解决的是开工歧义、不可满足依赖和开发现场。M1c 仍是首个完整停止点；M2–M5 到阶段前另写工程规划。

## 开工状态

**规划已足够指导 M-1 → M1c，允许立即进入代码开发；实施尚未自动开始。**

第一天先把已提交 Git 历史迁到实验室数据盘并固定唯一远端工作树，再建 Python 3.12 env；随后冻结 splits/SolveOptions/T2 recipe、落私有数据边界、生成并测试 OpenArm 的可移植真实碰撞/动态夹爪 URDF。之后进 M-1 抽样预检。

**没有外部人员或公司全量数据阻塞项。** 但若远端尚无 20 ep 样本，必须先确认该公司样本允许复制到实验室主机；这是数据权限问题。源机器人 URDF 只影响条件交叉校验，精确 recorder revision 只影响 provenance 等级。

**数据边界：** `private-sample-20` 的真实路径、内部来源标识、parquet、视频和运行产物不得进入 Git；CI 只使用 synthetic/public fixtures。

**阈值边界：** M1a 为 `provisional`，M1c 留出集一次通过后为 `sample_validated`，仅对 `private-sample-20@<manifest-hash>` 有效，不外推公司全分布。
