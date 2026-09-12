当前范围与修改进度以 [实施状态](current-implementation-status.md) 为准；带日期的审计和实验报告保留历史语义。

# 文档导航

当前实现以代码、评价协议和验收记录为准。探索计划与阶段记录用于追溯设计，不自动构成待执行任务。

| 文档 | 内容 |
| --- | --- |
| [A 项修改与验收](section-a-implementation-20260912.md) | 文献双入口、图方法三轴、来源组合、窗口/多输出及完整经典流程的当前修改与实测边界 |
| [正式业务整改与验收](release-business-logic-review-20260912.md) | 临时逻辑清单、真实 API 验收及未完成缺口；不等于已发布正式版本 |
| [训练工作流](training-workflow.md) | 六模块流程、启动与交付 |
| [预处理评价协议](preprocessing-evaluation.md) | EEGNet 主指标、CSP-LDA 对照、数据权限与选择规则 |
| [预处理策略搜索](offline-preprocessing-search.md) | 方法空间、预算、候选谱系与证据读取 |
| [本轮文献方法接入](literature-method-mainflow.md) | 多分支拆解、真实方法空间、受约束组合、来源追踪与验证边界 |
| [图表与解读](visualization-and-interpretation.md) | 图表范围、参数依据、知识卡和解释边界 |
| [作图与复现](assessment-figure-design.md) | 稳定坐标与色限、科研导出、字体及视觉回归 |
| [神经先验缺口分析](neural-prior-gap-analysis.md) | 当前能力核查、32 项端到端缺口、研究范围与证据边界 |
| [神经先验实施路线](neural-prior-implementation-plan.md) | 知识与规则合同、工作包、依赖、决策闭环与验收计划 |
| [神经先验实现与实测](neural-prior-implementation-review.md) | 已落地闭环、真实模型 API 与 EEG 实测、发现并修复的问题和剩余缺口 |
| [验收记录](offline-search-acceptance.md) | 已验证范围、测试记录与未完成实验 |
| [全量预处理图执行系统](preprocessing-integration-v2.md) | 52 单元、88 op、306 profile 的实际执行、参数与产物分支、全量矩阵及验证边界 |
| [版本管理](version-control.md) | 源码、运行产物及本地历史的管理边界 |
| [离线展示](../exports/README.md) | 已保存运行的单文件导出与验证 |

`data-preprocessing-v2-*`、`*-plan.md`、`*-demo.md` 和各阶段 review 文档保留当时的设计范围与验证条件。阅读其中的模型、阈值或成绩时，应同时核对日期和对应运行协议。历史记录不会因当前实现更新而重算。

本机交接摘要、个体化研究草稿及 `.local/` 内容可能不在源码版本中；不能把它们作为新环境启动的依赖。已有草稿应保留，纳入正式文档前需单独审阅。
