# 项目文档入口

当前执行状态：**2026-09-10，按用户要求暂停实验，先完成资料整理。**

先看 [当前状态](current-status.md)，再看 [报告索引](report-index.md) 和 [施工清单](build-checklist.md)。不要按最新文件名、最高百分比或日志末尾的旧“下一步”猜测项目进度。

## 文档职责

| 文件 | 角色 | 回答的问题 |
|---|---|---|
| [current-status.md](current-status.md) | **唯一当前事实入口** | 已完成什么，哪条证据适用，当前卡在哪里 |
| [report-index.md](report-index.md) | **运行证据导航** | 每个 run 的含义、口径、完成状态和证据 ID |
| [evidence/run-report-inventory-20260910.json](evidence/run-report-inventory-20260910.json) | 文件级清单 | 已有报告、日志、recipe 的相对位置、大小、SHA-256 |
| [build-checklist.md](build-checklist.md) | 当前施工表 | 已有基础、暂停状态、恢复后顺序、未通过出口 |
| [product-plan-v2.md](product-plan-v2.md) | 唯一产品基线 | 做什么、为什么、首版范围与验收定义 |
| [engineering-plan-v1.md](engineering-plan-v1.md) | 唯一工程设计基线 | 接口、契约、代码责任、设计任务；不是完成率报表 |
| [openarm-mapping-spec.json](openarm-mapping-spec.json) | 语义事实与候选 | 源事实、目标资产约定、仍未确认的跨机器人映射 |
| [development-log.md](development-log.md) | 追加式历史日志 | 当时做过什么；日期较早的“下一步”不是当前指令 |
| [m1-004-frame-semantics-blocker.md](m1-004-frame-semantics-blocker.md) | 历史 blocker 档案 | 9 月 2–9 日阻塞演变；当前停止点看 current-status |
| [archive/build-checklist-before-20260910.md](archive/build-checklist-before-20260910.md) | 历史施工表 | 保留整理前版本，不再勾选推进 |
| [current-product-plan.md](current-product-plan.md) | 已卸任产品规划 | 名称有 current，但自 8 月 27 日起是归档 |
| [planning-discussion-archive.md](planning-discussion-archive.md) | 历史讨论 | 被覆盖的方案与决策理由 |
| [eef-trajectory-tool-architecture-review.md](eef-trajectory-tool-architecture-review.md) | 历史技术评审 | 早期调查，不能作为现行实现需求 |
| [weekly-meeting-plan-brief-2026-08-26.md](weekly-meeting-plan-brief-2026-08-26.md) | 历史周会材料 | 当时的汇报，不能作为今日进度 |

## 阅读与冲突规则

1. 用户最新指示优先。当前只整理，不运行实验。
2. 产品范围由产品基线决定，接口设计由工程基线决定；两者不表示实现已完成。
3. 当前状态页必须引用实际报告或已验证代码。若它与报告冲突，先核对报告、约束和样本并修正文档。
4. 历史日志保留，不回填成“当时已知”；遗漏结果用当前日期补登，并标注原实验日期。
5. OpenArm 是当前目标，MQ03 是源数据解释材料，Panda 是历史重选证据与回归夹具。
6. 私有数据、运行产物与源路径不进 Git。本目录只记录别名、相对产物位置、聚合结果与哈希。

## 运行位置

源码、环境、资产和完整 runs 以实验室远端唯一工作树为准。Windows 文档只作查看镜像。运行目录与真实机器路径的关系在本地配置中维护；报告索引使用仓库相对路径。

9 月 9 日后半段实验报告曾未同步进开发日志，导致本轮接续选错基线。已将这段断层显式记录；今后接续必须同时检查报告索引与相关完整报告，不能只看 Git HEAD 或旧日志。
