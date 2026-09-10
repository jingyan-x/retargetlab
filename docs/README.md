# 项目文档入口

**2026-09-10 用户已授权恢复开发；文档整理提交已推送。** 先读 [当前状态](current-status.md)，再按需查看 [报告索引](report-index.md)、[开发主线](development-log.md) 和 [施工清单](build-checklist.md)。

| 文档 | 唯一职责 |
|---|---|
| [current-status.md](current-status.md) | 当前已完成项、关键结果口径、未通过的出口 |
| [report-index.md](report-index.md) | 全部run、候选引用、完成/中断状态和证据导航 |
| [development-log.md](development-log.md) | 里程碑、关键实现约束、决策演变、失败教训 |
| [build-checklist.md](build-checklist.md) | 当前待办与恢复后顺序；按最新用户指示执行 |
| [product-plan-v2.md](product-plan-v2.md) | 产品范围与验收定义 |
| [engineering-plan-v1.md](engineering-plan-v1.md) | 接口、代码责任与工程设计 |
| [openarm-mapping-spec.json](openarm-mapping-spec.json) | 已知语义、目标约定、未确认的映射候选 |
| [文件级证据清单](evidence/run-report-inventory-20260910.json) | 33个run、403个文件的路径、大小与哈希 |
| [历史材料与全文追溯](archive/README.md) | 早期技术/决策资料及精简前Git版本 |

## 使用规则

1. 用户最新指示优先；当前已恢复OpenArm开发，下一步见施工清单。
2. OpenArm是当前目标，MQ03是源数据解释材料，Panda是历史对照和回归夹具。
3. 规划不是完成度报表，代码测试不是私有数据验收；有冲突先核对具体报告的约束、样本和版本。
4. 日志可合并精简，但保留改变结论的证据与失败原因；逐提交细节从Git追溯，不再反复追加过期“下一步”。
5. 恢复工作必须核对相关完整报告，不能只看Git HEAD或最高百分比。9月9日后续报告漏归档造成的接续错误已在主线中记录。
6. 源码、环境和完整runs以远端唯一工作树为准，Windows仅为文档查看镜像。私有数据/源路径不进Git，文档只保留别名、聚合结果和引用。
