# 侵入式神经数据预处理标准与 BrainAgent 工作流设计

## 执行摘要

图中除 pi-VAE 人造数据外，其余数据都来自侵入式或需开颅的采集手段，但它们并不是一种可以共享同一条数值处理链的数据：Rat Hippocampus、NLB Area2 Bump、FALCON M1/M2 主要是细胞外电生理及其已提取的 spike/threshold crossing；Allen Visual Coding 与 Sinz 2018 包含双光子钙成像；Allen 另有独立的 Neuropixels 队列；MICrONS 则把双光子功能成像与电镜重建、连接组注释组合起来。把它们统称为“侵入式数据”有助于数据治理，却不足以决定算法。

标准方面，没有一个已经稳定、且能覆盖微电极阵列、Neuropixels、双光子与连接组数据的“侵入式 BIDS”。建议采用分层约定：

1. **NWB（Neurodata Without Borders）作为实验/会话级主标准**，统一表达电生理、spike unit、行为、刺激、trial、双光子 ROI 和处理历史。当前 NWB schema 为 2.11.0，原生包含 `ElectricalSeries`、`Units`、`Position`、`EyeTracking`、`TwoPhotonSeries`、`RoiResponseSeries`、`Fluorescence`、`DfOverF`、`ImageSegmentation` 等类型。[^1]
2. **DANDI 作为 NWB/BIDS 数据的验证、版本化和分发层**。本调研中的 NLB、FALCON、MICrONS 已经以 NWB 形式进入 DANDI，说明这套组合可直接覆盖主要的首批数据。[^2]
3. **OME-Zarr/OME-NGFF 作为超大原始光学或电镜像素数据的存储层**，NWB 保存实验语义、行为、ROI、派生信号及外部数据引用。OME-NGFF 0.5 已定义多尺度图像、轴和标签等结构，适合云端/分块访问。[^3]
4. **BIDS-iEEG 仅用于未来的人体 SEEG/ECoG/DBS 宏电极数据**。它不是动物微电极阵列或双光子数据的通用标准。[^4]
5. **跟踪 BIDS BEP032，但暂不把它作为生产依赖**。截至 2026-08-26，BEP032 仍是微电极电生理扩展提案，衍生 spike-sorted 数据和示例数据仍列为阻塞项；预览规范当前还只规定 NIX 作为主数据格式。[^5]

因此，标准能显著简化的是文件发现、元数据、实体身份、时间轴和 provenance；它不能替代 spike bin 宽度、单元质量阈值、参考方式、钙信号去卷积方法等科学决策。BrainAgent 的实现不应寻找一条“侵入式默认流水线”，而应建立一个**模态无关的执行内核 + 分模态 Unit 库 + 数据集 Method profile**。

首个 MVP 建议只消费发布方已经处理好的数据，而不从 30 kHz 原始电压或双光子原始 movie 重跑 spike sorting/ROI extraction。优先顺序为：pi-VAE synthetic → Rat Hippocampus（先确认数据集身份）→ NLB Area2 Bump → FALCON M1/M2 → Allen/Sinz/MICrONS 的发布版派生信号。原始电生理与原始双光子处理应作为后续独立能力建设。

## 一、标准约定：应采用“标准栈”，而不是单一格式

### 1.1 NWB 是最接近“侵入式数据 BIDS”的主干

NWB 的优势不是只支持某种仪器，而是用一套会话级对象模型同时承载采集信号、派生信号、行为、刺激、trial、设备、电极/ROI 元数据和处理模块。电生理中，原始/连续电压可保存为 `ElectricalSeries`，LFP 与滤波信号进入 processing module，spike times 和质量指标进入动态的 `Units` 表；双光子中可以表达原始 movie、motion correction、ROI mask、原始 fluorescence、neuropil、dF/F 和活动估计。PyNWB 还允许底层 HDF5 数据分块、切片和延迟读取，不需要把数百 GB 输入一次性载入内存。[^6]

这与当前 EEG workflow 的最大区别是：侵入式数据不能假设“所有记录都是规则采样的 channel × sample 矩阵”。spike times 是不规则事件；ROI trace 是规则或近规则的时间序列；行为和刺激可能有各自时钟；trial 是 interval；一个 session 还可能同时存在原始电压、LFP、已排序单元和不同层级的派生表示。

### 1.2 DANDI 提供可验证、可版本固定的分发层

DANDI 接受 NWB 和 BIDS 等标准数据，并为 Dandiset 提供版本、资产、校验和与流式访问机制。[^2] 对本项目很重要的不是“必须把数据上传到 DANDI”，而是复用它的三个约定：

- 输入必须固定到明确的 Dandiset/version/asset 或等价的本地版本标识；
- manifest 必须记录源 URL、许可证、校验和和 schema validator 结果；
- 大文件应允许远程或本地分块读取，而不是复制后全部 preload。

### 1.3 OME-Zarr 与 NWB 是互补关系

原始双光子 movie、体成像和 MICrONS 电镜体数据的像素规模可能远超单个普通 HDF5 文件适合的访问方式。OME-Zarr 适合保存多尺度、分块、压缩的 `t/c/z/y/x` 像素阵列与 labels；NWB 更适合保存 session 语义、采集参数、同步关系、ROI identity、行为、刺激和派生 trace。[^3]

推荐策略是：

- 中小型或发布方已经提供的 NWB：原样只读消费；
- 超大 raw movie/EM：保持 OME-Zarr 或发布方的 cloud volume，不为“统一格式”重复拷贝；
- 在 BrainAgent derivative 中记录外部资产 URI、内容哈希、切片范围和生成 lineage；
- 模型输入另行输出分块 Zarr、Parquet 或 NPZ，但这些只是 derivative，不取代 canonical session record。

### 1.4 BIDS 家族的适用边界

BIDS-iEEG 已覆盖人体 intracranial EEG 的目录、事件、电极和坐标等约定，支持 EDF、BrainVision、EEGLAB、NWB、MEF3 等文件。[^4] 若未来项目进入临床 SEEG/ECoG/DBS，这一规范应作为入口；当前截图中的动物 silicon probe、Utah array、FMA、Neuropixels 和双光子并不应被强行伪装成 iEEG。

BIDS Microscopy 已并入 BIDS 1.7.0，适合组织显微图像与采集元数据，但它不是“功能钙信号 + 行为 + trial + unit/ROI provenance”的完整分析标准。[^7] BEP032 的字段设计可以作为 probe/electrode/channel 命名参考，但在正式合并和生态成熟前，不应阻塞实现。[^5]

## 二、数据集逐项调研

### 2.1 pi-VAE 人造数据

pi-VAE 官方代码中的 synthetic example 不是生物信号清理任务。生成流程由 latent 与条件变量经可逆映射产生 firing rate，再按 Poisson 分布采样 spike count；真实 latent 可用于表示学习评估。[^8]

建议 workflow：

- 明确数组是 rate、count 还是 spike event，禁止三者混用；
- 校验维度、时间轴、有限值、非负性、条件标签和 ground-truth latent 对齐；
- 固定生成代码 commit、参数和随机种子；
- 先按 sequence/trial 做 train/validation/test 切分，再拟合标准化或其他有状态变换；
- 不执行滤波、去伪迹、重参考、spike sorting 或 calcium deconvolution。

它适合作为整个新架构的第一个 golden fixture：数据很小、有 ground truth、可检查可逆性、泄漏和确定性。

### 2.2 Rat Hippocampus Dataset

这里存在一个必须在实际接入前消除的身份歧义。截图只给出“140G+ Rat Hippocampus Dataset”，无法由大小唯一判断数据集。由于它与 pi-VAE 放在同一调研中，而 pi-VAE 官方仓库明确使用 CRCNS hc-11 的 `Achilles_10252013`，本报告暂按该 session 给出复现方案；如果本地数据实际来自 hc-3，文件结构、session 数量、元数据和预处理历史都不同。[^8]

pi-VAE 的作者预处理脚本对 `Achilles_10252013` 做了以下操作：读取 `sessInfo/Spikes/Position/MazeEpoch`；将 spikes 限制在线性轨道 epoch；保留 pyramidal cells；以 25 ms 分箱；对齐 1250 Hz theta/LFP；丢弃位置或速度不可用的 bin；通过轨道两端的局部极值推断 trial 边界；输出 trial、spikes、location 与 LFP。[^9] 原始 session 页面记录为 Amplipex 20 kHz、134 channels、14 spike groups，并包含睡眠—线性轨道—睡眠 epochs。[^10]

建议分成两个 profile：

- `hc11-pivae-reproduction-v1`：严格复现作者的 25 ms bin、maze epoch、pyramidal-cell selection、位置/速度缺失处理和 trial 推断，用于和论文/现有结果可比；
- `hc11-canonical-events-v1`：保留原始 spike times、unit identity、位置时间戳、行为缺口和显式 trial，再由下游 task 决定 bin 宽度。

如果数据实际是 hc-3，则应读取其已发布的 spike sorting、LFP、位置和方向结果。hc-3 原始信号为约 20 kHz，官方材料描述了 1 Hz–5 kHz 记录带宽、LFP 下采样至 1250 Hz、KlustaKwik 聚类后人工 Klusters 修订，并剔除漂移或 refractory period 不良的单元。[^11] 这类发布数据默认应消费既有 sorting；除非研究问题明确要求比较 sorter，否则不应把原始电压重新排序当作通用预处理。

### 2.3 Monkey S1 / NLB Area2 Bump

Area2 Bump 是 Neural Latents Benchmark 的数据集之一，官方数据以 NWB/DANDI 发布，`nlb_tools` 提供加载、trialization、binning 和 benchmark 输入生成。[^12] NLB 对原始电压完成 spike sorting 后，将活动按 5 ms 分箱，围绕主动到达与被动 bump 事件构造样本，并设置 held-in neuron、held-out neuron 以及 forward-prediction 区段用于评测。[^13]

推荐处理原则：

- 把官方 NWB 和官方 split 作为事实来源，不重做 spike sorting；
- 默认生成与 benchmark 一致的 5 ms 张量，任何 10/20/25 ms re-bin 都是新的 Method 参数；
- 保留 active/passive trial 类型、事件对齐点、held-in/held-out neuron 和 train/validation/test 角色；
- 所有 normalization、unit selection 和有状态变换只能在允许的训练集合拟合；
- 因 NLB 的原始 benchmark 包含连续预测和神经元外推，不可把公开 test 数据无意并回训练集。

### 2.4 Allen Brain Observatory Visual Cortex

截图中“2-photon + Neuropixels”容易被理解为同一 session 的同步多模态记录。Allen Brain Observatory 实际上包含独立的 Visual Coding 2P cohort 与 Visual Coding Neuropixels/ecephys cohort；workflow 应把它们作为两个数据集 profile，而不是尝试按共同小鼠或共同 stimulus 强行逐帧拼接。

Allen 的 Neuropixels 发布流程包括：AP band common-median subtraction、150 Hz 以上高通和分块 whitening、Kilosort2、平均波形、伪迹/噪声模板过滤、质量与 tuning metrics。LFP 分支执行通道/时间降采样、0.1 Hz 高通和参考处理。发布 NWB 已包含 spike times、amplitudes、waveforms、unit quality、stimulus presentations、running、pupil、LFP 与 session metadata。[^14] Allen 也公开了相应模块化处理代码。[^15]

双光子 Visual Coding 发布流程包括细胞 mask 分割、跨 experiment 关联、原始 fluorescence、重叠信号 demixing、neuropil correction、dF/F 和 tuning metrics；NWB 中同时记录 motion correction、ROI、fluorescence 与 dF/F。[^16]

因此第一版应提供：

- `allen-vcnp-released-nwb-v1`：选择 unit、刺激 epoch、行为流并生成任务所需 spike tensor；
- `allen-vc2p-released-nwb-v1`：选择 ROI/dF/F 或发布的活动表示，关联 stimulus presentation、running、eye/pupil；
- 对“重跑 Kilosort2”或“从 movie 重跑 ROI extraction”建立独立 raw profile，默认关闭；
- 在输出中记录 Allen data release、session ID、unit/ROI source ID 和原始 quality metrics，避免阈值变化造成身份丢失。

### 2.5 Sinz 2018

Sinz 2018 使用三组 mesoscope 记录：每组约 1,344–4,692 个同时记录的 V1 L2/3 神经元，输入是约 6 Hz 的已去卷积 fluorescence traces，同时记录 pupil position/dilation 和 running speed。作者将行为信号以 2.5 Hz Hamming low-pass 处理，再把神经和行为 trace 线性上采样到 30 Hz 以对齐视频；视频转灰度、中心裁为 16:9 并降采样到 36×64。训练中的 pupil position 使用训练集均值/标准差标准化，其他行为按训练集标准差缩放，并采用按 clip 划分及 15-frame burn-in。[^17]

这说明该数据集入口已经不是 raw 2P movie。推荐 profile `sinz2018-author-reproduction-v1`：

- 校验已去卷积 trace、eye/running、video frame 的时间与 trial/clip 对齐；
- 严格复现低通、30 Hz 插值、视频变换和 burn-in；
- 只用训练 clip 拟合标准化参数；
- 在元数据中把输出标为 `deconvolved_calcium_activity`，不能标为精确 spike count。Suite2p 等工具也明确提醒，calcium deconvolution 不会直接产生精确 spike counts。[^18]

### 2.6 MICrONS

MICrONS 的功能数据、刺激和行为可通过 DataJoint 或 DANDI/NWB 访问，结构数据与注释通过 CAVE/CloudVolume 访问。[^19] 功能处理包括基于 CNMF 的 soma segmentation、fluorescence extraction/deconvolution、行为同步以及功能影像与 EM 的 co-registration。[^20]

它需要两条彼此解耦的工作流：

1. `microns-functional-released-v1`：从发布版 NWB/DataJoint 读取 ROI 活动、自然视频/刺激、running、pupil 等，生成对齐的模型输入；
2. `microns-connectome-enrichment-v1`：固定 CAVE materialization/数据库版本，通过 co-registration table 将 functional ROI 映射到 EM cell/root ID，并输出匹配置信度、版本和失败原因。

不能把所有 functional cells 默认视为已有 EM 重建，也不能只保存“当前 root ID”而忽略 materialization version，因为 proofreading 与 segmentation 会演化。原始 EM volume 不应进入第一阶段信号预处理；它是后续结构特征或图数据构建能力。

### 2.7 FALCON M1

FALCON M1 数据来自 monkey M1 的 floating microelectrode arrays，神经输入是 threshold crossing/multiunit activity，目标是 16 通道 EMG。发布数据采用 NWB/DANDI，M1-A 和 M1-B 分别对应 Dandiset 000941 和 001209。[^21]

官方 benchmark 的关键预处理是：30 kHz 宽带信号按每通道阈值提取 crossing，并以 20 ms 分箱；EMG 对 60 Hz 及谐波 notch，四阶 acausal Butterworth 65 Hz high-pass，整流，按分位数 clipping/scaling，重采样为 50 Hz，再次整流并以四阶 acausal 10 Hz low-pass。[^22]

推荐 `falcon-m1-official-v1` 完整复现上述 observation/target 生成，同时记录：

- threshold 是按 session/channel 定义的发布参数，不与 sorted unit 混为一谈；
- 20 ms bin 和 EMG 的 acausal 处理是 benchmark contract，不一定适用于在线 BCI；
- calibration/evaluation 的时间顺序与官方 split 必须保持；
- normalization、clipping percentile 等只能在对应的 held-in/calibration 范围拟合。

### 2.8 FALCON M2

FALCON M2 使用两个 64-channel Utah arrays，发布 96 个神经通道；手指运动学原始约 1 kHz，神经宽带约 30 kHz。官方 benchmark 同样将 threshold crossing 分为 20 ms bins，并把手指 kinematics 重采样到 50 Hz；Dandiset 为 000953。[^21]

推荐 `falcon-m2-official-v1` 保留官方连续时间顺序与 calibration/evaluation split。FALCON 明确按连续 timestep 评测；如果预处理只生成随机 trial 片段，模型可能利用 trial 边界或在真实连续评估中失败。论文 baseline 对 spikes 的指数平滑与历史窗口属于模型特征工程，不应固化成不可逆的 ingest 默认步骤。[^22]

## 三、可以抽象出的公用经验

### 3.1 “当前处理阶段”必须是一等公民

同一个 session 可能提供以下任一入口：

- `raw_voltage` / `lfp`；
- `spike_times` / `sorted_units`；
- `threshold_crossing_events` / `binned_counts`；
- `raw_movie` / `motion_corrected_movie`；
- `roi_fluorescence` / `neuropil_corrected_fluorescence` / `dff`；
- `deconvolved_calcium_activity`；
- `em_volume` / `segmentation` / `connectome`。

Planner 必须先判断输入阶段，再允许合法变换。对 `spike_times` 不能做电压高通；对 `dff` 不能执行 spike sorting；对已经 deconvolved 的 Sinz trace 不能默认再去卷积；对 threshold crossing 不能声称得到 sorted single unit。这个约束比“数据集名称”更能防止错误。

### 3.2 时间同步比滤波更通用，也更容易出错

所有数据集都需要把神经、行为、刺激和 trial 关联起来，但它们可能有不同采样率、timestamp、丢帧、clock drift 或间断。内部模型应允许多个 `Timebase`，并显式保存：

- 原始 timestamp 或 `starting_time + rate`；
- 源时钟与目标时钟；
- 同步脉冲/锚点；
- 拟合的 affine 或 piecewise transform；
- 同步残差、外推范围、丢帧和无效 interval；
- resampling 方法及其 causal/acausal 属性。

绝不能把所有流都压缩成一个未经证明的 `sfreq`，也不能跨 missing gap、trial boundary 或 train/test boundary 平滑。

### 3.3 实体身份与选择决策必须可追踪

EEG channel 通常在一个 recording 内较稳定；侵入式数据还必须追踪 electrode/contact、sorted unit、threshold channel、ROI、functional cell、EM segment/root 等身份。每次 unit/ROI 筛选都应输出 `entity_map` 和 QC decision，区分：

- 发布方原始 ID 与当前输出索引；
- 原始质量指标；
- 检测出的 QC flag；
- Method 应用的 inclusion/exclusion rule；
- 被剔除实体及原因。

QC 的“测量”与“是否剔除”应是两个 Unit，便于比较不同阈值而不重算昂贵特征。

### 3.4 分箱、平滑和标准化是任务相关 Method，不是文件清洗

调研中已经出现 5 ms（NLB）、20 ms（FALCON）、25 ms（pi-VAE rat reproduction）、约 30 Hz（Sinz 视频对齐）等目标网格。不存在普遍正确的 bin width。建议始终保留事件级或最高可信度的发布表示，再按 Method profile 生成任务 derivative。

任何需要估计参数的变换——均值/方差、whitening、PCA、坏通道阈值、clipping percentile、速度尺度——都必须声明 `fit_scope`，默认仅使用 training/calibration 数据。切分单位优先是 subject/session/连续 trial block，而不是随机 time bin，以避免时间自相关泄漏。

### 3.5 默认复用发布方派生结果

截图中的 Area2 Bump、Allen、Sinz、MICrONS、FALCON 均已有发布方处理结果。第一版 workflow 的主要价值是：验证、选择、同步、trialize、tensorize、QC 与 provenance，而不是重新完成 Kilosort、Suite2p 或 CNMF。

仅在以下情况从 raw 重算：研究问题要求比较预处理方法；发布方 derivative 缺少目标信号；发现确定的处理缺陷；或接入全新原始数据。Raw ephys 可采用 SpikeInterface 的 reader/preprocessor/sorter/analyzer 生态，但 filter、reference、whitening、bad-channel 与 motion correction 应按 probe/profile 配置，不应形成全局默认链。[^23] Raw 2P 可用 Suite2p/CaImAn 风格的 motion correction → ROI detection → trace/neuropil → dF/F → deconvolution → QC，但每一步同样要受输入阶段和方法证据约束。[^18]

## 四、仿照现有 EEG workflow 的实现方案

### 4.1 保留现有四层结构，替换 EEG 专属契约

`dev-xx` 当前设计的 Unit library、Method library、Planner、Executor/Worker，以及 immutable input、training/calibration/test scope、planning screening、provenance 和 delta report 都值得保留。需要改变的是底层数据契约，而不是另起一套作业系统。

当前实现中的几个结构性限制包括：

- `CollectionSnapshot.standard` 固定为 `BIDS-EEG`；
- `RecordSpec` 假设 `sfreq/samples/channels`，channel type 也限定为 EEG/EOG/ECG/EMG 等；
- reader 只接受 BrainVision BIDS，并以 `preload=True` 读入完整矩阵；
- Planner 的类型、资源估算和 Unit 输入输出都围绕 MNE Raw/Epochs；
- Runner 主要写 FIF 与完整 `signal_V.npy`。

对 140 GB+ 电生理或超大 movie，这些假设既不正确也不可扩展。建议不要继续扩充 `RecordSpec` 的可选字段，而是引入新的模态无关 snapshot，并让 EEG 也逐步成为一个 adapter。

### 4.2 新的 canonical snapshot

建议核心对象命名为 `NeuroDatasetSnapshot`，至少包含：

```text
dataset_identity
  dataset_id, version, release, doi, license
  subject_id, session_id, recording_id
source
  standard, schema_version, container, assets[], hashes[]
signal_collections[]
  modality: synthetic | ecephys | ophys | connectomics
  representation: raw_voltage | lfp | spike_times | ...
  entity_axis: electrode | unit | threshold_channel | roi | cell | segment
  entity_ids[], shape, dtype, physical_units
  timebase_id, storage_ref, chunks
timebases[]
  timestamps or starting_time/rate
  sync_transforms[], gaps[], residual_metrics
streams[]
  behavior | stimulus | target | covariate
intervals[]
  trials, epochs, invalid_ranges, split_roles
processing_state
  upstream_steps[], code/version, parameters, evidence
```

关键设计原则是 representation、物理单位、实体轴和 timebase 都不可隐式推断。snapshot 只描述不可变输入状态；“筛了哪些 unit”“重采样到多少 Hz”属于 plan 和 derivative。

### 4.3 Reader/Adapter 层

定义统一 reader protocol：

```text
inspect(uri) -> SourceDescription
validate(source) -> ValidationReport
snapshot(source) -> NeuroDatasetSnapshot
read_slice(collection_id, entity_slice, time_slice) -> array/events
fingerprint(source) -> SourceFingerprint
```

首批 adapter：

1. `NWBAdapter`：PyNWB/HDF5 延迟读取，覆盖 `Units`、`ElectricalSeries`、ophys processing、behavior、stimulus 与 intervals；
2. `SyntheticAdapter`：NPZ/MAT/HDF5，显式映射 rate/count/latent/condition；
3. `Hc11LegacyAdapter`：只在确认原文件身份后实现；更推荐做一次可验证的 legacy → NWB 转换并固定转换版本；
4. `OMEZarrAdapter`：后续用于 raw ophys/EM；
5. 数据集 profile mapper：只负责把 Area2 Bump、Allen、Sinz、MICrONS、FALCON 的字段与官方 split 映射到 canonical contract，不在 reader 内偷偷执行数值处理。

所有 adapter 必须支持 bounded inspection 和 chunked read。Planner 只读 header/table/sample windows 做规划；Executor 按 chunk 运行，禁止全量 preload。

### 4.4 Unit library 的分层

**跨模态公共 Unit**

- schema/state/hash validation；
- select interval/entity；
- timestamp synchronization 与 residual QC；
- missing-data mask；
- continuous stream resampling；
- trialize/window；
- split assignment；
- train-only normalization；
- artifact/QC/provenance report。

**Event/spike Unit**

- unit QC measurement 与 selection；
- spike/threshold-event binning；
- causal/acausal smoothing；
- event-aligned raster/rate；
- neural—behavior/stimulus alignment。

**Raw extracellular Unit（后续）**

- probe geometry/phase-shift；
- band/high-pass；
- bad-channel detection；
- CAR/CMR/reference；
- whitening；
- motion/drift correction；
- sorter invocation；
- waveform/quality extraction 与 curation；
- 独立 LFP branch。

**Ophys Unit**

- motion correction 与 bad-frame detection；
- ROI segmentation/classification；
- fluorescence/neuropil extraction；
- demixing/neuropil correction；
- dF/F；
- deconvolution/activity inference；
- ROI QC。

**Connectomics Unit**

- pin materialization/version；
- fetch annotation/table；
- functional ROI ↔ EM cell co-registration；
- mapping confidence/QC；
- graph/structural feature materialization。

**Synthetic Unit**

- deterministic generate/load；
- support/range/alignment validation；
- latent/condition preservation。

### 4.5 Method library：一数据集一条可复现 profile

首批 Method 不应叫 `invasive_default`，而应显式命名并固定证据、代码版本、参数、适用 stage 与输出 contract：

- `pivae-synthetic-v1`
- `hc11-pivae-reproduction-v1`
- `nlb-area2-bump-official-v1`
- `allen-vcnp-released-nwb-v1`
- `allen-vc2p-released-nwb-v1`
- `sinz2018-author-reproduction-v1`
- `microns-functional-released-v1`
- `microns-connectome-enrichment-v1`
- `falcon-m1-official-v1`
- `falcon-m2-official-v1`

同一数据集可以有多个 candidate Method，例如 NLB 5 ms 与下游 decoder 的 20 ms，或 Allen 使用发布方 `good` unit 与自定义质量阈值。Method selection 通过验证集/校准集与科学约束完成，不应由 LLM 在执行期临时生成代码。

### 4.6 Planner 的新增职责

Planner 应按 `(modality, representation, task_goal)` 派发，而非只按 dataset name：

- 检查状态转换是否合法；
- 检查需要的行为/刺激/interval/entity 是否存在；
- 检查所有 timebase 有可接受的同步变换和误差；
- 检查 fit scope 与 split，阻止数据泄漏；
- 标记每个 filter/resample 为 causal 或 acausal；
- 明确选择 `consume_released_derivative` 或 `reprocess_from_raw`；
- 以 chunk、事件数、像素体积、sorter/GPU 需求做资源估算；
- 检查输出的 identity、units、time grid 与 task contract；
- 若原始数据身份、版本或 stage 不确定，停止生成数值计划，只输出需要人工确认的诊断。

### 4.7 Executor 与输出

沿用现有 immutable plan、job state、失败恢复和 provenance 机制，增加 per-modality executor registry 与 artifact writer。昂贵步骤必须能 checkpoint/resume；Kilosort、Suite2p 等可选依赖应运行在固定容器/环境中，不污染基础 worker。

每次运行至少输出：

- `manifest.json`：数据集、版本、资产、哈希、license、输入 stage；
- canonical derivative：`.nwb` 或分块 `.zarr`；
- 模型张量：按任务选择 NPZ/Zarr/Parquet；
- `entity_map.parquet`：源 ID、输出索引、QC、选择原因；
- `timebase_map.json`：时钟变换、误差、gap、丢帧；
- `intervals.parquet` / `splits.parquet`；
- `qc_metrics.parquet` 与 `qc_decisions.parquet`；
- `provenance.json`：Method/Unit/code/container/environment/seed；
- delta report：输入状态到输出状态的逐步变换。

原始输入永远只读；输出不得用压缩索引覆盖发布方 unit/ROI ID。

### 4.8 对 `dev-xx` 的建议改造落点

为了让实现可以拆成独立 PR，建议按下面的文件边界推进：

- `backend/app/preprocessing/schemas.py`：新增 modality-neutral contract；第一步保留现有 `RecordSpec`/`CollectionSnapshot` 作为 EEG v1 compatibility schema，不做破坏式原地扩字段；
- `backend/app/preprocessing/adapters/base.py`：新增 `NeuroDataAdapter` protocol 和 bounded inspection/read contract；
- `backend/app/preprocessing/adapters/nwb.py`：实现 NWB session、collection、entity、timebase、interval 的索引与 lazy slice；
- `backend/app/preprocessing/adapters/synthetic.py`：实现 pi-VAE 数组与 ground-truth latent；
- `backend/app/preprocessing/profiles/`：存放数据集字段映射和官方 split，和数值 Unit 解耦；
- `backend/app/preprocessing/units/common/`、`units/ecephys/`、`units/ophys/`、`units/connectomics/`：按 representation 拆 Unit；原 `units/source/eeg_*` 保持不变；
- `backend/app/preprocessing/planner.py`：增加 state-transition registry、timebase/split checks 与 chunk-aware resource estimate；旧 EEG planner 先作为一种 modality dispatch；
- `backend/app/preprocessing/runner.py`：增加 executor/artifact-writer registry，避免 invasive 路径经过 MNE/FIF 和 `preload=True`；
- `backend/app/preprocessing/methods/` 或现有 catalog：新增上述 dataset profiles，并记录 source citation、upstream processing stage 与 code commit；
- `backend/tests/fixtures/neurodata/`：加入用 PyNWB 生成的 tiny fixtures，测试代码生成 fixture，避免提交大型二进制样本。

建议的 PR 顺序是：`contracts + compatibility tests` → `NWB adapter + tiny fixture` → `common event/timebase Units` → `Area2/FALCON profiles` → `HC11 adapter/profile` → `ophys representations`。每个 PR 都保持现有 EEG tests 通过，避免把“支持侵入式”变成一次性重写。

## 五、实施阶段

### Phase 0：身份审计与契约重构

- 确认 Rat Hippocampus 的正式名称、DOI/下载地址、session 和文件结构；
- 确认 Allen 使用 2P、Neuropixels 或两者的哪些 release/session；
- 为所有数据建立 manifest，标注 raw/processed stage 和官方 split；
- 引入 `NeuroDatasetSnapshot`、representation/timebase/entity identity；
- 保留现有 EEG 路径，并通过 compatibility adapter 避免回归。

### Phase 1：最小可用的 spike/event + behavior workflow

- `SyntheticAdapter` 与 pi-VAE golden fixture；
- `NWBAdapter` 的 `Units`、behavior、intervals、trial 与 split；
- HC11 已排序 spikes + position；
- NLB Area2 Bump；
- FALCON M1/M2；
- 公共 bin/alignment/trialize/split/normalization/provenance Units。

这一阶段复用率最高：四个真实数据家族最终都可形成“事件/计数 + 行为/目标 + interval”的任务张量。

### Phase 2：发布版 ophys/ecephys derivative

- Allen Neuropixels 与 2P 拆成两个 profile；
- Sinz 2018 作者复现 profile；
- MICrONS functional NWB/DataJoint profile；
- ROI identity、dF/F/deconvolved activity、stimulus-frame alignment 与 calcium-specific QC。

### Phase 3：从原始数据重处理

- 基于 SpikeInterface 建设 raw extracellular pipeline；
- 按 probe family 配置 reference、filter、whitening、motion、sorter 和 QC；
- 基于 Suite2p/CaImAn 风格建设 raw 2P pipeline；
- 引入 GPU/container capability、checkpoint 和长作业资源计划。

这一阶段不应成为 Phase 1/2 上线的前置条件。

### Phase 4：MICrONS 连接组增强

- OME-Zarr/CloudVolume 大体积访问；
- CAVE materialization pinning；
- functional ↔ EM co-registration 与置信度；
- morphology/connectivity graph derivative。

## 六、验证与验收标准

1. **Contract/property tests**：representation 转换合法；单位明确；entity ID 唯一且稳定；timestamp 单调；split 不相交。
2. **最小 golden fixtures**：synthetic、NWB Units+behavior、NWB ElectricalSeries、NWB ophys ROI+behavior、OME-Zarr；每个 fixture 足够小，可在 CI 内运行。
3. **官方实现数值对照**：HC11 的 25 ms bins/trials 对齐 pi-VAE 脚本；Area2 Bump 对齐 `nlb_tools`；Sinz 对齐低通/上采样/clip split；FALCON 对齐 20 ms/50 Hz 与 M1 EMG chain。
4. **泄漏测试**：normalization、whitening、clipping 等 fit Unit 只能读取声明的 training/calibration interval；测试跨 gap/trial/split 的滤波被拒绝或正确截断。
5. **同步测试**：已知 clock drift、丢帧、piecewise offset 的 round-trip 和 residual 阈值；禁止无依据插值跨越长缺口。
6. **大数据测试**：用 instrumented reader 证明内存随 chunk 大小而非数据总量增长；140 GB 输入不得 full preload。
7. **恢复与 provenance**：中断后 resume 与一次运行结果一致；所有 artifact 可从 manifest 重读并校验 hash；输入不发生变更。
8. **代表性样本验证**：每个 Method 从 `draft` 升为 `validated` 前，必须在真实小样本上运行，并生成 QC 图/指标和与官方结果的误差报告。

## 七、需要尽快确认的两个问题

1. **Rat Hippocampus 到底是哪一个数据集？** 请用下载 URL、README、DOI 或顶层目录文件名确认。若是 hc-11 `Achilles_10252013`，可直接复现 pi-VAE；若是 hc-3，应做多 session manifest 和另一套 adapter/profile。
2. **第一版目标是“模型可用的发布版派生数据”，还是“从原始电压/movie 完整重算”？** 本报告建议前者。后者会引入 probe geometry、sorter/GPU、人工 curation、双光子 ROI 参数和数日级长作业，范围和验证成本完全不同。

## 最终建议

把项目命名为“多模态神经数据 preprocessing”，而不是“统一侵入式 preprocessing”。实现上以 NWB 为主标准、DANDI 为版本/分发约定、OME-Zarr 为大影像后端；现有 EEG 的 Unit/Method/Planner/Runner 机制继续使用，但把 channel-matrix/single-sfreq 假设替换为 representation、entity identity 和 multiple timebases。

第一版成功标准不是“支持 Kilosort 和 Suite2p”，而是同一套可审计框架能无泄漏地复现 HC11、Area2 Bump、FALCON、Sinz 等官方张量，并能消费 Allen/MICrONS 发布版 NWB。完成这一层后，raw ephys、raw ophys 和 connectomics 才能作为独立、可验证的能力逐步加入。

## Sources

[^1]: Neurodata Without Borders, “NWB Format Specification 2.11.0,” official schema documentation, accessed 2026-09-12. https://nwb-schema.readthedocs.io/
[^2]: DANDI Archive, “Standardizing data” and “Get to know a Dandiset,” official documentation, accessed 2026-09-12. https://docs.dandiarchive.org/user-guide-sharing/converting-data/ and https://docs.dandiarchive.org/example-notebooks/tutorials/open_data_quick_start_2026/Get-to-know-a-Dandiset/
[^3]: OME-NGFF Community, “OME-Zarr specification 0.5,” official specification, updated 2026-09-08. https://ngff.openmicroscopy.org/0.5/
[^4]: BIDS Contributors, “Intracranial Electroencephalography,” official BIDS specification. https://bids-standard.github.io/bids-specification-ignore/src/04-modality-specific-files/04-intracranial-electroencephalography.html
[^5]: BIDS Contributors, “BEP032: Microelectrode electrophysiology,” official proposal status page, updated 2026-08-26; preview specification. https://bids.neuroimaging.io/extensions/beps/bep_032.html and https://bids-specification.readthedocs.io/en/relax-bep032/modality-specific-files/microelectrode-electrophysiology.html
[^6]: PyNWB Contributors, “Extracellular electrophysiology,” official PyNWB tutorial. https://pynwb.readthedocs.io/en/dev/tutorials/domain/ecephys.html
[^7]: Niso et al., “BIDS extension proposals for microscopy data,” *Scientific Data* 9, 2022. https://pmc.ncbi.nlm.nih.gov/articles/PMC9063519/
[^8]: Zhou & Wei, “Learning identifiable and interpretable latent models of high-dimensional neural activity using pi-VAE,” NeurIPS 2020; official repository and supplement. https://github.com/zhd96/pi-vae and https://proceedings.neurips.cc/paper/2020/file/510f2318f324cf07fce24c3a4b89c771-Supplemental.pdf
[^9]: Zhou & Wei, `rat_preprocess_data.py`, pi-VAE official repository. https://github.com/zhd96/pi-vae/blob/main/code/rat_preprocess_data.py
[^10]: Buzsáki Lab, “Achilles_10252013” session metadata. https://buzsakilab.com/wp/sessions/entry/51450/
[^11]: CRCNS, “hc-3: Hippocampal electrophysiology data”; Mizuseki et al., hc-3 supplementary methods. https://crcns.org/data-sets/hc/hc-3/about-hc-3/ and https://buzsakilab.com/content/PDFs/Mizuseki2013Supp.pdf
[^12]: Neural Latents Benchmark, official datasets page and `nlb_tools`. https://neurallatents.github.io/datasets.html and https://github.com/neurallatents/nlb_tools
[^13]: Pei et al., “Neural Latents Benchmark '21,” official OpenReview paper. https://openreview.net/pdf?id=KVMS3fl4Rsv
[^14]: Allen Institute, “Visual Coding — Neuropixels,” AllenSDK official documentation. https://allensdk.readthedocs.io/en/stable/visual_coding_neuropixels.html
[^15]: Allen Institute, `ecephys_spike_sorting`, official processing repository. https://github.com/alleninstitute/ecephys_spike_sorting
[^16]: Allen Institute, “Brain Observatory” and “NWB file organization,” AllenSDK official documentation. https://alleninstitute.github.io/AllenSDK/brain_observatory.html and https://alleninstitute.github.io/AllenSDK/brain_observatory_nwb.html
[^17]: Sinz et al., “Stimulus domain transfer in recurrent models for large scale cortical population prediction on video,” NeurIPS 2018; official code/data links are identified in the paper. https://papers.nips.cc/paper/7950-stimulus-domain-transfer-in-recurrent-models-for-large-scale-cortical-population-prediction-on-video.pdf and https://github.com/sinzlab/Sinz2018_NIPS
[^18]: Pachitariu et al., Suite2p official documentation and FAQ. https://suite2p.readthedocs.io/en/latest/index.html and https://suite2p.readthedocs.io/en/latest/FAQ/
[^19]: MICrONS Explorer, “Python tools”; DANDI, “MICrONS Dandiset 000402 demo.” https://tutorial.microns-explorer.org/python-tools.html and https://docs.dandiarchive.org/example-notebooks/000402/MICrONS/demo/000402_microns_demo/
[^20]: MICrONS Consortium et al., functional connectomics methods and results, open-access article. https://pmc.ncbi.nlm.nih.gov/articles/PMC11981939/
[^21]: FALCON Challenge, official datasets page and Python package. https://snel-repo.github.io/falcon/datasets.html and https://pypi.org/project/falcon-challenge/
[^22]: Wang et al., “FALCON Benchmark for Neural Decoding,” NeurIPS 2024 Datasets and Benchmarks Track. https://papers.nips.cc/paper_files/paper/2024/file/8c2e6bb15be1894b8fb4e0f9bcad1739-Paper-Datasets_and_Benchmarks_Track.pdf
[^23]: SpikeInterface Contributors, official documentation and preprocessing module. https://spikeinterface.readthedocs.io/en/latest/index.html and https://spikeinterface.readthedocs.io/en/stable/modules/preprocessing.html
