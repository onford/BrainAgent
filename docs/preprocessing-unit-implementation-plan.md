# Data Preprocess 附件：50 项基本单元

更新：2026-09-06。以 [飞书《预处理基本单元》](https://wcnoz2fqndr2.feishu.cn/docx/C0uOdP3GooCAlqxom6CcpeOPnRe) 当前表格为定义来源；本次通过表格全选复制，读取其十列与全部 50 行，保存 [规范化 CSV 快照](E:/work/BrainAgent/docs/sources/preprocessing-units-feishu-2026-09-06.csv) 和 [逐字段差异记录](E:/work/BrainAgent/docs/sources/preprocessing-units-feishu-2026-09-06-diff.json)。

CSV SHA-256：12e4b3e18ebdab8e2d935b9bab2283d0b4331340eafaebd017fc8de420603004。2026-09-06 是本次读取日期；父文档显示的修改时间不用于推断内嵌表格版本。

## 1. 当前范围与核查程度

当前共 **50 个唯一 ID，50 项均提供代码**。与旧 CSV 的 43 项相比，新增 14 个 ID、移除 7 个；保留的 36 项中，25 项代码变化，11 项仅修改描述。旧版“23 项附代码、20 项待接入”不再代表当前来源。

十列仍为 id、输入合同、输出合同、参数、代码、描述、其他产物、完成条件、验证、父记录；父记录全部为空，执行依赖仍由方法步骤及合同表达。

本次读取全部合同、参数、产物和验证说明，对 50 份代码做语法解析，并静态查看入口、操作分支、依赖和关键变更；未执行代码、安装环境或复验数值。源表部分“验证”列已声称实际运行通过，并引用 core/results、proposal/core/results 或实现审阅报告；这些收据尚未取得，保存为 source_claim，不等同本项目 verification_passed。

## 2. 旧 ID 的迁移关系

以下是根据新版定义作出的能力迁移判断，不表示参数或数值完全等价。旧计划继续绑定旧快照；新计划按新版 ID/op/profile 重新编译。

| 旧 ID | 当前承接位置 | 需要重新核对 |
|---|---|---|
| `EEG-NOTCH` | EEG-FILTER / notch | 参数、边界及实际实现版本 |
| `EEG-CLEANLINE` | EEG-SINE-REGRESSION / cleanline | 固定作者源码、Octave 环境、尾段与统计 |
| `EEG-AMPLITUDE-FLAT` | EEG-AMPLITUDE-THRESHOLD / amplitude_detect | 相邻差判据及原参数语义 |
| `EEG-BAD-CHANNEL-FLAT` | EEG-AMPLITUDE-THRESHOLD / flat_detect | 平直时长、容差、断点和比较符号 |
| `EEG-BAD-CHANNEL-AMPLITUDE` | EEG-AMPLITUDE-THRESHOLD / amplitude_windows | 峰峰值、有效窗分母与比例 |
| `EEG-PREP-BAD-CHANNEL` | EEG-BAD-CHANNEL-ENSEMBLE / prep_detect 或 prep_detect_native | 参数化与原生联合检测、共享状态及随机流 |
| `EEG-TRIAL-INTERPOLATE` | EEG-INTERPOLATE / trial_interpolate | 掩码、Trial ID、供体与坏道状态 |

净新增能力还包括回归基线、窗口 MAD、频谱斜率、EOG 阶跃、联合概率、峰度、眨眼 IQR、稳健参考、逐 IC 眨眼权重、坏道删除预算和肌电 Trial 决策。旧 ID 移除不代表对应操作消失。

## 3. 50 项单元当前覆盖

此表概括新版代码提供的操作及接入重点。完整函数、全部参数、默认值和源验证说明以版本化 CSV 为准；下列验收项是 BrainAgent 后续集成工作。

| 当前 ID | op / 变体 | 关键合同及接入验证 |
|---|---|---|
| EEG-CROP | crop、crop_join | 单段闭区间裁剪；半开保留区间拼接须绑定决定，同步辅助道、注释、旧新样点与事件 |
| EEG-DETREND | detrend | constant/linear；Raw 按采集断点拆分，未选通道及事件保持 |
| EEG-FILTER | filter、butter、notch | 按 op 区分 Raw/Epochs、EEG/辅助道、注释策略及 FIR/IIR 参数；显式 NaN 策略与频带元信息 |
| EEG-SINE-REGRESSION | spectrum_fit、cleanline | MNE 指定频率正弦估计与作者 CleanLine 分开；后者锁定源码/Octave、迭代、覆盖和保留尾段 |
| EEG-RESAMPLE | resample、resample_fft、resample_fir、resample_eeglab、decimate | 区分 polyphase、FFT、显式 FIR、EEGLAB 配方和不另滤波的 Epoch 抽取；保留分数事件、碰撞、越界和首网格偏移 |
| EEG-REREFERENCE | reference、relax_car、reference_estimate、reference_apply | 供体与目标分离；参考向量绑定采样/时轴/选择；RELAX C+1 参考独立于普通 CAR |
| EEG-REST | rest | 外部 Forward 与通道、几何和参考兼容；单位 V |
| EEG-CSD | csd | 输出 csd 类型及 V/m²，后续按空间导数接收 |
| EEG-BAD-CHANNEL-LOF | lof_detect | 至少两个好 EEG；请求邻居数裁到好道数−1，保存请求值与实际值及分数轴 |
| EEG-AMPLITUDE-THRESHOLD | amplitude_detect、flat_detect、amplitude_windows、absolute_voltage | 相邻差、最长平直段、窗口峰峰值和绝对电压分别验收；检测不修改波形/标记 |
| EEG-MUSCLE-DETECT | muscle_detect | 真实带宽满足高频判据；保留 BAD 屏蔽的评分 NaN、有效掩码与时间框架 |
| EEG-BAD-CHANNEL-MARK | mark_channels、mark_repaired | 坏道并集与确认修复后清除分开；清除须绑定修复决定并保留前后状态 |
| EEG-BAD-SEGMENT-MARK | mark_segments | 应用当前数据版本的 BAD 决定；核验 orig_time、first_samp 与区间 |
| EEG-BAD-CHANNEL-DROP | drop | 仅删除已标坏 EEG，保留来源理由、通道映射及至少一个好 EEG |
| EEG-ICA | ica_fit、eog_assess、ecg_assess、muscle_assess、ica_apply | 支持 FastICA/Picard/Infomax，分别核验参数、拟合高通与收敛；评估、决定、应用及模型身份分开 |
| EEG-EOG-REGRESSION | eog_fit、eog_apply | 真实 EOG、固定参考；实际训练/校准范围、不跨 BAD/断点；模型和移除信号可恢复 |
| EEG-SSP | ssp_apply | 仍只应用已审核 Projection，未提供 SSP 拟合；保存投影身份与秩变化 |
| EEG-BRIDGE-DETECT | bridge_detect | 电距离单位 µV²、上三角有效，保留原通道映射；KDE 退化明确失败 |
| EEG-BRIDGE-REPAIR | bridge_repair | 绑定桥接对、坐标及簇上限；保存修复前信号与影响范围 |
| EEG-INTERPOLATE | interpolate、spherical、interpolate_native、trial_interpolate | 区分全局/逐 Trial、MNE/Perrin/EEGLAB 配方；按 op/profile 推导 bads 是否清除、供体和非有限值条件 |
| EEG-EPOCH | epoch、epoch_with_nonfinite | 显式 picks 可保留 EOG 等辅助道；后者标注并排除含非有限样点的片段，全部丢弃为失败 |
| EEG-TRIAL-REJECT | reject_trials、drop_mask | 阈值拒绝与确认掩码应用分开；当前位置、原 selection 和 Trial ID 分开保存 |
| EEG-BASELINE | baseline | 均值基线；窗口有任务依据，校验事件与形状保持 |
| EEG-ZAPLINE | zapline_plus | 固定作者算法及 Octave/SciPy profile；采样率/通道/时长/谱网格条件，分块覆盖、成分及 sigma 迭代 |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect、prep_detect_native | 共享构造检查、判据与 RNG 状态；native 可识别 NaN，Inf 拒绝；联合检测不等价于独立单判据重建 |
| EEG-BAD-CHANNEL-DEVIATION | deviation_detect | 固定 PyPREP、实际阈值和检测副本；分数、映射、随机状态；零尺度明确无法判定 |
| EEG-BAD-CHANNEL-CORRELATION | correlation_detect | 相关窗、阈值、坏窗比例与构造状态；保存分数、有效分母与候选 |
| EEG-BAD-CHANNEL-HF-RATIO | hf_ratio_detect | PyPREP 高频残差判据，阈值/频带与检测状态明确 |
| EEG-BAD-CHANNEL-LINE-NOISE | line_noise_detect | Welch 平均 PSD 带积分比；互不重叠频带、带边界插值、零背景未定义 |
| EEG-ICLABEL | iclabel_assess | 固定 mne-icalabel 权重、torch/onnx 后端、IC×7 概率及 component_id；实际 CAR 残差和域标记按方法处理 |
| EEG-MARA | mara_assess | 锁定作者代码、训练资产、EEGLAB 坐标和 Octave 工具箱；六特征、后验和 IC 身份 |
| EEG-ADJUST | adjust_assess | 锁定作者代码、坐标尺度及区域覆盖；Epoch/IC/电极前提，特征、EM 阈值和四类候选 |
| EEG-FASTER-IC | faster_ic_assess | 固定 mne-faster 1.2.2 指标；逐轮 z、未定义标志与候选，不直接改 ICA 排除列表 |
| EEG-SASICA | sasica_assess | 自身指标加已绑定 ADJUST/FASTER 结果；缺人工决定保持 pending，只有确认排除项可用于 apply |
| EEG-ASR | asr_fit、asr_apply | 固定 asrpy 0.0.8 欧氏 correction；校准范围、lookahead 补偿和样点保持；当前不声明 ASR rejection 分支 |
| EEG-WICA | wica_apply：ordinary/targeted | RELAX 两种变体；固定小波/阈值、EEGLAB 激活与回投；targeted 依赖概率、Eye 权重、决定和带宽 |
| EEG-CCA | cca_fit、cca_apply | 单边延迟、满秩协方差、无正则；范围、冻结排除决定、相关及回投 |
| EEG-MWF | mwf_fit、mwf_apply | 固定 mask/干净与伪迹样本、延迟协方差/GEVD/秩；NaN 掩码策略、模型兼容和移除信号 |
| EEG-AUTOREJECT | autoreject_fit、autoreject_apply：global/local | 固定 autoreject 0.5.0、真实 CV、阈值/损失、局部修复和 Trial 分区；两模式分别验证 |
| EEG-REGRESSION-BASELINE | regression_baseline_epochs_fit/apply、regression_baseline_fit/apply | Epochs 与数组入口；训练因素、逐通道系数与满秩；冻结应用不需要测试标签，只移除基线贡献 |
| EEG-WINDOW-MAD | window_mad、blink_upper_bound | 诊断窗 ptp/MAD 与眨眼上界；有眨眼窗/上尾回退、Hazen 分位、并列和通道轴 |
| EEG-SPECTRAL-SLOPE | spectral_slope | 明确频谱模式、频点与拟合范围；require/author_attenuated 有来源差异，不能只按 Nyquist 判断 |
| EEG-EOG-STEP | eog_step | Epoch EOG 阶跃；通道差方向、两侧窗含中心、trimmed mean/mean、原 Trial 映射 |
| EEG-JOINT-PROBABILITY | joint_probability | 固定直方图、局部/全局量及 Epoch 轴标准化；零尺度未定义和阈值 0 关闭语义 |
| EEG-KURTOSIS | kurtosis | 未校正 Pearson 峰度及 Epoch 轴标准化；局部/全局、零尺度与单位缩放 |
| EEG-BLINK-IQR | blink_iqr | 独立检测副本、临时补道及 C+1 参考证据；原版/repaired 索引 profile、边缘及峰事件 |
| EEG-ROBUST-REFERENCE | prep_reference_fit、prep_reference_finalize | PyPREP 0.7.1 迭代参考；fit 返回待最终插值状态，finalize 绑定数据/状态后只执行一次 |
| EEG-IC-BLINK-WEIGHTS | eye_weights | IC×样点权重绑定 ICA 和参考；原版/repaired 时间/索引 profile、最短长度与平滑 |
| EEG-CHANNEL-REJECTION-BUDGET | relax_budget | 极端/肌电坏道预算；原始通道分母、并列与 profile；只产决定，不直接删道 |
| EEG-MUSCLE-TRIAL-DECISION | relax_muscle_trials | 逐 Trial 肌电斜率、最坏比例与并列规则；输出掩码再交 EEG-TRIAL-REJECT |

## 4. 对现有工程规划的影响

统一结构仍使用 UnitSpec、MethodSpec、ExecutionPlan、RunResult，详见 [主方案](E:/work/BrainAgent/docs/data-preprocessing-v2-plan.md)。本次需要更新其内容和检查粒度：

1. **支持状态细化到 op/profile。** 同一 ID 有不同算法、输入类型、参数和产物，单元级“可用”不足以表达部分支持。源验证声明与本项目集成验证分别保存。
2. **首次导入保留整份源码。** 部分行通过重复定义公开入口、保留旧函数别名来扩展 op；提取第一个 def 或只保留最后一段都会丢失行为。稳定后再有依据地重构；未知 op 的 NotImplementedError 不能作为“整行是占位代码”的判断。
3. **环境与资产按操作锁定。** Python/MNE 基线仍在代码中声明，但新增 PyPREP、ICLabel、asrpy、autoreject、PyWavelets、作者源码/权重与 Octave 工具箱；不能把所有操作当作同一组纯 Python 依赖。
4. **按操作处理 NaN、参考和 bads。** source profile 允许的 NaN 传播、检测或最终修复走明确状态；interpolate_native 和 mark_repaired 可清除修复标记。保持数据状态推导，避免沿用“全部有限”“插值总保留 bads”等旧规则。
5. **时间与决定可直接组合。** crop_join、分数事件重采样、epoch_with_nonfinite、drop_mask、Trial 插值及新增预算/拒绝单元需要明确的样点、事件、Trial 和决定引用。
6. **来源变体进入方法身份。** 原版与 repaired profile、ordinary/targeted、原生/参数化检测及 author_attenuated 不能在去重或缓存中合并。参考向量、稳健参考状态和 RNG 也属于需要保存的产物。

## 5. 已更新的理解与仍需验证的部分

ICA 已不再限于 FastICA/EOG；Epoch 已可显式保留辅助道；wICA 已包含 ordinary 和 targeted；完整稳健参考已有独立单元；逐 Trial 插值与多个检测操作已合并进相应 ID。源表同时明确了一些范围：SSP 仍只有应用，ASR 当前为 correction，SASICA 的排除仍依赖人工确认。

PREP、RELAX 等方法的“缺少算法代码”清单需重算。已有这些单元不自动证明整个方法忠实完成：仍要检查来源版本、顺序、默认值、profile、辅助通道往返、模型/状态传递和全部必需产物。

开发统一按主方案 A/B/C 推进：先接一条真实流程，再接两种方法来源和多候选，最后按需扩展其余操作。当前工作重点是复用 50 项已有代码及其验证资料，完成依赖探测、适配、集成验证；不再把旧表的 20 项整体列为从零开发。
