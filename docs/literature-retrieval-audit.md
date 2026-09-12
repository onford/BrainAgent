# 文献检索检查与验证（2026-09-11）

检查链路：DataSurveyAgent / WorkflowCognition → ToolRegistry → 各文献 API → 结果归一化 → 来源阅读 → 筛选。修复前可以发起真实检索，但存在漏召回、错误解析和过早结束的问题。

## 发现与修复

| 问题 | 修复后的行为 |
| --- | --- |
| arXiv 将整句关键词强制转为精确短语，还删除用户引号 | 普通关键词使用 AND 连接；保留显式短语和原生字段/布尔查询 |
| ToolRegistry 无论请求多少结果都只返回前 5 条 | 请求与返回使用同一 limit（1–100）；工作流默认获取 10 条 |
| Unpaywall 搜索响应被当作单篇论文，产生标题和 URL 为空的假条目 | 展开 results[].response，同时支持 DOI 对象与空结果集 |
| 多个文献源丢失摘要，arXiv 丢失 PDF 链接 | 保留摘要与实际返回的全文链接；Europe PMC 请求 core 元数据；OpenAlex 重建摘要倒排索引 |
| 上游错误对象、损坏 XML 可能被当作成功的零结果 | 返回明确的工具失败，保留可供 agent 使用的错误类别 |
| 一次失败或零命中即满足工作流“已检索”条件 | 未命中时要求切换尚未尝试的可用源；只有一个源时要求至少两次不同查询；耗尽后仍记录缺口 |
| 阅读失败或只读摘要即可满足阅读条件 | 有全文候选时要求继续尝试；有限尝试后允许结束，但保留访问/内容缺口 |

检索完成条件只说明已做必要尝试，不代表全面召回，也不代表所有候选均相关。文献纳入仍由现有筛选阶段根据实读证据判定，摘要不能直接作为已核实的全文方法依据。

接口格式核对依据：[arXiv API 手册](https://info.arxiv.org/help/api/user-manual.html)、[Unpaywall API](https://data.unpaywall.org/products/api)、[Europe PMC REST API](https://europepmc.org/RestfulWebService)、[Semantic Scholar API 示例](https://api.semanticscholar.org/api-docs/snippets)。

## 真实联网验证

可复跑的匿名接口检查，在 backend 目录运行：

```powershell
.venv/Scripts/python.exe scripts/literature_smoke.py --read-full-text --output ../docs/literature-smoke-result.json
```

本轮查询 `EEGMMIDB motor imagery`：

- Europe PMC 命中 84 条，返回 10 条；10 条包含摘要，6 条提供全文 URL。
- Crossref 返回 10 条，但其宽泛匹配包含低相关记录，因此返回数量不能替代相关性筛选。
- OpenAlex、arXiv、Semantic Scholar 本轮匿名请求均被限流，记录为 `rate_limited`。较早的探查中 OpenAlex 曾成功返回；公共接口可用性会变化。
- 从实际返回的 Europe PMC 全文链接成功读取 76,152 字符，保存内容哈希；没有下载整批论文。
- Unpaywall 未进行真实请求，因为需要联系邮箱；其解析使用与官方格式一致的响应样例进行回归测试。

详细结果见 [接口实测记录](literature-smoke-result.json)。`passed` 代表至少一个源成功返回候选，并完成所要求的正文读取，不代表所有源均可用。

另用项目已配置的真实 LLM 对“查找使用 EEGMMIDB 的运动想象分类论文”运行了单目标、6 次动作预算的 WorkflowCognition 检索：模型自主构造了数据集别名查询，执行 Europe PMC 和 Crossref 两次搜索，并跟进了四个实际全文 URL。四次阅读均成功，正文长度分别为 23,021、57,169、58,533、77,199 字符。该检查验证检索与阅读，没有运行完整的八目标文献筛选或下游 EEG 训练。见 [真实 agent 实测记录](literature-agent-smoke-result.json)。

## 自动化测试

新增回归覆盖查询意图、返回数量、Unpaywall 真实响应结构、异常响应、摘要/PDF 保留、失败/空结果后的替代检索、摘要后的全文读取，以及模型提前结束被拒绝后成功切换来源的流程。

基础环境中的相关测试：62 项通过。加入来源阅读、文献筛选和引用段落校验后，在 `.venv-eeg` 中 78 项通过。更广的测试使用项目已有 `.venv-eeg` 环境；基础 `.venv` 不包含 MNE/joblib，不能收集全部 EEG 工作流测试。

最终完整相关回归：**234 项通过**，耗时 367.99 秒，覆盖工作流、agents、集成和工具；仅有两条既有 Starlette 依赖弃用警告。

```powershell
.venv-eeg/Scripts/python.exe -m pytest tests/workflows tests/agents tests/integrations tests/tools -q
```

修改文件的 Ruff 检查与 `git diff --check` 均通过。
