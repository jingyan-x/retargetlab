# retargetlab 细化工程规划 v1.2

> **本文定位：** 把 [`product-plan-v2.md`](./product-plan-v2.md)（**产品基线，管「做什么、为什么」**）翻译成可以直接开写的代码结构、接口契约和任务清单（**管「怎么写、写在哪、写完怎么算过」**）。
>
> **本文不改变产品范围。** 与基线冲突处一律以基线为准；本文新定的实现决策集中在 §9，凡涉及对外语义的都要回写基线 §14.1。
>
> **日常推进照** [`build-checklist.md`](./build-checklist.md)**。** 那是勾选清单，本文是设计依据；两者冲突时以本文为准，并同步修清单。
>
> **施工覆盖范围：M-1 → M0 → M1a → M1b → M1c。** 本文足以指导首个完整交付点 M1c；M2–M5 只保留产品路线，到达对应阶段前另写工程规划，避免现在过度设计。
>
> 生效日期 2026-09-02，基于基线第七轮 remote-first 收口。

> **当前执行覆盖（2026-09-04）：OpenArm-first。** 这是用户确认的执行
> 顺序：先完成 OpenArm 的 M-1 语义/约束闸门与正式数值闭环；Panda 仅作
> 历史重选证据和后续回归夹具。文中原有的 “M0 Panda → M1 OpenArm”
> 分层是设计演进记录，不能覆盖当前工作区的目标选择。当前停止点和证据
> 以 `docs/development-log.md` 及 `docs/m1-004-frame-semantics-blocker.md`
> 为准。

---

## 1. 环境与依赖

### 1.1 目标环境（已实测确定）

| 项 | 决定 | 依据 |
|---|---|---|
| 主开发环境 | **实验室远程 Linux 主机**，通过本机 SSH alias / Remote-SSH 进入；alias、主机地址和账号不进 Git | 2026-09-02 已实测连通，Ubuntu 20.04.6；后续源码、env、测试和 run 都在远端执行 |
| Windows 角色 | 编辑器/SSH 客户端/文档查看，不运行项目 Python，不保留第二个活跃工作树 | 避免 Windows、WSL、远端三份代码漂移；迁移后远端工作树是唯一开发现场 |
| Python | 远端 conda env **Python 3.12**；不使用系统 Python 3.8 | `lerobot==0.6.1` 要求 `>=3.12`；`pin` 有 cp312 manylinux wheel；远端 conda 已实测可用，真实安装路径不进 Git |
| 包管理 | conda 只建 Python 3.12 env，env 内一律用 pip + constraints 安装 | Pinocchio 有 pip wheel，不必混用 conda-forge 包解析 |
| 计算资源 | 已实测 **64 CPU / 2× RTX 4090 24 GB**；M-1–M1 仍按纯 CPU 编写 | 不能因为有 GPU 就提前引入 CuRobo；GPU 保留给 M3 |
| 存储 | 项目、私有输入和 run 分开；`RETARGETLAB_REMOTE_ROOT` 指向经确认的远端数据盘目录，不落根 overlay | 根 overlay 已使用 95%、仅余约 206 GB；远端另有 TB 级数据盘。`doctor` 必须检查可写与剩余空间，绝对路径只进 gitignored 本地配置 |

### 1.1.1 一次性迁移规则

当前仓库没有 Git remote，且有尚未提交的规划改动。进入代码开发前只做一次迁移：

1. 本地补 `.gitignore` / `.gitattributes`，提交现行规划基线；
2. 用 **Git bundle 或后续明确选定的私有 Git remote** 把已提交历史送到远端，再在 `RETARGETLAB_REMOTE_ROOT` 下 clone；不得用文件夹拖拽制造无历史副本；
3. 私有数据、内部路径、本地配置、run 和导出物不进 bundle；
4. 迁移完成后只在远端工作树开发，Windows 本地仓库转为只读备份；
5. 20 ep 私有样本若不在远端，必须先确认其允许进入实验室主机，再单独放入 gitignored 数据目录。**“项目代码迁移到远端”不自动授权“公司数据复制到远端”。**
6. OpenArm 的 Apache-2.0 源资产不依赖本地旧工作区：远端按钉住的上游 revision 获取，再应用仓库内可审计的 portability patch；最终固化产物记录 source/patch/output 三层哈希。

### 1.2 依赖分层

**核心不许 import `lerobot`。** 这是硬约束，不是风格偏好：`lerobot==0.6.1` 有 222 个依赖，包含 `torch>=2.7`、`torchvision`、`gymnasium`、`opencv`，装完数 GB。基线 §1.6 写的是「装得上 > 功能多，首次运行不应要求 CUDA」——把它放进核心会直接违反。

```
[core]      numpy, scipy, pyarrow, pydantic>=2, pyyaml, typer, rich
            → contracts / io / diagnose / run / cli 全部只依赖这一层
[solver]    pin (Pinocchio), pin-pink, qpsolvers[osqp]
            → kinematics / solve / robot
[lerobot]   lerobot==0.6.1
            → 只有 export/acceptance.py 与 tools/ 用；import 失败要给出可读错误，不是 ImportError 堆栈
[viz]       matplotlib（M0 静态图）；React/R3F 前端在 M2 独立管理
[dev]       pytest, pytest-cov, ruff, mypy
```

安装形态：`pip install -e ".[solver,dev]"` 是开发默认；`pip install -e ".[solver,lerobot,dev]"` 才能跑 M1b 的出口验收。

**为什么导出模块本身不进 `[lerobot]`：** 保持格式的重写（§7.2）**只需要 `pyarrow`**——写 parquet、复制 mp4、改 JSON。真正需要 `lerobot` 的只有「用官方读取端把导出物再读一遍」这件事，也就是 §7.1.5 的五步验收。把这条线分开，核心用户不装 torch 也能完整导出。

### 1.3 版本钉法

`env/constraints.txt` 钉死全部直接依赖的精确版本，`pyproject.toml` 只写下界。`doctor` 命令打印实际装到的版本并与 constraints 比对。

已确定的关键钉子：

```
lerobot==0.6.1          # v3 已进稳定版（2026-08-03 发布），不再需要钉 commit
                        # DEFAULT_TASKS_PATH = "meta/tasks.parquet"，.jsonl 已降为 LEGACY
pin==4.1.0              # Pinocchio
pin-pink==4.3.0         # Pink
qpsolvers==4.13.0       # 明确只选 OSQP，不在运行时漂移 solver
osqp==1.1.3
```

`Recipe` 必须记录 `qp_solver: osqp` 及其容差、最大迭代数与 warm-start 设置。不得写成 `quadprog|osqp` 让安装环境自行决定；同一轨迹换 QP solver 后不再是同一个可复现 run。

---

## 2. 仓库骨架

代码与现有 `docs/` 同仓。`projects/` 是本地工作区，进 `.gitignore`。

```
.
├── pyproject.toml                    包名 retargetlab，CLI 入口 retargetlab
├── LICENSE                           Apache-2.0（与 lerobot / pink / openarm_description 一致）
├── README.md
├── env/
│   ├── environment.yml               conda: python=3.12
│   └── constraints.txt               全部直接依赖的精确版本
├── docs/                             ← 现有规划文档
├── src/retargetlab/
│   ├── contracts/                    纯数据契约，只依赖 pydantic/numpy，任何后端都不 import
│   │   ├── evidence.py               EvidenceLevel、Provenance、SemanticField
│   │   ├── canonical.py              CanonicalTrajectory v0.1
│   │   ├── mapping_spec.py           MappingSpec（按流声明）
│   │   ├── export_profile.py         ExportProfile
│   │   ├── robot_profile.py          RobotProfile、KinematicGroup、Capabilities
│   │   ├── threshold.py              Threshold（带来源与冻结状态）
│   │   ├── diagnostics.py            FrameDiagnostics / EpisodeReport / DatasetReport
│   │   └── recipe.py                 Recipe / RunManifest
│   ├── io/
│   │   ├── probe/
│   │   │   ├── base.py               StructureManifest、Prober 协议
│   │   │   └── parquet_prober.py     M1a 唯一实现
│   │   ├── storage/
│   │   │   └── lerobot_v3.py         读 + 写，只用 pyarrow
│   │   └── normalize.py              源 + MappingSpec → CanonicalTrajectory
│   ├── robot/
│   │   ├── assets.py                 URDF 哈希、mesh 路径解析、派生产物过期检查
│   │   ├── profile_io.py             RobotProfile 加载与校验
│   │   └── collision.py              GeometryModel、碰撞对、SRDF 屏蔽表
│   ├── kinematics/
│   │   ├── transforms.py             ★ 唯一的四元数/SE3/单位转换出入口
│   │   ├── base.py                   KinematicsBackend 协议 + Capabilities
│   │   ├── pinocchio_backend.py      FK / Jacobian / 距离
│   │   ├── pink_backend.py           IK
│   │   └── registry.py
│   ├── solve/
│   │   ├── sequence.py               连续求解、warm start、失败重试
│   │   └── coupling.py               solve_coupling 的四种取值
│   ├── diagnose/
│   │   ├── thresholds.py             阈值加载与来源标注
│   │   ├── frame_checks.py
│   │   ├── cross_stream.py           §6.1 三层判据
│   │   └── episode_rules.py          PASS / WARN / FAIL
│   ├── export/
│   │   ├── layout.py                 目标向量布局（§9.1）
│   │   ├── lerobot_v3_writer.py      保持格式重写，只用 pyarrow
│   │   ├── stats.py                  stats.json 重算
│   │   ├── mask.py                   valid.retarget / retarget.status
│   │   ├── training_config.py        产出可直接运行的训练配置
│   │   └── acceptance.py             ★ 五步出口验收，唯一 import lerobot 的模块
│   ├── run/
│   │   ├── workspace.py              project/ 目录读写
│   │   ├── fingerprint.py            recipe 哈希与可复现性
│   │   └── report.py                 report.json / .md / .csv
│   └── cli/
│       ├── main.py                   typer app
│       └── commands/                 一命令一文件
├── harness/m_minus_1/                ★ 一次性可抛弃 harness，不被 src/ 引用，CI 不跑
├── tools/                            非产品脚本（§10.3 的 FK 预处理等）
├── assets/
│   ├── robots/panda/                 M0
│   ├── robots/openarm_bimanual/      M1
│   └── golden/                       §5.3.2 golden cases（JSON）
├── tests/
│   ├── unit/
│   ├── contract/                     golden cases + 元测试
│   ├── synthetic/                    §10.1 合成往返 + 10 项负例
│   └── fixtures/                     仅合成/公开夹具（≤ 数 MB，可进 git）
└── projects/                         本地工作区，gitignore
    └── private-sample-openarm/{source,robots,runs}/
```

**三条目录纪律：**

1. **`contracts/` 不许 import 任何求解后端。** 它要能在没装 `pin` 的机器上被读取和校验——这是「装得上」的第一道保障，也让契约测试跑得飞快。
2. **`harness/` 与 `src/` 单向隔离。** 基线 §12 明写 M-1 是用完即弃的 harness。物理隔离才防得住「反正能用就搬进去」——M1 要的是**重新实现**，不是搬运。
3. **`assets/golden/` 里的数值不许由本项目的代码生成。** 它们是外部参照（厂商 DH、官方文档、手推），自己算自己对是没有意义的（基线 §5.3.2）。来源要写在每个 case 的 `source` 字段里。
4. **公司数据永远不进 Git。** 现有 20 ep 只允许从本地私有路径读取；不得复制 parquet、视频、真实帧、内部服务器路径或可识别任务内容到 `tests/fixtures`、文档示例和 CI artifact。CI 的真实形状夹具必须由 schema 合成，公开 demo 另选可再分发数据。

---

## 3. 核心数据契约

全部用 pydantic v2 建模，可 YAML/JSON 双向序列化。以下给字段骨架，不是完整定义。

### 3.1 证据等级（贯穿全部语义字段）

```python
class EvidenceLevel(StrEnum):
    EXPLICIT = "EXPLICIT"                      # 可自动进流程
    ADAPTER_CERTIFIED = "ADAPTER_CERTIFIED"    # 可
    DERIVED = "DERIVED"                        # 可
    DATA_DERIVED = "DATA_DERIVED"              # 可，但必须声明证据范围与限制
    INFERRED_CANDIDATE = "INFERRED_CANDIDATE"  # ✗ 仅草稿与预览
    USER_CONFIRMED = "USER_CONFIRMED"          # 可
    MISSING = "MISSING"                        # 真值存在但未记录
    UNDEFINED = "UNDEFINED"                    # 物理上无真值

class SemanticField[T](BaseModel):
    value: T
    evidence: EvidenceLevel
    provenance: str                            # 一句话说清怎么来的
    evidence_scope: str | None = None            # DATA_DERIVED 必填
    limitations: list[str] | None = None           # DATA_DERIVED 必填，允许显式传 []
    corroboration: list[str] = Field(default_factory=list)  # 例如 LOCAL_CODE_CORROBORATED
    pending_confirmation: str | None = None      # 可选，不得成为隐式阻塞项
    confidence: float | None = None             # 仅 INFERRED_CANDIDATE 用
```

**这个类型是基线 §3.4 的执行机制。** 语义值和它的证据等级绑在同一个对象里，就不可能出现「记了等级但用的时候忘了看」。`normalize` 的准入检查是一个函数：遍历所有 `SemanticField`，凡 `INFERRED_CANDIDATE` 或 `MISSING` 一律拒绝进正式流程，`DATA_DERIVED` 缺 `evidence_scope` 或 `limitations` 字段也拒绝。`pending_confirmation` 只是 provenance 提醒，不改变准入结果。

### 3.2 CanonicalTrajectory v0.1

```python
class MotionGroupTrajectory(BaseModel):
    name: str                        # left_arm / right_arm
    position: NDArray                # (N, 3) 米
    orientation: NDArray             # (N, 4) 四元数 wxyz，已符号连续化
    gripper: NDArray | None          # (N,) 开合度分数 ∈ [0,1]
    tool_point: Literal["flange", "tcp"]
    tcp_provenance: TcpProvenance

class Stream(BaseModel):
    name: str                        # observation_state / action
    role: Literal["robot_state", "command"]
    groups: dict[str, MotionGroupTrajectory]

class CanonicalTrajectory(BaseModel):
    schema_version: Literal["0.1"]
    source: SourceRef                # dataset_id, revision, episode_index, sha256
    coordinate: CoordinateSemantics  # source_frame(SemanticField), handedness, trajectory_mode
    timing: TimingSemantics          # fps, timestamps, command_timing
    streams: dict[str, Stream]       # ★ 顶层是流，与 MappingSpec 同构
    passthrough: dict[str, Any]
    reference: dict[str, ReferenceChannel]
    provenance: Provenance
```

**`streams` 作为顶层结构是基线 §3.3 的结论落到代码里。** 早期草稿只映射了 `action`，在这个结构下写不出来——漏掉一条流会是类型错误，不是运行时的静默错误。

### 3.3 Threshold：阈值不是裸 float

```python
class ThresholdSource(StrEnum):
    SOLVER = "solver"      # 由后端实测收敛能力决定，跨后端取严
    ROBOT = "robot"        # 从 RobotProfile 换算，不跨机器人统一
    TASK = "task"          # 使用方设定，无输入时用保守默认

class Threshold(BaseModel):
    warn: float
    fail: float
    unit: str
    source: ThresholdSource
    provenance: str
    status: Literal["provisional", "sample_validated", "frozen"] = "provisional"
    calibrated_on: str | None = None
    validation_scope: str | None = None # 例如 "private-sample-20/calibration@<hash>"
    limitations: list[str] = Field(default_factory=list)
```

基线 §6.3 第一条原则是「阈值必须注明来源，不能是拍脑袋的数字」。做成类型之后，写不出来源的阈值构造不出来。现有私有样本只有 20 ep，M1c 只能把阈值标成 `sample_validated`，并把覆盖限制写进 `limitations`；**不得等待或暗示未来会取得公司全量数据，也不得把它升级为“全分布已冻结”。** `frozen` 只用于将来在一份有权访问、可明确描述验证范围的数据集上重新校准后的版本。CI 断言 `sample_validated` / `frozen` 都必须有 `calibrated_on` 与 `validation_scope`。

### 3.4 其余契约

| 契约 | 关键字段 | 冻结时点 |
|---|---|---|
| `MappingSpec` | 严格对齐基线 §3.3 的 YAML 结构 | 随 `DataProfile` 认证到 dataset revision |
| `RobotProfile` | assets(含 URDF sha256) / motion_groups / end_effectors / limits / locked_joints / backend_configs(含来源哈希) / capabilities | M1c 冻结结构 |
| `ExportProfile` | stream→列映射 / solve_coupling / command_timing / gripper_mapping / **target_layout（§9.1）** / normalization_exclude | M1c 冻结结构 |
| `Recipe` | 输入哈希 / robot 版本 / 后端与版本 / 参数 / 随机种子 / 数据划分 / 阈值集 | 每 run 一份，不可变 |

---

## 4. 模块接口

### 4.1 KinematicsBackend：照最弱的后端设计

```python
class Capabilities(BaseModel):
    batch_targets: bool = False
    world_collision: bool = False
    self_collision_barrier: bool = False
    multi_group_joint_solve: bool = False

class KinematicsBackend(Protocol):
    name: str
    version: str
    @property
    def capabilities(self) -> Capabilities: ...

    def load(self, profile: RobotProfile) -> None: ...
    def fk(self, group: str, q: NDArray) -> tuple[NDArray, NDArray]:
        """(M, nq) -> (position (M,3), quaternion wxyz (M,4))"""
    def jacobian(self, group: str, q: NDArray) -> NDArray: ...
    def solve_frame(self, group: str, target: Pose, seed: NDArray,
                    opts: SolveOptions) -> IKResult: ...
    def solve_sequence(self, group: str, targets: PoseSequence, seed: NDArray,
                       opts: SolveOptions) -> IKSequenceResult: ...
    def min_distance(self, q: NDArray) -> DistanceReport | None:
        """不支持时返回 None，不抛异常"""
```

`SolveOptions` 不再只引用不定义。M-1 先用下列最小字段集；M0 提升为正式 pydantic 契约，字段名和单位不变：

```python
class SolveOptions(BaseModel):
    qp_solver: Literal["osqp"] = "osqp"
    integration_dt_s: float = 0.01
    max_iterations: int = 300
    position_tolerance_m: float = 0.005
    orientation_tolerance_rad: float = 0.034906585  # 2 deg
    damping: float = 1e-12
    position_cost: float = 1.0
    orientation_cost: float = 1.0
    qp_eps_abs: float = 1e-5
    qp_eps_rel: float = 1e-5
    qp_max_iterations: int = 4000
    qp_polish: bool = True
    no_progress_window: int = 20
    no_progress_min_delta: float = 1e-6
    retry_seed_count: int = 3
    random_seed: int = 20260902
    enforce_configuration_limits: bool = True
    enable_self_collision_barrier: bool = True
```

这些是 **M-1 feasibility 的预登记默认值，不是产品最终精度**。任何改动都要生成新 recipe/run，旧结果不改写。`integration_dt_s` 只是 Pink 速度积分步长，不是数据帧率；`qp_max_iterations` 是单次 OSQP 上限，`max_iterations` 是外层 Pink 积分上限，不得混为一个字段。no-progress 监控量固定为 `max(position_error/position_tolerance, orientation_error/orientation_tolerance)`，连续 20 次下降不足 `1e-6` 就提前停止并报告 `RESIDUAL_TOO_HIGH`。三次总尝试的种子固定：孤立帧用 neutral + 两个由 `random_seed` 生成的低差异种子；连续片段用上一帧解替换 neutral，另两个种子不变。

Pink 是局部微分 IK：单次调用给出切空间速度，本项目的 `solve_frame` 必须显式实现“设置任务目标 → 求速度 → 积分配置 → 复算残差”的闭环，终止条件由 `SolveOptions` 给出。`IKResult` 只报告后端**实际观察到的**状态：

```python
class IKStatus(StrEnum):
    CONVERGED = "CONVERGED"
    MAX_ITER = "MAX_ITER"
    QP_FAILED = "QP_FAILED"
    LIMIT_VIOLATION = "LIMIT_VIOLATION"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    RESIDUAL_TOO_HIGH = "RESIDUAL_TOO_HIGH"
```

同时必须返回 `iterations`、位置/姿态末残差、终止原因和实际 solver。**Pink 不能证明“真不可达”，也不能可靠地把局部最优直接分类成 `INFEASIBLE`。** “不可达候选”由诊断层在固定的多种子/重试预算全部失败后生成，仍不得写成物理真值。

**上层查 `capabilities`，不写 `try/except`。** 基线 §4.2 的原话，落到这里就是：`solve/sequence.py` 里不许出现对具体后端名字的分支判断。

### 4.2 求解流水线

```python
# solve/sequence.py
def solve_stream(traj: CanonicalTrajectory, stream: str, group: str,
                 backend: KinematicsBackend, profile: RobotProfile,
                 opts: SolveOptions, seeds: NDArray | None) -> StreamSolution

# solve/coupling.py
def solve_coupled(traj, group, backend, profile, opts,
                  coupling: SolveCoupling) -> dict[str, StreamSolution]
```

`solve_coupled` 是唯一知道「两条流之间有关系」的地方；`solve_stream` 只管一条流，不知道另一条存在。这样 `independent` / `warm_start_from_state` 的差异收敛在一个 40 行的函数里，也让 §9.2 那个容易搞错的顺序只有一处实现。

### 4.3 诊断

```python
def diagnose_episode(traj, solutions, profile, backend,
                     thresholds: ThresholdSet) -> EpisodeReport
```

诊断**只读**，不改任何解——基线 §6 首版只检测不修复。签名里没有返回修改后轨迹的位置，是刻意的。

跨流一致性单独成模块，因为它是三层判据、且返回的是**候选**而非判决：

```python
# diagnose/cross_stream.py
def cross_stream_candidates(...) -> list[BranchConflictCandidate]
def adjudicate(candidates, frame_diags) -> list[BranchConflictFinding]
```

两个函数分开，对应基线 §6.1「异常候选生成器 + 联合判定」。合成一个函数会诱使人把比值门限当判决用——那正是清单里第 3 条常犯错误。

---

## 5. CLI 契约

```
retargetlab doctor                             环境、依赖版本、资产、写入权限
retargetlab inspect      <dataset>             Prober 结构清单 → JSON
retargetlab validate-input <dataset> --spec    MappingSpec 与实际结构是否吻合
retargetlab normalize    <dataset> --spec      → CanonicalTrajectory
retargetlab solve        --recipe              → q(t) + FK 复算
retargetlab diagnose     --run                 → metrics.jsonl + report.json
retargetlab export       --run --profile       → 数据集 + 训练配置
retargetlab verify-export --run                五步出口验收（需 [lerobot]）
retargetlab robot-config {build,verify,review} 资产链（build/verify 进 M0，CuRobo 部分到 M3）
```

**统一规则：**

- `--json` 输出结构化结果到 stdout，人读的进度与日志一律走 stderr。Agent 接入（M4）靠这一条，现在就要守住。
- 退出码分类：`0` 成功 / `2` 用法错 / `3` 语义或校验不通过（**需要人**）/ `4` 质量闸门未过（有 `FAIL` episode）/ `5` 环境或依赖缺失 / `1` 其他异常。**`3` 和 `4` 必须分开**——前者是「你的配置有问题」，后者是「配置没问题但数据没过」，处理方式完全不同。
- 每个命令幂等：同 recipe 重跑写新 run 目录，不覆盖旧的。

---

## 6. 工作区与 run 目录

严格照基线 §8.2，不加对象图：

```
projects/private-sample-openarm/
  source/<dataset-sha256>/         只读引用 + 哈希 + mapping_spec.yaml
  robots/openarm_bimanual/
    profile.yaml                   RobotProfile
    urdf/                          固化的 URDF + mesh（相对路径）
    derived/                       派生配置，各带来源 URDF 哈希
  splits.yaml                      ★ calibration / held_out 划分，一次写定不再改
  runs/20260901-001/
    recipe.yaml  export_profile.yaml  thresholds.yaml
    result/  metrics.jsonl  report.json  report.md  export/
```

`splits.yaml` 单独提到 project 层而不是每个 run 各写一份——它必须是**全局唯一且不可变**的。放进 run 里等于允许每次运行换一个划分，那 `held_out` 就没有意义了。加一条启动检查：run 的 recipe 引用的 splits 哈希与 project 层的不一致就拒绝执行。

本项目第一次划分直接冻结为下列值；选择只依据均匀抽样后的 episode 序号，不看任何运动或质量指标：

```yaml
dataset_alias: private-sample-20
calibration:
  episode_index:        [0, 1, 3, 5, 6, 8, 10, 11, 13, 15, 16, 18]
  source_episode_index: [0, 87, 263, 438, 526, 701, 876, 964, 1139, 1315, 1402, 1578]
held_out:
  episode_index:        [2, 4, 7, 9, 12, 14, 17, 19]
  source_episode_index: [175, 350, 613, 789, 1052, 1227, 1490, 1666]
```

写文件时再附 `info.json`、episode 元数据与主 parquet 的哈希。`held_out` 内容在 M1c 前不进入 inspect/plot/统计；只允许读取上面已经公开在 split 文件里的索引。

---

## 7. 测试与 CI

| 层 | 位置 | 依赖 | 何时跑 | 预算 |
|---|---|---|---|---|
| 契约与单元 | `tests/unit`、`tests/contract` | 仅 core | 每次提交 | < 30 s |
| golden cases | `tests/contract` | solver | 每次提交 | < 1 min |
| 合成往返 + 10 负例 | `tests/synthetic` | solver | 每次提交 | < 5 min |
| 真实数据回归 | 本地，不进 CI | solver + 数据 | 每段里程碑 | 分钟级 |
| 导出验收 | `tests/` 打 `@pytest.mark.lerobot` | + lerobot | 手动 / nightly | 分钟级 |

CI（GitHub Actions，ubuntu-latest，Python 3.12）跑前三层。`lerobot` 那层不进默认 CI——装 torch 会让每次 CI 多几分钟且经常超时，而它检验的东西每段里程碑跑一次就够。

**两条必须有的元测试：**

1. **打乱 joint-name 顺序的负例必须被检出**（基线 §5.3.2）。一组永远通过的测试和没有测试等价。
2. **OpenArm 资产元测试**：断言加载的 URDF 无半径 < 1 mm 的 collision 球、无绝对 mesh 路径、所有 collision mesh 可解析；左右 `finger_joint1` 为 `prismatic`、`finger_joint2` 正确 mimic、开闭端点确实改变两指间距。现成生成 URDF 同时存在占位球和把 finger 固定化的问题，任何一个漏检都会制造假绿灯。

---

## 8. 任务分解

工作量是**粗估**，单位为人日，用于排序而非承诺。依赖列写的是必须先完成的任务号。

### M-1 可行性闸门（harness，用完即弃）

| # | 任务 | 产出 | 依赖 | 估 |
|---|---|---|---|---|
| M-1.0 | 按 §1.1.1 把已提交 Git 历史迁到远端数据盘，固定唯一工作树；检查私有样本远端授权/位置 | 远端 clone + gitignored 本地配置 | — | 0.5 |
| M-1.1 | 远端 conda env + 依赖装通 + harness 环境检查 | `env/`、`harness/m_minus_1/doctor_env.py` | M-1.0 | 0.5 |
| M-1.2 | 按 §6/§9.4/§9.5 固定 splits、SolveOptions、闸门判据与 T2 候选生成 recipe | `projects/private-sample-openarm/splits.yaml` + recipe | M-1.0 | 1 |
| M-1.3 | 读 20 ep parquet，抽 600 帧 + 20 连续片段（**只从 calibration**） | harness 脚本 + 抽样结果 | M-1.2 | 1 |
| M-1.4 | 建可复现 OpenArm 资产：以现有 xacro 为权威、`openarm_bimanual_origin.urdf` 为参照，生成真实 collision、可移植 mesh 路径和动态手指的双臂 URDF并计哈希 | `assets/robots/openarm_bimanual/` | — | 1.5 |
| M-1.5 | `assert_openarm_assets.py` + Pinocchio 加载：占位球、绝对路径、mesh 可解析、指关节 prismatic/mimic、TCP、限位与开闭方向 | JSON 核对记录 | M-1.4 | 1 |
| M-1.6 | GeometryModel + 碰撞对（复用 `openarm.srdf`，补检 body↔link0） | harness 内 | M-1.4 | 1 |
| M-1.7 | 双臂同时 IK 预检：81 候选×60 帧预筛 → 前9跑完整 600 帧+连续片段 → 按预登记规则排名 | 预检报告 | M-1.2、M-1.3、M-1.6 | 2 |
| M-1.8 | 闸门判定与记录 | `runs/` 记录 | M-1.7 | 0.5 |

> **M-1.4 是本阶段唯一的硬骨头，也是最容易被跳过的一步。** 现成 `openarm_bimanual.urdf` 看起来能加载、能 FK、能跑 IK，但 collision 是占位球、mesh 路径不可移植、finger 被固定化。跳过资产重建会同时制造碰撞假绿和夹爪假验证。

### M0 骨架与合成闭环（Panda，纯 CPU）

| # | 任务 | 依赖 | 估 |
|---|---|---|---|
| M0.1 | 仓库骨架、`pyproject.toml`、CI、`ruff`/`mypy` | — | 1 |
| M0.2 | `contracts/`：evidence、canonical v0.1、threshold、robot_profile、正式 `SolveOptions` | M0.1 | 2 |
| M0.3 | `kinematics/transforms.py` + 其单元测试（四元数/SE3/单位，**唯一出入口**） | M0.2 | 1 |
| M0.4 | `pinocchio_backend`：加载、FK、Jacobian | M0.3 | 1.5 |
| M0.5 | Panda `RobotProfile` + GeometryModel + 碰撞对屏蔽表 | M0.4 | 2 |
| M0.6 | §5.3.2 golden cases（6 组，含打乱 joint-name 元测试） | M0.4 | 2 |
| M0.7 | §5.3.1 内部约定一致性测试 | M0.6 | 1 |
| M0.8 | 合成轨迹生成器（随机 q → 平滑不越限 → FK） | M0.4 | 1 |
| M0.9 | 10 项负例生成器 | M0.8 | 1 |
| M0.10 | `pink_backend`：迭代闭环单点 + 序列 IK，按 §4.1 返回可观测 `IKStatus` | M0.4 | 2.5 |
| M0.11 | `solve/sequence.py` 连续求解 + 失败重试 | M0.10 | 1.5 |
| M0.12 | 自碰撞 barrier 挂载 + 独立距离复核（两条代码路径） | M0.5、M0.10 | 1.5 |
| M0.13 | `diagnose/` 逐帧与 episode 判定 + `thresholds.yaml` | M0.11 | 2 |
| M0.14 | `run/` 工作区、recipe 哈希、报告 | M0.13 | 1.5 |
| M0.15 | CLI 最小六命令（doctor/inspect/normalize/solve/diagnose/export）+ `--json` + 退出码；其余命令在对应任务补 | M0.14 | 2 |
| M0.16 | matplotlib 静态图确认数值 | M0.13 | 1 |

**出口：** 合成往返误差达标无分支跳变；10 项负例全检出；golden cases 全过且元测试确实报错。

### M1a 真实数值闭环（OpenArm，不导出）

| # | 任务 | 依赖 | 估 |
|---|---|---|---|
| M1a.1 | `parquet_prober` → StructureManifest | M0.15 | 1.5 |
| M1a.2 | `MappingSpec` 契约 + 校验器（对齐基线 §3.3） | M0.2 | 2 |
| M1a.3 | 首个 `DataProfile`（钉 revision + `lerobot==0.6.1`） | M1a.2 | 1 |
| M1a.4 | `normalize`：含四元数符号连续化、源夹爪 `(state+3)/5` → `aperture_fraction` | M1a.3 | 2.5 |
| M1a.5 | 对**可访问的 20 ep**做结构与统计扫描并落覆盖声明；不访问上游公司全量 | M1a.1 | 0.5 |
| M1a.6 | 纯关节空间跟踪延迟复核（`action.position` vs `state.position`），冲突则使 DataProfile 失效 | 图 + 结论 | M1a.5 | 0.5 |
| M1a.7 | OpenArm `RobotProfile` 正式化（把 M-1 结论重新实现） | M-1.8、M0.5 | 2 |
| M1a.8 | 双臂 IK + 双夹爪确定性映射；夹爪不进入 IK | M1a.7、M0.11 | 2 |
| M1a.9 | `solve_coupling: warm_start_from_state`（§9.2） | M1a.8 | 1.5 |
| M1a.10 | 跨流一致性三层判据 | M1a.9、M0.13 | 2.5 |
| M1a.11 | 批量报告（JSON/CSV/Markdown） | M1a.10 | 1.5 |
| M1a.12 | 在 `calibration` 上标定 `provisional` 阈值 | M1a.11 | 1.5 |

**出口：** 12 个 calibration ep 跑通出报告；**两条流**的 FK 都回到各自源 EEF 目标且误差达标。

### M1b 数据集闭环

| # | 任务 | 依赖 | 估 |
|---|---|---|---|
| M1b.1 | `export/layout.py` 目标向量布局（§9.1） | M1a.12 | 0.5 |
| M1b.2 | `lerobot_v3_writer`：parquet + 视频 `hardlink→copy` 降级 + `info.json`，manifest 记录复制策略 | M1b.1 | 2.5 |
| M1b.3 | `meta/episodes/*` 与 `meta/tasks.parquet` 重写（走偏移，不靠文件名） | M1b.2 | 2 |
| M1b.4 | 掩码与白名单（carry-forward、首帧规则） | M1b.2 | 1.5 |
| M1b.5 | `stats.json` 重算，口径 = 白名单 ∩ 有效帧 | M1b.4 | 1.5 |
| M1b.6 | 训练配置产出（`DatasetConfig(repo_id, root, episodes)`） | M1b.4 | 0.5 |
| M1b.7 | 五步出口验收实现（唯一 import lerobot） | M1b.5、M1b.6 | 2.5 |

**出口：** calibration 导出物通过五步验收。

### M1c 留出集验收与结构冻结

| # | 任务 | 依赖 | 估 |
|---|---|---|---|
| M1c.1 | 打开 `held_out` 8 ep 端到端跑一次 | M1b.7 | 0.5 |
| M1c.2 | 若已有源 URDF：§10.2 交叉校验（同侧同行配对） | M1c.1 | 2 |
| M1c.3 | 冻结 `CanonicalTrajectory v0.1` / `ExportProfile v0.1` **结构** | M1c.1 | 1 |

**出口：** `held_out` 一次通过，不回头调参；冻结契约结构，阈值升级为 `sample_validated` 并显式限定在这 20 ep，不宣称覆盖上游全分布。

---

## 9. 本文新定的实现决策

以下是基线留白、但代码非定不可的。凡涉及对外语义的（§9.1、§9.2）应回写基线 §14.1。

### 9.1 目标数据集的向量布局 ★

**基线从未定义导出的 `observation.state` / `action` 各维是什么。** §7.2 只说「换成目标机器人的关节值」，但列顺序、是否含夹爪、`names` 怎么写都没定。这是 M1b 的前置，也是 M1c 要冻结的结构。

决定：

```
shape [16], dtype float32
names = [openarm_left_joint1..7, openarm_left_finger_joint1,
         openarm_right_joint1..7, openarm_right_finger_joint1]
units = [rad × 7, m, rad × 7, m]
```

**理由是可比性。** 源数据的关节通道 `observation.state.position` 的 `names` 正是 `[Larm1..7_Joint, Lgripper_Joint, Rarm1..7_Joint, Rgripper_Joint]`——同样的「臂在前、夹爪在后、左先右后」。采用同一顺序后，导出的 `observation.state` 与源 `observation.state.position` 可以逐位并排看，§10.2 的交叉校验和人工抽检都省一层心智转换。

**刻意不沿用源 EEF 通道的 `[gripper, quat, pos] × 2` 顺序**（夹爪在前）：那个顺序是 EEF 表示的产物，目标侧是关节空间，照搬只会制造一个没有含义的巧合。**唯一的权威是 `info.json` 的 `names` 和 `ExportProfile.units`**，任何下游都不该靠位置猜。

Canonical 层的夹爪统一为 `aperture_fraction ∈ [0,1]`，约定 `0=closed, 1=open`。OpenArm v0.1 的训练/运动学导出采用 URDF 可验证的 `finger_joint1` 位移（米）；`finger_joint2` 由 mimic 得到，不作为独立维度。硬件电机命令不是本次导出语义，未来若接真机控制器，必须另建 controller-specific `ExportProfile`，不得把电机角与米制开度混用。

### 9.2 `warm_start_from_state` 的确切顺序 ★

基线 §7.1.2 只写「先解 `state` 流，再以它为初值解 `action` 流」，**没说 action 流自己是否也逐帧链式**。两种读法结果不同：

```python
# 第一遍：state 流，逐帧链式（保证自身时间连续性）
q_state[0] = solve(eef_state[0], seed=profile.default_posture)
q_state[t] = solve(eef_state[t], seed=q_state[t-1])

# 第二遍：action 流，每帧种子取同帧 q_state，★ 不链式
q_action[t] = solve(eef_action[t], seed=q_state[t])
```

**第二遍不链式是关键。** 若 `q_action[t]` 从 `q_action[t-1]` 出发，action 流就获得了独立漂移到自己分支的自由——那正是耦合要防的事。每帧种子锚在 `q_state[t]` 上，action 流的分支被逐帧钉死在 state 流上。

代价是 action 流自身的时间连续性只能**间接继承**自 state 流的连续性。所以：

- §6.1 的时间连续性检查必须**对两条流各跑一遍**，不能只查 state 流；
- 第二遍某帧失败时，回退到 `seed=q_action[t-1]` 重试一次，**并把该帧标记为 `coupling_degraded`** 计入报告。不标记的话，耦合在个别帧上悄悄失效而报告全绿——又是一个静默错误。

### 9.3 数据集原生坐标系与 T2

正式流程把输入数值所在的坐标系命名为 `dataset_native`，其数值定义来自数据本身，证据级别为 `EXPLICIT`；这只是在项目内建立稳定标识，**不声称知道它在真实场地中的物理身份**。目标机器人 base 相对 `dataset_native` 的变换是 T2，是 recipe 中显式选择并由 M-1 排名的设计参数，不属于待推断真值。

真实物理 frame 名称和重力方向作为可选 provenance 注释，缺失不参与 normalize 准入门禁。任何 `INFERRED_CANDIDATE` 仍只能用于 harness/预览，不能进入 M1 导出。这样 §3.1 的证据门禁与“无需知道 T1 身份也能自洽回验”不再冲突。

### 9.4 M-1 的“可达”是独立闸门定义

M-1 不直接拿 §6.3 的 `PASS=1 mm/0.5°` 当求解停止条件；那是 M0/M1 诊断阈值，且仍为 provisional。M-1 单帧在下列条件**同时**满足时才计为 `reachable_nominal`：

1. 左右 EEF 都满足位置残差 `≤5 mm`、姿态残差 `≤2°`；
2. 所有关节在 URDF 硬限位内；
3. 真实 collision geometry 下无穿透；
4. 两臂结果属于同一个联合构型，而非“左右分别有解”的拼接假象。

若位置仍 `≤5 mm`、姿态仅能落在 `(2°,5°]`，计作 `reachable_relaxed`，**只能贡献黄灯，不能计入绿灯的 ≥95%**。位置误差不放宽到 5 mm 以上。连续片段还要求每帧 nominal 可达，且相邻帧变化不超过 `3×v_max/fps`；超过即记分支跳变候选。这样 M-1 的可达率、§6.3 的质量阈值和 Pink 的数值收敛状态是三件分开的事。

### 9.5 T2 候选不是临场手调

候选生成只读取 `calibration` 与 OpenArm 资产，并在第一次 IK 前把完整列表及哈希写进 recipe：

1. 用 calibration 中左右 EEF 中点的逐轴中位数，与固定随机种子下 OpenArm 双臂可达点云中点的逐轴中位数对齐，得到 `T2_anchor`；roll/pitch 固定为 0；
2. 围绕 anchor 枚举 `dx,dy,dz∈{-0.10,0,+0.10} m`、`yaw∈{-10°,0,+10°}`，共 **81** 个候选，候选 ID 按 `(dx,dy,dz,yaw)` 字典序固定；
3. 第一阶段每个 calibration episode 取 `round((N-1)×{0,0.25,0.5,0.75,1})` 五帧，共 60 帧筛 81 个候选；按既定排名保留前 9；
4. 第二阶段只对前 9 跑完整 600 单帧 + 20×60 帧连续片段，最终仍按 §12 的既定规则排名，完全相同再按候选 ID；
5. 若前 9 全红，当前 recipe 结论就是红灯。扩大范围必须新建 recipe/version，不能把追加候选偷偷并回原结果。

`T2_anchor` 的点云采样数量、随机种子、关节限位裁剪比例也必须进 recipe；M-1 默认 `4096` 组、`random_seed=20260902`、每个关节只采硬行程的 `[5%,95%]`，避免恰好落在限位端点。

### 9.6 M-1 资产断言的唯一落点

M-1 写 `harness/m_minus_1/assert_openarm_assets.py`，直接运行并输出机器可读 JSON；它不依赖 M0 的 pytest/CLI 骨架。必须断言：无占位球、无绝对 mesh 路径、mesh 全部可解析、finger prismatic/mimic/限位正确、TCP 存在、开闭端点改变指间距。M1a 正式化时把同一组规则**重新实现**到 `tests/contract/test_openarm_assets.py`，不得从 harness import。`doctor` 同理：M-1 是 `harness/m_minus_1/doctor_env.py`，M0.15 才做正式 CLI 命令。

### 9.4 四元数与单位的单一出入口

内部一律 SI（米、弧度），四元数一律 `wxyz`（与源元数据一致）。但 **Pinocchio 的 `SE3` / `Quaternion` 用 `xyzw`**——这个转换只允许出现在 `kinematics/transforms.py`，其他任何文件里出现 `[3, 0, 1, 2]` 这类重排下标即视为 bug。

基线 §5.3.1 说内部一致性测试抓的是「关节顺序错位、TCP 重复施加、四元数分量搞反」这类**我们自己的 bug**。把转换收敛到一个文件，是让那类 bug 只有一个可能的藏身处。

### 9.5 掩码列的 dtype

`valid.retarget` 注册为 `bool`、shape `[1]`；`retarget.status` 不进 `features`（它是 episode 级，写进 `meta/episodes/*` 与 `retarget` 段）。掩码列写入 `ExportProfile.normalization_exclude`。

基线 §14.2 第 8 项把「bool 列进 v3 features 后 LeRobot 的实际行为」列为待实测——**M1b.7 就是那次实测**，结果要回写基线。

---

## 10. 风险与停止点

| 风险 | 触发信号 | 停止点与动作 |
|---|---|---|
| **OpenArm 覆盖不住工作空间** | M-1 双臂同时可达率 < 80% | M-1 红灯流程：扩 T2 → 放宽姿态 ≤5° → 目标重选 spike。**M1 保持阻塞** |
| **碰撞判据是空判据** | collision 几何为占位球 | M-1.5 的断言必须先过，否则 M-1.6/M-1.7 的结果作废 |
| **私有样本不代表上游全分布** | 只能访问 20 ep | 报告、阈值和 README 始终声明 `validation_scope=private-sample-20`；不设获取公司全量的任务，不做全分布承诺 |
| **未来出现与当前 action 语义矛盾的直接证据** | 新的原始 manifest/生产代码与现有数据、转换代码和 recorder 快照冲突 | 使该 `DataProfile` 失效并重新认证；当前本地代码已旁证 action 是同行目标命令，精确 recorder revision 未知不阻塞双流实现 |
| **Pink 局部最优卡住率过高** | M1a 可解率显著低于 M-1 预检 | 先查种子策略与重试，再考虑提前引入 CuRobo（打乱 M2/M3 顺序） |
| 源 URDF 始终拿不到 | — | 已有预案：§10.2 保持条件项，由 §10.3 真实往返测试承担同类职责 |

---

## 11. 第一天做什么

按依赖排序，前四项无相互依赖，可并行：

1. **迁移唯一工作树**（M-1.0）：提交当前规划，补 `.gitignore` / `.gitattributes`，用 Git bundle 或私有 remote 在实验室数据盘 clone；Windows 本地副本转只读。私有样本是否可复制到远端必须单独确认。
2. **建远端 env**（M-1.1）：用远端现有 conda 建 `python=3.12` env，装钉住的 `pin` / `pin-pink` / `qpsolvers[osqp]` / `pyarrow` / `pydantic`，确认 `import pinocchio`、`import pink` 与 `osqp in qpsolvers.available_solvers`。
3. **冻结首轮 recipe**（M-1.2）：照 §6、§9.4、§9.5 写入 12/8 split、可达定义、SolveOptions、T2 的 81→9 预算和全部种子，**在跑任何 IK 前**产生哈希。
4. **建立远端私有数据配置**：真实路径只进 gitignored 配置，公开 recipe 用 `dataset_alias: private-sample-20`；`doctor_env.py` 检查路径、权限、空间，不打印绝对路径。
5. **修 OpenArm 资产**：以 xacro/`origin` URDF 为依据生成可移植产物，同时修真实 collision 和动态 finger；先让 `assert_openarm_assets.py` 失败，再修到通过。

然后进 M-1.3 抽样。**在 M-1 闸门给出结论之前，不要开始 M0 的正式代码**——不是因为技术上不能并行，而是因为闸门红灯会改变目标机器人，而 M0 的 Panda 部分虽然不受影响，注意力被摊薄会让闸门本身被草草跑过。基线把它单列为一个阶段，就是这个意思。
