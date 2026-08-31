# EEF 轨迹本体化工具：产品规划 v2

> **文档状态：现行唯一基线（2026-08-27 生效）。** 本文经四轮评审修订后取代 [`current-product-plan.md`](./current-product-plan.md)；后者转为历史归档。开发、拆任务与验收以本文为准。
>
> **与 v1 规划的关系：** 产品定位不变，九条核心属性一条不删。变化集中在三处——输出对象从「轨迹」改为「数据集」、主形态从「单条工作台」改为「批量流水线」、AI 的第一战场从「自动修复」改为「自动接入」。此外把治理级机制（认证等级、自治挡位、审批门禁、完整版本对象图）整体移出首版，理由见 §13。
>
> **2026-08-27 修订轮次（外部评审后）。** 本轮补上一个被跳过的环节：原文把「运动学求解结果」直接当成了「可训练的数据集」，中间缺少导出语义的定义。修订集中在五处，均已核实上游事实（记录见 §14.1）——
> 1. 新增 **§7.1 导出契约**，定义 `observation.state` / `action` 的目标语义、两条求解流之间的**IK 分支耦合**、夹爪量纲转换、时间对齐。这是本轮最重要的新增。
> 2. **§3.3 `MappingSpec` 重构为按流声明**，消除同一语义写在两处的隐患，并补上原文漏掉的 `observation.state` 映射。
> 3. **§4.3 碰撞球生成改为封装 CuRobo 现成能力**；原文「现有开源工具里确实没人做」经核实不成立，自研球拟合整块删除。
> 4. **§3.2 认证粒度**从「LeRobot v3.0 版本级」下沉到「数据集 revision + 读取端版本」级。
> 5. **§12 M1 收缩**：通用基座搜索、hdf5/zarr/csv Prober 后移；源 FK 交叉校验改为条件出口项。
>
> **2026-08-27 第二轮修订（同日，第二次外部评审后）。** 上一轮自身引入了三个语义问题，本轮修掉，逐条对照见 §14.1「第二轮评审修订」——
> 1. **新增必填 `command_timing`（§7.1.3）**：`independent_command` 不含时间信息，`action[t]` 与 `state[t]` 是否同帧此前是未经证实的假设，错了会让训练标签整体差一帧。当前证据等级 `MISSING`，须问人。
> 2. **删除「`state` 侧夹爪由 `action` 派生」这条退路（§7.1.4）**：那是把预测目标泄漏进观测，属训练数据完整性错误。改为「正确映射 / 删除该维 / 标 synthetic」三选一。
> 3. **出口验收改为走训练入口的加载路径，并断言白名单生效（§7.1.5）**：否则白名单只是被记录，不保证被使用。
> 4. 另修五处工程准确性：跨流一致性改为相对判据（§6.1）、`delta_from_state` 是两次 IK（§7.1.1）、`joint_solve` 移出 M1 并新增 `interleaved_sequence`（§7.1.2）、碰撞几何拆为两条派生分支（§4.3）、可达性预检改为抽真实帧跑双臂 IK（§11）。
> 5. **新增 §12 `M-1 可行性闸门`**，先于 M0：上一轮把 OpenArm 建模与可达性预检写成「不占开发工作量」，那是错的。
>
> **2026-08-27 第三轮修订（全量数据实测后）。** 前两轮悬置的两个「必须问人」项，已由对全部 20 episode / 13,746 帧的实测直接解出，逐条见 §14.1「第三轮修订」——
> 1. **`command_timing` 实测解出（§2.3、§7.1.3）**：`action[t] ≈ state[t+4~5]`，即手臂约 133–167 ms 的物理跟踪延迟（夹爪 5–6 帧）。**训练配对仍是同行 `observation[t] → action[t]`，`shift_policy: none`**——跟踪延迟不是标签移位的依据。
> 2. **源夹爪语义实测解出（§7.1.4）**：`state ≈ 5·action − 3`（R²≈0.95+），证实 state 是关节角、action 是归一化指令，「删除该维」从主路径退为备选。
> 3. **`interleaved_sequence` 被实测否掉（§7.1.2）**：上一轮把它列为推荐耦合方式，但它隐含假设 `action[t]` 落在 `state[t]` 与 `state[t+1]` 之间；实测是 `t+4~5`，代入后是一条折返锯齿。M1 采用 `warm_start_from_state`。
> 4. **跨流一致性判据再修（§6.1）**：可行性窗口取实测的 4–5 帧而非零；「关节距离大」降级为**异常候选**，须与「两条流 FK 是否各自命中」联合判定。
> 5. **证据等级新增 `DATA_DERIVED`（§3.4）**，并明确 `MISSING` 项的处理顺序是「查元数据 → 能测就测 → 问人升级」，而不是一律阻塞等回复。
>
> **方法论教训：先测数据再定契约。** `interleaved_sequence` 读起来优雅、经两轮评审无人质疑，被一次全量实测直接否掉。
>
> **2026-08-27 第四轮修订（施工化评审）。** 前三轮修的是「设计对不对」，这一轮修的是「能不能照着施工」，六项全接受，逐条见 §14.1「第四轮修订」——
> 1. **消除 M-1 / M0 循环依赖（§12）**：M-1 改为一次性可抛弃 harness（OpenArm，裸 API）；M0 是 Panda 正式管线与 **Panda** 碰撞资产；M1 才把 OpenArm 做进正式资产链。原文写「M-1 建 OpenArm `GeometryModel` 供 M0 用」而 M0 用 Panda，是明确的对象错配。
> 2. **M-1 补上量化闸门判据（§12）**：预先登记抽样规模、五项红黄绿标准、T2 排名规则和红灯后的目标重选流程。判据必须在跑第一次预检之前定下。
> 3. **训练承诺降级（§1.1、§1.3、§15）**：全文统一为「训练接口兼容、运动学验证通过的**候选**训练数据集」，明确不保证训练效果、任务成功与真机可执行性。
> 4. **标定集与验收集划开（§6.3）**：`calibration` 12 ep / `held_out` 8 ep / 全量 1682 ep 结构扫描。原文规则与计划自相矛盾。
> 5. **M0 的「跨后端 FK 一致性」名不副实（§5.3）**：Pink 建在 Pinocchio 上，M0 没有第二个独立 FK 实现。拆为内部约定一致性 + 独立 golden cases（M0）+ 真跨后端（M3）。
> 6. **M1 拆为 M1a/M1b/M1c（§12）**：数值闭环 → 数据集闭环 → 留出集验收与结构冻结，每段各有可展示、可回退的产物。
>
> **2026-08-31 开工前一致性清理。** 本次不改变产品范围，只清除第四轮修订遗留的四处执行歧义：OpenArm 资产核实统一归入 M-1；阈值统一为 M3 全量后才冻结；Panda 双臂降为需重新过闸门的备用候选；里程碑改用交付优先级和停止点，不再绑定“暑假”这一失效日期。

---

## 1. 产品定位

### 1.1 一句话

一个开源工具，把**无本体 EEF 轨迹数据集**批量重定向到**指定机器人**，按显式导出契约（§7.1）产出**训练接口兼容、运动学验证通过的候选训练数据集**。转换用 IK/FK 完成，可信度用运动学回放和逐帧诊断证明，AI 用来把「接入一个新机器人 / 一份新数据格式」的成本从几天压到几分钟。

**这句措辞是 2026-08-27 第四轮加严的结果，不是谦辞。** 前几轮写的是「可直接用于训练的数据集」，那句话承诺过头了。本工具能证明的是：数据能被训练框架加载、shape/dtype/stats/白名单正确、两条关节流的 FK 都能回到各自的源 EEF 目标、运动学与静态碰撞检查合格。

**它不验证也不承诺：** 目标机器人控制器的实际跟踪能力、动力学与接触可行性、任务成功率，以及「源机器人视频 + 目标机器人动作」这种跨本体组合训练出来到底有效。§1.5 已声明结论止于 `A1 运动学`、首版不运行训练——那么产品定位的第一句话就不该越过这条线。**明确可信边界不削弱项目，它是这个项目唯一真正在卖的东西。**

### 1.2 「无本体」的准确含义

数据记录了末端在空间里怎么动，但**丢失了绑定信息**：这是哪台机器人、末端点定义在法兰还是夹爪中心、坐标系相对机器人基座在哪、单位是米还是毫米、四元数是 `xyzw` 还是 `wxyz`、时间戳代表真实速度还是采样顺序、夹爪那一列的语义和方向。

所以本工具的本质工作是：**把丢失的绑定信息补回来，并把「怎么补的、依据是什么」记录成可审计的证据。** IK 只是绑定信息补全之后的一次机械计算，那部分由现成求解器完成，不是本项目的价值所在。

这个视角有两个推论，贯穿全文：

- 整段轨迹不可达，通常不是求解器不行，而是绑定信息错了（坐标系、单位、基座位置、TCP 定义）。
- 语义错误**不会报错**，只会安静地产出一条平滑但错误的轨迹。因此语义确认和可追溯不是流程负担，是正确性的前提。

### 1.3 输入与输出

| | 内容 |
|---|---|
| 输入 | 一批无本体 EEF 轨迹数据集（通常由源机器人关节数据经 FK 派生），可含图像、语言指令等同步通道 |
| 输出 | 同一批数据在**目标机器人**上的版本，按 §7.1 导出契约组织的**候选训练数据集**（训练接口兼容、运动学验证通过；不保证训练效果与真机可执行性）；附逐帧有效性掩码、可训练 episode 白名单、逐条质量报告与完整谱系 |
| 机制 | IK 求解 + FK 复算 |
| 证据 | 逐帧误差、约束检查、三维回放、批量质量报告 |

### 1.4 九条核心属性

以下九条构成产品定位。任何一条被去掉，就不再是这个产品。

1. 输入是 EEF 轨迹，输出是目标机器人的连续关节轨迹
2. 数据语义必须显式确认和记录，不得静默假设
3. 整段连续求解，不是逐帧独立 IK
4. FK 复算并给出逐帧误差与诊断
5. 失败必须能定位到具体片段和具体原因
6. 能在机器人模型上回放看见
7. 人能介入审核和修正
8. 全程可追溯、可复现
9. 本地 / 自托管优先——确定性核心（`normalize` / `solve` / `diagnose` / `export`）全程离线可跑，AI 辅助为可选增强；不承诺物理可行与真机安全

### 1.5 明确不做

- 不做新的 IK / 规划 / 碰撞算法库
- 不做物理仿真、训练平台、benchmark 平台
- 不向真实机器人下发轨迹
- 不生成或渲染视频（见 §7.3）
- 不做视频 / 人体姿态到 EEF 的提取（属于上游）
- 不做源机器人关节到 EEF 的 FK（属于导入前的预处理）
- 结论止于 `A1 运动学`，静态几何碰撞不等于物理可行

### 1.6 成功标准

项目目标包含**开源影响力**，这对技术决策有具体约束，且优先级高于功能数量：

- **装得上 > 功能多。** 首次运行不应要求 CUDA。
- **五分钟跑通样例 > 完备的认证体系。**
- **别人能贡献机器人配置 > 自己适配更多机器人。**
- **一张能看懂的效果图 > 一页架构说明。**

---

## 2. 参考数据基线

首个正式适配目标是学长提供的真实数据（`0529_accessory_newSop_1682ep_dual_eef_fk_tcp`，抽样 20 episode 版本）。以下为实测事实，设计以此为锚。

### 2.1 实测结构

| 项 | 实测值 |
|---|---|
| 格式 | LeRobot `codebase_version: v3.0` |
| `robot_type` | `"generic"`（源机器人已匿名化） |
| 规模 | 抽样 20 ep / 13746 帧 / 30 fps / 1 task；全量 1682 ep |
| 相机 | `head`、`left`、`right` 三路，1080×1920，mjpeg |
| 数据布局 | `data/chunk-000/file-000.parquet` 合并存储；视频按 `videos/{key}/chunk-000/file-{ep}.mp4` |
| EEF 通道 | `observation.state` / `action`，shape 16，布局 `[gripper, qw, qx, qy, qz, x, y, z] × 2` |
| 源关节通道 | `observation.state.position` / `.velocity` / `.effort` 及 `action.*`，16 维，关节名 `Larm1..7_Joint`、`Lgripper_Joint`、`Rarm1..7_Joint`、`Rgripper_Joint` |
| 四元数顺序 | `wxyz`（元数据显式声明） |
| 控制语义 | `dual_eef_absolute`（绝对位姿，非增量） |
| TCP | 已由法兰沿工具 z 偏移 `0.22855 m`；`quat` 未变，参考点即 TCP |
| 源本体线索 | `fk_waist` 记录腰部三关节被固定在 `Waist1=0.23`、`Waist2=19.48°`、`Waist3=0`；末端 link 为 `Larm08_link` / `Rarm08_link` |

### 2.2 从数据得到的设计约束

**双臂是第一等公民，不是边缘情况。** 首份真实数据就是 `dual_eef`。多运动组（左臂 + 右臂 + 两个夹爪）必须在早期就被数据模型支持，不能等到第四个里程碑。

**源机器人是带腰的双臂本体。** `fk_waist` 说明源 EEF 位姿是在腰部固定于某个姿态下算出来的。这意味着源坐标系原点是**腰部固定后的某个基座**，不是简单的「机器人 base」。重定向时的基座变换必须显式建模，不能假设两台机器人的 base 语义相同。

**位置单位是米。** 实测 `x ∈ [0.16, 0.61]`、`z ∈ [0.57, 0.90]`。这个量级也可用于单位推断规则的校准（见 §3.4）。

**左右臂可由 y 符号区分。** 左臂 `y ∈ [-0.31, 0.45]`，右臂 `y ∈ [-0.57, -0.02]`。可作为运动组归属的推断证据之一，但不得作为唯一依据。

**同名通道在 `state` 和 `action` 里语义不同。** 这是最重要的发现：

| 通道 | `observation.state` | `action` |
|---|---|---|
| `gripper_0` / `gripper_1` | `[-3.00, 3.00]` — 量级与符号符合关节角（弧度）读数 | `[0.00, 1.00]` — 归一化指令 |

一个按通道名统一映射的适配器**会在这里出错**。因此 `MappingSpec` 必须允许 `state` 与 `action` 分别声明语义，且夹爪语义（范围、方向、开合含义）必须是显式字段而非推断默认值。

**四元数符号连续性需要检查。** 右臂 `qw ∈ [-0.03, 0.56]` 跨越零点，存在 `q` 与 `-q` 交替导致插值跳变的风险。规范化阶段必须做符号连续化。

**上游已有批量筛选流程。** `episode_report_filter` 记录了「从 1682 条里按规则保留 20 条、生成报告 CSV、视频复制并重编号」。这直接印证主形态是**批量处理 + 质量报告 + 筛选**，不是逐条人工审核。

### 2.3 `state` 与 `action` 的实测时间关系（2026-08-27 全量实测）

前两轮修订把这一项列为「未知，必须问人」。**现已对全部 20 episode / 13,746 帧做了实测，不再是推测。**

方法：逐 episode 扫偏移 `k`，比较 `action[t]` 与 `observation.state[t+k]`，同时算三组独立指标——左右臂 EEF 位置误差、四元数测地角、14 个手臂关节的 RMSE。

| 偏移 `k` | 双臂平均位置误差 | 平均姿态误差 | 手臂关节 RMSE |
|---:|---:|---:|---:|
| 0 帧 | 10.33 mm | 1.58° | 0.0258 rad |
| 1 帧 | 8.15 mm | 1.24° | 0.0202 rad |
| 3 帧 | 3.79 mm | 0.58° | 0.0090 rad |
| **4 帧** | **2.10 mm** | **0.35°** | **0.0047 rad** |
| 5 帧 | 2.27 mm | 0.40° | 0.0053 rad |

20 个 episode 中 13 个最佳偏移为 4 帧、7 个为 5 帧；左右臂分别分析、只保留运动帧分析，结论不变。

**结论：**

```
observation.state[t] = 当前测得状态
action[t]            = 当前控制周期发出的绝对 EEF 目标
state[t+4~5]        ≈ action[t]        → 手臂跟踪延迟 ≈ 133–167 ms @30fps
夹爪延迟 5–6 帧                        → ≈ 167–200 ms
```

**两点让这个结论比一般统计推断可靠得多：**

1. **延迟在 EEF 空间和关节空间同时出现，且最佳偏移一致。** 如果这只是坐标系、TCP 或四元数约定的错误，两个空间不会给出同一个 `k`。所以它是**真实的执行器跟踪延迟，不是表示层的 artifact**。
2. 曲线在 `k=4` 有单一极小值且两侧单调，不是噪声下的偶然最优。

**夹爪语义一并被解出：** 对齐后 `state_gripper ≈ 5 × action_gripper − 3`，左 R²≈0.968、右 R²≈0.942。这证实 `state` 侧是**实际关节角**、`action` 侧是 `[0,1]` 归一化指令，并给出可用的仿射关系——推论出开合度分数 `aperture ≈ (state_gripper + 3) / 5`。目标侧的精确映射仍需 OpenArm 自己的夹爪限位与方向（§7.1.4）。

**必须防住一个误读，这是本节最重要的一句话：**

> **4–5 帧是机器人「从命令到实到」的物理跟踪延迟，不是「训练标签需要平移 4–5 帧」的证据。**

训练要学的是「在当前观测下，示教者当前发出了什么命令」，即 `observation[t] → action[t]`，**同行配对，不做任何移位**。把 `action` 平移过去会让策略去预测已经被执行完的状态，而不是要发出的指令。也**不能**据此改写成 `action[t] = state[t+1]`——那是 `absolute_next_state` 语义，与本数据不符。落档见 §7.1.3。

---

## 3. 输入接入设计

### 3.1 核心问题

HDF5、Zarr、Parquet 都是**容器**，不是 schema。同样的后缀，内部布局可以完全不同。因此不存在「一个 HDF5 适配器」，只存在一套接入机制。

### 3.2 三层结构

```
容器          Prober            MappingSpec         CanonicalTrajectory
(hdf5/zarr/  ──探测结构──▶  ──声明字段映射──▶   ──规范化──▶  统一内部表示
 parquet/csv)                      ▲
                                   │
                            DataAdapter = StorageAdapter（容器布局）
                                       + DataProfile（固化并认证的 MappingSpec）
```

**第一层 `Prober`——只读探测。** 遍历容器结构，产出一份「结构清单」：每个数组的路径、shape、dtype、attrs，以及抽样统计（min/max/mean、是否单调、是否近二值、NaN 数量）。这一层**格式相关但 schema 无关**，最终需要四个：`h5py`、`zarr`、`pyarrow`、`csv`。加一种容器就是加一个 Prober，不动上层。**M1 只实现 `pyarrow` 一个**，其余按选定的第二个数据集的实际容器再补（§12）——现在没有对应测试数据，写了也验证不了。

**第二层 `MappingSpec`——声明式映射。** 一份版本化的 YAML，把容器里的路径映射到规范字段，并显式记录语义。这是整个接入机制的核心契约，也是 AI 生成、人工确认、复用和分享的对象。

**第三层 `DataAdapter`——认证适配器。** 对已知数据集把 `MappingSpec` 固化并测试，用户直接可用。

这一层必须把**存储布局**与**通道语义**分开，二者的认证粒度不同：

| | 管什么 | 认证粒度 | 例子 |
|---|---|---|---|
| `StorageAdapter` | 目录结构、分片路径模板、元数据文件的读写 | **格式版本级** | `lerobot-v3` |
| `DataProfile`（即固化的 `MappingSpec`） | `observation.state` / `action` 每一维是什么、单位、坐标系、夹爪方向 | **数据集 revision 级** | `0529_accessory_newSop_1682ep@<hash>` |

**理由（已核实）：** LeRobot v3 规范定义的只有目录布局、`meta/info.json`（features 的 shape/dtype、fps、路径模板）、`meta/stats.json`、`meta/tasks.*`、`meta/episodes/`。**它不规定 `observation.state` 和 `action` 各维的语义，也不规定两者的时间关系。** 因此两份都合法的 v3 数据集，其 `action` 可以一个是绝对位姿、一个是关节增量。「支持 LeRobot v3.0」只是一句关于**容器**的话，和「支持 HDF5」在逻辑上是同一类陈述，只是范围更窄。

**因此认证声明必须写成两句：**「`StorageAdapter` 支持 LeRobot v3.0 布局」+「`DataProfile` 认证于数据集 X 的 revision Y」。

还要钉住第三个东西：**下游读取端的版本**。核实时发现 LeRobot 官方 v3 文档写的任务文件是 `meta/tasks.jsonl`，而 main 分支代码里是 `meta/tasks.parquet`（`DEFAULT_TASKS_PATH`）——同一个「v3」在文档和实现之间已经有分歧，且 v3 尚未进入稳定版（官方说明 v3 将随 `lerobot >= 0.4.0` 发布，在此之前需用 main 分支）。所以 `DataAdapter` 的认证记录必须包含**测试时所用的 `lerobot` commit**，否则 §12 M1 的出口条件「导出的数据集能被 LeRobot 正常加载」是一个会随上游漂移的标准。

### 3.3 MappingSpec 结构

以真实数据为例（这份即首个 `DataProfile` 的内容）：

```yaml
mapping_spec:
  version: 1
  name: lerobot-v3-dual-eef-absolute
  container: parquet
  storage_adapter: lerobot-v3          # 只声明容器布局
  dataset_id: 0529_accessory_newSop_1682ep_dual_eef_fk_tcp
  dataset_revision: "<sha256>"         # 语义认证钉在这一层，见 §3.2

  # ---- episode 与帧的组织方式 ----
  layout:
    mode: index_column          # index_column | group_per_episode | file_per_episode
    episode_column: episode_index
    frame_column: frame_index
    time_column: timestamp
    time_unit: s

  # ---- 通道映射：按「流」声明 ----
  # 每个流是一条独立的时间序列，本工具对每个流各求一次 IK。
  # 同一通道在不同流里的语义可以不同，各自就近声明；不设第二处覆盖机制。
  streams:
    observation_state:
      role: robot_state                # robot_state | command
      column: observation.state
      channels:
        left.position:     { slice: "5:8",   unit: m, axes: xyz }
        left.orientation:  { slice: "1:5",   representation: quaternion, order: wxyz }
        left.gripper:      { index: 0,  semantics: joint_angle, unit: rad, range: [-3.00, 3.00] }
        right.position:    { slice: "13:16", unit: m, axes: xyz }
        right.orientation: { slice: "9:13",  representation: quaternion, order: wxyz }
        right.gripper:     { index: 8,  semantics: joint_angle, unit: rad, range: [-3.00, 3.00] }
    action:
      role: command
      column: action
      channels:
        left.position:     { slice: "5:8",   unit: m, axes: xyz }
        left.orientation:  { slice: "1:5",   representation: quaternion, order: wxyz }
        left.gripper:      { index: 0,  semantics: normalized_open, range: [0.0, 1.0] }   # 0=闭合, 1=张开
        right.position:    { slice: "13:16", unit: m, axes: xyz }
        right.orientation: { slice: "9:13",  representation: quaternion, order: wxyz }
        right.gripper:     { index: 8,  semantics: normalized_open, range: [0.0, 1.0] }

  # ---- 运动组与末端语义 ----
  # channels 引用的是流内通道名；此处两条流声明了同一套通道名，故运动组对两者共用。
  # 若某条流只覆盖部分运动组，需在该运动组下用 streams: [...] 显式限定。
  motion_groups:
    - name: left_arm
      channels: [left.position, left.orientation]
      gripper: left.gripper
      tool_point: tcp                    # 数据已是 TCP
      tcp_provenance:
        derived_from: flange
        t_flange_to_tcp: [0.0, 0.0, 0.22855]
    - name: right_arm
      channels: [right.position, right.orientation]
      gripper: right.gripper
      tool_point: tcp
      tcp_provenance:
        derived_from: flange
        t_flange_to_tcp: [0.0, 0.0, 0.22855]

  # ---- 坐标语义 ----
  coordinate:
    source_frame: source_robot_base_waist_fixed
    handedness: right
    trajectory_mode: absolute          # absolute | delta
    source_frame_note: >
      源 EEF 由源机器人 FK 得到，腰部固定于
      Waist1=0.23, Waist2=19.48deg, Waist3=0。
      该原点客观存在但未记录，属 MISSING（§3.4 的 T1），须问人或从 reference 反推，
      不得用搜索代替。目标机器人相对该原点的摆位是另一件事（T2）。

  # ---- state 与 action 的关系：必填，不得按通道名默认对齐 ----
  state_action_relation:
    type: independent_command        # absolute_next_state | independent_command | delta_from_state
    note: >
      本数据的 action 是控制指令，与 observation.state 不是同一物理量，
      不能假设 action[t] == state[t+1]。
    # 两条流都要求解时，两次 IK 必须耦合，否则会落到不同 IK 分支。见 §7.1。
    solve_coupling: warm_start_from_state

  # ---- 不参与求解、导出时原样带过的通道 ----
  passthrough:
    - { column: "observation.images.head",  kind: video }
    - { column: "observation.images.left",  kind: video }
    - { column: "observation.images.right", kind: video }
    - { column: task_index,   kind: label }
    - { column: timestamp,    kind: time }
    - { column: next.done,    kind: flag }

  # ---- 源本体参考通道（不参与求解，用于对照与诊断）----
  reference:
    source_joint_position:
      column: observation.state.position
      joint_names: [Larm1_Joint, ..., Rgripper_Joint]
```

五个设计要点：

- **通道按流声明，`slice`/`index` 在流内定位。** 因此能处理打包成单个向量的布局（本数据就是 16 维打包），也能处理一列一通道的布局。**`streams` 是顶层结构，这使得「漏掉 `observation.state`」在结构上不可能发生**——早期草稿只映射了 `action`，同时却声明两者互相独立，是自相矛盾的。
- **语义是显式字段，不是推断结果。** `unit`、`order`、`semantics`、`trajectory_mode` 必须写出来。写不出来的，进 §3.4 的证据流程。
- **同一语义只有一个声明位置。** §2.2 实测发现同名的 `gripper` 通道在 `state` 里是关节角弧度、在 `action` 里是归一化指令——**一个按通道名统一映射的适配器会在这里静默出错**。解法是让每个流各自声明自己的通道语义，而不是先统一声明、再用一张「例外表」覆盖。两处声明同一件事必然漂移，宁可重复六行 YAML。
- **`state_action_relation` 是必填字段。** `absolute_next_state` 表示 `action[t] == state[t+1]`（此时 `action` 对本工具是冗余的，只吃 `state` 即可）；`independent_command` 表示两者是不同物理量，**两条流都要求解，且必须按 `solve_coupling` 耦合**；`delta_from_state` 表示增量。
- **`reference` 段保留源关节数据**。它不参与求解，但极有价值：在**源机器人 URDF 可得时**，可以用它做「源 FK 与数据里的 EEF 是否一致」的自检，等于免费得到一份端到端校验（§10.2）。本数据源机器人已匿名化，该校验是否可用取决于能否取得源模型，见 §14.2。

### 3.4 语义证据与 AI 的位置

每项语义记录证据等级：

| 等级 | 含义 | 能否自动进入正式流程 |
|---|---|---|
| `EXPLICIT` | 数据或元数据显式声明（如本数据的 `quaternion_order: wxyz`） | 可以 |
| `ADAPTER_CERTIFIED` | 由已测试的 `DataAdapter` 提供 | 可以 |
| `DERIVED` | 由显式信息确定性推导 | 可以 |
| **`DATA_DERIVED`** | **由全量或大样本实测统计得出，有量化判据与稳健性检查，并登记了待确认来源** | **可以，但必须记 `pending_confirmation`** |
| `INFERRED_CANDIDATE` | 统计推断，带置信度 | **不可以**，仅用于草稿与预览 |
| `USER_CONFIRMED` | 人工确认 | 可以 |

**`DATA_DERIVED` 是 2026-08-27 新增的一级，用来容纳 §2.3 那类结论。** 它和 `INFERRED_CANDIDATE` 的区别不是「置信度更高」这种程度差别，而是三条可检查的硬标准：

1. **跑的是全量或统计意义上足够的样本**，不是抽样启发式（§2.3 是 20/20 episode、13,746 帧全量）
2. **有量化判据和明确的极值**，不是「看起来像」（单一极小值、两侧单调）
3. **有独立维度的交叉印证**（§2.3 的延迟在 EEF 空间与关节空间给出同一个 `k`，排除了表示层 artifact）

达不到这三条的，仍然是 `INFERRED_CANDIDATE`，不得进入正式流程。

**优先走自描述通道，而不是推断通道。** 少数数据集自带机器可读的语义声明块——例如公开数据集 `simple-world-lab/HiFi-UMI-2K` 在其 `meta/info.json` 中扩展出的 `state_layout` / `action_layout`，直接写出了旋转表示布局、夹爪单位、`shift_policy`、无效帧填充策略。**必须说清楚：这是该数据集自己加的扩展字段，不是 LeRobot v3 规范的一部分**（v3 规范只规定 `features` 的 shape/dtype，不规定各维语义，见 §3.2），因此不能假设任何 v3 数据集都有。凡有这类声明，`DataAdapter` 应直接读取并标 `EXPLICIT`，**不进 AI 推断路径**。对称地，本工具导出的 `retarget` 元数据段（§7.2）也按同一粒度写出，使下游同样免于推断。这项约定成本极低，是本工具对生态的直接贡献之一——**恰恰因为上游规范不管这件事，谁都自己写一套，才值得做。**

**AI 的第一职责就是把 `Prober` 的结构清单变成一份 `MappingSpec` 草稿**，逐项标注证据等级与置信度，把 `INFERRED_CANDIDATE` 项抛给人确认。这是「无本体数据丢进来自动适配」的落点。

可用的确定性推断规则（AI 调用，非 AI 猜测）：

| 待定语义 | 判据 |
|---|---|
| 位置单位 | 数值范围：`0.1–2.0` → m；`100–2000` → mm |
| 四元数顺序 | 两种解释下分别算模长偏差与相邻帧角速度连续性，取更优者 |
| 四元数符号 | 相邻帧点积为负则翻转，做符号连续化 |
| 哪一列是夹爪 | 近二值 / 有界 / 变化次数远少于位姿通道 |
| 左右臂归属 | 通道名 + `y` 符号 + 与源关节名的对应 |
| 时间语义 | 单调且间隔均匀 → 真实时间；整数递增 → 帧序号，需重定时 |
| 绝对 / 增量 | 数值围绕零点小幅波动 → 增量；落在工作空间范围内 → 绝对 |

**不得推断的项：** 参考坐标系身份、TCP 定义、夹爪开合方向的物理含义。任何模型对这三项都只能猜。

但「推断不出来」有两种原因完全不同、处理方式相反的情形，必须分开标记：

| 语义状态 | 含义 | 典型数据 | 正确处理 |
|---|---|---|---|
| `MISSING` | 真值客观存在，只是数据里没记录 | 源机器人 FK 派生的数据。如 §2 的参考数据，源坐标系是腰部固定后的某个基座，它确实存在，只是被匿名化了 | 查元数据、问人、或从 `reference` 源关节通道反推 |
| `UNDEFINED` | **物理上不存在真值** | 人手直接采集、根本没有源机器人的数据。世界原点每段任意初始化，通常只保证 Z 轴沿重力 | **搜索或设计**：base_transform 是一个待定的自由度，不是待恢复的信息 |

这个区分直接决定 AI 的行为：对 `UNDEFINED` 项去问用户「你的源坐标系是什么」是无意义的，正确动作是搜索或设计，并把选择结果与依据写进谱系。反过来，对 `MISSING` 项直接跑搜索，则是在掩盖一个本可查明的事实，属于静默错误。

**`MISSING` 项还有第三条出路，前两轮修订漏了：实测。** §2.3 的 `command_timing` 原本被判为 `MISSING`、结论是「必须问人、不得推断」。但它是**可测的**——真值虽然没被记录，却在数据里留下了可量化的痕迹。正确处理是：跑全量实测 → 标 `DATA_DERIVED` → 登记 `pending_confirmation` → 不阻塞后续工作。

这条出路和「静默猜测」的界线很清楚：**测量并公开量化结果、同时保留待确认标记**，与**直接假设一个默认值**是两件事。前者可以进正式流程，后者不行。因此 `MISSING` 项的处理顺序应是：**查元数据 → 能测就测（`DATA_DERIVED`）→ 问人确认（升级为 `USER_CONFIRMED`）**，而不是一上来就阻塞等人回复。

**但「基座变换」其实是两件事，原文把它们混成了一件，导致 M1 背上了不必要的工作量。**

| | 是什么 | 本参考数据属于 | M1 怎么做 |
|---|---|---|---|
| **T1 源坐标系身份** | 数据里的位姿是相对哪个原点记的 | `MISSING`——腰部固定后的基座客观存在，只是被匿名化了 | **问人 / 从 `reference` 源关节反推**，不搜索 |
| **T2 目标机器人摆位** | 目标机器人的 base 相对该原点放在哪 | 永远是设计自由度，与源数据无关 | **人工给定 + 粗网格按可达率择优** |

推论很直接：**通用的「基座变换有限自由度搜索」服务的是 `UNDEFINED` 类数据，而这类数据的样本（`HiFi-UMI-2K`）已明确推到 M3 之后（§14.1）。因此 M1 不需要它**，只需要 T1 的人工确认加 T2 的粗扫。这是 §12 M1 得以收缩的依据之一。

诚实的产品承诺是：**自动做完；遇到从数据里确定不了的语义时停下来问一句，而不是猜。** 设计目标是让「问一句」的频率尽可能低，靠的是认证适配器的覆盖面，不是更激进的推断。

---

## 4. 本体与资产模型

### 4.1 URDF 为唯一主资产

各后端吃的东西不同：

| 组件 | 消费格式 | 额外成本 |
|---|---|---|
| Pinocchio | URDF | 无，原生 |
| CuRobo | URDF + 自有 YAML | **碰撞球配置**，每机器人一份 |
| MuJoCo / Mink | MJCF | 需转换；Menagerie 多有现成 |
| SAPIEN（v2） | URDF | 无格式转换，物理参数需调 |

因此：**`RobotProfile` 以 URDF + mesh 为唯一主资产，CuRobo YAML、MJCF、SAPIEN 配置全部作为派生产物管理。** 每份派生配置记录来源 URDF 的版本与哈希；URDF 变更时所有派生配置标记为过期，必须重新生成或重新校验。这个机制与 §5.3 的一致性测试互相咬合，用来堵「改了 URDF 忘了改后端配置」这类静默错误。

### 4.2 RobotProfile 与运动组

```
RobotProfile
├─ assets            URDF / mesh / 哈希
├─ motion_groups[]   KinematicGroup：关节链、root、末端 link、关节顺序、受控自由度
│                    （本项目首个数据即双臂，故多运动组是基础能力）
├─ end_effectors[]   法兰 / TCP / 夹爪中心 / 工具偏移，四者分开
├─ limits            位置 / 速度 / 加速度 / jerk
├─ locked_joints     未支持的自由度必须显式锁定或拒绝，不得隐式近似
├─ backend_configs   派生产物：curobo.yml / mjcf / …（含来源哈希）
└─ capabilities      每项能力标记 SUPPORTED / CONDITIONAL / NOT_SUPPORTED
```

`capabilities` 是诚实声明机制，也是上层查询接口——上层管线查询能力而不是 `try/except`。模型能加载不等于能力已验证。

### 4.3 碰撞球配置：封装既有能力，不自研拟合算法

「广泛适配」的一个现实拦路虎是 CuRobo 的碰撞球配置：大部分人不知道怎么写，写完也不知道对不对。

**但球拟合本身已经有成熟实现，不要重写。** 核实 CuRobo 官方 `docs/reference/sphere_fitting.rst` 的结果：

| 本项目原本打算做的 | CuRobo 现状 |
|---|---|
| 从 mesh 采样、聚类、拟合球 | `curobo.geom.sphere_fit.fit_spheres_to_mesh()`，三种算法（`SURFACE` / `VOXEL` / `MORPHIT`），默认 `MORPHIT` = VOXEL 初始化 + Adam 优化，损失函数即「最小化覆盖缺口与突出」 |
| 自动决定球数量 | `n_spheres=None` 时按包围盒体积与 `sphere_density` 自动估计 |
| 检查覆盖 / 过度膨胀 | `compute_metrics=True` 给出 8 项：`coverage`、`protrusion`、`protrusion_dist_mean/p95`、`surface_gap_mean/p95`、`max_uncovered_gap`、`volume_ratio` |
| URDF → 配置的命令行 | `python -m curobo.examples.getting_started.build_robot_model --urdf robot.urdf --asset-path meshes/ --output robot.yml --compute-metrics` |
| —— | 还额外有 `--clip-link base_link z 0.0` 处理底座球陷进安装面，以及一个 Viser 交互对比 demo |

**因此 v2 早期版本里「现有开源工具里确实没人做」这句话是错的，据此论证的自研 `generate` 整块删除。**

保留下来的价值在别处——上游给的是一个**算法**，本项目要的是一条**可追溯、可复现、可审核的资产链**：

```
robot-config build   <urdf>     调用 CuRobo build_robot_model，记录来源 URDF 哈希、
                                CuRobo 版本、拟合参数与随机种子
robot-config verify  <config>   1) 复核 CuRobo 报告的 coverage / protrusion 是否过阈
                                2) 球模型 FK 与 Pinocchio FK 的一致性（§5.3）
                                3) URDF 哈希是否与配置记录的一致，不一致则标记过期
robot-config review  <config>   输出待人工确认清单：link 分组、命名对应、需 clip 的底座 link
```

即 §4.1 的派生产物管理机制在碰撞几何这一项上的落地。link 分组与命名判断、哪些 link 需要 `--clip-link`，由 AI 辅助起草、人工确认——**这部分才是上游没有的**。

**但碰撞几何有两条派生分支，不是一条（2026-08-27 修正）。** 早期版本写成「Pink 的自碰撞规避也吃这条资产链的产出」，这是错的：Pink 的 `SelfCollisionBarrier` 用的是 Pinocchio 的 `GeometryModel` 与碰撞对（底层 hpp-fcl），**不读 CuRobo 的 robot YAML 和球模型**。两者共享的只有上游的 URDF/mesh 和审核原则。

```
URDF / mesh（唯一主资产，§4.1）
├─ Pinocchio GeometryModel + 碰撞对 / SRDF 屏蔽表     → Pink（M0–M2）、诊断用距离计算
└─ CuRobo robot YAML + collision spheres              → CuRobo（M3）
```

两条分支各自记录来源 URDF 哈希，各自过 `verify`。**两者必须交叉核对**：同一构型下 Pinocchio 报的最小距离与 CuRobo 球模型报的最小距离若符号相反（一个说碰了一个说没碰），说明至少有一份几何配置是错的——这正是 §5.3 那类「不报错、只是安静给出错误结果」的 bug，值得一个专门的一致性测试。

---

## 5. 求解后端

### 5.1 四条线分级

| 后端 | 角色 | 承诺等级 |
|---|---|---|
| **Pinocchio** | 基础设施：FK、Jacobian、碰撞距离（hpp-fcl）、合成数据、跨后端参照 | 总是可用 |
| **Pink** | CPU 求解（微分 IK）；自带自碰撞规避 barrier | 官方支持，单条轨迹可用 |
| **CuRobo** | GPU 求解 | 官方支持，批量生产可用 |
| **Mink + MuJoCo** | CPU 求解备选，兼作 MuJoCo 生态入口 | 实验性，不写入发布承诺 |

Pinocchio 只做正算，结果唯一确定，不需要认证。它承担三件无论如何都要做的事：从随机 `q` 正算出天然可达的合成轨迹（§10.1）、跨后端 FK 一致性的参照实现、诊断所需的 Jacobian 量。

**Pink 的两项性质对本项目有直接影响，原文没写：**

**其一，Pink 是微分 IK，天然连续。** 它求的是把机器人推向目标的关节速度，从当前构型积分前进。这意味着「整段连续求解」（§1.4 第 3 条）不需要额外机制，也意味着 §7.1 要求的**跨流分支耦合可以直接由「用 state 的解 warm-start action 的解」实现**。代价是它是**局部方法**——官方明确说明可能收敛到受限位卡住的局部最优，因此 §6.1 的可解性诊断必须区分「真不可达」与「局部卡住」，重试策略（换初值重解）要留位置。

**其二，Pink 已有自碰撞规避能力。** `pink.barriers.SelfCollisionBarrier` 基于 Pinocchio 的 hpp-fcl，参数为碰撞对数量与最小间距 `d_min`，官方 `examples/barriers` 里有双臂示例（Yumi 球模型自碰撞、Iiwa 全身碰撞）。**这回答了「CuRobo 在 M3，那 M0–M2 的碰撞承诺由谁兑现」：由 Pink + Pinocchio/hpp-fcl 兑现自碰撞。** 三个前提必须写清楚：

1. URDF 必须带 collision 几何，且需要建碰撞对并屏蔽相邻 link（通常靠 SRDF 或自动生成的屏蔽表）——这是一块**没有被计入 M0 的实际工作量**。
2. 官方注明「非光滑碰撞几何下行为未定义」，所以 mesh 需要凸分解或用凸包。
3. barrier 是**约束**不是**检测器**：它会主动改变解，这与 §6「首版只检测不修复」的立场有张力。首版取法：**求解时挂 barrier（避免产生自碰撞解），诊断时另用 Pinocchio 的距离计算独立复核**，两者不共用同一段代码，否则等于自己给自己打分。

**与环境几何的碰撞，首版不承诺。** §6.1 该项标注为 `CONDITIONAL`：仅当用户提供静态几何时启用，且 M0–M2 只做球/凸体级别的粗检。

### 5.2 接入顺序：先 CPU 后 GPU

**Pinocchio → Pink → CuRobo →（可选）Mink，一个通了再接下一个。**

这个顺序有两个实际好处。其一，接 CuRobo 时已有 Pink 的结果作为对照，关节顺序、四元数约定、TCP 定义接错了立刻能发现；反过来先接 CuRobo，一旦结果不对，「自己的变换写错了 / 后端配置错了 / 数据本身有问题」三个可疑源同时存在，很难定位。其二，**整条管线可以在笔记本上开发，不需要一直占用实验室 GPU 机器**，早期迭代速度差别显著。

关于 Mink 那条：RoboCasa 建在 robosuite 上，robosuite 跑 MuJoCo。因此做 Mink 这条线等于**为 MuJoCo 生态的 v2 提前付款**，成本是每个机器人一份 MJCF（Menagerie 大概率现成）。**后续接入仿真已确认是明确期望**，因此这个期权的价值高于纯粹的「多一个 CPU 后端」——但 v2 究竟走 MuJoCo 生态还是 SAPIEN 生态现在不定，Mink 仍排在 M5，不提前。

### 5.3 接口规则与一致性测试

**`KinematicsBackend` 照最弱的后端设计，不照 CuRobo 设计。** 核心接口只保留公共最小集：加载、FK、Jacobian、单点求解、序列求解、碰撞距离（可选）。CuRobo 独有的批量目标、世界更新、MPC 通过 `capabilities` 声明，上层查询后使用。

**这里要分清两种一致性测试，前两轮把它们混成了一件（2026-08-27 第四轮修正）。**

#### 5.3.1 内部约定一致性测试（M0 就能做）

```
对每个机器人:
  随机采 100 组合法的 q
  过我们自己的封装算 FK
  断言：关节顺序、TCP 偏移、四元数约定、单位换算前后自洽
```

**必须诚实说明它测的是什么：M0 阶段只有 Pinocchio 一个 FK 实现。** Pink 是建在 Pinocchio 之上的 IK 层，它的 FK 就是 Pinocchio 的 FK——拿两者互相比对等于把一个东西和它自己比，**不构成跨实现验证**。前两轮把 M0 的这一项写成「跨后端 FK 一致性测试」，那个命名是错的。

它仍然有价值，但价值在**我们自己的代码**上：关节顺序有没有在封装层错位、TCP 偏移有没有被重复施加或漏掉、四元数分量顺序有没有在转换时搞反、`RobotProfile` 声明的关节顺序与 URDF 实际顺序是否一致。这些都是本项目的 bug，不是后端的 bug，而且同样是「不报错、只安静给出错误结果」那一类。

#### 5.3.2 独立 golden cases（M0 必须补，用来提供真正的外部参照）

因为 5.3.1 没有第二个独立实现，M0 必须补一小组**来自本项目之外**的真值：

| golden case | 来源 | 抓什么 |
|---|---|---|
| 已知 `q` → 已知末端位姿 | 官方文档 / 厂商 DH 参数 / 手工推算（Panda 有公开数据） | 整条 FK 链的绝对正确性 |
| 零位姿态 | URDF 中性构型下的末端位姿 | 基座与末端 link 选择是否正确 |
| 单关节转动 | 只动一个关节，其余为零 | 逐关节的轴向与旋转方向 |
| 固定 TCP 偏移 | 法兰位姿 + 已知偏移 vs 直接算 TCP | 偏移施加的位置与次数 |
| 左右臂镜像 | 双臂机器人上对称构型 | 左右臂 `RobotProfile` 是否串了 |
| **负例：打乱 joint-name 顺序** | 故意错配 | 5.3.1 那类错误是否真的能被抓到 |

最后一条是元测试——**验证测试自身有检出能力**，否则一组永远通过的测试和没有测试等价。

#### 5.3.3 真正的跨后端一致性（M3，CuRobo 接入后）

只有第二个独立 FK 实现（CuRobo，或 M5 的 MuJoCo/Mink）到位后，「跨后端断言末端位姿两两差值 < 1e-4」才是一句有意义的话。那时它抓的是新一类 bug：URDF 与 MJCF 其实不是同一个模型、CuRobo 球模型与 URDF 不同步、两个后端的关节顺序约定不同。**这一项排在 M3，不在 M0。**

---

## 6. 诊断：首版只检测，不修复

首版做**检测与定位**，不做自动修复。修复留到后续里程碑。

### 6.1 逐帧与分段检测项

| 类别 | 检测内容 | 承诺 |
|---|---|---|
| 可达性 | IK 是否有解、求解状态、连续不可解区间；**区分「真不可达」与「局部最优卡住」**（§5.1） | 总是 |
| 精度 | FK 复算后的位置误差、姿态误差 | 总是 |
| 约束 | 关节越界、限位余量、速度 / 加速度 / jerk 是否超限 | 总是 |
| 连续性（时间方向） | 相邻帧关节距离（IK 分支跳变）、轨迹断点 | 总是 |
| **一致性（跨流）** | **`q_state[t]` 与 `q_action[t]` 的关节距离，相对源端 EEF 位移所预期的距离**——超出即两次求解落到了不同分支（§7.1.2）。**不是固定关节距离阈值**，见下 | 两条流都求解时 |
| 奇异 | Jacobian 条件数 / manipulability | 总是 |
| 自碰撞 | Pinocchio + hpp-fcl 距离计算，独立于求解时挂的 barrier | 总是（需 URDF 带 collision 几何） |
| 环境碰撞 | 与给定静态几何的碰撞 | `CONDITIONAL`：仅当用户提供几何；M0–M2 只做粗检 |
| 输入质量 | NaN、时间戳重复 / 倒序 / 间隔异常、四元数未归一化、符号跳变 | 总是 |
| 语义一致性 | 与 `reference` 源关节通道的 FK 交叉校验 | `CONDITIONAL`：**仅当源机器人 URDF 可得**（§10.2）；多数数据集不满足 |
| 疑似语义错误 | 整段不可达且平移后可达（坐标系嫌疑）、量级差 1000 倍（单位嫌疑）、镜像可达（手系嫌疑） | 总是 |

最后一项优先级高：它把「求解失败」翻译成「你的绑定信息可能错了」，这才是用户真正需要的信息。

**「跨流一致性」是本轮新增，且属于最危险的一类问题。** 它不像其他项那样会让回放变难看——两条流各自都平滑、各自 FK 误差都合格、三维回放完全正常，只有把两者放在一起看才发现 `action` 描述的构型和同一时刻的 `observation.state` 处在不同的 IK 分支（例如一个肘上一个肘下）。训练时策略学到的就是在两个分支之间反复跳。这正是 §1.2 所说「不报错、只安静地产出错误结果」的典型，因此必须做成一个显式的、有阈值的检测项，而不是指望求解阶段自然避免。

**但阈值不能是一个固定的关节距离，而且这一项本身不能单独下结论（2026-08-27 两轮修正）。** `state` 与 `action` 是实际状态与控制目标，源端本来就要求不同的 EEF 位姿；§2.3 实测更进一步表明**机器人需要 4–5 帧才追上命令**，因此 `q_action[t]` 与 `q_state[t]` 之间存在**合法且量级确定**的差距。拿固定阈值去判，会把正常的控制跟踪误差大批误判成 IK 分支冲突。

判据分三层，缺一层都会误报：

**第一层，相对量而非绝对量。**

```
Δx     = 源端 state[t] 与 action[t] 之间的 EEF 位姿差（位置 + 姿态）
Δq_exp = ‖J⁺(q_state[t]) · Δx‖        # 一阶预期的关节距离
Δq_act = ‖q_action[t] − q_state[t]‖
比值 r = Δq_act / max(Δq_exp, ε)
```

**第二层，可行性检查用实测延迟窗换算，不是零间隔。** `Δq_act` 必须能在 `observed_tracking_delay_frames`（本数据手臂 4–5 帧 ≈ 133–167 ms，§7.1.3）内由关节速度、加速度与控制幅度约束完成。第二轮修订曾写「`same_step` 时间隔为零，则任何显著的 `Δq_act` 都可疑」——**那是错的**：同行配对不等于同一物理时刻，可行性窗口应取实测跟踪延迟。

**第三层，比值大只是异常候选，不是判决。** `r` 超门限只能生成一个候选，必须与另外两项证据联合才能判为分支冲突：

| 证据组合 | 结论 |
|---|---|
| `r` 大 **且** 两条流各自 FK 都命中自己的 EEF 目标（误差在 §6.3 内） | **判为分支冲突**——两个解都"对"，却互相矛盾，正是 §7.1.2 描述的情形 |
| `r` 大 **且** 某条流 FK 未命中 | 判为该流的求解失败，按可达性/精度处理，不是分支问题 |
| `r` 大 **且** 该帧已被奇异项告警 | **降级为不判定**——近奇异时 `J⁺` 不可靠，`Δq_exp` 会爆掉 |
| `r` 大 **且** 超出速度可行窗 | 标为异常候选，进人工复核队列 |

所以这一项的正确定位是**异常候选生成器 + 联合判定**，不是一个独立的 `FAIL` 判据。门限数值进 §14.3，按 M1 首轮实测分布标定。

### 6.2 报告形式

主输出是**批量质量报告**，不是单条轨迹的详细视图：

- 每条 episode 一行：通过 / 警告 / 失败、可达率、最大误差、失败区间、主要失败原因
- 汇总：分布统计、失败原因排行、建议优先排查项
- 机器可读（JSON / CSV）+ 人可读（Markdown / HTML）

这与上游 `episode_report_filter` 的形态一致，可直接用于筛选。

### 6.3 阈值策略

阈值由本项目自行制定。原则有三条：

**一、阈值必须注明来源，不能是拍脑袋的数字。** 三类来源不同，处理方式也不同：

| 来源 | 例子 | 如何确定 |
|---|---|---|
| 求解器收敛能力 | IK 残差 | 由后端实测精度决定，跨后端取较严者 |
| 机器人硬限制 | 关节限位、速度、加速度 | 从 `RobotProfile` 换算，**不跨机器人统一** |
| 任务忠实度 | 允许的 EEF 偏差 | 由使用方设定；无输入时用保守默认 |

**二、宁可误报，不可漏报。** 本工具的产出直接进入训练。一条被错误放行的坏数据会静默污染训练集，代价远高于一条被误判的好数据（人工复核即可救回）。因此所有阈值向保守一侧取，`FAIL` 判据从严。

**三、标定集与验收集必须事先划开（2026-08-27 第四轮加严）。** 下表是**临时值**，用于让 M0/M1 能跑起来；之后用真实误差分布重新标定。

前两轮只写了一句「不得反复用同一批数据调参又用它验收」，但接下来的计划正是「用 M1 首轮的 20 episode 标定阈值，再用同样的 20 episode 完成 M1 验收」——**规则和计划自相矛盾**。现按如下划分，且划分必须在跑第一次批处理**之前**固定并写进 `runs/` 的 recipe：

| 集合 | 规模 | 只允许用于 |
|---|---|---|
| `calibration` | 20 ep 中的 12 | 标定 §6.3 阈值、调求解器参数、调 T2、看误差分布 |
| `held_out` | 20 ep 中的 8 | **仅 M1c 出口验收跑一次**。看过分布就作废，不得回头调参 |
| `structural_scan` | 全部 1682 ep 的**元数据与 schema** | 确认那 20 条没有漏掉新的字段布局、任务类型、维度变化。只读 schema 与统计，不求解，成本极低 |

**全量结构扫描不是可选项，理由前几轮都漏了：那 20 个 episode 是上游 `episode_report_filter` 按规则从 1682 条里筛出来的（§2.2），本身就偏向「质量好的样本」。** 在它们身上标定出来的阈值对全量必然偏乐观。所以：

- 阈值可以在 M1 标定，但只能标记为 `provisional`，**M3 全量跑完才允许冻结**
- `CanonicalTrajectory` 与 `ExportProfile` 的**结构**可以在 M1c 冻结为 `v0.1`（结构不依赖阈值）
- **机器人相关与数据集相关的阈值不在 M1 冻结**

前两轮写的「M1 首次全量批处理后标定并冻结」这句话本身也不准确——M1 处理的是 20 个 episode，不是全量。

#### 逐帧判定（临时值）

| 指标 | `PASS` | `WARN` | `FAIL` |
|---|---|---|---|
| EEF 位置误差 | ≤ 1 mm | ≤ 5 mm | > 5 mm |
| EEF 姿态误差 | ≤ 0.5° | ≤ 2° | > 2° |
| 关节限位余量 | ≥ 10% 行程 | ≥ 0 | 越界 |
| 相邻帧关节变化 | ≤ `v_max/fps` | ≤ 3× | > 3×（判为 IK 分支跳变） |
| 最小碰撞距离 | ≥ 安全裕量 | ≥ 0 | 穿透 |

关节连续性阈值**从 `RobotProfile` 的速度限位换算**（本数据 30 fps），不写死固定弧度值——这是「机器人硬限制」类阈值的正确处理方式。

#### Episode 判定（临时值）

| 判定 | 条件 |
|---|---|
| `PASS` | 全帧可解，且无 `FAIL` 帧 |
| `WARN` | 可解率 ≥ 99%，不可解帧**孤立**（连续 ≤ 3 帧，可插值），无硬约束越界 |
| `FAIL` | 可解率 < 99%，或存在连续不可解区间 > 3 帧，或任一帧硬约束越界 |

区分「孤立失败帧」与「连续不可解区间」很重要：前者多为数值抖动可修复，后者通常意味着绑定信息错误或结构性不可达，是完全不同的问题。

首版只输出判定与证据，**不自动修复**（见 §6 开头）。

---

## 7. 输出设计

### 7.1 导出契约（`ExportProfile`）

**这一节是 2026-08-27 修订新增，补的是原规划最大的一个断口：**运动学求解的产物是 `q(t)`，而训练需要的是「哪一列叫什么、代表哪一时刻的什么物理量」。原文直接跳到「把 `observation.state` 和 `action` 换成目标机器人的关节值」，中间这层定义是空的。缺了它，导出的数据集能被 LeRobot 加载、回放也好看，但训练读到的语义是错的——而且不报错。

因此每次导出必须绑定一份 `ExportProfile`，与 `MappingSpec`（管输入语义）对称，管输出语义。它和 `recipe.yaml` 一起进 run 目录（§8.2）。

#### 7.1.1 求解流到输出列的映射

首先要回答的是：目标数据集里的 `observation.state` 和 `action` 分别从哪来。这取决于输入侧的 `state_action_relation`（§3.3）：

| 输入声明 | 求几次 IK | `observation.state` 输出 | `action` 输出 |
|---|---|---|---|
| `absolute_next_state` | 一次（只吃 `state`） | `q_state[t]` | 按 `action_definition` 从 `q_state` 派生 |
| `independent_command` | **两次**（两条流各一次，须耦合） | `q_state[t]` | `q_action[t]` |
| `delta_from_state` | **两次**（`action` 先还原成绝对 EEF 目标，仍需为它求解） | `q_state[t]` | `q_action[t]` |

本参考数据是 `independent_command`，所以**两条流都要求解**。原草稿只映射了 `action` 一条流，那样导出的 `observation.state` 无处可来。

**`delta_from_state` 也是两次，不是一次**（2026-08-27 修正，原表写错）。把 EEF 增量加回 `state` 得到绝对目标之后，这个目标同样需要一次 IK 才能得到 `q_action`。存在一个一次求解的变体——用 `state` 处的 Jacobian 伪逆把 EEF 增量直接映射成关节增量 `Δq = J⁺(q_state) · Δx`——但那是**一阶近似**，增量大或接近奇异时误差显著。若采用必须在 `ExportProfile` 里显式声明，并在质量报告中给出该近似引入的 FK 误差，不得当作等价做法默认使用。

#### 7.1.2 跨流 IK 分支耦合（必须，且是最容易错的一处）

一旦对两条流各求一次 IK，**两次求解可能落到不同的解**。有两个互相独立的成因，都会造成同一后果：

- **离散分支**：同一末端位姿存在有限个不同构型（肘上 / 肘下、腕翻转），六自由度臂就有这个问题
- **连续零空间**：七自由度臂对同一末端位姿有一维自运动流形，解可以在其上任意滑动——OpenArm 每臂正是 7DOF（§11），所以这一项一定会遇到

源端 `state` 与 `action` 物理上很接近，解出来却可能分处不同分支或流形上相距很远的位置。后果见 §6.1：两条流各自平滑、各自误差合格、回放正常，但同一帧的 state 与 action 互相矛盾。

契约必须写死耦合方式，`solve_coupling` 的取值：

| 取值 | 做法 | 适用 | M1 |
|---|---|---|---|
| **`warm_start_from_state`** | 先解 `state` 流得 `q_state[t]`，再以它为初值解 `action` 流 | 通用；Pink 是微分 IK，天然支持 | **M1 采用** |
| `independent` | 各自独立求解 | **仅允许在两条流描述不同运动组时使用**；同组用此项即为配置错误，`doctor` 应报错 | 允许但需显式 |
| `interleaved_sequence` | 按真实时序把两条流拼成**一条**序列 `state[t] → action[t] → state[t+1] → …`，当作单条连续轨迹求解 | **本参考数据不适用**，理由见下 | 不用 |
| `joint_solve` | 对 `(q_state, q_action)` 两个变量联合优化，各自满足自己的 EEF 目标，附加两者距离正则 | 需要比 warm-start 更强的一致性保证时 | **不进 M1** |

**`joint_solve` 为什么不进 M1：** 第一轮把它写成「两条流作为同一 QP 的两组任务联合求解」，这个说法数学上不成立。Pink 的接口是对**一个** `configuration` 求解一组 tasks 的速度，两条流是**两个不同的构型**，不能塞进同一个单构型 QP 当作两组任务——那样求出来的是「一个构型同时逼近两个末端目标」，含义完全不同。真正的联合求解需要自己写 `(q_state, q_action)` 双变量优化器，属于自研求解器，违反 §1.5。

**`interleaved_sequence` 被 §2.3 的实测数据否掉了（2026-08-27 第三轮修正）。** 第二轮曾把它列为推荐做法，理由是「把跨流一致性化归为已有的时间连续性问题」。这个想法本身没错，但它隐含假设了 `action[t]` 在空间上位于 `state[t]` 与 `state[t+1]` 之间。**实测结论是 `action[t] ≈ state[t+4~5]`，该假设不成立。** 代入后交错序列实际访问的位置是：

```
state[0]  action[0]  state[1]  action[1]  state[2]  ...
 ≈p(0)     ≈p(4.5)    ≈p(1)     ≈p(5.5)    ≈p(2)   ...
```

即一条**幅度约 4.5 帧、每步来回折返的锯齿轨迹**。把它当作连续轨迹求解，不但无助于保持分支，反而会与速度限位直接冲突，并产出毫无物理意义的关节速度曲线。

这个例子值得记下来：**一个在文档层面听起来很优雅的设计，被一次全量实测直接否掉。** 它也说明 §7.1.3 的 `command_timing` 不只是「选哪种耦合」的输入，而是**决定某些耦合方式是否根本可用**。

无论哪种取值，§6.1 的跨流一致性检测都要跑——耦合是预防，检测是验证，不能互相替代。

#### 7.1.3 时间关系与 action 定义

**先必须回答一个问题：`action[t]` 和 `state[t]` 是同一时刻的吗？**

`state_action_relation: independent_command` 只说明两者是不同的物理量，**它不包含任何时间信息**。它无法证明：`action[t]` 对应 `state[t]`、还是对应 `state[t+1]`；控制链路上有没有延迟；两者的时间戳是不是同一个采样点采的。第一轮修订直接选用 `target_position_same_step` 并注「本数据的自然选择」，那是一个未经证实的假设；第二轮把它判为 `MISSING`、结论是等人回复。

**现在两者都被实测取代了（§2.3）：**

```yaml
state_action_relation:
  type: independent_command

command_timing:
  pairing: same_row_command            # 训练配对：observation[t] ↔ action[t]，不移位
  action_definition: absolute_eef_target
  shift_policy: none                   # 明确不做任何时间移位，理由见下
  observed_tracking_delay_frames:      # 源机器人的物理跟踪延迟，非配对偏移
    arm: [4, 5]                        # ≈133–167 ms @30fps
    gripper: [5, 6]                    # ≈167–200 ms
  fps: 30
  evidence: DATA_DERIVED               # §3.4；全量 20 ep / 13,746 帧
  pending_confirmation: source_recording_code_or_owner
```

**`observed_tracking_delay_frames` 与 `pairing` 是两个不同的东西，绝不能混用。** 这是本节唯一容易出人命的地方：

| | 是什么 | 用来做什么 | 是否影响导出 |
|---|---|---|---|
| `pairing: same_row_command` | 训练时 observation 与 action 的配对方式 | 决定 `observation.state[t]` 与 `action[t]` 写在同一行 | **是**，且答案是「保持同行、不移位」 |
| `observed_tracking_delay_frames` | 源机器人执行器从收到命令到实到的物理延迟 | 供 §6.1 跨流一致性判据换算合法关节位移；供诊断解释残差 | **否**，不改变任何一行数据的位置 |

**为什么测出 4–5 帧延迟却不移位：** 训练目标是「在当前观测下，示教者当前发出了什么命令」。`action[t]` 正是那个命令，它写在第 `t` 行是正确的。把它平移 4–5 帧，策略学到的就变成「预测已经被执行完的状态」，那是一个不同的、且没用的任务。同理也**不能**改写成 `action[t] = q_state[t+1]`——那是 `absolute_next_state` 语义，与本数据的实测结论矛盾。

`action_definition` 的取值仍需显式声明：

| `action_definition` | 含义 | 备注 |
|---|---|---|
| **`absolute_eef_target`** | `action[t]` = 第 `t` 帧发出的**绝对**目标位姿，经 IK 得 `q_action[t]` | **本数据取此项**，`DATA_DERIVED`（§2.3） |
| `next_state` | `action[t] = q_state[t+1]` | 仅当输入是 `absolute_next_state` 时有意义；**与本数据实测结论冲突，不得用** |
| `delta_position` | `action[t] = q[t+1] - q[t]` | 需同时写出量纲与是否归一化 |
| `velocity` | 关节速度 | 需写出 `dt` 来源 |

两条附带规则：

- **不做重定时。** `timestamp` / `frame_index` / `fps` 一律继承源数据（§7.2），因为视频不重编码，时间轴必须保持对齐。
- **`control_mode` 声明为 `position`**，首版只产出位置量；速度与力矩不承诺。

#### 7.1.4 夹爪映射

源 `action` 侧夹爪是归一化 `[0, 1]`，源 `state` 侧是弧度 `[-3.00, 3.00]`（§2.2），目标机器人的夹爪则是它自己的关节量。这是一次**必须显式配置的量纲转换**，不是推断项：

```yaml
gripper_mapping:
  left:
    source_stream_semantics:            # 两侧不同，各自声明
      observation_state: { semantics: joint_angle, unit: rad, range: [-3.00, 3.00] }
      action:            { semantics: normalized_open, range: [0.0, 1.0] }
    target_joint: openarm_left_gripper_joint
    target_range: [q_closed, q_open]    # 从目标 RobotProfile 的限位取，必须写出实测值
    mapping: linear                     # linear | table | passthrough
    direction_confirmed_by: USER        # 开合方向不得推断（§3.4）
    out_of_range_policy: clamp_and_flag # 越界钳位并计入掩码原因
```

**源 `state` 侧夹爪语义已由实测解出（2026-08-27，§2.3）。** 前两轮把它判为 `MISSING`，M1 退路是「从 `observation.state` 删除该维」。现在不必了：按跟踪延迟对齐后，

```
state_gripper ≈ 5 × action_gripper − 3        左 R²≈0.968，右 R²≈0.942
⇒ aperture(t) ≈ (state_gripper(t) + 3) / 5    开合度分数，∈[0,1]
```

这同时证实了两件事：`state` 侧确实是**实际关节角**（弧度），`action` 侧确实是**归一化开合指令**；并且给出了把 `state` 侧换算成开合度分数的可用关系。**注意这条关系是从 `state` 自己推出开合度，不是用 `action` 去填 `state`**——不构成 §7.1.4 下文所述的标签泄漏。

因此夹爪映射分两段，两段的证据状态不同：

| 段 | 内容 | 证据 |
|---|---|---|
| 源侧 → 开合度分数 | `state`：`(x+3)/5`；`action`：直接就是分数 | **`DATA_DERIVED`**，已解决 |
| 开合度分数 → 目标夹爪关节值 | 需 OpenArm 自己的夹爪限位、行程与开合方向 | **仍待 M-1 从 `openarm_description` 取得**（§14.2） |

三条实施细则：

- 仿射关系是控制器的**稳态**标定，快速开合的瞬态段会有偏差。M1 应统计该关系的逐帧残差并纳入质量报告，残差异常大的帧按 §6.1 输入质量项处理。
- 夹爪的实测延迟是 5–6 帧，与手臂的 4–5 帧**不同**。它同样只用于诊断换算，**不改变同行配对**（§7.1.3）。
- 源侧 `state` 观测范围 `[-3.00, 3.00]` 比仿射关系推出的 `[-3, 2]` 略宽，超出部分应查明是过冲还是离群帧，不要直接裁剪。

**不得用同帧 `action` 填 `state` 侧夹爪。** 第一轮修订给的退路是「`state` 侧夹爪不参与本体化，导出时置为由 `action` 侧派生的值」——**这是一个训练数据完整性错误，不是权宜之计**。它把当前帧的指令写进当前帧的观测，等于把模型要预测的目标泄漏进输入；同时把「夹爪实际状态」和「夹爪指令」这两个不同的物理量混为一谈。策略在这种数据上会学到一条捷径，离线指标好看，实际部署时观测里没有这一项可用。

**§2.3 的实测结论没有推翻这一条，反而让它更清楚。** 实测给出的是 `state → 开合度` 的换算，走的是 `state` 自己的数值；泄漏指的是拿 `action[t]` 去充当 `observation.state[t]`。两者方向相反，不要因为「现在知道两者有仿射关系」就认为可以互相替代——**恰恰因为存在 4–5 帧延迟，`action[t]` 与 `state[t]` 在数值上就不相等**，用前者冒充后者既泄漏标签又引入 4–5 帧的系统偏差。

处理优先级：

| 处理 | 做法 | 代价 | 状态 |
|---|---|---|---|
| **实测仿射映射** | 用 `(state+3)/5` 得开合度，再按目标夹爪限位映射 | 需 OpenArm 夹爪规格 | **M1 主路径**（本节上文） |
| 降维 | 从 `observation.state` 中**删除**夹爪维度，只保留 `action` 侧 | 观测里没有夹爪状态；须在 `retarget` 段与 `info.json` 的 `features` 里显式反映维度变化 | 退路，仅当 OpenArm 夹爪规格也拿不到时 |
| 延迟模型估计 | 用**历史** action 推导夹爪状态估计 | 结果必须标 `synthetic`，不得与实测状态混同 | 不进 M1 |
| ~~同帧 action 填充~~ | —— | **标签泄漏 + 系统偏差** | **禁止** |

#### 7.1.5 出口验收（替代「能被加载」）

原 M1 出口条件是「导出的数据集能被 LeRobot 正常加载」。加载成功证明不了语义正确，因此加严为五步，全部 CPU 可跑。

**关键点：必须走训练入口实际会走的那条路径，而不是裸 `LeRobotDataset(root=...)`。** 否则训练白名单只是被记录了，没有任何机制保证使用者不会忘记加上它——白名单形同注释。已核实 `lerobot` 的 `DatasetConfig`（`src/lerobot/configs/default.py`）同时提供 `root`、`episodes: list[int] | None` 与 `exclude_episodes: list[int] | None`（后者注释即为「drop corrupt or heterogeneous episodes」，语义与本工具的 `FAIL`/`WARN` 正好对应），所以这条路径是现成的。

1. **按白名单加载**：从导出的 `retarget` 段读取 `training_episode_allowlist`，经 `DatasetConfig(root=..., episodes=allowlist)`（或等价的训练配置）构造数据集；`features` 的 shape / dtype / 关节名与 `RobotProfile` 一致
2. **断言白名单真的生效**：遍历所加载数据集的 `episode_index` 集合，断言其中**不含任何 `retarget.status != PASS` 的 episode**。这一步专门用来抓「白名单写了但没被应用」
3. **时间窗**：带 `delta_timestamps` 取一个窗，形状为 `[T, ...]` 且窗内 `timestamp` 间隔符合 `1/fps ± tolerance_s`
4. **归一化 batch**：过 `DataLoader` 取一个 batch，用**重算后的** `meta/stats.json` 做归一化，断言各通道落在合理区间（例如归一化后 `|z| < 5`）；掩码列不在归一化清单内（§7.2.2）
5. **FK 语义回验**：抽样若干帧，用 Pinocchio 对导出的 `observation.state` **和** `action` 分别正算 FK，**按 T1/T2 变换（§3.4）回到源坐标系后**与源 EEF 轨迹比对，误差在 §6.3 阈值内。必须两条流都验：只验 `action` 无法发现 §7.1.2 的分支不一致

**导出时同时产出一份可直接运行的训练配置 / 命令**（含 `--dataset.root`、白名单或 `exclude_episodes`），作为交付物的一部分。这不是为了真去训练，而是让「正确的加载方式」成为默认路径而非文档里的一句提醒。

不把「跑通一个最小训练 step」列为出口条件：它要引入 policy 与训练侧依赖，而上面五步能覆盖同一类错误（shape、dtype、stats、时间窗、白名单未生效、语义），成本低一个量级。

### 7.2 保持格式的重写

**关键认识：一个 LeRobot 数据集 = 一张数值表 + 一堆 mp4 + 一组指向它们的元数据。重定向只动表，不动 mp4——但元数据不止 `info.json` 一个文件。**

| 内容 | 处理 |
|---|---|
| `observation.images.*`（mp4 分片） | **原样复制或硬链**，一帧不改 |
| `task_index` / `timestamp` / `frame_index` / `episode_index` | 不变（§7.1.3 不做重定时） |
| `observation.state` / `action` | 换成目标机器人的关节值，语义按 §7.1 契约 |
| **新增 `valid.retarget`（逐帧）/ `retarget.status`（逐 episode）** | 本体化失败的帧**保留行、标记掩码**，不删除（见 §7.2.1） |
| `meta/info.json` 的 `robot_type`、`features` 维度与关节名 | 相应改写；新增掩码列注册为正式通道 |
| `meta/stats.json` | **必须重算，且与训练白名单口径一致**（见 §7.2.2） |
| **`meta/episodes/chunk-*/file-*.parquet`** | **原文漏项。** v3 把每 episode 的长度、task、以及在共享 parquet/mp4 里的**字节与帧偏移**存在这里；episode 边界靠它解析，不靠文件名。列集合变了就要一起重写 |
| **`meta/tasks.*`** | **原文漏项。** 任务描述到整数 ID 的映射。注意官方文档写 `meta/tasks.jsonl`、main 分支代码写 `meta/tasks.parquet`（§3.2），按钉住的 `lerobot` 版本走 |
| 新增 `retarget` 元数据段 | 源数据集哈希与 revision、目标 `RobotProfile` 版本、`ExportProfile`、求解配置、后端与版本、误差摘要、诊断结论、**训练 episode 白名单** |

因此导出的实际工作是：写一份新 parquet（两列换掉、两列新增）、复制视频目录、改 `info.json`、重写 `meta/episodes/*` 与 `meta/tasks.*`、重算 `stats.json`、加一段谱系。**工具的能力边界没有扩大——它仍然只是回放工具，只是把回放结果装回了原来的盒子。**

新增的 `retarget` 段沿用上游 `synthesis_fk` / `alignment` 的写法，保持同一份数据集里派生记录风格一致。

**不要假设「一个 mp4 = 一个 episode」。** v3 的视频按大小分片（`DEFAULT_VIDEO_FILE_SIZE_IN_MB = 200`），路径模板是 `videos/{video_key}/chunk-{i:03d}/file-{j:03d}.mp4`，一个文件通常含多个 episode。§2.1 观测到的 `file-{ep}.mp4` 是这份 1080×1920 数据的分片结果，不是格式保证。导出实现必须一律通过 `meta/episodes/*` 的偏移定位，不得靠文件名推断 episode。

#### 7.2.1 坏帧标记，不删除；可训练子集用白名单表达

§6.3 判 `WARN` 的 episode 里存在孤立不可解帧。**这些帧不能删行**——一删就和 mp4 帧、`timestamp`、`frame_index` 全部错位，本节开头「只动表，不动 mp4」的前提当场失效。

规则：

- 逐帧列 `valid.retarget`：该帧关节值是否可用于训练
- 逐 episode 列 `retarget.status`：`PASS` / `WARN` / `FAIL`
- 失败帧**保留行**，关节值 carry-forward，掩码置 `false`
- **首帧即失败时没有前一有效帧**，此时向后填充自第一个有效帧；若整条 episode 无任何有效帧，直接判 `FAIL`

carry-forward 有一个必须正视的陷阱：**填充后的无效帧长得像一个完全合理的位姿，只有掩码能把它和真解区分开。** 因此掩码是与数值同等地位的导出产物，不是附注——必须在 `info.json` 的 `features` 段注册为正式通道，并在质量报告里说明。

**但掩码本身不会让数据变得可训练，这一点原文说得不够。** 核实结果：`LeRobotDataset` 只是把 `features` 里的每个 key 当张量返回，**没有任何按列过滤的钩子**；带 `delta_timestamps` 时它直接返回时间窗堆叠。所以自定义的 `valid.retarget` 会被当作又一个张量原样喂给模型，不会自动生效。带时间窗的训练更不能只看当前帧有效——窗内所有 observation 与 action 都必须有效。

**解法比原先设想的便宜得多，不需要导出两份数据集。** `LeRobotDataset.__init__` 已经有 `episodes: list[int] | None` 参数，支持 episode 级白名单加载。因此：

| 视图 | 怎么得到 | 用途 |
|---|---|---|
| **审计视图** | 物理导出的那一份：全部 episode、全部帧、掩码齐全 | 检查、追溯、质量报告 |
| **训练视图** | **同一份物理数据** + `retarget.training_episode_allowlist` + `LeRobotDataset(root, episodes=allowlist)` | 训练 |

**M1 的白名单只放 `PASS` episode。** `WARN` episode 留在物理数据里带掩码，但不进白名单——这样就绕开了「时间窗跨越无效帧」的全部复杂度，代价是损失少量数据。

这个做法的三个好处值得写明：不必给 episode 重新编号、不必改动 mp4 分片、不必重算 `meta/episodes/*` 的偏移。**朴素做法——物理上导出第二份「只含好 episode」的数据集——会同时触发这三件事**，因为 v3 的 episode 边界靠 `meta/episodes/*` 的字节与帧偏移解析（§7.2）。把过滤放在加载期而不是导出期，这些成本全部消失。

后续要挽回 `WARN` 那部分数据，有两条路，都不进首版：提供一个掩码感知的 sampler（保证整窗有效），或把 `WARN` episode 在坏帧处切成子 episode（要重写偏移，较贵）。

#### 7.2.2 `meta/stats.json` 必须重算

`stats.json` 存各通道的 min/max/mean/std，v3 官方说明其用途就是归一化（`dataset.meta.stats`）。本体化之后关节值域完全变了，**继承源数据集的统计量等于用源机器人的分布去归一化目标机器人的关节值**——不报错、训练照跑、结果安静地错，正是 §1.2 最警惕的那类失败。

三条规则：

1. **必须重算，不得继承。**
2. **口径必须与训练视图一致**，即只统计 `training_episode_allowlist` 内、且 `valid.retarget == true` 的帧。原文只写了「按掩码过滤」，漏了 episode 白名单这一层；两个口径不一致，归一化就带上了永远不会被训练看到的数据的分布。
3. **`stats.json` 是全局的、只有一份**，所以它服务的是训练视图。审计视图不得依赖它做归一化，这一点在 `retarget` 段写明。

一个实现注意点：掩码列若注册进 `features`，LeRobot 的统计计算会把它当数值通道一起算（bool 会被提升为 float32），得到一组无意义的 0/1 统计量。这不会报错，但下游若无差别地对所有 key 做归一化就会去归一化掩码。掩码列需在 `retarget` 段显式列入「不参与归一化」清单。

### 7.3 视频：按跨本体惯例全部保留（已确认）

那些 mp4 拍的是**源机器人**在做任务。动作重定向到别的机器人后，画面里仍是原机器人的手臂，**视觉本体与动作标签不匹配**。

**已确认策略：按跨本体训练惯例全部保留。** 图像提供场景与任务上下文，动作提供运动标签；本体不匹配是该范式的已知特征，不作为缺陷处理。

因此导出模块的行为是确定的：

- 三路视频全部原样复制或硬链，不筛选、不裁剪、不重新渲染
- 导出的 `retarget` 元数据段中显式写入 `visual_embodiment: source`，并记录源机器人标识（本数据为 `generic`）
- 质量报告在数据集层面声明一次「视觉本体为源机器人」，不逐帧重复

保留 `video_policy` 配置项（`keep_all` / `drop`），默认 `keep_all`。**不实现 `wrist_only` 与重新渲染**——前者收益不明确，后者属 v2 仿真范围。

### 7.4 附加导出

除数据集本身，另提供：通用 CSV / JSON（便于查看）、NPZ（便于数值处理）、质量报告。生态适配器（RoboTwin 等）留接口，不进首版。

---

## 8. 批量与可追溯

### 8.1 主形态是流水线

数据规模是 1682 episode，没人会逐条人工审核。主形态是：**批量进、批量出、出一份质量报告说明哪些能用哪些不能用。** 三维回放是失败时的调试工具与抽检手段，不是主流程。

### 8.2 便宜的诚实实现

可追溯不需要完整版本对象图。首版用目录结构实现：

```
project/
  source/
    <dataset-hash>/          原始数据集只读引用 + 哈希 + MappingSpec
  robots/
    <robot>/profile.yaml     URDF + 派生配置 + 哈希
  runs/
    20260826-001/
      recipe.yaml            输入哈希、robot 版本、后端与版本、参数、随机种子
      export_profile.yaml    导出契约（§7.1）：流映射、solve_coupling、action 定义、夹爪映射
      result/                q(t) 与 FK 复算结果
      metrics.jsonl          逐帧指标
      report.json            批量质量报告
      export/                导出的数据集（或其引用）
```

规则只有三条：**原始数据只读；每次运行写一个新 run 目录；recipe 相同则结果可复现。** 这几十行代码覆盖了第 8 条核心属性的全部实质内容。

`SQLite` 只在需要索引和检索时加入，不用于存放逐帧数值。

---

## 9. 可视化与人工介入

### 9.1 首版范围

- 三维视图：目标机器人、源 EEF 轨迹、实际 FK 轨迹、坐标系、碰撞点
- 统一播放时钟：播放 / 暂停 / 拖动 / 逐帧
- 曲线：位置误差、姿态误差、关节曲线、速度、限位余量
- 时间轴上标出问题区间，点击跳转
- 少量参数控件 + 局部重算

### 9.2 技术路径

**先用最土的办法确认数值正确，再做界面。** 顺序是：静态图（matplotlib）确认求解结果对 → 三维回放。反过来先做界面，会对着假数据调交互。

界面实现走 **薄 React + R3F**：单页面，3D 画布 + 时间轴 + 曲线 + 少量控件，后端是很小的 FastAPI 返回 JSON。跳过多工作区、跳过 Tauri 桌面壳、跳过完整状态管理层。

两个已知坑：three.js 默认 Y-up 而机器人学是 Z-up；URDF mesh 路径与格式处理。若时间紧，可先用 Viser 一周内看到真实结果，把它当作 React 版本的功能草图——代价是那部分界面代码将来会丢弃。

### 9.3 鼠标绘制

**本质上是另一个 `SourceAdapter`**：鼠标画出的路径规范化后就是一条 `CanonicalTrajectory`，后续走与数据导入完全相同的管线。增量只有「二维鼠标位置转三维路径」这一小块（选平面、定姿态策略、采样、时间化）。

它对开源影响力的投入产出比很高——README 里一张「画一条曲线，机器人跟着走」的动图，传播效果胜过任何架构说明。但它**依赖三维前端和求解器都已存在**，因此排在后期。局部重绘（圈选一段重画）与整段绘制共用同一套机制。

---

## 10. 测试与质量

### 10.1 合成往返测试台

**首版最重要的测试设施，且不需要真实数据、不需要 GPU。**

从目标机器人 URDF 出发，在关节空间随机采一条平滑且不越限的 `q(t)`，用 Pinocchio 正算出 EEF 轨迹——**这条轨迹按构造一定可达**。把它当输入喂给工具，断言能找回 `q'(t)` 满足：EEF 误差在容差内、连续性达标、无越界。`q'` 不必等于 `q`（IK 多解），验证的是性质而非固定轨迹。

负向样例全部由扰动同一条基准轨迹生成：

| 扰动 | 期望检出 |
|---|---|
| 位置 × 1000 | 单位错误 |
| 交换四元数分量顺序 | 姿态约定错误 |
| 整体平移 2 m | 不可达区间 |
| 镜像一个轴 | 手系错误 |
| 注入 NaN / 重复时间戳 / 时间倒序 | 输入质量问题 |
| 拼接两段不连续轨迹 | 连续性断点 |
| 穿过已知奇异位形 | 奇异告警 |
| 贴到关节限位 | 限位余量不足 |

这套设施对四个后端、所有机器人免费复用，且全程 CPU，可进 CI。

### 10.2 交叉校验

真实数据的 `reference` 段保留了源关节轨迹。用它做端到端自检：源关节 → Pinocchio FK（腰部按 `fk_waist` 固定）→ 应当复现数据里的 EEF 通道。这条校验能同时验证 URDF 加载、关节顺序、TCP 偏移和四元数约定，价值极高。

**但它有一个硬前置条件，原文没写：需要源机器人的 URDF。** §2.1 已确认这份数据的 `robot_type` 是 `generic`，源机器人**已匿名化**。没有源 URDF、关节约定和 TCP 模型，这条校验根本无法执行——它不是「尽早跑通」的问题，是「能不能做」的问题。

数据里留下的线索是充足的（关节名 `Larm1..7_Joint`、末端 link `Larm08_link`、`fk_waist` 的三个腰部固定值、TCP 沿工具 z 偏移 `0.22855 m`），所以按 §3.4 的分类这属于 `MISSING` 而非 `UNDEFINED`——**正确动作是向学长索取源机器人 URDF**，已记入 §14.2。据 2026-08-27 反馈，源 URDF **容易取得**，因此本项的风险已从「可能永久做不了」降为「排期问题」。

**配对必须同侧同行，这一点因 §2.3 的实测结论而变得关键。** 源数据同时有关节侧与 EEF 侧的 `state` / `action` 四条通道，校验只能同侧配对：

```
observation.state.position[t]  →  FK  →  应复现  observation.state[t]      ✓
action.position[t]             →  FK  →  应复现  action[t]                 ✓
observation.state.position[t]  →  FK  →  对比    action[t]                 ✗ 差 4–5 帧
```

第三种配对会得到约 2.10 mm 的系统性残差（§2.3），**那不是 FK 或 URDF 的错误，而是跟踪延迟**。不把这一条写清楚，第一次跑校验时几乎必然会把它误判成 TCP 偏移或坐标系错误，然后去"修"一个不存在的 bug。

**反过来，这条校验也是对 §2.3 结论的独立复核：** 如果源 URDF 拿到后，`observation.state.position` 的 FK 精确命中 `observation.state`、而与 `action` 相差恰好 4–5 帧，就在第三个独立维度（源本体 FK）上确认了跟踪延迟的存在。

因此这一项的地位改为条件式：

| 情况 | 处理 |
|---|---|
| 拿到源 URDF | **列为 M1 出口项**，尽早跑通；同时把 §6.1 的「语义一致性」诊断打开 |
| 拿不到源 URDF | **从 M1 出口条件中移除**，§6.1 该诊断项标 `NOT_SUPPORTED`；改由 §10.3 的单臂真实往返测试承担同类验证职责 |

无论哪种情况，§6.1 的该诊断项对**一般数据集**都只能是 `CONDITIONAL`——绝大多数公开数据集不会附带源机器人模型。

### 10.3 测试数据获取策略

现状：真实数据只有学长提供的那一份（双臂）。**单臂数据缺乏，其余数据集需自行从开源数据集获取。**

#### 一个必须先解决的障碍

**大多数开源具身数据集存的是关节轨迹，不是 EEF 轨迹。** 而本工具按定位只接收 EEF 输入（源机器人 FK→EEF 属工具外预处理，见 §1.5）。这意味着开源数据集**不能直接作为测试输入**。

解法：在 `tools/` 下提供一个 **FK 预处理脚本**，把关节空间数据集转成 EEF 数据集。

- 它是**测试数据制备工具，不是产品功能**，不进 CLI 公开契约，不写入能力清单
- 复用 Pinocchio，无新增依赖
- 它做的事和上游 `synthesis_fk` 完全一致（固定非受控关节 → FK 到指定末端 link → 加 TCP 偏移 → 写出 EEF 通道），因此产出的数据形态与真实数据一致

#### 顺带得到的最强验证：真实数据上的往返测试

用这个脚本处理**单臂关节数据集**时，会得到一个 §10.1 合成往返的真实数据版本，而且**带真值**：

```
真实关节轨迹 q_true
  → FK → EEF 轨迹（丢弃本体信息，成为「无本体数据」）
  → 本工具重定向回同一台机器人
  → 得到 q_solved
  → 与 q_true 比较
```

同机器人往返虽是退化情形，但价值极高：**你知道正确答案**。可直接量化 IK 分支选择、连续性、误差累积，而这在跨本体重定向时是没有真值可比的。这条测试应作为 M1 的重要验收项。

跨本体（例如 Franka 数据 → OpenArm）则是真实使用场景，无真值，只能靠 §6 的诊断判定。

#### 候选数据源

以下为候选方向，**具体格式与字段需逐个核实后再写 `DataAdapter`**（后缀相同不等于 schema 兼容）：

| 方向 | 特点 | 用途 |
|---|---|---|
| LeRobot Hub 上的公开数据集 | 与首份真实数据同族，格式最近 | 优先，`DataAdapter` 复用度最高 |
| Franka / 单臂为主的大型开源集 | 补齐单臂缺口，且与 Panda 夹具同本体 | 往返验证的最佳材料 |
| Open X-Embodiment 系 | 覆盖多种本体 | 广度测试、跨本体案例 |
| GenRobot 等国内开源集 | 任务类型丰富 | 广度测试 |

选取原则：**优先选已含 EEF 通道的数据集**（省去 FK 预处理，减少一层误差来源）；其次选本体明确、URDF 可得的（否则无法做 FK）。

#### 三层测试资产

| 层 | 来源 | 有无真值 | 用途 |
|---|---|---|---|
| 合成（§10.1） | Pinocchio 正算 + 扰动 | 有 | CI、负向样例、每次提交跑 |
| 真实往返（本节） | 开源单臂数据集 FK 后回灌 | 有 | 定期回归、精度标定 |
| 真实跨本体 | 学长提供的双臂数据 | 无 | 端到端验收、阈值标定 |

---

## 11. 机器人范围

**OpenArm 是首个正式交付目标——这是一个产品决定，不是从「它是双臂」推出来的技术结论。** 原文写成「OpenArm 已确认为双臂本体，因此它就是那份数据的目标机器人」，这个「因此」不成立：双臂的机器人有很多。真实依据是 §14.1 记录的 2026-08-26 决定与学长的提议，据此执行即可，但论证方式要改，否则后面会误以为这里有技术必然性。

**核实后的 OpenArm 事实（2026-08-27）：**

| 项 | 实际情况 |
|---|---|
| 形态 | 官方定义是**「开源 7 自由度手臂」——单臂 7DOF**。「双臂系统」是由两条臂组成的完整配置（官方标价 $6,500 的 bimanual system），不是「OpenArm 就是一台双臂机器人」 |
| 描述文件 | `enactic/openarm_description`，Apache-2.0。提供的是 **URDF/xacro 源文件，URDF 需要生成**，不是现成 URDF |
| 版本 | 仓库同时存在 `openarm_v2.0`（现行 preset 驱动流程）与 `openarm_v1.0`（旧 `v10 + parallel_link` 兼容路径）两套资产 |
| MJCF | **`enactic/openarm_mujoco` 已存在**，Apache-2.0 |

三条直接影响：

1. **必须锁定「哪一个 OpenArm」**：v1.0 还是 v2.0、哪个 preset、双臂配置的 root/躯干如何定义、两臂 base 的相对变换从哪来。「支持 OpenArm」不是一个可验收的陈述。
2. **URDF 从 xacro 生成这件事本身有成本**：需要 xacro 处理链，且生成结果要固化并计入哈希（§4.1），否则派生配置的溯源断掉。
3. **`openarm_mujoco` 的存在提高了 §5.2 里 Mink 那条线的性价比**——原文假设「Menagerie 大概率现成」，实际是官方直接提供 MJCF，不必依赖 Menagerie。这不改变 Mink 仍排 M5 的结论，只是把该期权的成本调低了。

机器人分两种角色，不要混为一谈：

| 角色 | 机器人 | 用途 |
|---|---|---|
| **开发脚手架 / 回归夹具** | Franka Panda | 打通管线、合成测试、单臂回归。URDF 易得，CuRobo 大概率自带配置，接入成本最低。**永久保留为测试夹具**，不作为交付目标 |
| **首个正式交付目标** | **OpenArm 双臂配置**（版本待锁定） | 真实数据的实际目标本体。多运动组、双 EEF、臂间关系 |

后续顺序：

| 顺序 | 机器人 | 验证什么 |
|---|---|---|
| 3 | UR5e | 非冗余、不同关节拓扑，清除 Panda / OpenArm 专用假设 |
| 4+ | 更多机器人 | 广度，主要靠 §4.3 的配置资产链 + 社区贡献 |
| 后续 | Unitree G1 上半身 | 高自由度、躯干冗余。最难，排最后 |

**OpenArm 早期化的三个后果，需要正视：**

1. **CuRobo 几乎肯定没有 OpenArm 的现成配置**，因此 §4.3 的碰撞球配置链是 M3 的**前置依赖**。好消息是核实后这一项的工作量大幅下降：拟合算法直接用 CuRobo 的 `build_robot_model`，本项目只做溯源、校验与人工审核。
2. **需先确认 OpenArm URDF 的可得性与质量**（版本选择、xacro 生成、关节命名、mesh 完整性、限位是否齐全）。这是 M1 的准入条件，必须在 **M-1** 完成并写入可行性记录；不得拖到 M0。
3. **必须做一次双臂可达性预检，这是原文漏掉的、可能推翻目标机器人选择的检查。** §2.2 实测源数据 `x ∈ [0.16, 0.61]`、`z ∈ [0.57, 0.90]`，左右臂 `y` 合计跨度约 1 m。OpenArm 双臂配置**是否覆盖得住这个范围，目前没有任何证据**。

   **但预检不能只比包围盒（2026-08-27 修正）。** 「源轨迹 AABB 落在可达点云的包围范围内」只是一个很弱的必要条件，它证明不了姿态可达、证明不了两臂能同时到位、更证明不了连续轨迹能保持在同一分支。正确的预检是**直接拿真实数据抽样跑 IK**：

   | 检查 | 做法 |
   |---|---|
   | 位置 + 姿态可达 | 从真实 20 个 episode 里分层抽样若干帧（含轨迹端点与极值帧），带完整位姿求 IK，不只查位置 |
   | **双臂同时可达** | 左右臂在**同一帧**必须同时有解——分别可达不等于同时可达 |
   | 臂间碰撞 | 同时求解的构型过一遍自碰撞检查（§5.1），含左右臂之间的碰撞对 |
   | 连续性 | 抽若干**连续片段**（而非孤立帧）连续求解，看能否保持同一分支 |
   | T2 摆位择优 | 以上四项在若干候选 T2 摆位下各跑一遍，按「同时可达率」择优（§3.4） |

   这比包围盒贵，但仍然是几小时量级，且**它产出的就是 M1 要用的 T2 摆位**，不是一次性的丢弃工作。若结果是覆盖不住，要动的是目标机器人选择或 T2 摆位——**这个结论必须在 M0 之前拿到**，不能到 M1 才发现整批数据大面积不可达。

M0 用 Panda + 合成数据打通管线（不依赖任何真实数据与 GPU），M1 换 OpenArm + 真实双臂数据。

第一天需核实三件事（几分钟可完成，会实质影响排期）：CuRobo `content/configs/robot/` 现成有哪些配置；CuRobo 当前版本对多末端 / 人形的支持程度；MuJoCo Menagerie 里目标机器人是否齐全（OpenArm 已可由官方 `openarm_mujoco` 覆盖）。

---

## 12. 里程碑

### M-1 可行性闸门（Feasibility Gate，先于 M0）

**这是 2026-08-27 新增的独立阶段。** 早期版本把这几件事写成「M0 期间并行完成的核实，不占开发工作量」——**那个说法是错的**：生成 OpenArm URDF、核对 xacro/preset、建立双臂 root、跑双臂可达性预检，每一项都要写代码、跑求解、判读结果，合起来是一个正式的 feasibility spike。

#### M-1 的形态：一次性 harness，不是正式管线（第四轮修正）

**前两轮存在循环依赖：M-1 要跑真实数据的双臂 IK 与碰撞检查，而 Pinocchio / Pink / 碰撞几何却排在 M0。** 名义上是可行性检查，实际上偷偷做了半个 M0。而且 M-1 原写「建立 OpenArm 的 `GeometryModel`，供 M0 自碰撞使用」——**M0 用的是 Panda，OpenArm 到 M1 才进入，两处机器人对象根本对不上。**

因此明确三阶段的代码归属：

| 阶段 | 机器人 | 代码形态 | 去向 |
|---|---|---|---|
| **M-1** | OpenArm | **最小、允许抛弃的 feasibility harness**：直接调 Pinocchio + Pink 的裸 API，不建 `RobotProfile`、不进 CLI、不写抽象层、不求复用 | 用完即弃，只留结论与数据 |
| **M0** | Panda | 正式通用管线 + **Panda** 的碰撞资产与 `GeometryModel` | 成为基线代码 |
| **M1** | OpenArm | 把 M-1 的探索结论**重新实现**进正式 `RobotProfile` 与碰撞资产链 | 正式交付 |

**M-1 harness 明确允许写得难看。** 它的产出是一个决策，不是一份代码资产；用完即弃是设计意图，不是妥协。这样才能既不阻塞 M0，也不让 M0 承担未估算的工作量。

#### M-1 工作项

- 锁定 OpenArm 模型版本（v1.0 / v2.0、preset、双臂 root 与两臂 base 相对变换）
- 生成并固化 URDF，计入哈希（§4.1）；用 Pinocchio 成功加载
- 核对 mesh 完整性、关节限位齐全性、TCP 定义，**以及夹爪的限位、行程与开合方向**（§7.1.4 目标侧映射所需）
- **抽样双臂可达性预检**（做法见 §11），在 harness 里跑
- 索取源机器人 URDF（据反馈容易取得），用于 §10.2 与对 §2.3 结论的第三方复核

#### M-1 出口：预先登记的量化判据（第四轮新增）

前两轮的出口只写「明确回答两个问题」，**那不是闸门，因为没有通过标准**。没有事先定下的判据，看到一个不理想的结果之后再定标准，等于没有闸门。以下判据必须在**跑第一次预检之前**写进 `runs/` 的 recipe：

**抽样规模（预先固定）：**

| 项 | 规模 |
|---|---|
| 分层抽样单帧 | 20 ep × 30 帧 = 600 帧（含每条轨迹的端点与各轴极值帧） |
| 连续片段 | 20 段 × 60 帧（2 s @30fps），跨不同 episode |
| T2 候选 | 粗网格，先定候选个数与范围，再逐个跑 |

**通过判据（预先固定）：**

| 指标 | 绿灯 | 黄灯（有条件） | 红灯 |
|---|---|---|---|
| **双臂同时**可达率（单帧） | ≥ 95% | 80–95% | < 80% |
| 连续片段端到端可解且无分支跳变 | ≥ 90% 的片段 | 70–90% | < 70% |
| 抽样构型的自碰撞 | 0 穿透 | 仅出现在 < 2% 帧且可由 T2 调整消除 | 结构性穿透 |
| 关节限位 | 无越界 | 余量 < 10% 行程的帧 < 5% | 越界 |
| 姿态容差放宽 | 无需放宽 | ≤ 5° 且逐帧记录 | 需 > 5° |

**T2 候选排名规则（预先固定）：** 先按「双臂同时可达率」降序；并列时按「连续片段通过率」；再并列时按「平均限位余量」。**不引入事后加权。**

**出口决策：**

- **全绿 →** OpenArm 继续作为 M1 目标，采用排名第一的 T2，进入 M0
- **任一项黄灯 →** 允许进入 M0，但必须记录条件与补偿动作（放宽项、受影响帧比例），并在 M1 出口复检
- **任一项红灯 →** 按优先级处理：扩大 T2 候选范围重跑 → 放宽姿态容差至黄灯上限 → 暂停 OpenArm 路线并进入**目标重选 spike**

**Franka Panda 双臂配置（两台单臂组合）只是目标重选时的第一候选，不是已经验证好的备用机器人。** 它虽然复用 M0 的单臂 Panda 资产，但双臂 root、两臂 base 相对变换、双夹爪/TCP、臂间碰撞对和同时可达性都仍需单独建立与验证。选择它或其他候选后，必须重新执行 M-1 的完整资产核查、抽样和红黄绿判据，不得沿用 OpenArm 的结果；没有候选通过前，M1 保持阻塞。

**已不在闸门内的两项（第三轮）：** `command_timing` 与源夹爪语义原为闸门项、需等学长回复；现已由全量实测解出（§2.3），降级为 `DATA_DERIVED` + 待确认，**不阻塞 M-1 与 M1 启动**。源码或负责人回复作为最终验证证据，在拿到时把证据等级升为 `USER_CONFIRMED`。

### M0 骨架与合成闭环（纯 CPU，笔记本可完成，机器人 = Panda）

- `CanonicalTrajectory v0.1`（标记 provisional，M1c 出口才冻结结构）
- Pinocchio 集成：URDF 加载、FK、Jacobian
- **Panda** 的 `RobotProfile`、`GeometryModel` 与碰撞对屏蔽表（§4.3）——注意是 Panda，不是 OpenArm
- §10.1 合成往返测试台 + 负向样例生成
- Pink 求解后端
- §5.3.1 内部约定一致性测试 + **§5.3.2 独立 golden cases**（后者提供 M0 唯一的外部参照）
- CLI 最小集：`doctor`、`inspect`、`normalize`、`solve`、`diagnose`、`export`
- 结果用静态图确认

**出口：** 合成轨迹能往返——EEF 进、`q` 出、FK 回、误差在阈值内、无分支跳变；十项负向样例全部被正确检出；golden cases 全部通过，且打乱 joint-name 的负例被正确检出。

**M0 需要计入、但原文漏掉的工作量：** 自碰撞检测所需的 Pinocchio `GeometryModel` 构建、碰撞对生成与相邻 link 屏蔽表（§4.3、§5.1）。这不是一行代码。

### M1 真实数据接入

范围按 2026-08-27 修订收缩。**收缩依据不是「时间不够」，而是这些项在 M1 没有服务对象：**

| 原列项 | 处理 | 依据 |
|---|---|---|
| `Prober`：parquet / hdf5 / zarr / csv | **只做 parquet** | 首份真实数据是 parquet。hdf5/zarr/csv 现在没有对应的测试数据，写了也验证不了；等选定第二个数据集时按其实际容器补 |
| 基座变换：人工给定 + **有限自由度搜索** | **只做人工给定 + T2 粗网格**（T2 候选由 M-1 给出） | 通用搜索服务 `UNDEFINED` 类数据，其样本已推到 M3 之后（§3.4） |
| §10.2 源关节 FK 交叉校验 | **改为条件出口项** | 需源机器人 URDF，而源已匿名化（§10.2） |
| `solve_coupling: joint_solve` | **移出 M1** | 需自研双变量优化器，Pink 的单构型 QP 做不到（§7.1.2） |
| **AI 生成 `MappingSpec` 草稿** | **保留在范围内，但明确不是出口条件（stretch goal）** | 第一份数据的 `MappingSpec` 已知，用 AI 生成它证明不了「新格式几分钟接入」的泛化能力——那需要第二个数据集才能验证。同时它牵涉模型配置、结构化输出、schema 校验和无网络降级（§1.4 第 9 条）。做出来是亮点，没做完不该阻塞真实数据闭环 |

收缩后的 M1 **再拆为三段（2026-08-27 第四轮）**。拆分理由：收缩后的 M1 仍然把「真实数据数值闭环」和「LeRobot 格式重写」两个高风险子系统捆在同一个出口里，任一处卡住就看不到任何产物。**拆开后每段各有能展示、能回退的成果，且数值正确性先于格式工作确立**——反过来先做格式，会在语义还没验证的数据上调 parquet 结构。

#### M1a 真实数值闭环（不导出数据集）

- `Prober`：parquet
- `MappingSpec` schema（按流声明，§3.3）+ 首个 `DataProfile`，认证钉到数据集 revision 与 `lerobot` commit（§3.2）
- **`command_timing` 落档（§7.1.3）** — 已由 §2.3 实测解出，只需落档 + 实现同行配对与 `shift_policy: none`
- **全部 1682 episode 的结构扫描**（§6.3，只读 schema 与统计，确认那 20 条没漏掉字段布局或任务类型）
- 多运动组（双臂 + 双夹爪），夹爪按 §7.1.4 的实测仿射关系映射
- 双流 IK + `warm_start_from_state` 耦合（§7.1.2）
- 基座变换：T1 人工确认 + T2 采用 M-1 的排名结果
- 诊断与批量质量报告（§6），含 §6.1 跨流一致性三层判据
- 在 `calibration` 集上标定 `provisional` 阈值

**出口：** `calibration` 的 12 个 episode 跑通，出诊断报告，两条流的 FK 都能回到各自的源 EEF 目标且误差在阈值内。**不产出 LeRobot 数据集。**

这一段结束时已经可以给学长看东西了：一份真实数据的批量诊断报告。

#### M1b 数据集闭环

- §7.2 保持格式的数据集重写，含 `meta/episodes/*` 与 `meta/tasks.*`
- `stats.json` 重算，口径与训练白名单一致（§7.2.2）
- 坏帧掩码 + 训练 episode 白名单（§7.2.1）
- 可直接运行的训练配置产出（§7.1.5）
- §7.1.5 五步出口验收的实现

**出口：** `calibration` 集导出的数据集通过五步验收（按白名单加载 → 断言白名单生效 → 时间窗 → 归一化 batch → 两条流 FK 语义回验）。

#### M1c 留出集验收与契约冻结

- 在 **`held_out` 的 8 个 episode** 上端到端跑一次，**这批数据此前从未参与任何调参**
- 若已取得源 URDF：§10.2 交叉校验（含同侧同行配对规则）
- *（stretch）* AI 生成 `MappingSpec` 草稿

**出口：** `held_out` 集一次通过五步验收，无需回头调参。**通过后冻结 `CanonicalTrajectory v0.1` 与 `ExportProfile v0.1` 的结构。**

**明确不在 M1c 冻结的：** §6.3 的各项阈值。它们只在 20 个**已被上游预筛过**的 episode 上标定过，对全量必然偏乐观，须待 M3 全量跑完才允许冻结（§6.3）。

**不作为任何一段出口条件：** AI 生成 `MappingSpec` 草稿。

> **当前交付优先级：M-1 → M0 → M1a → M1b → M1c。** M1c 是第一个完整、可验收、可停止的交付点；M2 可视化是其后的增量，不再绑定“暑假”或其他未经估算的日期。任何排期都应在 M-1 结果和实际开发容量明确后单独制定。

### M2 可视化与人工介入

- 薄 React + R3F 单页：3D 回放 + 时间轴 + 误差曲线
- 问题区间定位与跳转
- 参数调整 + 局部重算

**出口：** 能看见、能定位到具体失败片段、能改参数重算。

> **交付边界：** M1c 交付真实数据处理、候选训练数据集与质量报告；M2 再增加三维回放和问题定位。两者不能混写成同一个带日期承诺的里程碑。

### M3 CuRobo 与规模化

- CuRobo 后端 + §4.3 碰撞球配置资产链（封装 `build_robot_model` + 溯源 + 校验 + 人工审核）
- 跨后端一致性测试扩展
- 全量 1682 episode 批处理、吞吐与缓存
- 其余容器 `Prober`（hdf5 / zarr / csv），按选定的第二个数据集的实际容器决定先后

### M4 AI 深度介入

- Coding Agent Skill + 结构化 CLI 契约（JSON 输出、错误码分类、步骤幂等）
- 自动修复：`ChangeProposal` + 有预算的候选实验 + 候选比较

### M5 广度与开源发布

- 更多机器人（借 §4.3 的配置资产链）
- Mink + MuJoCo 后端（OpenArm 的 MJCF 由官方 `openarm_mujoco` 提供，见 §11）
- 鼠标绘制 Playground
- README、样例数据、一条命令跑通的 demo、机器人适配指南、能力矩阵

---

## 13. 移出首版的内容及理由

以下均非定位要求，属于「以后要对外承诺质量时才需要的机制」。移出不影响 §1.4 九条中的任何一条。

| 内容 | 理由 | 何时回来 |
|---|---|---|
| `T0`–`T3` 认证等级、`ReleaseEvidenceManifest`、发布阻断项 | 服务「把结论卖给不认识的人」；现在用户是本人与学长 | 对外承诺质量时 |
| 四档自治挡位的权限模型 | 依赖尚不存在的冻结测试集与阈值分布 | 自动修复成熟后 |
| `ExecutionPlan`、计划修订、`RunLease`、心跳、幂等键 | 为并发与无人值守设计 | 出现真实并发需求时 |
| 完整版本对象图与状态推导（`NEEDS_RECOMPUTE` 等） | §8.2 的 run 目录已覆盖可追溯的实质 | 多人协作时 |
| 原子导出门禁、任务修订号防并发 | 单人单机不存在该竞态 | 同上 |
| 九工作区完整前端、Tauri 桌面壳 | 平台工作量大，算法价值为零；官方环境下浏览器本就是主路径 | Web 端稳定后增量添加 |
| `EvaluationPolicyVersion`、`ScoringProfile`、五分项质量评分 | 首版用一份阈值 YAML + 硬门槛函数即可 | 需要跨候选排序时 |
| 物理仿真（SAPIEN / ManiSkill / RoboTwin / RoboCasa）、`A2` / `A3` | 已在 v1 规划中移出，本文维持 | v2 |
| OpenArm 之外的第五个机器人目标 | 广度靠 §4.3 的配置资产链与社区贡献，不靠自己堆 | M5 |

**这些设计本身都不错**，它们是产品长到有多个用户、多个贡献者、要对外承诺质量之后必然需要的东西。问题只是被放进了第一个版本，而第一个版本有一个用户和一个开发者。

---

## 14. 已确认与待核实

### 14.1 已确认

#### 本轮确认（2026-08-26）

| 问题 | 结论 | 影响 |
|---|---|---|
| 视频策略 | **按跨本体惯例全部保留**，不做腕部筛选与重新渲染 | §7.3 定稿，导出模块行为确定 |
| 目标机器人 | **OpenArm 为首个正式交付目标**（产品决定；「它是双臂」不是理由，见 §11） | §11 重排；碰撞球配置链成为 M3 前置依赖 |
| 仿真接入 | **后续接入仿真是明确期望** | 提升 Mink + MuJoCo 线的价值（§5.2）；v2 选型仍待定 |
| 误差阈值 | **由本项目自行制定** | 新增 §6.3；首轮用临时值，M1 后按实测分布回填 |
| 数据来源 | 真实数据仅此一份（双臂）；**单臂缺乏，其余需自行下载开源数据集** | 新增 §10.3 测试数据获取策略与 FK 预处理工具 |

#### 补充确认（2026-08-26，对照公开数据集 `simple-world-lab/HiFi-UMI-2K`）

该数据集是 LeRobot v3.0 格式、原生 EEF 通道、CC BY 4.0 的公开无本体数据，其 `meta/info.json` 与无效帧处理可作为本工具若干约定的对照实现。据此确认四项修订：

| 问题 | 结论 | 影响 |
|---|---|---|
| `state` 与 `action` 的关系 | **`MappingSpec` 新增必填字段 `state_action_relation`** | §3.3；封堵 §2.2 发现的 gripper 语义差异导致的静默错误。（2026-08-27 修正：原方案用 `divergent_channels` 做例外表，已改为按流声明） |
| 语义无法确定的原因 | **区分 `MISSING`（有真值未记录）与 `UNDEFINED`（物理上无真值）**，前者问人、后者搜索 | §3.4 新增分类表。（2026-08-27 修正：据此把基座变换拆为 T1/T2，通用搜索移出 M1） |
| 本体化失败帧的导出 | **保留行 + 掩码标记，禁止删行**；新增 `valid.retarget` / `retarget.status` 两列 | 新增 §7.2.1；保住「只动表不动 mp4」的对齐前提 |
| `meta/stats.json` | **必须重算**，不得继承源数据集 | 新增 §7.2.2；补上 §7.2 原清单的漏项 |

同时确认一项对生态的约定：源数据集若自带机器可读语义声明块，`DataAdapter` 直接读取并标 `EXPLICIT`，不进 AI 推断路径；本工具导出的 `retarget` 段按同一粒度写出（§3.4）。

该数据集**不作为 M1 材料**：它是双臂、无源关节真值，`§10.2` 交叉校验与 `§10.3` 真实往返验证都用不上，且不填单臂缺口。定位为 M3 之后的广度案例与「无源本体」极端样本。

#### 本轮确认（2026-08-27，外部评审 + 上游事实核实）

**以下五项均已核实一手来源，不是推测。核实方式记录在此，便于日后复查是否已过期。**

| 核实项 | 来源 | 结论 | 影响 |
|---|---|---|---|
| CuRobo 是否已有碰撞球拟合 | `NVlabs/curobo` `docs/reference/sphere_fitting.rst` | **已有且完整**：`fit_spheres_to_mesh`、自动球数、`MORPHIT` 优化、8 项质量指标、`build_robot_model` 命令行、`--clip-link` | **§4.3 重写**，删除自研球拟合与「没人做」的论断；M3 工作量下降 |
| LeRobot v3 规范管到哪 | `huggingface/lerobot` `docs/source/lerobot-dataset-v3.mdx` | 只规定布局、`features` 的 shape/dtype、fps、路径模板、`stats.json`、`tasks.*`、`episodes/`。**不规定各维语义、不规定 state/action 时间关系、无掩码约定** | **§3.2 认证粒度下沉**；§3.4 修正 `state_layout` 归属 |
| `LeRobotDataset` 能否按 episode 过滤 | `src/lerobot/datasets/lerobot_dataset.py`，`__init__(..., episodes: list[int] | None = None, ...)` | **能，是一等参数** | **§7.2.1 改用「一份物理数据 + 训练白名单」**，不需要导出两份，也不需要 episode 重编号 |
| v3 元数据是否只有 `info.json` | `src/lerobot/datasets/utils.py` 的 `DEFAULT_EPISODES_PATH` / `DEFAULT_TASKS_PATH` / `DEFAULT_VIDEO_PATH` | 还有 `meta/episodes/*`（含字节与帧偏移）与 `meta/tasks.*`；**视频按 200 MB 分片，一个 mp4 常含多个 episode** | **§7.2 补两个漏项**，并禁止按文件名推断 episode |
| M0–M2 的碰撞由谁兑现 | `stephane-caron/pink` `pink/barriers/self_collision_barrier.py` 与 `examples/barriers` | Pink 有 `SelfCollisionBarrier`（基于 Pinocchio + hpp-fcl），官方有双臂示例 | **§5.1 写明**；自碰撞在 M0–M2 可兑现，环境碰撞降为 `CONDITIONAL`；碰撞对屏蔽表计入 M0 工作量 |

另有两项文档级修正与一项设计级新增：

| 项 | 结论 |
|---|---|
| 「离线优先」 | 与「AI 生成 MappingSpec」直接冲突。改为**本地/自托管优先：确定性核心离线可跑，AI 辅助为可选增强**（§1.4 第 9 条） |
| OpenArm 形态 | 官方定义是**单臂 7DOF**，双臂是配置而非本体；`openarm_description` 提供 xacro 需自行生成 URDF，且 v1.0/v2.0 两套并存；`openarm_mujoco` 已存在（§11） |
| **跨流 IK 分支耦合** | **本轮唯一的设计级新增，且是外部评审也未提出的问题。** `independent_command` 下两条流分别求 IK 会落到不同 IK 分支，产生「各自都对、放在一起矛盾」的数据，回放与误差指标全部正常。新增 §7.1.2 契约与 §6.1 检测项 |

#### 第二轮评审修订（2026-08-27，同日）

**上一轮修订自身引入或遗留的问题，由第二轮外部评审指出。三项属于语义正确性，必须修；五项属工程准确性。**

| 项 | 上一轮写的 | 问题 | 现在 |
|---|---|---|---|
| **`command_timing`** | `action_definition: target_position_same_step`，注「本数据的自然选择」 | **`independent_command` 不含任何时间信息**，同步关系是未经证实的假设。错了不报错，训练标签整体差一帧 | 新增必填字段 `command_timing`（§7.1.3），当前证据等级为 `MISSING`，按 §3.4 规则须问人；已记入 §14.2 |
| **夹爪 observation 泄漏** | 退路是「`state` 侧夹爪由 `action` 侧派生」 | **这是训练数据完整性错误**：把当前指令写进当前观测，等于把预测目标泄漏进输入，同时混淆「夹爪状态」与「夹爪指令」 | 删除该退路。改为三选一：正确映射 / **从 `observation.state` 删除该维** / 有延迟模型时用历史 action 估计并标 `synthetic`（§7.1.4） |
| **白名单验收未走训练路径** | §7.1.5 第一步是裸 `LeRobotDataset(root=...)` | 白名单只是被记录，没有机制保证使用者会用它 | 改为经 `DatasetConfig(root, episodes=allowlist)` 加载，并**新增一步断言白名单真的生效**；导出时附一份可直接运行的训练配置（§7.1.5） |
| 跨流一致性阈值 | 固定关节距离阈值 | `state` 与 `action` 本就要求不同 EEF 位姿，指令超前时关节距离**理应**不为零；固定阈值会大量误报 | 改为相对判据 `Δq_act / Δq_exp`，`Δq_exp` 由源端 EEF 位移经 `J⁺` 一阶估计；附速度可行性检查；奇异帧降级为不判定（§6.1） |
| `delta_from_state` 的 IK 次数 | 「一次」 | 增量还原成绝对 EEF 目标后仍需为它求解，是两次 | 改为两次；`J⁺` 一阶映射的单次变体标为需显式声明的近似（§7.1.1） |
| `solve_coupling: joint_solve` | 「两条流作为同一 QP 的两组任务联合求解」 | **数学上不成立。** Pink 求解的是**一个** configuration 的速度，两条流是两个不同构型，不能当作同一构型上的两组任务 | 移出 M1，标为后续候选；新增 `interleaved_sequence` 作为推荐做法（**该项已被第三轮实测否掉，见下表**）（§7.1.2） |
| 碰撞几何资产链 | 「Pink 的自碰撞也吃这条资产链的产出」 | **Pink 用 Pinocchio `GeometryModel` + 碰撞对，不读 CuRobo 的球模型。** 两者只共享 URDF/mesh | 拆成两条派生分支，各自溯源、各自 `verify`，并新增两者最小距离的交叉核对测试（§4.3） |
| OpenArm 可达性预检 | 「查源轨迹包围盒是否落在可达点云内」 | 包围盒是很弱的必要条件，证明不了姿态可达、双臂同时可达、臂间不碰、连续同分支 | 改为抽真实帧跑「位置 + 姿态 + 双臂同时 + 连续片段」IK，并在候选 T2 下各跑一遍择优（§11） |
| M0 前置核实的定性 | 「不占开发工作量」 | 生成 URDF、核对 preset、建双臂 root、跑预检是正式的 feasibility spike | **独立为 §12 `M-1 可行性闸门`**，先于 M0，出口是决策而非功能 |
| AI 生成 `MappingSpec` | M1 范围内 | 第一份数据的 spec 已知，用 AI 生成它证明不了泛化；且牵涉模型配置、结构化输出、schema 校验、无网络降级 | 保留在范围内，**明确标为 stretch goal，不作为 M1 出口条件**（§12） |

#### 第三轮修订（2026-08-27，全量数据实测后）

**前两轮把 `command_timing` 和源夹爪语义都判为「必须问人才能定」。第三轮直接对全部 20 episode / 13,746 帧做了实测，两项都解出来了。** 实测方法与数据见 §2.3。

| 项 | 前两轮 | 实测结论 | 落地 |
|---|---|---|---|
| **`command_timing`** | `MISSING`，等学长回复才能定，列为 M-1 闸门项 | `action[t] ≈ state[t+4~5]`，手臂跟踪延迟 ≈133–167 ms；夹爪 5–6 帧 ≈167–200 ms。20/20 episode 一致，EEF 空间与关节空间给出同一个 `k` | 降为 `DATA_DERIVED` + `pending_confirmation`，**不再阻塞开工**（§7.1.3、§12 M-1） |
| **源夹爪语义** | `MISSING`，M1 退路是从 `observation.state` 删掉该维 | `state_gripper ≈ 5 × action_gripper − 3`，左 R²≈0.968 右 R²≈0.942 ⇒ `aperture ≈ (state+3)/5`；证实 state 是关节角、action 是归一化指令 | 主路径改为实测仿射映射；降维退为「连 OpenArm 夹爪规格也拿不到」时的备选（§7.1.4） |
| **训练配对** | 悬而未决 | **保持同行 `observation[t] → action[t]`，`shift_policy: none`** | 4–5 帧是**物理跟踪延迟**，不是标签移位依据；明确禁止改写成 `action[t] = state[t+1]`（§7.1.3） |
| **`interleaved_sequence`** | 第二轮列为**推荐**耦合方式 | **被实测否掉。** 它隐含假设 `action[t]` 位于 `state[t]` 与 `state[t+1]` 之间；实测是 `t+4~5`，代入后交错序列成为幅度约 4.5 帧的折返锯齿轨迹 | 移出可用集，M1 采用 `warm_start_from_state`（§7.1.2） |
| **跨流一致性判据** | 相对判据 `Δq_act/Δq_exp` + 速度可行性检查（其中「`same_step` 时间隔为零」） | 同行配对 ≠ 同一物理时刻；可行性窗口应取实测跟踪延迟 4–5 帧 | 改为三层判据，**「比值大」降级为异常候选**，须与「两条流 FK 是否各自命中」联合判定（§6.1） |
| 证据等级体系 | 五级，`MISSING` 只有「问人」一条出路 | 实测结论既不是 `DERIVED`（非确定性推导）也不该是 `INFERRED_CANDIDATE`（远强于启发式） | **新增 `DATA_DERIVED` 一级**，附三条准入硬标准；`MISSING` 的处理顺序改为「查元数据 → 能测就测 → 问人升级」（§3.4） |
| §10.2 交叉校验 | 条件项，需源 URDF | 源 URDF 容易取得；且校验**必须同侧同行配对**，否则会看到 2.10 mm 系统残差并误判为 TCP/坐标系 bug | 补配对规则与误判警告；并作为跟踪延迟的第三个独立复核维度（§10.2） |

**这一轮最值得记住的一条：** `interleaved_sequence` 是一个在文档层面读起来很优雅、经两轮评审都没被质疑、却被一次全量实测直接否掉的设计。**顺序应该是先测数据再定契约，不是先写契约再找数据印证。**

#### 第四轮修订（2026-08-27，施工化评审）

**前三轮修的是「设计对不对」，这一轮修的是「这份文档能不能照着施工」。六项全部接受。**

| 项 | 问题 | 现在 |
|---|---|---|
| **M-1 / M0 循环依赖** | M-1 要跑真实数据的双臂 IK 与碰撞检查，但 Pinocchio / Pink / 碰撞几何排在 M0；且 M-1 写「建 OpenArm `GeometryModel` 供 M0 用」，而 **M0 用的是 Panda**，机器人对象对不上 | 明确三阶段代码归属：M-1 = 一次性可抛弃 harness（裸 API，不建 `RobotProfile`）；M0 = Panda 正式管线与 Panda 碰撞资产；M1 = 把 M-1 结论重新实现进正式资产链（§12） |
| **M-1 不是真闸门** | 出口只写「回答两个问题」，无量化通过标准。看到不理想结果后再定标准 = 没有闸门 | 新增**预先登记**的抽样规模、五项红黄绿判据、T2 排名规则和红灯目标重选流程；Panda 双臂仅为第一候选，也必须重跑完整闸门（§12） |
| **训练承诺过强** | 首页写「可直接用于训练的数据集」，但首版只验证加载、shape/dtype/stats/白名单、FK 回验、运动学与静态碰撞 | 全文统一为「**训练接口兼容、运动学验证通过的候选训练数据集**」，并显式声明不保证训练效果、任务成功、真机可执行性（§1.1、§1.3、§15） |
| **标定集与验收集未分开** | §6.3 写了「不得用同一批数据调参又验收」，但计划正是用同一批 20 episode 标定并验收——规则与计划自相矛盾 | 划为 `calibration` 12 ep / `held_out` 8 ep / 全量 1682 ep 结构扫描；划分须在首次批处理前固定（§6.3） |
| **M0「跨后端 FK 一致性」名不副实** | Pink 建在 Pinocchio 上，其 FK 就是 Pinocchio 的 FK；M0 阶段**没有第二个独立实现**，互比等于自己和自己比 | 拆为 §5.3.1 内部约定一致性（M0，测我们自己的封装）+ §5.3.2 **独立 golden cases**（M0，提供唯一外部参照，含打乱 joint-name 的元测试）+ §5.3.3 真跨后端（M3，CuRobo 到位后） |
| **M1 仍偏大** | 收缩后仍把「真实数据数值闭环」与「LeRobot 格式重写」捆在一个出口，任一处卡住看不到任何产物 | 拆为 **M1a 数值闭环（不导出）→ M1b 数据集闭环 → M1c 留出集验收与结构冻结**，每段各有可展示、可回退的产物（§12） |

**另外补了一条前几轮都漏的事实：** 那 20 个 episode 是上游 `episode_report_filter` 从 1682 条里按规则筛出来的（§2.2），**本身偏向质量好的样本**。在它们身上标定的阈值对全量必然偏乐观。因此 M1c 只冻结 `CanonicalTrajectory` / `ExportProfile` 的**结构**，**阈值须待 M3 全量跑完才允许冻结**（§6.3）。

**本轮未做的事：** 上游仓库版本与技术事实未重新联网复核，沿用第一至三轮的核实结果。

### 14.2 待自行核实（会实质影响排期）

**M-1 可行性闸门期间必须完成的两项（决定 M1 可行性）：**

1. **OpenArm URDF：版本选择与生成。** v1.0 还是 v2.0、哪个 preset、双臂配置的 root/躯干定义、两臂 base 相对变换、xacro→URDF 的工具链、mesh 完整性、限位是否齐全，**以及夹爪的限位、行程与开合方向**（§7.1.4 目标侧映射所需）。已核实仓库为 `enactic/openarm_description`（Apache-2.0，提供 xacro 而非现成 URDF）。
2. **OpenArm 双臂可达性预检。** 源数据 `x ∈ [0.16, 0.61]`、`z ∈ [0.57, 0.90]`、双臂 `y` 跨度约 1 m（§2.2）。做法见 §11——**抽真实帧跑「位置 + 姿态 + 双臂同时 + 连续片段」IK，不是比包围盒**。若覆盖不住，按 §12 M-1 的优先级动 T2 摆位或换目标机器人。

**待确认但不阻塞（2026-08-27 第三轮下调）：**

3. **源机器人 URDF。** 据反馈容易取得。拿到后：§10.2 交叉校验成为 M1 出口项；`§2.3` 的跟踪延迟结论获得第三个独立维度的复核；源夹爪仿射关系可升级为 `USER_CONFIRMED`。**拿不到不阻塞 M1**——夹爪已有 `DATA_DERIVED` 路径，§10.2 保持条件项。
4. **`command_timing` 的源码/负责人确认。** 已由全量实测解出（§2.3、§7.1.3），当前 `DATA_DERIVED` + `pending_confirmation`。确认动作是核对上游数据生成 / 控制代码，或问学长采集时的控制回路结构。**这是把证据等级从 `DATA_DERIVED` 升到 `USER_CONFIRMED` 的动作，不是开工前置条件。**

**其余：**

5. CuRobo `content/configs/robot/` 现成有哪些机器人配置（决定几个目标是白送的）。
6. CuRobo 当前版本对多末端 / 双臂 / 人形的支持程度。
7. 候选开源数据集中哪些**已含 EEF 通道**（可省去 FK 预处理，减少一层误差来源）。
8. 掩码列以 `bool` 注册进 v3 `features` 后，`LeRobotDataset` 加载与统计计算的实际行为（§7.2.2 已给出预期，需在 M1 实测确认）。
9. 要钉住的 `lerobot` commit（v3 尚未进稳定版，且官方文档与 main 分支在 `tasks.jsonl` / `tasks.parquet` 上已不一致，见 §3.2）。

> MuJoCo Menagerie 的覆盖情况已部分回答：OpenArm 的 MJCF 由官方 `enactic/openarm_mujoco` 提供，不必依赖 Menagerie（§11）。

### 14.3 留到实施期按证据决定

- §6.3 各项阈值的最终数值：M1 只在 `calibration` 上标记为 `provisional`；必须等 **M3 完成 1682 episode 全量批处理后**才能冻结，**含 §6.1 跨流一致性的 `Δq_act / Δq_exp` 门限**
- §7.1.4 目标侧夹爪映射：开合度分数 → OpenArm 夹爪关节值，需 M-1 取得其限位与开合方向。**源侧语义已由 §2.3 实测解出，不再待定**
- §7.1.4 仿射关系 `state ≈ 5·action − 3` 的逐帧残差分布，及据此判定的瞬态异常门限
- `solve_coupling` 已定为 `warm_start_from_state`（§7.1.2），`joint_solve` 是否值得做留待 M1 实测跨流一致性的误报率后决定
- v2 仿真选型：MuJoCo 生态（RoboCasa / robosuite）还是 SAPIEN 生态（ManiSkill / RoboTwin）
- 首批 `DataProfile` 的具体清单与其认证的数据集 revision
- 前端页面布局与视觉细节
- 项目正式名称、开源许可证

---

## 15. 一句话汇报版本

> 我们做的是具身训练数据链上缺失的那一环：把无本体的末端轨迹数据集，批量重定向成指定机器人的关节轨迹数据集，并对每一条给出可追溯的质量结论。转换复用现成求解器，价值在于三件事——**把丢失的输入语义显式补回来、把输出语义按契约定义清楚**、批量诊断与可复现谱系，以及把新机器人 / 新数据格式的接入成本压到分钟级。

> **可信边界说清楚：产出的是「训练接口兼容、运动学验证通过的候选训练数据集」。** 首版只做运动学，不碰物理仿真与真机，**不保证训练效果、任务成功率或真机可执行性**。
