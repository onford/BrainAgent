# 文档导航

当前实现以代码、评价协议和验收记录为准。探索计划与阶段记录用于追溯设计，不自动构成待执行任务。

| 文档 | 内容 |
| --- | --- |
| [训练工作流](training-workflow.md) | 六模块流程、启动与交付 |
| [预处理评价协议](preprocessing-evaluation.md) | EEGNet 主指标、CSP-LDA 对照、数据权限与选择规则 |
| [预处理策略搜索](offline-preprocessing-search.md) | 方法空间、预算、候选谱系与证据读取 |
| [图表与解读](visualization-and-interpretation.md) | 图表范围、参数依据、知识卡和解释边界 |
| [验收记录](offline-search-acceptance.md) | 已验证范围、测试记录与未完成实验 |
| [版本管理](version-control.md) | 源码、运行产物及本地历史的管理边界 |
| [离线展示](../exports/README.md) | 已保存运行的单文件导出与验证 |

`data-preprocessing-v2-*`、`*-plan.md`、`*-demo.md` 和各阶段 review 文档保留当时的设计范围与验证条件。阅读其中的模型、阈值或成绩时，应同时核对日期和对应运行协议。历史记录不会因当前实现更新而重算。

本机交接摘要、个体化研究草稿及 `.local/` 内容可能不在源码版本中；不能把它们作为新环境启动的依赖。已有草稿应保留，纳入正式文档前需单独审阅。
