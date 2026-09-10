# 历史材料与全文追溯

日常只读 [当前状态](../current-status.md)、[开发主线](../development-log.md) 和 [报告索引](../report-index.md)。本目录仅保留仍有技术或决策参考价值的历史材料。

| 文件 | 保留理由 | 适用范围 |
|---|---|---|
| [product-plan-v1.md](product-plan-v1.md) | 首版范围的前身与后续收缩背景 | 2026-08-14记录，8月27日卸任 |
| [planning-discussion.md](planning-discussion.md) | 重要方案的选择与否决理由 | 历史讨论，不是当前需求 |
| [architecture-review-20260809.md](architecture-review-20260809.md) | 技术调查与方案比较 | 版本与推荐可能过期，不直接作为实现依据 |
| [meeting-20260826.md](meeting-20260826.md) | 当时对外汇报口径 | 历史快照，不代表今日进度 |

## 已从工作目录移除的重复材料

| 原文件 | 当前保留内容 |
|---|---|
| development-log.md 的逐切片长流水 | 合并到现行同名主线日志，保留重要约束、纠错、失败原因与证据边界 |
| m1-004-frame-semantics-blocker.md | 阻塞演变并入开发主线，数值证据保留于报告索引/原报告 |
| archive/build-checklist-before-20260910.md | 旧施工表全文在Git，操作只用现行清单 |
| archive/document-index-before-20260910.md | 旧导航全文在Git，不再保留重复文件 |

精简前全文可从远端仓库Git提交 ca70821读取，例如：

    git show ca70821:docs/development-log.md
    git show ca70821:docs/m1-004-frame-semantics-blocker.md

不额外复制旧日志作为备份档案；Git保留全文，当前文档保留必要信息。原始实验报告、recipe、运行日志和中断回执仍留在远端run目录，其清单未改变。
