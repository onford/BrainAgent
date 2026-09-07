# Brain Agent 文献到预处理流程实测

2026-09-07，本机 Brain Agent 已接入准备好的上游材料，实际调用配置的模型生成文献方法草案，再调用 Data Preprocessing 的计划接口完成初筛。最终结果是 **4 步草案、初筛 blocked、0 项可执行记录**。此次没有提交数值处理，也没有新增处理后的 EEG 数据。

本次验证的是“上游已准备好 → Data Preprocess 文献接入与拆分 → 初筛”。Data Survey 的自主文献检索尚未在本例中实现；上游材料由人工准备，通过现有 Data Survey 文献包注册入口接入。

## 输入与来源

文献为 Cho 等人 2017 年发表于 GigaScience 的 [EEG datasets for motor imagery brain–computer interface](https://academic.oup.com/gigascience/article/6/7/gix034/3796323)，DOI `10.1093/gigascience/gix034`。取得了公开 PDF、全文 XML、全文文本和 6 段带页码的证据；PDF 第 4–5 页已核对。对应数据仓库是 [GigaDB 100295](https://gigadb.org/dataset/100295)，没有把数据仓库当成作者代码仓库。

目标数据沿用 `eeg-smoke-20260907` 的标准化合成 BIDS-EEG：2 条记录，每条 40 秒，200 Hz，4 个 EEG 通道及 VEOG。这与论文原始数据不同，仅用于软件验证。最终核验 24 个输入文件的哈希，全部一致。

| 接入对象 | 内容 |
| --- | --- |
| Survey / Collection 输入 | 数据集身份、事件映射、标准目录、选中记录、通道、采样率及文件哈希 |
| 文献包 | 文献身份、全文/PDF 引用、6 段证据、目标分支及适用差异 |
| 基本单元合同 | 已启用操作的参数模式、输入输出语义、步骤引用和变量格式 |

引用的 `id` 与 `sha256` 相同：

```text
input_ref:      ba8f77f89efd3d348f08266a6964c4020473aaa98bf3d16c468416def6dccdaa
literature_ref: be4e3c16019c1148e58092fd88296c755985d0adf8d1103650d04b7ecc60821a
method_ref:     f6dce5fd252cf5bf64b690e49bb7adc8904c1b696c901d2200e920259a2c8bcb
plan_ref:       56f6afdb050b499a4d9a3c9c4390d44adcdb27d27480d453b79915fcc42d109a
```

## Brain Agent 实际生成的草案

下面只整理真实输出，未手工改写已注册的方法。

| 顺序 | 基本单元 | 参数与连接 | 证据编号 |
| --- | --- | --- | --- |
| 1 | EEG-FILTER / filter | Raw → 高通；截止频率保留为 `$profile.highpass_freq` | 0、4 |
| 2 | EEG-REREFERENCE / reference | 接高通输出；平均参考 | 4 |
| 3 | EEG-FILTER / filter | 接参考输出；8–30 Hz 带通 | 0、4 |
| 4 | EEG-EPOCH / epoch | 接带通输出；刺激后 0.5–2.5 秒；事件与 EEG 通道绑定上游信息 | 4 |

证据编号固定指向上游证据表：0 是滤波器说明，4 是分类前预处理段落。模型不再另写或重排证据。两处滤波采用当前集成的四阶 Butterworth IIR 实现；模型把零相位和先处理连续数据再分段等差异记入 `adaptations`。

最终 `checks` 有 4 条。主要阻塞包括分类分支高通截止频率未明确，以及目标数据缺少论文前置坏试次筛查所需的标记/EMG。坏试次的绝对幅度判据没有被替换成当前单元库中的连续窗口峰峰值检测。没有加入 ERD/ERS、CSP 或 FLDA 操作。

**审核边界：**`checks` 目前把真正缺口、待验证条件和说明性限制放在同一个列表中，初筛遇到非空列表就阻塞，尚未逐项向上游发起自动补充。本次得到的 `supplement_requests=[]` 只表示全文证据包接入阶段未请求补充，并不表示方法没有缺口。论文原始被试的坏试次索引也不能直接套用于合成记录；后续需要目标数据对应的筛查结果或明确、可追踪的适配方案。

## 文件位置与查看方式

本机材料根目录为：

```text
E:\work\BrainAgent\backend\workspace\literature-demo-cho2017
```

| 位置 | 内容 |
| --- | --- |
| `sources/` | PDF、XML、全文文本及核对页 |
| `source-manifest.json` | 来源文件哈希与引用 |
| `survey-literature-bundle.json` | 交给 Brain Agent 的上游文献包 |
| `survey-agent-result.json` | 上游文献包注册结果 |
| `brain-agent-run/method-latest.json` | 最终真实方法草案，原样导出 |
| `brain-agent-run/screening-latest.json` | 最终 blocked 理由 |
| `brain-agent-run/plan-latest.json` | 完整计划及输入快照 |
| `brain-agent-run/session.json`、`events.json` | 实际网页对话及执行事件 |
| `brain-agent-run/manifest.json` | 会话编号、三版草案和两次计划的引用 |
| `brain-agent-run/acceptance.json` | 文件核验和测试结果 |

权威方法、计划和证据对象存放于 `backend/workspace/eeg-smoke-20260907/output/preprocessing.db`；网页会话存放于 `backend/brain_agent_dev.db`。上述 JSON 是这些实际记录的可读导出。

打开 [本地网页](http://127.0.0.1:5173/)，进入标题以“文献到流程模拟”开头的现有对话。最后一张计划卡片已展开“查看方法初筛”。也可直接打开 [最终计划](http://127.0.0.1:8000/api/preprocessing/plans/56f6afdb050b499a4d9a3c9c4390d44adcdb27d27480d453b79915fcc42d109a)。

会话编号为 `18e12025-70fc-4878-bf17-5d9f382a5280`。重新提取时，在 Brain Agent 网页发送：

```text
请实际调用 data_preprocessing，使用 action=literature，literature_ref 的 id 和 sha256 均为 be4e3c16019c1148e58092fd88296c755985d0adf8d1103650d04b7ecc60821a。由你的模型提取分类前 EEG 预处理草案，保留未知参数和未实现步骤。
```

模型输出可能变化，应使用当次返回的 `method_ref` 继续计划。计划需提供上述 `input_ref`、该方法引用、`mode=validation`、`parameters={}`。保留缺口时预期为 blocked；空计划不能提交执行。

本机 `prepare_upstream.py` 只准备并注册上游材料，不调用预处理模型。`export_brain_agent_run.py` 只读取实际网页结果。早期 `simulate_literature.py` 的独立调用在模型返回前已取消，留下的 `llm/request-01.json` 不属于网页执行成果；不要用它重放本例。

这些文献和本地运行产物在被忽略的 `backend/workspace/` 中，不随 Git 提交。其他机器需要重新准备证据和输入；本页引用仅适用于本机当前输出库。服务启动方式见 [运行说明](data-preprocessing-demo.md)，本例的输入/输出根应使用 `eeg-smoke-20260907`。

## 本次修复与验证

- 模型读取完整操作参数合同、语义、连接规则及变量示例，减少仅凭操作名称猜测实现。
- 提取用 `MethodDraft`，系统从上游固定列表附加证据，避免模型重排证据导致引用错位。
- 方法注册提前检查参数字段、步骤依赖、输出引用、证据范围和错误的集合变量包装；这些问题会保留为阻塞项。
- 模型响应等待时间支持 `LLM_TIMEOUT_SECONDS`，默认 180 秒；连接超时为 10 秒。本次保留了原 60 秒读超时及临时连接超时的失败/重试记录。
- 最终后端测试：**75 passed**，24.52 秒；18 条警告来自依赖弃用和刻意触发空 Epoch 的异常用例。实际网页调用已验证文献提取和计划初筛。

此次完成了准备上游材料并让 Brain Agent 自己生成、筛查文献流程的验证。数值执行、效果评价与论文结果复现仍未完成。
