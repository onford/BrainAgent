# 数据调研报告

数据调研阶段结束时生成六份独立 HTML 报告。运行页面的“报告阅读”工作区可在目录中直接切换，支持章节跳转、专注阅读、新窗口和下载；“记录文件 → 数据调研”保留全部文件链接。无需等待接入、预处理或最终交付。

| 固定路径（相对运行目录） | 内容 | 结构化来源 |
| --- | --- | --- |
| `survey/reports/dataset-basic.html` | 名称、版本、DOI、发布方、发布日期、许可、训练任务与本轮范围、未知信息和引用依据 | `survey.json`、`verification.json`、`sources.json` |
| `survey/reports/data-information.html` | 目录、格式、文件头、数组、通道、采样率、事件、任务 Run、被试、时长、采集、许可和版本的三方核对；冲突、官方论文身份、原文与本地定位 | `local-inspection.json`、`verification.json`、`sources.json` |
| `survey/reports/statistics.html` | 总体规模、逐被试及逐记录统计、事件与采样率分布、通道集合、数组检查、无法读取的记录 | `survey.json`、`local-inspection.json` |
| `survey/reports/literature-usage.html` | 使用该数据集的分析与算法论文/仓库，分别记录用途；供 3.2、3.4（待讨论）使用 | `literature.json` |
| `survey/reports/literature-discussion.html` | 讨论数据集特点、问题、限制和排除事项的论文/仓库；供 2.3 使用 | `literature.json` |
| `survey/reports/literature-preprocessing.html` | 同类数据预处理方法的论文/仓库；供 3.2 使用 | `literature.json` |

报告以 Pydantic 验证后的过程记录填入 `backend/app/workflows/templates/survey-report.html`，不另行请求 LLM 编写报告，也不产生另一套事实 JSON。三个文献报告按用途过滤条目和覆盖记录，保留纳入、暂缓、排除、原因、阅读范围、指标、原文及来源链接。总体文字缺口因原始字段没有用途标记，放在明确标注“跨用途”的折叠区，避免错误分配。`covered` 仅表示已有纳入条目，不能视为充分调研。

统计仅在已选择且成功读取的记录上汇总，目录扫描规模单独列出；未知值不替换成零。不推算人口统计、频谱或信噪比等未测量指标。任务和事件含义标注为适配器配置，是否获外部证实另见三方核对报告。来源原文确实存在不等同于模型结论已被充分支持。

新运行在 `process/formats.json` 的 `survey_reports` 中冻结版本、六个文件名和 HTML 模板 SHA-256。原有 JSON/TSV 格式保持不变。历史运行缺少该新增目录项时仍可读取；补生成报告不重写原始调研记录、旧格式快照或已交付训练包。

从后端目录可为已有运行重建报告（需具备五个来源 JSON）：

```powershell
.venv-eeg/Scripts/python.exe -X utf8 -m app.workflows.survey_reporting workspace/training-workflow/workflows/<workflow-id>/survey
```

刷新运行页面后，产物接口会发现新增文件。若修改已有报告，应重启服务清除文件哈希缓存。各 HTML 自带样式，原文默认折叠；在线打开时支持报告互跳和结构化记录下载。
