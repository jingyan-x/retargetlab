# 开发主线与关键记录

整理至：2026-09-10。**文档整理已推送，用户已授权恢复开发。** 本日志记录“发生了什么、为什么改变、留下什么证据”；当前进度见 [current-status.md](current-status.md)，运行参数/哈希见 [report-index.md](report-index.md)，下一步只在 [build-checklist.md](build-checklist.md) 维护。

原 2801 行流水已按用户要求合并：删除重复测试计数、重复实现切片、过期行动指令；保留影响结论的成功、失败、语义修正和证据缺口。整理前全文与被移除的重复档案保存在 Git 提交 `ca70821`，不在文档目录再存一份副本。

## 主线概览

| 时间 | 里程碑 | 结果与影响 |
|---|---|---|
| 9 月 2–3 日 | 远端环境、OpenArm 资产、冻结数据划分与 M-1 预筛 | 可移植真实碰撞与动态夹爪资产可用；旧 identity recipe 仍 RED |
| 9 月 4 日 | 独立双 Panda 重选实验、通用基础代码 | Panda 得到有条件 YELLOW，仅为独立实验；不能代替 OpenArm |
| 9 月 4 日 | M1a/M1b 接入、回放、导出契约的代码切片 | 已有大量实现与合成验证；OpenArm 私有数据阶段出口未通过 |
| 9 月 4 日 | 用户再次确认 OpenArm-first；隔离单臂、碰撞和 frame 假设 | 旧映射失败主要不能归咎于碰撞；源到目标语义仍需核对 |
| 9 月 9 日 | MQ03 源材料加入，分离 world/tool 变换 | 源 pose、轴向与 TCP 生成偏移获得验证；旧旋转搜索族不完整 |
| 9 月 9 日 | per-side tool 与 T2 诊断 | position-only 达 95% / 90% / 同帧 85%；full-pose 单臂达 78.33% / 88.33% |
| 9 月 10 日 | 纠正接续基线，复现旧 full-pose 结果 | 复现 47/60、53/60；细化点复核被用户叫停，没有完整结果 |
| 9 月 10 日 | 资料核对与日志精简 | 建立唯一状态入口、全部 run 索引；停止继续实验 |

## 1. 远端环境与目标资产

远端工作树是源码、环境与 runs 的事实源；Windows 只查看文档镜像。依赖约束在 `env/constraints.txt`，Python 3.12、Pinocchio/Pink/OSQP 为当前 CPU 路线，LeRobot 是可选读取端依赖。

OpenArm 资产构建修复了早期生成 URDF 的三个问题：0.3 mm 碰撞占位球、绝对 mesh 路径、固定 finger。固化资产使用真实 collision mesh、相对引用和动态 prismatic/mimic；xacro 是运动学权威。当前目标上游 revision 为 `6148297241fb0402eafe2c6eed455ae4e90d4552`，完整指纹在目标 manifest 中。

正式 Profile 已实现：root 为 world，组为 openarm_left/right，EEF 均为 hand_tcp；夹爪 driver 范围 [0, 0.044] m，finger_joint2 由 mimic 得到，不作为独立控制维。SRDF 屏蔽与需要保留的 body/arm-base 碰撞对明确记录。

| 关键代码 | 用途 |
|---|---|
| `harness/m_minus_1/build_openarm_assets.py`、`assert_openarm_assets.py` | 构建与资产断言 |
| `src/retargetlab/robot/openarm.py`、`assets.py` | 正式 Profile、URDF/SRDF/mesh 哈希和关节/TCP 校验 |
| `src/retargetlab/robot/collision.py` | 碰撞策略、有限 barrier 子集与完整几何复检 |

碰撞 barrier 曾因一次放入 2680 个 Panda 碰撞对而导致 QP 失败。修正为确定性的有限 barrier 子集，保留必须检查的对，并用完整几何做最终 postcheck。减少优化约束数量不等于减少最终碰撞检查。

## 2. OpenArm 早期闸门与 Panda 对照

OpenArm 的单帧 smoke 曾通过，但注册 60 帧预筛仍失败。这确立了第一条边界：**一个诊断帧成功不能选定正式 T2，也不能替代注册样本。**

旧 `20260904-m1-openarm-006` 完成 81 候选，最佳 t2-023 nominal 30%、relaxed 35%、penetration 15%。它只否定当时的 identity 映射与候选族，不能作为此后所有 OpenArm 映射的结论。

双 Panda 使用独立资产、base/side mapping 与碰撞策略重新评估；早期反向 side mapping 的运行被废弃。修正后的 `20260904-m1-panda-002` 在完整 600 帧上记录 nominal 594/600（99.17%）、penetration 0.83%，20/20 连续段 nominal、连续段无穿透，等级为 YELLOW。该结果保留为历史重选证据，不是 OpenArm 可用性或 source frame 身份证明。

9 月 4 日用户再次确认 OpenArm-first，当前交付目标据此固定为 OpenArm；已有 Panda 代码继续作为回归夹具。相关报告分别为索引中的 OA-LEGACY-M1 与 PA-HISTORICAL。

## 3. 通用基础与 M1a/M1b 的已实现能力

以下合并原 M0、M1a.1–34、M1b 的连续代码切片。列的是已有实现及其关键约束，**不是私有数据验收完成表**；精确接口以代码与工程规划为准。

### 求解、诊断与运行溯源

| 能力 | 保留的关键行为 |
|---|---|
| 坐标与 Pose | 四元数/SE(3)/单位集中转换；有限值校验、wxyz、等价符号连续化，不以换号改变物理姿态 |
| Pink 后端 | 迭代 solve → integrate → residual 复检；固定重试种子与 warm start；局部失败不输出“证明全局不可达” |
| 双流耦合 | `warm_start_from_state`；拒绝不受支持的 joint_solve 和已被时序证据否掉的 interleaved_sequence |
| 只读诊断 | 位置、姿态、限位、连续跳变与碰撞分开；未知碰撞状态不能当安全 |
| Run | recipe/input/profile/backend/threshold 指纹绑定；禁止覆盖旧 run；失败可保留 recipe-only 的部分目录 |
| CLI / 报告 | stdout 输出结构化摘要；报告提供 JSON/Markdown/CSV/JSONL；数值制品与聚合报告分开 |

落点：`kinematics/`、`solve/`、`diagnose/`、`run/execute.py`、`run/workspace.py`、`cli/main.py`。合成往返与负例用于验证契约、算法链路；不作为目标私有数据分布上的通过率。

### 接入、审阅与 DataProfile

| 能力 | 保留的关键行为 |
|---|---|
| Parquet / metadata 清点 | schema/footer 与 info 声明分开；变长 list 的物理宽度不能靠声明猜测；外部视频不当作 Parquet 缺列 |
| MappingSpec | 按流记录 state/action、槽位、索引、单位和 frame；候选 REVIEW_REQUIRED 与可执行映射分开 |
| Review / decision | 结构兼容、未验证 shape 的显式接受、语义证据、decision 指纹逐层绑定；下游重验 |
| Bounded calibration | 明确 episode 选择与上限，先审核 lineage 再读数值；审计报告不嵌源 pose/joint 数组 |
| Coverage | 已有 20 ep / 13,746 行的元数据与结构覆盖报告；不能据此宣称所有向量宽度已验证 |
| DataProfile | dataset revision、timing、gripper、coverage 与 decision 绑定；落盘私有版本仍 REVIEW_REQUIRED，未因新 MappingSpec 自动认证 |

落点：`io/`、`contracts/mapping.py`、`contracts/profile.py`、`run/decision.py`、`run/profile.py`、`run/coverage.py`。

**时序与夹爪修正必须保留：** 最初把全部 16 个通道混算 RMSE，混入归一化夹爪指令与弧度 state，结论不适用。分开后 calibration 的 14 个臂关节最佳延迟 4 帧，两夹爪经 `5*x-3` 同单位换算后为 6 帧；最终分组报告为 SUPPORTED。它们是物理跟踪延迟，训练仍同行配对、`shift_policy:none`。state 夹爪用自身数值 `(state+3)/5` 转 aperture，不能拿 action 填 observation。

### 回放、导出与读取端

| 能力 | 保留的关键行为 |
|---|---|
| Replay lineage | canonical、Profile、recipe、各组 arm solve、gripper 引用与哈希一致；双臂必须有完整组集合 |
| 目标向量 | 按组输出 7 个 arm rad + 1 个 gripper driver m，OpenArm 共 16 维 float32；mimic 不重复导出 |
| 双流 bundle | state/action 两个独立值制品；不能用一条 action 同时冒充两条流；校验时间戳、布局与帧数 |
| 导出输入 gate | CERTIFIED Profile、完整且 shape 已验证的 coverage、allowlist、双流 replay 与 ExportProfile；当前私有 Profile 不满足 |
| 合成表写入/复验 | 写前校验引用；显式选 episode；保留非目标列与同行对齐，替换两条目标流；逐值复验检测篡改 |
| LeRobot metadata / 分片 | plan → replay binding → target-table binding → grouped shards；任务索引、episode 区间、dtype 和完整文件清单一致 |
| Mask / 统计 | 保留失败行；开头失败取首个有效目标，后续失败 carry-forward；全无效 episode 保留 FAIL；训练 allowlist 取计划与 PASS 的交集，统计仅取该视图内有效帧 |
| 视频与兼容视图 | 已验证的是 numeric/video-free 路径，PARTIAL 状态明确；源 episode ID 保留，另建显式零起点 loader view，不静默重编号 |
| 五步 acceptance | 配置绑定 → allowlist → 时间窗 → normalization batch → 两流 FK；缺运行时记 ENVIRONMENT_UNAVAILABLE，未完成检查不能记 PASSED |

落点：`export/layout.py`、`export/table.py`、`run/replay.py`、`run/export_gate.py`、`run/lerobot_export.py`、`run/lerobot_compat.py`、`run/lerobot_acceptance.py`。

仍影响后续接入的限制：
- 读取端 runtime 钉 `lerobot==0.6.1`，本机只读源码快照曾为 0.6.2，不能替代已安装的验收 runtime。
- FK acceptance 当前只支持显式 `identity_dataset_native_hypothesis`；新 separated-frame 映射接入前必须检查此边界。
- 审计报告、loader preflight/config 放在数据集 root 外，避免污染导出文件清单。
- 任务表采用 pandas-compatible named index；不伪造 PyArrow 写入端的 pandas_version。
- `valid.retarget` 为正式 mask 特征，排除于 normalization；统计、allowlist、mask 的哈希沿数据链保留。

## 4. 9 月 4 日：隔离源/目标语义与求解约束

旧 `link7 + viser_left_inverse` 假设在 60 帧上，独立单臂为 40/60、34/60；全预算双臂去碰撞后同帧成功 29/60，完整碰撞后 28/60、penetration 11.7%。这次对照只说明该假设下碰撞不是主要损失，不能推广为所有映射都无碰撞问题。

frame-lineage 检查确认目标资产、TCP 固定链和 mesh 可移植性；随后明确源 URDF 是可选交叉校验材料，其缺失不阻塞 data-only 路径。

旧严格搜索完成 24 个右手 world 轴旋转 × pose 正逆 × link7/hand_tcp，共 96 候选，没有两侧同时达到 80%。后来确认其缺少独立的 tool 右乘，所以结果仅对这个 legacy 搜索族成立。

相关代码提交：`53115ef` / `de7a8f9` / `c47919c` / `3c51df4`。具体运行目录与哈希统一在报告索引，不在日志重复列长哈希。

## 5. 9 月 9 日：MQ03 源语义与新映射基线

MQ03 是源机器人，OpenArm 是目标。源声明及历史 600 帧、state/action、左右臂 FK 交叉验证记录支持：
- pose 为 forward `base_link_T_tcp`，base 轴为前/左/上，TCP 轴为左/上/前，四元数 wxyz。
- 数据实际使用源 link 局部 +z 0.22855 m：位置平均残差约 3e-8 m，姿态约 2e-6°。
- 后续声明 0.23116 m 对该 revision 会产生固定 2.610 mm 偏差；数据已经是 TCP，两个偏移都不重复施加。

源 URDF 指纹在 MappingSpec。**独立的源 FK 数值报告未在 runs 中找到**；结论依据历史执行记录与语义文档，不能说本次重新做过该校验。

world 变换左乘位置与姿态，tool 修正右乘姿态；拆分 API 及测试已提交为 `4cb6830`。下表合并原 source-semantics-001–008：

| 探索链 | 样本 / 预算 | 关键结果 | 后续意义 |
|---|---|---|---|
| 001–002：旧 t2-023，共用工具初探及 24 个 tool 旋转 | 60 帧；120 次/1 初值 | hand_tcp 两侧各自最佳 46.67% / 70%（工具不同） | 不是当前最佳基线 |
| 003：旧 T2 网格，position-only | 同上 | t2-047：56/60 左、54/60 右、同帧独立两侧 50/60 | 找到位置覆盖较好的区域 |
| 004–005：t2-047，per-side tool 及完整预算 | 005 为 300 次/4 初值 | **47/60 左、53/60 右，即78.33% / 88.33%** | 左 axis-13、右 axis-17；左臂未过80% |
| 006–007：10 点 shortlist + 定向 tool 检查 | 60 帧；120 次/1 初值 | 无同一候选两侧 full-pose 同时过80% | 不能启动正式双臂验收 |
| 008：局部81点 position-only细化 | 同上 | **57/60 左、54/60 右、同帧51/60，即95% / 90% / 85%** | 当前有效的位置诊断基线 |

完整位姿旧最佳：相对 anchor 偏移 [0.30,-0.20,-0.10] m，yaw 0°，旧网格 t2-047。位置细化最佳：[0.25,-0.15,-0.15] m，yaw +5°，细化网格 t2-020。候选名必须绑定 run；两个网格的同名 ID 不等价。

**85% 的口径是未约束姿态、移除碰撞对后的同帧独立两侧成功。** 它不是同一联合构型、完整位姿、真实碰撞与连续性通过率。006 报告的 joint_nominal_rate 是两臂率的较小值，也不是实测双臂相交率。per-side tool 只是数据推导候选，不证明物理工具 frame。

这段后续实验当时有报告，但追加日志失败；9 月 10 日核对原报告后补登。因此不能只从当时已提交的日志判断完整进度。

## 6. 9 月 10 日：纠正接续、复现与暂停

本轮最初漏查上述未归档后续报告，从旧共用 tool / t2-023 接续，产生低分旁路实验。用户提醒后恢复原基线。这是接续错误，不是此前高分结果失效。

| 本轮 run 尾号 | 结果 | 保留用途 |
|---|---|---|
| separated-frames-001 | 居中七点，均未通过单臂双侧门槛 | 旁路对照，不覆盖9月9日结果 |
| 002 | 居中完整预算15% / 15%；target-only FK对照恢复11/12、12/12 | 前者是映射对照，后者仅验证求解链路 |
| 003 | 旧t2-023共用tool完整预算63.33% / 38.33% | 旁路对照，不作当前最佳 |
| 004 / restored-t2-047 | **完整位姿47/60、53/60，与旧结果一致** | 当前已复现基线 |
| 004 / refined-t2-020 | 用户要求停止，SIGINT中断，无完整报告 | 未完成，不推测成功率 |

本轮 runner 会核对目标 hand_tcp 固定链、分开 world/tool、只评估冻结60帧并输出聚合结果；它和对应测试在暂停时是未提交WIP，当时整理未改其实现；恢复后已审阅提交，见下节。004 的 stop-receipt 明确记录1/2候选完成，是事后审计回执而非原始solver日志。

OpenArm 左右局部手结构相同：link7→hand_tcp 沿+z 0.1801 m、零固定旋转，开合轴±y。源参考点是TCP时，直接把link7放到同一目标位置会改变任务点；若改目标frame必须换算偏移。局部结构相同也不自动证明跨机器人功能轴必须使用同一修正矩阵。

## 7. 9 月 10 日归档后恢复：单臂门槛通过，双臂预筛仍RED

文档整理提交ca70821/4cf7b77已推送。诊断runner/tests经审阅后提交d51cc8c/a96085a：执行前核验数据/资产/split指纹，区分独立两侧相交率；双臂模式必须绑定通过的单臂报告及原recipe，禁止换候选、映射、样本、容差或预算借用通过结果。

| Run / 证据 | 本次实际结果 | 结论 |
|---|---|---|
| separated-frames-005 / OA-POSE-PASS | refined-t2-020，60帧、300次/4初值；左49/60、右50/60；同帧独立相交40/60 | 首次两侧full-pose均过80% |
| separated-frames-006 / OA-BIMANUAL | 同一候选与预算，双臂联合40/60 nominal；碰撞0、越界0；20帧RESIDUAL_TOO_HIGH | 双臂80%门槛未过，不启动更大样本/连续段评估 |

几何补充审计确认23个碰撞对象、SRDF后236对完整后检、16对barrier子集；复制并清空求解几何不会清空后检几何。后检使用布尔碰撞判定，minimum_distance=null表示未计算距离裕度，不能误报为测得无限安全间隙。

两个新run都有独立recipe、执行回执、日志和完整报告；005继承004中断候选，未覆盖旧记录。工具映射仍为数据推导候选。下一步在固定候选下定位20帧残差失败，具体任务只维护在施工清单。

## 8. 固定候选归因与有界对照

新增聚合残差诊断（25728af/c76c076），不保存原始pose或q：分离位置阶段与最终两侧残差，统计距臂关节限位1%以内的活动，并记录失败侧平均世界位置误差方向。007/010保持求解行为不变，均复现40/60。

| 发现/对照 | 结果与决定 |
|---|---|
| 20帧归因 | 9帧位置阶段未达标；11帧位置达标后full-pose失败。最终左单侧9、右单侧9、双侧2；失败最小关节余量中位数接近0 |
| 008直接full-pose | 49/60、50/60、独立相交40/60，无改善；不把阶段顺序认定为根因 |
| 009初值4→16 | 同上，无改善；停止增加该预算 |
| 010/011有向摆位对照 | 两臂聚合残差主要−x/+y；沿该方向30mm后51/60、49/60、相交40/60，反向48/60、50/60、相交39/60；不继续放大，不替换联合基线 |

上述结果支持检查完整位姿、工具对应与受限工作空间的匹配，但不证明全局无解。当前联合基线仍为40/60、碰撞/越界0；新T2只有单臂诊断，不冒充联合验证。全部对照独立recipe/日志/回执，未改变5mm/2°容差，未读held-out，未扩展600帧。工具功能轴与下一轮完整位姿T2校准进入施工清单。

## 8b. 功能轴与适配边界诊断（012–015）

回应“数据是否本身不适配OpenArm”：新增URDF保守腕点界和共同平移最小包围球上下界。固定摆位下数值工具族5/60、保持+z族6/60帧可证不可达；共同平移可将两族全部腕点容纳于外包球，所以没有得到任意摆位全局不适配证明。外包球不检查关节限位、碰撞或连续性。

资产审计发现旧数值工具矩阵将伸出轴偏转90°，此前66.67%不能认证源抓取功能复现。源开合轴按用户答复保留UNCONFIRMED。按+z族外包界拟合提出的共同平移，0/90/180/270四roll完整位姿探针的独立相交分别0/0/2/0帧（各60帧），均未过双侧门槛，无联合验证；这里只否定所测候选。

014在最后候选发生局部QP异常，保留FAILED与三份完整报告。单臂诊断现仅捕获NoSolutionFound、保留有限残差并允许原有初值重试；015独立recipe完成270度。新增数学界、roll不变性和异常重试测试，完整套件155 passed / 1 skipped（LeRobot未安装）。没有放宽容差、扩展600帧、访问held-out或导出训练数据。详细参数/文件指纹见报告索引；下一步集中见施工清单。

## 9. 必要验证记录与未闭合证据

| 检查 | 已记录结果 | 解释 |
|---|---|---|
| 双目标资产回归（历史 M1b.3o） | 121 passed，无资产相关 skip | 当时OpenArm/Panda资产链回归，不是私有数据验收 |
| 恢复后完整套件 | 155 passed / 1 skipped | 两资产均启用，唯一skip为未安装LeRobot |
| 恢复后 world/tool 与 gate 测试 | 19 passed | 代码约束验证，不是轨迹通过率 |
| 资料整理 | 37个run、429个文件、140份日志；指纹与关键指标核对通过 | 原始运行产物保留，未重新执行实验 |

必须保留的缺口：
1. 源FK独立报告、部分旧诊断独立recipe和原始日志缺失；用报告basis/override及历史记录解释，不补造原日志。
2. 早期规划记录过全部20ep的数值分析；后续run的held_out=false不能证明其历史上完全未被使用。M1c前需按已有记录审计独立性。
3. 目标功能轴配对仍是候选；新映射双臂预筛未达标，连续性与私有M1a/M1b/M1c出口未完成。本候选布尔碰撞后检为零，不代表全部后续轨迹无碰撞。
4. 可选LeRobot runtime未安装，新映射的读取端FK验收支持也未闭合。

## 日志维护规则

每条记录只保留：**问题/决定 → 实际变化 → 有意义的证据 → 结论与限制**。

- 同一功能连续小改合成一条，保留最终行为及改变结论的失败原因；普通提交细节留在Git。
- 测试只记录里程碑结果、失败修复和未覆盖范围；不重复每次“多一个测试通过”。
- run参数、候选明细和完整哈希集中在报告索引/原报告；日志引用ID，不复制整份报告。
- 失败与中断若影响主线必须保留；不因为低分就删除。当前下一步只写施工清单。
- 可合并改写旧日志，但不能改变原实验含义；重要纠错标明发生/补登日期，原文从Git追溯。
