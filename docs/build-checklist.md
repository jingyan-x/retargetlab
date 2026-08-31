# 施工清单（v0.1，2026-08-27）

> 唯一用途：照着做。产品理由、设计权衡、被否掉的方案一律见 [`product-plan-v2.md`](./product-plan-v2.md)，本页不重复。
>
> 规则：**闸门未过不得进入下一段。** 每段结束写一条 `runs/` 记录。

---

## 开工前必须先写下来的三件事

在写第一行求解代码之前完成，否则后面无法证明结论没有被事后调整过。

- [ ] **M-1 判据写进 `runs/` recipe** —— 抽样规模、红黄绿阈值、T2 排名规则（照抄规划 §12 M-1，不得临场改）
- [ ] **数据划分固定** —— `calibration` 12 ep / `held_out` 8 ep，写进 recipe。**`held_out` 在 M1c 之前不得打开**
- [ ] **`lerobot` commit 钉死** —— v3 未进稳定版，且官方文档与 main 在 `tasks.jsonl`/`tasks.parquet` 上已不一致（§3.2）

---

## M-1 可行性闸门 · OpenArm · 一次性 harness

**允许写得难看。裸调 Pinocchio + Pink，不建 `RobotProfile`，不进 CLI，用完即弃。**

- [ ] 锁定 OpenArm 版本（v1.0/v2.0、preset、双臂 root、两臂 base 相对变换）
- [ ] xacro → URDF，固化并记哈希；Pinocchio 加载成功
- [ ] 核对 mesh、关节限位、TCP，**以及夹爪限位/行程/开合方向**（M1 目标侧映射要用）
- [ ] 抽样预检：600 单帧（20ep × 30）+ 20 段连续片段（60 帧），每个 T2 候选各跑一遍
- [ ] 按预先登记的排名规则选出 T2
- [ ] 顺带：向学长要源机器人 URDF（不阻塞）

**闸门 →** 全绿进 M0｜黄灯记录条件后进 M0，M1 复检｜红灯：扩 T2 范围 → 放宽姿态 ≤5° → 暂停 OpenArm 并进入目标重选 spike

**Panda 双臂只是重选时的第一候选，不是现成退路。** 必须先建立双臂 root、base 相对变换、双夹爪/TCP 与臂间碰撞对，再重新执行 M-1 全套抽样和红黄绿判据；没有候选通过前不得进入 M1。

---

## M0 骨架与合成闭环 · Panda · 纯 CPU

**机器人是 Panda，不是 OpenArm。**

- [ ] Pinocchio：URDF 加载、FK、Jacobian
- [ ] **Panda** 的 `RobotProfile` + `GeometryModel` + 碰撞对屏蔽表（有工作量，别漏估）
- [ ] `CanonicalTrajectory v0.1`（provisional）
- [ ] 合成往返测试台 + 10 项负向样例（§10.1）
- [ ] Pink 后端 + 自碰撞 barrier
- [ ] §5.3.1 内部约定一致性测试
- [ ] **§5.3.2 独立 golden cases** —— M0 唯一的外部参照，含「打乱 joint-name」元测试
- [ ] CLI：`doctor` `inspect` `normalize` `solve` `diagnose` `export`
- [ ] 静态图确认数值（先别做界面）

**出口 →** 合成轨迹往返误差达标无分支跳变；10 项负例全检出；golden cases 全过且元测试确实报错

---

## M1a 真实数值闭环 · OpenArm · 不导出数据集

- [ ] parquet `Prober`
- [ ] `MappingSpec` schema（按流声明）+ 首个 `DataProfile`（钉 revision + lerobot commit）
- [ ] `command_timing` 落档：**同行配对，`shift_policy: none`**（延迟 4–5 帧是物理跟踪延迟，**不是**移位依据）
- [ ] **全量 1682 ep 结构扫描**（只读 schema/统计，确认那 20 条没漏字段布局或任务类型）
- [ ] 双臂 + 双夹爪多运动组；夹爪按 `aperture ≈ (state+3)/5` → OpenArm 夹爪行程
- [ ] 双流 IK + **`warm_start_from_state`**（`interleaved_sequence` 已被实测否掉，别用）
- [ ] T1 人工确认 + T2 用 M-1 结果
- [ ] 诊断 + 批量报告，含跨流一致性**三层**判据（比值 → 速度可行性 → 联合判定）
- [ ] 在 `calibration` 上标 `provisional` 阈值

**出口 →** 12 个 calibration ep 跑通出报告；**两条流**的 FK 都回到各自源 EEF 目标且误差达标

> 这里就可以给学长看东西了：一份真实数据的批量诊断报告。

---

## M1b 数据集闭环

- [ ] 保持格式重写：新 parquet + 视频硬链 + `info.json` + **`meta/episodes/*`** + **`meta/tasks.*`**
   - 一律走 `meta/episodes/*` 偏移定位，**不得靠文件名推断 episode**
- [ ] 坏帧掩码（保留行、carry-forward、首帧失败要有规则）+ episode 白名单
- [ ] `stats.json` 重算，口径 = 训练白名单
- [ ] 产出可直接运行的训练配置（`DatasetConfig(root, episodes=...)`）
- [ ] 五步验收的实现

**出口 →** calibration 集导出物通过五步：按白名单加载 → **断言白名单生效** → 时间窗 → 归一化 batch → 两条流 FK 回验

---

## M1c 留出集验收与结构冻结

- [ ] 打开 `held_out` 8 ep，端到端跑一次
- [ ] 若已拿到源 URDF：§10.2 交叉校验（**同侧同行配对**；错配会看到 2.10 mm 系统残差，那是跟踪延迟不是 bug）

**出口 →** held_out **一次通过**，不回头调参 → 冻结 `CanonicalTrajectory v0.1` + `ExportProfile v0.1` 的**结构**

**不在此冻结：** §6.3 阈值（20 ep 是上游预筛过的，偏乐观，待 M3 全量）

---

## M2 可视化

- [ ] 薄 React + R3F 单页：3D 回放 + 时间轴 + 误差曲线
- [ ] 问题区间定位跳转、参数调整局部重算

> M1c 是第一个完整交付点；M2 是其后的增量，不绑定未经估算的日期。

---

## 随时可以做、不阻塞任何人的

- [ ] AI 生成 `MappingSpec` 草稿（stretch，**不是任何一段的出口条件**）
- [ ] 向学长确认 `command_timing`（把 `DATA_DERIVED` 升为 `USER_CONFIRMED`）
- [ ] CuRobo 现成机器人配置清单、对双臂的支持程度

---

## 五条最容易犯的错（都是评审里真实出现过的）

1. **把跟踪延迟当成标签移位** —— 4–5 帧是机器人追不上命令，不是数据错位。配对保持同行。
2. **用同帧 `action` 填 `observation.state` 的夹爪** —— 标签泄漏 + 4–5 帧系统偏差。宁可删掉这一维。
3. **拿 `‖q_action − q_state‖` 大就判 IK 分支冲突** —— 两者本来就该有差距。必须走三层判据。
4. **在 `calibration` 上反复调参后拿同一批数据验收** —— `held_out` 只能开一次。
5. **先做界面再验数值** —— 会对着假数据调交互。
