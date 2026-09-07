# Data Preprocess 附件：经典流程依据与覆盖

方法来源取证：2026-09-05；单元覆盖更新：2026-09-06。范围：PREP、HAPPE 家族、Automagic、RELAX、MNE-BIDS-Pipeline；补充 PyPREP 作为 PREP 的 Python 实现。本文是方法调研和实现设计，未安装软件、未运行 EEG 数据，也未证明这些方法在本项目数据上有效。下文的“建议”“门槛”“应保存”均为项目设计，不是原作者的统一规范。

## 1. 必须先明确的概念

**基础库保存的是“有来源、版本和适用条件的具体流程模板”，不是软件名字列表。** 同一软件可以产生多条流程；同名流程在不同版本中也可能改变步骤。方法身份建议区分 `published_native`（按文献对应版本原生执行）、`upstream_configured`（官方软件加明确配置）与 `project_derived`（项目新增、替换或组合步骤）。

MNE-Python 官方提供预处理 API 和不同技术的教程，不能据此称存在适用于所有 EEG 的“官方默认完整流程”。项目组合 MNE 单元时应称“基于 MNE 的项目基线”。这是依据官方文档组织和工具性质作出的架构判断。[MNE 预处理教程](https://mne.tools/stable/auto_tutorials/preprocessing/index.html)、[MNE 预处理 API](https://mne.tools/stable/api/preprocessing.html)

MNE-BIDS-Pipeline 才是配置驱动的批处理流水线。当前 stable 文档中 `spatial_filter=None`、`reject=None`，分别意味着默认不做 ICA/SSP 空间伪迹清理和幅度阈值 epoch 剔除；不能把“软件默认参数”解释为已经确定的完整去伪迹方案。其 ICA 文档还要求检查每位被试的报告和成分表。因此，保留官方复核环节的流程应记录为“自动计算＋复核”；若项目用自动决策规则替代复核，应登记为派生模板。[空间伪迹设置](https://mne.tools/mne-bids-pipeline/stable/settings/preprocessing/ssp_ica.html)、[幅度剔除设置](https://mne.tools/mne-bids-pipeline/stable/settings/preprocessing/artifacts.html)

这不是要求当前规划任务停下来确认，而是未来执行系统需要准确表达的 `automation_level` 和 `review_policy`。

## 2. 候选方法及基础库定位

| 候选 | 已核实的覆盖阶段 | 数据与任务适用条件 | 建议纳入方式 |
| --- | --- | --- | --- |
| PREP | 线噪处理、稳健平均参考、坏道检测与插值 | 连续头皮 EEG；原生输入为带通道位置的 EEGLAB 结构；参考通道、待处理通道、线噪频率必须明确 | 基础准备流程/复合单元；不能单独标为已完成全部眼动、肌电等清理 |
| HAPPE 原始方法及后续家族 | 原始方法含滤波、线噪/坏道处理、wICA 与 ICA/MARA、分段和插值等；HAPPE+ER、HAPPILEE 有不同设计 | 原始论文关注发育与高伪迹数据；ERP 和低导联场景应分别核对 HAPPE+ER、HAPPILEE，不能直接套用原版条件 | 按家族成员、论文和实现版本分别建卡；先保留候选，避免把新版脚本称作 2018 原始复现 |
| Automagic | 将坏道检测、滤波、参考、ICA/MARA、RPCA 等可选操作及质量记录组织为配置流程 | 静息和任务 EEG；须提供布局、通道类型及选定算法需要的信息 | 以“版本＋明确配置”为模板；原生包装器接入，保留原质量指标 |
| RELAX | 连续数据极端伪迹/坏道处理，MWF、wICA/ICLabel 等可选组合；另有分段入口 | 头皮 EEG；振荡与 ERP 有不同文献配置，不能混为同一参数集 | MWF+wICA 与 wICA-only 等分别建方法；按第 5 节新版覆盖选择单元组合或原生适配 |
| MNE-BIDS-Pipeline | BIDS 读取、滤波/重采样、配置选择的伪迹处理、epoch、幅度/ autoreject 剔除、报告等 | BIDS raw 数据；需明确 EEG 通道、事件条件和分段目标；设置依具体研究而定 | Python/BIDS 接入候选；显式配置，并独立注明 ICA 复核和 EEG 坏道策略 |

表格来源：[PREP 作者说明](https://vislab.github.io/EEG-Clean-Tools/)、[HAPPE 原论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC5835235/)、[HAPPE+ER 原论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC9356149/)、[HAPPILEE 原论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC9395507/)、[Automagic 原论文](https://www.sciencedirect.com/science/article/pii/S1053811919305439)、[RELAX Part 1](https://www.sciencedirect.com/science/article/pii/S1388245723000275)、[MNE-BIDS-Pipeline 步骤](https://mne.tools/mne-bids-pipeline/stable/features/steps.html)。表中不对不同论文的效果排序，原论文的验证结论不能直接推出本项目的最优方法。

### 2.1 PREP：适合作为可复用的基础准备阶段

- 原生入口：`prepPipeline(EEG, params)`；输出 EEG、展开后的参数、计算时间；可作为独立 MATLAB 工具或 EEGLAB 插件使用。输入须有可解释的 EEG 通道和位置。参考与线噪频率从数据合同绑定，不能照抄示例国家的工频。[固定源码入口](https://github.com/VisLab/EEG-Clean-Tools/blob/0914132081ea7d534ee19f96973791fd81825755/PrepPipeline/prepPipeline.m)
- 依赖：MATLAB 及锁定版本要求的工具箱/随附代码；使用 EEGLAB 读写时同时锁定 EEGLAB。PyPREP 是基于 MNE 的 Python 实现，应单列 `implementation_id=pyprep`，不宣称与 MATLAB 原版逐点相等。[PyPREP 官方文档](https://pyprep.readthedocs.io/en/latest/)
- 自动/人工：参数和通道布局明确后可自动运行；数据适用性和结果审核由项目合同定义。
- 接入要求：保留坏道原因、插值通道、参与参考的通道、最终参考状态、线噪配置、实际参数和原生统计结构；若后接 ICA，应传递插值及参考造成的秩变化。
- 分类建议：`stage_scope=preparation`。若在 PREP 后补充 ICA 或 autoreject，组合流程的身份为项目派生方法。

### 2.2 HAPPE：家族名、论文方法和当前实现需分开

原始 HAPPE、HAPPE+ER 和 HAPPILEE 分别记录证据、参数与限制。尤其 HAPPE+ER 采用针对 ERP 的 wavelet-thresholding 设计，不能从原始 HAPPE 的 wICA/MARA 步骤推导其方法链。[HAPPE+ER 方法论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC9356149/)

- 当前作者仓库含 `1. pre-process/HAPPE_v3.m` 和 `HAPPE_v4.m`；此次锁定检查的 v4 脚本头标记 Version 4.1，并提供预设参数选择及命令行交互。接入时应提取参数加载和批运行机制，消除运行中等待输入的情况；尚未完成无交互适配或可恢复交互设计前，不能进入相应执行模式的正式方法集合。[固定 v4 脚本](https://github.com/PINE-Lab/HAPPE/blob/217e646aec2fe9a5159eed43f1131af34d6d39fc/1.%20pre-process/HAPPE_v4.m)
- 依赖：MATLAB、EEGLAB 及选定配置的附加包；上述脚本检查 Wavelet、Signal Processing、Statistics and Machine Learning、Optimization 工具箱。此项为该源码快照条件，不能外推到全部历史版本。
- 自动/人工：一次性参数设定后批处理；交互入口和 QC 检查另行记录。原生提供质量产物不等于项目已评价合格。
- 接入要求：保存实际参数文件、阶段数据（按存储策略）、坏道及分段剔除记录、重参考状态、wavelet/ICA 相关记录、原生数据质量和处理质量报告。不同家族分支的必需项由实际算法决定；不适用字段显式为 `not_applicable`。
- 纳入建议：保留家族候选及文献卡；先选择与首批数据任务一致的一个分支验证，不为覆盖面同时上线全部成员。

### 2.3 Automagic：一个可配置的包装框架

- 原生入口：GUI 为 `runAutomagic`，独立计算入口为 `preprocess(data, params)`；官方提供独立代码用法。配置项缺省、空结构及空结构数组可具有不同意义，参数适配器必须保存最终生效值，不能简单删除“空值”。[独立调用说明](https://github.com/methlabUZH/automagic/wiki/Standalone-preprocessing-code)、[固定实现](https://github.com/methlabUZH/automagic/blob/1a11f16bab0f4f7f13dab67d2500615fcc1d2a7f/preprocessing/preprocess.m)
- 依赖：MATLAB、兼容 EEGLAB 的数据结构和选定算法依赖。MARA、PREP、clean_rawdata、RPCA 等随配置选择；不要把所有可选操作同时当成默认步骤。
- 自动/人工：计算可脚本化；原生工作流还包含质量查看、插值及评分管理。项目应将人工覆盖记录与算法原始决策分开。[作者仓库说明](https://github.com/methlabUZH/automagic)
- 接入要求：保存原生 EEG 附加字段、完整配置、坏道与插值映射、成分决策和质量分数。原生质量字段可供 Data Evaluation 使用，但不能跨方法仅按 Automagic 自己的分类直接比较。[原生质量说明](https://github.com/methlabUZH/automagic/wiki/Quality-Assessment-and-Rating)
- 纳入建议：待一个确定配置、依赖集和最小数据夹具核验通过后上线；论文推荐配置与仓库开发分支新增功能分别建版本。

### 2.4 RELAX：保留原生实现和明确的清理变体

- 原生入口：`RELAX_SET_PARAMETERS_AND_RUN.m` 设置参数并调用 `RELAX_Wrapper.m`；分段可使用 `RELAX_EPOCH_CLEAN_DATA_FOR_ANALYSIS.m`。官方提供 EEGLAB 插件及脚本入口。[作者安装/运行说明](https://github.com/NeilwBailey/RELAX/wiki/1-%E2%80%90-Installing-and-Running-RELAX)
- 依赖：MATLAB、EEGLAB、所用 PREP/滤波/ICA/ICLabel/MWF/wavelet 组件及对应工具箱。实际依赖必须从锁定配置解析，不能用一份可选软件名单替代运行环境检查。
- 自动/人工：作者定位为自动 EEG 清理；项目仍需事前配置适用条件和事后核查执行合同。后续 targeted wICA 是不同的方法变体，须额外证据卡。[作者仓库及论文清单](https://github.com/NeilwBailey/RELAX)
- 接入要求：保存清理后的连续数据、极端伪迹/时段掩码、坏道列表、MWF/wICA/ICA 的启用项和参数、ICA 模型与分类决策、事件/分段映射、原生指标。字段以锁定实现的实际结构映射；缺少所需记录时由适配层提取或注明缺失。
- 纳入建议：新版表格已有相关操作源码，优先核验目标配置所需的单元组合，以固定原生运行作对照；必要时再用原生复合入口。单元组合与原生方法保持正确身份。振荡与 ERP 配方分别追溯 [Part 1](https://doi.org/10.1016/j.clinph.2023.01.017) 和作者仓库中的 Part 2 正式论文。

### 2.5 MNE-BIDS-Pipeline：显式配置的 BIDS 工作流

- 原生入口：`mne_bids_pipeline --config=<config.py> --steps=preprocessing`。BIDS raw 是官方输入要求；初次运行所需初始化、配置依赖和缓存失效交由锁定版本适配器核验。只执行预处理范围，后续 decoding/CSP 等留给 Data Evaluation。[官方基本用法](https://mne.tools/mne-bids-pipeline/stable/getting_started/basic_usage.html)
- 依赖：Python、MNE-Python、MNE-BIDS、MNE-BIDS-Pipeline，以及启用的 autoreject/ICA 分类器等依赖；完整环境锁定，不只记录 MNE 版本。
- EEG 坏道注意事项：当前 bad-channel 文档描述 `find_flat_channels_meg` / `find_noisy_channels_meg` 和 Maxwell 方法，不能把 `_01_data_quality` 步骤名称当作 EEG 全局坏道自动检测的证据。需要时显式增加已验证 EEG 坏道单元，此时记录项目派生关系。[当前坏道设置](https://mne.tools/mne-bids-pipeline/stable/settings/preprocessing/autobads.html)
- 接入要求：输出实际配置、处理后的 raw/epochs（取决于配置）、事件与剔除映射、ICA 模型/成分表（适用时）、报告和软件环境；若项目要求连续清理输出，应显式配置并验证该产物，不根据“运行成功”推断其存在。
- 纳入建议：提供一个任务明确的 `upstream_configured` 模板；不要将其称为唯一默认基线。若由本项目单元重新组织调用 MNE，身份改为 `project_derived`。

## 3. 版本锁定：本次可核查快照与以后执行的区别

下列提交由作者 GitHub 仓库 API 只读查询得到，只证明本次调研所看的代码位置，**不是本项目已经验证可执行的版本推荐**。上线时另需依赖锁、配置锁和验证记录。

| 仓库 | 本次查看的分支 | 提交快照 |
| --- | --- | --- |
| [PREP](https://github.com/VisLab/EEG-Clean-Tools/tree/0914132081ea7d534ee19f96973791fd81825755) | master | `0914132081ea7d534ee19f96973791fd81825755` |
| [HAPPE](https://github.com/PINE-Lab/HAPPE/tree/217e646aec2fe9a5159eed43f1131af34d6d39fc) | master | `217e646aec2fe9a5159eed43f1131af34d6d39fc` |
| [Automagic](https://github.com/methlabUZH/automagic/tree/1a11f16bab0f4f7f13dab67d2500615fcc1d2a7f) | master | `1a11f16bab0f4f7f13dab67d2500615fcc1d2a7f` |
| [RELAX](https://github.com/NeilwBailey/RELAX/tree/dd25438353c3d53b88c93167d8e9c6d13255a42a) | v2.0.1（分支名） | `dd25438353c3d53b88c93167d8e9c6d13255a42a` |

MNE-BIDS-Pipeline 与 PyPREP 的网页使用 stable/latest 路径，会随时间变化；入库必须转换为实际安装版本对应文档、发行版/提交及源码默认值快照。可读别名不能当作版本锁。

每个可执行模板的锁至少包含：模板版本、上游版本/提交、原论文版本、文档取证日期、所有依赖版本、MATLAB/Python 与工具箱信息、模型权重/分类器版本、配置散列、随机种子策略、输入数据散列和执行环境摘要。参数展开后再计算方法指纹。

## 4. 调研结果如何用于方法库

子 Agent 的产品职责、统一 MethodSpec 和开发顺序见 [主方案](E:/work/BrainAgent/docs/data-preprocessing-v2-plan.md)，本文保留方法证据与映射细节。

本次调研作为建库材料，后续补齐指定模板的可定位证据、准确映射、环境与配置锁、必需产物和代表数据验证。调研完成不等于模板已通过验证；实际缺口写入 MethodSpec.checks，验证证据写入 validation。

每个来源步骤记录 unit_id、unit_catalog_hash、coverage（exact / related_only / planned / missing）、参数/状态差异及证据。所有必要步骤须准确映射至可用单元或正式注册的原生复合入口，才能进入当前执行计划。原生适配需与直接调用原软件核对数据、单位、事件、通道和必需产物。

固定版本及配置后形成可重用方法，库更新不改变已启动任务。方法是否更适合当前数据，由后续 Evaluation 比较。

## 5. 与新版单元目录的覆盖关系

本节改用 [2026-09-06 飞书表格快照](E:/work/BrainAgent/docs/sources/preprocessing-units-feishu-2026-09-06.csv)：50 个唯一 ID，全部附代码。旧版 43 项的逐项迁移及关键变化见 [单元附件](E:/work/BrainAgent/docs/preprocessing-unit-implementation-plan.md)。本节判断的是当前来源覆盖，尚未完成 BrainAgent 集成或完整方法对照运行。

源码依赖按 op/profile 固定。MNE 基线仍为 1.10.2；新版另出现 PyPREP 0.7.1、mne-icalabel 0.9.0、asrpy 0.0.8、autoreject 0.5.0，以及作者源码、权重和 Octave 工具箱约束。不能拿此前 stable 网页版本替换这些来源锁，也不能仅凭方法名称认为数值一致。

### 5.1 当前覆盖与后续核查

| 方法 | 新版已有源码覆盖 | 仍须核对的完整方法条件 |
|---|---|---|
| PREP / PyPREP | EEG-BAD-CHANNEL-ENSEMBLE 的联合检测；EEG-ROBUST-REFERENCE 的 fit/finalize 迭代与终结；参考估计/应用及原生插值；EEG-SINE-REGRESSION 提供线噪操作 | 已不能称“缺少稳健参考代码”。须核对所选 PREP/PyPREP 版本的线噪实现、通道总体、NaN/坏道处理、随机状态、停止/终结顺序，以及辅助道暂存恢复 |
| MNE-BIDS-Pipeline / MNE 项目模板 | 滤波/多种重采样；FastICA/Picard/Infomax；EOG/ECG/肌电判据；ICLabel；可保留辅助道的 Epoch；global/local autoreject、逐 Trial 插值 | 官方流水线与项目单元组合仍分身份。核对具体配置、模型/域、人工复核和产物；SSP 当前仍只有应用，没有拟合单元 |
| HAPPE 家族 | CleanLine、MARA/ADJUST/ICLabel、ICA、多种插值与 Trial 检测/拒绝、参考及基线等具相关源码 | EEG-WICA 的 ordinary/targeted 是 RELAX 定义，不能据此认定覆盖 HAPPE 或 HAPPE+ER 的小波实现。逐家族核对步骤、模型、默认参数和输出 |
| Automagic | 联合坏道检测、参考/滤波、回归、MARA/ICLabel、ASR correction、插值等已有源码 | 配置和依赖须与原框架逐项对应；RPCA 仍没有独立表内单元，clean_rawdata 整体也不等于单个 ASR correction |
| RELAX | ordinary/targeted wICA、MWF、ICLabel、Picard/Infomax、C+1 参考、眨眼 IQR/IC 权重、窗口 MAD/眨眼上界、频谱斜率、坏道预算、肌电 Trial 决定、EOG 阶跃、回归基线、拼接与拒绝 | 缺口已主要转为流程组合、状态/掩码连接、原生与 repaired profile、单位/时间轴及全部分支产物验证；有单元源码仍不等同完整 RELAX 已复现 |

以上是依据用户新版表格与既有方法资料作出的映射判断。新表中已经声明验证的结果需取得具体收据后复核；本项目未重跑其方法或验证所报告的性能数值。

### 5.2 编译与初筛应据此更新

1. **能力身份使用 unit_id + op + profile + 实现版本。** 同一个单元已能包含多个算法。FIR notch、spectrum_fit、CleanLine 仍分别表达，不能因同属工频处理就合并。
2. **按新合同连接通道与状态。** Epoch 可保留所需 EOG；插值后保留或清除 bads 依操作而定；mark_repaired 需要已确认修复，不能盲目清空标记。
3. **实际数据条件仍要检查。** ICA 高通前提按 solver 区分；ICLabel 返回实际 CAR 和其他域标记，MNE 与 RELAX 路线可能采用不同来源规则；频谱判据的 author_attenuated 要显式记录。
4. **保留作者版本与修正版本的差异。** relax_2_0_1、repaired_indices、repaired_units_indices 等只在支持它们的操作中使用，区别进入方法证据、参数、去重和验证。
5. **已提供的源码优先适配与验证。** 先按目标方法确定最小操作集合，再安装或接入所需依赖并取得验证收据；只有实际缺失的步骤才列为新算法开发。开发阶段统一使用主方案 A/B/C。
