# 数据接入与标准化：要求对照及实现范围

原始六模块规划中，Data Collection 负责只读扫描、标准化、结构异常检查、文献排除对象核对以及筛选前后统计。本轮审阅保留 EEGMMIDB 作为首个适配器；不将格式转换称为信号预处理。

| 原始要求 | 审阅发现 | 当前实现与边界 |
|---|---|---|
| 先只读扫描，再创建标准输出 | 原代码逐文件检查后立即转换，尚未完成全体所选记录检查 | 先扫描全部所选记录，发布检查和前后快照，再创建 BIDS 工作副本 |
| 保护源文件并核验 | 仅可读记录有哈希，失败记录缺少保护证据 | 对实际存在、已读取的所选 EDF 保存 SHA-256；转换前后复核同一清单，包括被筛除的已读取文件；不写源目录 |
| EEG 按 BIDS-EEG 整理 | 已有 MNE-BIDS 转换和信号往返检查 | 增加完整事件、通道/时间一致性与元数据来源记录；继续使用输入合同检查完整文件组和哈希。官方完整 BIDS validator 未运行 |
| eCoG/sEEG、侵入式标准 | 没有适配器 | BIDS-iEEG、NWB 明确列为尚不支持；不将 EEG 输出冒充这些标准 |
| 统一异常分类与字段 | 只有少数检查，异常常被统一写成可读性问题 | 15 类固定枚举，保存对象、预期、实际证据、状态、严重度、动作及 provenance；无行为、刺激同步、人口学或实测坐标依据的项目标为无法核查 |
| 从讨论数据集的文献提取排除对象 | 建议停留在调研文字中 | 接入 LLM 提取来源条目、对象类型、编号、原文证据和理由；代码核对本轮对象，区分匹配、范围外和无法定位 |
| 异常排除规则 | 规则尚未最终确定 | 仅排除已确认的结构性失败，例如缺文件、不可读、非有限信号、未定义或无效事件；文献建议和元数据缺失保留标记；不运行 ICA、坏道评分或科学质量排除 |
| pre-screen、post-screen、Delta | 缺少 Session/Run、通道、行为等维度和原因 | 固定 13 项统计，Delta 同列前后值、变化及原因。未知为 JSON null/TSV 空数值，不解释为零；Run 按被试与 Run 组合计数 |
| 固定映射、异常、排除、统计产物 | 文件映射只给主文件；标准事件表删去了 T0 | 增加通道与逐事件映射。BIDS 保留 T0/T1/T2，训练合同显式区分目标事件与上下文事件；T0 不成为训练类别 |

## 执行流程

1. Survey 提供本地扫描、三方核对和已纳入的数据集讨论资料。
2. 接入 LLM 审阅所选任务与标签，抽取文献报告的排除对象；代码校验引用及显式被试编号并匹配本地范围。
3. 只读检查所有所选记录。结构性失败进入排除表，未知项和非阻断差异保留标记。
4. 按同一输入范围形成筛选前后统计和 Delta；全部被排除时也保留这些记录，停止标准转换。
5. 将保留记录写为独立 BIDS-EEG BrainVision 副本，保留所有事件。模板电极坐标注明非个体实测；采集设备、硬件滤波与参考未知时不从目标格式推断。
6. 复读信号并比较通道、时间和完整事件，校验原文件哈希，注册预处理输入。预处理只对目标左右手事件生成 Epoch。
7. 报告从接入记录提取检查汇总、标准化范围、文献对象核对和前后统计。

## 固定产物（格式版本 4）

| 文件 | 内容 |
|---|---|
| `collection/review.json` | 模型的接入判断与文献排除对象提取 |
| `collection/literature-exclusions.json` | 文献对象与本轮范围的匹配及保留标记 |
| `collection/audit.json`、`anomalies.tsv` | 15 类检查与代码哈希、软件版本、参数、检查时间和路径 |
| `collection/source-integrity.json` | 所选实际源文件的哈希及转换后不变性核验 |
| `collection/mapping.tsv` | 源 EDF、目标主文件哈希、路径与数值误差；完整标准目录清单在 `input.json` |
| `collection/channel-mapping.tsv` | 原名、标准名、顺序、类型、解码单位和坐标来源 |
| `collection/event-mapping.tsv` | 原始事件索引、标签、时间/样点、标准代码和是否用于训练 |
| `collection/exclusions.tsv` | 实际结构性排除及对应原因 |
| `collection/pre-screen.json`、`post-screen.json`、`delta.tsv` | 同一筛选范围的前后统计及变化原因 |
| `collection/standardization.json` | 写入标准/版本、支持范围、验证级别及源/标准/训练事件数 |

Session 缺少显式编号时不虚构为每个被试一次 Session；行为记录尚未解析时记未知。通道数分为不同名称数和各记录通道数合计。`files` 为这些记录对应的原始 EDF 数，标准输出文件数另记，避免把格式转换增加的边车文件当成筛选增加的数据。

依据：[BIDS EEG 规范](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html)、[MNE-BIDS 写入接口](https://mne.tools/mne-bids/stable/generated/mne_bids.write_raw_bids.html)。MNE-BIDS 写入、数值往返检查和完整官方 validator 属于不同验证范围，产物中分别注明。
