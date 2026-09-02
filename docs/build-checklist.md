# 施工清单（v0.4，2026-09-02）

> 唯一用途：照着做。产品理由、设计权衡、被否掉的方案一律见 [`product-plan-v2.md`](./product-plan-v2.md)；代码结构、接口、任务分解见 [`engineering-plan-v1.md`](./engineering-plan-v1.md)。本页不重复。
>
> 规则：**闸门未过不得进入下一段。** 每段结束写一条 `runs/` 记录。
>
> **v0.4 变更：** 主开发环境改为实验室远程 Linux；补齐 M-1 可达定义、`SolveOptions`、T2 的 81→9 确定性预算和 harness 资产断言落点。

---

## 开工前必须先完成的五件事

在写第一行求解代码之前完成，否则后面无法证明结论没有被事后调整过。

- [ ] **M-1 判据写进 `runs/` recipe** —— 抽样规模、红黄绿阈值、T2 排名规则（照抄规划 §12 M-1，不得临场改）
- [ ] **数据划分固定** —— `calibration=[0,1,3,5,6,8,10,11,13,15,16,18]`；`held_out=[2,4,7,9,12,14,17,19]`。写进 recipe；**M1c 前不得读取 held_out 的 parquet、视频或统计**
- [ ] **依赖版本钉死** —— `lerobot==0.6.1`（可选 extra）、`pin==4.1.0`、`pin-pink==4.3.0`、`qpsolvers==4.13.0`、`osqp==1.1.3` 进 constraints；安装写 `qpsolvers[osqp]`
- [ ] **私有数据边界落地** —— 本地配置只写别名 `private-sample-20` 与外部路径；`.gitignore` 覆盖数据、run 产物与本地配置；CI 只用 synthetic/public fixtures
- [ ] **远端唯一工作树** —— 当前规划提交后，用 Git bundle/私有 remote 在实验室数据盘 clone；Windows 本地副本转只读，不维护双份活跃代码

## 远端环境与素材

- [ ] **实验室 Linux + Python 3.12 env** —— 远端已核实 Ubuntu 20.04.6、64 CPU、双 4090、miniconda 可用；不用系统 Python 3.8
- [ ] **存储落盘** —— 项目、输入、run 使用经确认的数据盘目录；不落只余约 206 GB 的根 overlay。真实根路径只进本地配置
- [ ] **数据授权/挂载** —— 若远端尚无 `private-sample-20`，先确认该公司样本允许进入实验室主机，再单独复制；代码迁移不等于数据迁移授权
- [ ] **环境检查脚本** —— `harness/m_minus_1/doctor_env.py` 检查版本、可写空间、数据 alias、资产可读，不回显 SSH 地址和绝对数据路径
- [ ] **素材清点** —— 确认本地 OpenArm xacro、`origin` URDF、SRDF 与 collision mesh 可读；源机器人 URDF 仅为未来可选交叉校验，拿不到不阻塞

---

## M-1 可行性闸门 · OpenArm · 一次性 harness

**允许写得难看。裸调 Pinocchio + Pink，不建 `RobotProfile`，不进 CLI，用完即弃。**

### 先修资产的三个坑（不修则闸门失效）

本地资产快照已有 xacro、生成 URDF、`origin` URDF、`openarm.srdf` 和完整 collision STL。但：

- [ ] **修 collision 占位球** —— 生成的 URDF 里每个 link 的 collision 是 `<sphere radius="0.0003"/>`，真 mesh 那行被注释掉了。**不修的话「自碰撞 0 穿透」是恒真判据，比没有闸门更糟**
- [ ] **修绝对 mesh 路径** —— 输出只允许相对路径或可移植 package URI
- [ ] **恢复动态 finger** —— `finger_joint1` 为 `prismatic [0,0.044] m`，`finger_joint2` 恢复 mimic；不得沿用固定 finger 的旧生成物
- [ ] 在 `harness/m_minus_1/assert_openarm_assets.py` 写断言：Pinocchio 加载成功；无 <1 mm collision 球；mesh 全可解析且无绝对路径；finger 类型/限位/mimic 正确；开闭端点改变指间距；固化产物计入哈希

### 版本与资产

- [ ] 锁定 OpenArm v1.0 本地资产快照：记录上游 revision、源哈希与完整 diff；已知 4 处 xacro diff 都是路径替换，不等待口头确认
- [ ] 以 xacro 为运动学权威、`origin` URDF 为碰撞参照生成产物；目标夹爪导出采用物理 `finger_joint1` 位移，不采用未确认的控制器电机角
- [ ] 核对全部关节限位与 TCP；canonical 夹爪固定为 `aperture_fraction`（0=闭，1=开）
- [ ] 复用 `openarm.srdf` 屏蔽表，但**补检 body ↔ 两臂 link0** 是否也需屏蔽（SRDF 里没有）

### 预检

- [ ] **可达定义冻结** —— 双臂同一联合构型；位置 ≤5 mm、姿态 ≤2°、硬限位内、无穿透才计 nominal；姿态 `(2°,5°]` 只计黄灯 relaxed
- [ ] **SolveOptions 冻结** —— `dt=0.01 s`、外层 `max_iter=300`、OSQP 容差/上限、cost、damping、no-progress 与三种子预算全部写进 recipe
- [ ] **T2 候选冻结** —— calibration/robot 点云中位数生成 anchor；`dx/dy/dz=±0.10/0 m`、`yaw=±10/0°` 共 81 个；先 60 帧筛前 9
- [ ] **完整抽样预检** —— 前 9 候选跑 **600 单帧（12×50）+ 20 段×60 帧**，全部只从 calibration 取
- [ ] 按预先登记的排名规则选出 T2；全红则当前 recipe 判红，扩网格必须新建 recipe

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
- [ ] Pink 迭代器 + 状态契约：`CONVERGED/MAX_ITER/QP_FAILED/LIMIT_VIOLATION/NUMERICAL_FAILURE/RESIDUAL_TOO_HIGH`；不得由单次局部失败输出 `INFEASIBLE`
- [ ] QP 固定 OSQP，recipe 记录容差、最大迭代数、warm-start 与实际 solver
- [ ] §5.3.1 内部约定一致性测试
- [ ] **§5.3.2 独立 golden cases** —— M0 唯一的外部参照，含「打乱 joint-name」元测试
- [ ] CLI：`doctor` `inspect` `normalize` `solve` `diagnose` `export`
- [ ] 静态图确认数值（先别做界面）

**出口 →** 合成轨迹往返误差达标无分支跳变；10 项负例全检出；golden cases 全过且元测试确实报错

---

## M1a 真实数值闭环 · OpenArm · 不导出数据集

- [ ] parquet `Prober`
- [ ] `MappingSpec` schema（按流声明）+ 首个 `DataProfile`（钉 dataset revision + `lerobot==0.6.1`）
   - slice 映射已与 `info.json` 的 `names` 逐位核对过，**索引 0 = 左臂是 `EXPLICIT`**，不必再推断
   - 别漏 `action.position/.velocity/.effort` 和逐帧 `control_mode` 列
- [ ] `command_timing` 落档：**同行配对，`shift_policy: none`**（延迟 4–5 帧是物理跟踪延迟，**不是**移位依据）
- [ ] **可访问 20 ep 完整结构扫描**，生成 `private-sample-20@<manifest-hash>` 与 `validation_scope`；不访问、不等待公司全量
- [ ] 纯关节空间扫 `action.position[t]` vs `observation.state.position[t+k]`，复核延迟仍在 `k=4~5`；冲突则使 `DataProfile` 失效
- [ ] 双臂 + 双夹爪多运动组；夹爪按 `aperture=(state+3)/5` / action 原值 → `finger_joint1∈[0,0.044] m`，`finger_joint2` 由 mimic 得到
- [ ] 双流 IK + **`warm_start_from_state`**（`interleaved_sequence` 已被实测否掉，别用）
- [ ] 输入坐标显式命名 `dataset_native`；T2 用 M-1 结果并写进 recipe，不等待真实场地 frame 身份
- [ ] 诊断 + 批量报告，含跨流一致性**三层**判据（比值 → 速度可行性 → 联合判定）
- [ ] 在 `calibration` 上标 `provisional` 阈值

**出口 →** 12 个 calibration ep 跑通出报告；**两条流**的 FK 都回到各自源 EEF 目标且误差达标

> 这里已经形成第一个可审阅产物：一份覆盖私有样本 calibration 子集的批量诊断报告。

---

## M1b 数据集闭环

- [ ] 保持格式重写：新 parquet + 视频 `hardlink→copy` 降级 + `info.json` + **`meta/episodes/*`** + **`meta/tasks.parquet`**；manifest 记录 materialization method
   - 一律走 `meta/episodes/*` 偏移定位，**不得靠文件名推断 episode**
- [ ] 坏帧掩码（保留行、carry-forward、首帧失败要有规则）+ episode 白名单
- [ ] `stats.json` 重算，口径 = 训练白名单
- [ ] 产出可直接运行的训练配置：`DatasetConfig(repo_id=..., root=..., episodes=allowlist)`
   - **`exclude_episodes` 在 0.6.1 里不存在**，别照旧文档写
- [ ] 五步验收的实现

**出口 →** calibration 集导出物通过五步：按白名单加载 → **断言白名单生效** → 时间窗 → 归一化 batch → 两条流 FK 回验

---

## M1c 留出集验收与结构冻结

- [ ] 打开 `held_out` 8 ep，端到端跑一次
- [ ] 若已拿到源 URDF：§10.2 交叉校验（**同侧同行配对**；错配会看到 2.10 mm 系统残差，那是跟踪延迟不是 bug）

**出口 →** held_out **一次通过**，不回头调参 → 冻结 `CanonicalTrajectory v0.1` + `ExportProfile v0.1` 的**结构**；阈值升为 `sample_validated`

**范围限制：** `sample_validated` 只对 `private-sample-20@<manifest-hash>` 有效；不代表公司全分布，换数据必须重新校准

---

## M2 可视化

- [ ] 薄 React + R3F 单页：3D 回放 + 时间轴 + 误差曲线
- [ ] 问题区间定位跳转、参数调整局部重算

> M1c 是第一个完整交付点；M2 是其后的增量，不绑定未经估算的日期。

---

## 随时可以做、不阻塞任何人的

- [ ] AI 生成 `MappingSpec` 草稿（stretch，**不是任何一段的出口条件**）
- [ ] 若将来取得精确生产 recorder revision，将当前 `LOCAL_CODE_CORROBORATED` provenance 升级；**不是 M1c 阻塞项**
- [ ] CuRobo 现成机器人配置清单、对双臂的支持程度

---

## 七条最容易犯的错（都是评审里真实出现过的）

1. **把跟踪延迟当成标签移位** —— 4–5 帧是机器人追不上命令，不是数据错位。配对保持同行。
2. **用同帧 `action` 填 `observation.state` 的夹爪** —— 标签泄漏 + 4–5 帧系统偏差。state 必须从自己的数值换算。
3. **拿 `‖q_action − q_state‖` 大就判 IK 分支冲突** —— 两者本来就该有差距。必须走三层判据。
4. **在 `calibration` 上反复调参后拿同一批数据验收** —— `held_out` 只能开一次，**M-1 抽样也不许碰**。
5. **先做界面再验数值** —— 会对着假数据调交互。
6. **信一个恒真的检查** —— OpenArm URDF 的 collision 是 0.3 mm 占位球，碰撞检查会「全部通过」。**判据要先证明它抓得住东西**（这正是 golden cases 里那条打乱 joint-name 元测试存在的理由）。
7. **把私有数据路径或样本提交进开源仓库** —— 代码、测试、日志和文档只认 `private-sample-20` 别名；CI 只用 synthetic/public fixtures。
