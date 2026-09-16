# RetargetLab

EEF 轨迹处理工具：配置输入与机器人，连续求解 observation/action，检查质量，交互回放，并导出可由实际 LeRobot 读取的带掩码数据集。

当前候选版本为 **0.1.0rc4**。支持 Linux / Python 3.12；Pink + Pinocchio、Mink + MuJoCo 两套后端。已登记的真实数据布局为 OpenArm EEF sidecar 与 MQ03 EEF。v0.1 不宣称任意机器人自动适配、动力学执行或训练效果。

## Agent Skill

已提供[RetargetLab Skill](docs/skill-guide.md)：安装与使用两个独立流程，默认完整安装，使用时不自动修改依赖。Skill基线为CLI 0.1.0rc4。

## 安装

从候选 wheel 安装处理环境（完整记录见 [首版验收](docs/v0.1-acceptance.md)）：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -c env/v0.1-process-linux-py312.txt './dist/retargetlab-0.1.0rc4-py3-none-any.whl[pipeline]'
retargetlab --version
retargetlab doctor --scope pipeline --json
```

开发安装使用 `python -m pip install -e '.[pipeline,dev]'`。实际 LeRobot 读取建议使用独立环境安装 `[lerobot]`，避免下游训练依赖影响求解环境。项目自身代码采用 [MIT 许可证](LICENSE)。发布入口为 [GitHub Releases](https://github.com/jingyan-x/retargetlab/releases)；随包第三方文件保留各自许可证。

## 快速开始：公开模型与合成数据

示例不读取私有数据。OpenArm 模型来自固定版本的官方 Apache-2.0 仓库；两条 EEF 流由合成关节轨迹生成，三路视频为 RGB 测试图案。第二段故意设置突变，用于观察失败和掩码，不代表真实采集任务。

```bash
git clone https://github.com/enactic/openarm_description.git
git -C openarm_description checkout 6148297241fb0402eafe2c6eed455ae4e90d4552
retargetlab demo-init --openarm-source openarm_description --output demo --json
retargetlab process --config demo/process-pink.json --output demo/processed --json
retargetlab training-export --processing-run demo/processed --policy demo/quality-policy.json --output demo/dataset --json
retargetlab build-mujoco-model --profile demo/robot-profile.json --output demo/mujoco --kinematic-inertia-repair --json
retargetlab replay-build --config demo/replay.json --output demo/replay --json
retargetlab replay --bundle demo/replay --port 8790
```

打开 http://127.0.0.1:8790/ 。左键旋转、右键或 Shift＋拖动平移、滚轮缩放；播放严格逐帧推进。首次模型传输较大，加载完成后本地渲染。远端运行时在本机用 `ssh -N -L 8790:127.0.0.1:8790 <host>` 转发端口。服务器只绑定 loopback。

切换 Mink：先构建 MuJoCo 模型，再用 `demo/process-mink.json` 运行 process，选择新的输出目录，并在回放配置中指向该输出。不要覆盖已有 run。示例的惯量修正仅用于运动学模型编译，不表示动力学参数已经验证。

## 实际读取

在独立的 Python 3.12 环境中先安装 CPU PyTorch，再装读取依赖（无需求解依赖）：

```bash
python3.12 -m venv .venv-reader
source .venv-reader/bin/activate
python -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -c env/v0.1-reader-linux-py312.txt './dist/retargetlab-0.1.0rc4-py3-none-any.whl[lerobot]'
retargetlab doctor --scope reader --json
```

随后执行：

```bash
retargetlab verify-reader --dataset demo/dataset --output demo/reader-report.json --horizon 16 --json
```

训练代码通过 `retargetlab.run.training_dataset.MaskedLeRobotDataset` 读取，不能直接忽略 `valid.retarget` 使用全部行。导出保留失败行以维持时间轴，只把 observation/action 联合合格且完整的动作窗口交给读取端；夹爪 raw 通道不冒充米制开度。

## 输出与接入

`processed/` 保存配置、来源指纹、逐流诊断 Parquet 和报告；`dataset/` 保存 LeRobot 元数据、数值表、视频及 `retarget/` 质量/策略；`replay/` 保存按关节名回放的数据；`reader-report.json` 记录实际读取验收。

先阅读 [输入与配置](docs/v0.1-usage.md)，再替换所支持的数据/机器人配置。缺失语义或不支持的布局会报错，不自动猜测坐标或单位。公开文档入口在 [docs/README.md](docs/README.md)。内部验证使用实验室私有数据，不随工具分发；见[数据与许可边界](docs/data-policy.md)。
