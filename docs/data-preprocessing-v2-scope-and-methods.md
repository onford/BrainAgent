# Data Preprocess 附件：接口与初筛依据

日期：2026-09-06，已同步飞书新版单元语义。本文只展开上游字段、方法证据、结果交接与初筛依据。模块组成、命名和开发阶段以 [主方案](E:/work/BrainAgent/docs/data-preprocessing-v2-plan.md) 为准。

## 1. 上游输入：PreprocessInput

一个请求携带一份输入协议，引用上游已保存的产物。共用引用格式为 id、version、hash；大型文件通过产物引用读取。

| 字段 | 提供方与内容 | 就绪要求 |
|---|---|---|
| schema_version、request_id | 请求身份 | 可解析、可追踪 |
| dataset_id、dataset_version | Survey/Collection | 所有上游引用对应同一数据版本 |
| survey_ref | Survey：数据身份、采集信息、任务/Trigger、处理历史、证据与未知项 | 覆盖本次分析和候选方法需要的事实 |
| collection_ref | Collection：标准目录、标准版本、核验报告、记录及完整文件组索引 | 已完成标准化；文件、单位和记录身份明确 |
| selection_ref | Collection：筛选后记录集合及排除依据 | 对应本次输入版本和明确纳入范围 |
| literature_ref | Survey：SurveyLiteratureBundle | 可为空并记录状态；申请文献候选时必须有相应证据 |
| analysis_profile | 请求目标：任务、目标阶段、频段/时间约束、Epoch 定义及拟合/评估协议 | 能据此绑定当前流程参数；不设跨任务统一科研默认值 |
| method_selection | 方法来源、指定 ID/版本、全选或探索性筛选策略 | 明确本轮候选范围 |
| runtime_policy | 自动/复核模式、内存/磁盘预算、输出需求 | 与选定方法和当前环境相容 |

collection_ref 中的记录索引保存 subject/session/task/acquisition/run/recording 身份、文件组、哈希、读取格式、采样率、通道/单位/参考/坐标、时间基准、事件和既有标记。首版直接消费该索引，避免再维护内容相同的 DatasetManifest 副本。

请求冻结后保存上游引用的不可变快照。上游更新产生新版本，不改变已开始的执行计划。

“调研充分”针对当前目标判定：需要切段的方法检查事件/窗口，需要空间插值的方法检查可信坐标。可选条件缺失影响相应候选；数据身份或标准化证据缺失则阻塞整个请求。不能只凭 ready=true 判断就绪。

当前 Collection 仍是占位实现。开发可使用标明 development_fixture 的标准目录和完整协议样本；生产验收仍需真实上游产物或实现这些产物的上游交付能力。

## 2. 文献证据：SurveyLiteratureBundle

文献来源为原规划 1.4 和 1.6。1.5 的数据排除依据交给 Collection；若同一材料也包含方法步骤，保留原分类后复用该证据。

| 字段 | 含义 |
|---|---|
| schema_version、bundle_id、version、hash | 证据包版本 |
| survey_run_id、dataset_id、dataset_version | 调研与数据身份 |
| papers[].paper_id、DOI、title、year | 稳定文献身份 |
| survey_bucket、relation_to_dataset、inclusion_reason | 原分类、与数据/任务的关系及纳入理由 |
| landing_url、pdf_ref、fulltext_ref | 论文入口与实际可读取的证据文件 |
| repositories[] | URL、tag/commit、代码快照引用、与论文的对应关系 |
| evidence_locations[] | 页码、章节、表格或源码位置及相关片段 |
| retrieval_status、missing_items、conflicts | 全文/代码访问结果、缺失项与来源冲突 |
| quality_metadata | 引用量、仓库星数等辅助信息及采集时间；允许未知 |

Preprocess 加载证据并提取 MethodSpec.evidence 与 MethodSpec.recipe。Survey 无须预先完成可执行步骤拆解；只提供标题或摘要不足以支持声称完整复现。

缺关键证据时返回补充项：survey_run_id、paper_id、candidate_id、missing_fields、source_locator、blocking_reason。总编排将其交回 Survey；补充形成新证据包。可独立运行的其他候选继续处理。

论文与代码不一致时记录两套来源及采用依据；修改参数或组合步骤标记 adapted。论文中的 CSP、分类器及统计评价从预处理步骤中分离，交给 Evaluation。

现有 [DataSurveyAgent](E:/work/BrainAgent/backend/app/agents/data_survey/agent.py) 需要发布持久化证据包；[检索输出处理](E:/work/BrainAgent/backend/app/tools/output.py) 应分别保存完整证据和面向模型的摘要。总编排通过 [AgentTask.inputs](E:/work/BrainAgent/backend/app/runtime/context.py) 传递引用，跨轮从存储读取。

## 3. 核心对象的最小字段

以下结构先用版本化文件和 Pydantic 模型实现，不要求为每种嵌套记录单建数据库表。

| 对象 | 最小字段 |
|---|---|
| UnitSpec | id、source（原表/哈希/定义版本/来源验证声明）、implementation（入口/op/profile/合同/代码与环境和资产版本）、validation（逐操作状态/实际证据） |
| MethodSpec | id/version、evidence、applicability、recipe（步骤/参数规则/单元映射）、adaptations、checks、validation、status |
| ExecutionPlan | id/hash、input_snapshot、method_versions、record_configs、steps/依赖、实际参数与来源、fit_scope、screening、environment、required_outputs |
| RunResult | job_id、plan_ref、状态、逐候选/记录结果、artifacts、变化统计、warnings/errors |

MethodSpec 的发布状态为 draft / validated / retired。checks 记录来源、映射、实现与验证的具体缺口，不再将每个检查进度变成一种顶层状态。当前数据上的 blocked 记录在候选初筛结果中。

单元 source.status 与 validation.status 保持独立，防止把“已有代码”或“源表声称已验证”展示为本项目已验证。来源列中引用的测试收据需另取证；当前以 2026-09-06 的 50 项快照及 op/profile 为粒度，旧 ID 不静默重定向。原 UnitDefinition/UnitImplementation 合并到 UnitSpec 字段组；MethodCard/Recipe 合并到 MethodSpec；原 PipelineSpec 对应 ExecutionPlan；模块运行总清单统一由 RunResult 表达。

ExecutionPlan 另保存来源 profile、非有限值策略、实际 RNG 状态、参考向量或稳健参考状态引用，以及分数事件/整数化决定。模型与决定产物按实际算法设置兼容性检查，完整语义见单元附件。

DataState、ModelRecord、DecisionRecord、EventTrialMap 等是执行上下文和产物结构，具体含义见 [逐单元附件](E:/work/BrainAgent/docs/preprocessing-unit-implementation-plan.md)。它们可以独立序列化，但不各自设立领域服务。

## 4. 执行状态和产物交接

Job 使用 queued / running / completed / partial / failed / interrupted / cancelled。每条选定记录保存自己的状态、attempt、完成步骤和错误；不适用记录另列 reason，不从输入范围中消失。

“请求已提交”是 Agent 调用结果；“处理已完成”是 Job 状态。[现有 agent_run 保存逻辑](E:/work/BrainAgent/backend/app/db/repository/agent_run.py) 需区分二者。对话断开不影响独立 Worker；Worker 中断后通过固定计划重跑未完成记录。

首版采用单 Worker 和持久化任务索引，核验进程退出后才释放执行归属。重复提交由请求键去重，同一记录禁止并发重跑。无需在首版同时建设多 Worker 租约、逐步骤缓存和事件回放。

产物先写入独立 attempt 临时目录，按格式重读验证，再发布完整结果包并更新任务状态。启动恢复时核对结果包和数据库，未完成文件不得展示为成功。输入/输出路径别名检查、源文件组前后哈希及现有用户归属检查保留。

| 产物组 | 最低要求 |
|---|---|
| 数据 | 实际方法/记录对应的输出，阶段、通道、单位、参考、采样率和格式明确 |
| 复现材料 | 输入引用、计划与实际参数、代码/环境、单元要求的模型/决定/分数/掩码及日志 |
| 映射 | 原事件到当前事件/Epoch/Trial 的关系，通道和时间段的实际变化 |
| 汇总 | 输入、适用、成功、失败和未完成范围；保留/剔除及不适用项；产物哈希与验证 |
| 下游引用 | dataset/selection/plan/job/method/recording 身份、产物 ID、父产物与可比较条件 |

所有必需产物通过验证才提交该记录成功。失败保留已知参数、原因和可用诊断；没有可用输出不能仅因写出空文件就标成功。恢复复用已完成记录前核验输入、配置及产物哈希。

Epoch 数与 Trial 数分别统计；Trial 按原始 ID 聚合，明确部分保留的含义。方法各自的输出范围如实交给 Evaluation，再由其确定共同 Trial、通道或其他比较条件。

## 5. 初筛规则的文献依据

主方案的初筛规则是项目探索性建议，尚非统一评分标准。以下证据解释为何考虑适用范围、处理阶段和方法差异，不能直接推出当前数据的最佳方法。

| 证据 | 可以支持什么判断 | 对当前项目的启发 |
|---|---|---|
| PREP 原始论文定义为 early-stage pipeline，聚焦工频、坏道与稳健参考 | 流程覆盖阶段存在差异；不能把早期处理与完整清理直接当同类替代 | 标注 coverage，并在需要完整流程时显式补齐后续步骤；补齐后记为组合流程。[原文](https://www.frontiersin.org/journals/neuroinformatics/articles/10.3389/fninf.2015.00016/full) |
| HAPPE 原始论文针对发育群体、高伪迹和较短记录 | 方法验证范围与数据特征有关 | 将人群、记录长度、伪迹特征和分析目标作为适用性证据；目标不同需说明迁移依据。[原文](https://pmc.ncbi.nlm.nih.gov/articles/PMC5835235/) |
| HAPPE 1.0 独立研究中，数据保留、噪声与信号恢复指标表现不完全一致 | 保留更多或去噪更强不能单独证明信号更忠实；结论限于所测版本和数据 | 初筛保留多类处理策略；信号保存和伪迹抑制的实际比较放到 Evaluation。[原文摘要](https://pubmed.ncbi.nlm.nih.gov/35182604/) |
| EEG 预处理多路径研究发现，处理选择对解码的作用依赖任务，未校正伪迹可能提高解码表现 | 不能把最高分类准确率直接等同于最合适的预处理 | 初筛不用测试集准确率；保留任务适用性和方法差异。研究基于 ERP CORE，不能把其具体最优参数直接迁移为 MI 默认。[原文](https://www.nature.com/articles/s42003-025-08464-3) |

初筛实现先保存规则结果与理由，不设置未经验证的权重、星数门槛或固定保留方法数。候选记录至少含 candidate_id、方法与来源、适用记录、规则版本、checks、decision、reason、duplicate_of、method_features、estimated_cost。

将来若增加试运行初筛，应另定义样本、预算和评价协议；当前初筛只使用方法信息、输入条件和资源条件，处理效果留给 Evaluation。
