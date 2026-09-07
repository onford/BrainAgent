# Data Preprocess 首版实现与运行

2026-09-07。实现以讨论方案的 A+B 为范围：已有标准 EEG 的方法规划、真实执行、可追溯结果和基本恢复。四个核心部分仍为基本单元库、方法库、规划器、执行器。

## 已交付范围

| 部分 | 当前能力 |
|---|---|
| 基本单元 | 新版 50 项定义及全部原始代码入库，代码哈希校验；启用下表 8 类、9 个操作 |
| 方法库 | 两个 MNE 项目模板；经典调研子 Agent 的显式更新入口；Survey 文献全文证据与方法提取入口 |
| 规划 | 输入/版本核验、参数绑定、通道/状态/依赖/拟合范围检查、严格去重、机制多样性与预算初筛 |
| 执行 | BrainVision BIDS-EEG 读取、工作副本、校准分支、模型/决定绑定、数据与事件映射、数组/模型落盘及重读 |
| 任务 | SQLite 持久化、独立单 Worker、重复提交幂等、逐记录失败隔离、取消、重跑、进程中断恢复 |
| 接入 | Agent 结构化 inputs、API、现有对话任务卡片、进度查询、计划提交与产物下载 |

| 单元 | 当前启用操作及范围 |
|---|---|
| EEG-DETREND | detrend：constant / linear，明确 EEG picks |
| EEG-FILTER | filter：4 阶 Butterworth IIR、zero phase、Raw、明确 EEG picks；其余参数使用源表固定默认 |
| EEG-REREFERENCE | reference：average 或明确 EEG 参考电极 |
| EEG-EPOCH | epoch：事件切段，允许保留辅助通道；保留 selection 和 drop_log |
| EEG-BASELINE | baseline：Epochs，明确时间范围 |
| EEG-EOG-REGRESSION | eog_fit / eog_apply：真实 EOG 通道、一个明确的训练/校准连续区间 |
| EEG-AMPLITUDE-THRESHOLD | amplitude_windows：只生成候选与分数/掩码 |
| EEG-BAD-CHANNEL-MARK | mark_channels：绑定同一输入版本的检测决定，检查合并后坏道比例 |

这 9 个操作采用有限值输入合同。NaN 原生处理、重采样、ICA、插值、ASR、autoreject、完整 PREP/RELAX 及其他变体保留原表实现和未接入状态，需要逐操作补适配、依赖和验证。没有把 50 项的语法通过记为 50 项集成验证通过。

两个预定义模板是 `mne-project-baseline` 与 `mne-project-eog-regression`，均明确标记为项目改编流程。频带、Epoch 时间和基线参数由请求提供；MNE 没有在此被称为全任务统一默认流程。两个模板初始为 draft，须通过验证运行及发布接口，才可用于 production。

## 本地启动

EEG 运行固定使用 Python 3.12；数值库与源表目标版本一致，完整安装解析见 `backend/uv.lock`。在 backend 目录执行：

```powershell
uv sync --python 3.12 --extra dev --extra eeg
$env:PREPROCESSING_ROOT='E:/work/BrainAgent/backend/workspace/preprocessing'
$env:PREPROCESSING_INPUT_ROOTS='["E:/datasets/standardized"]'
uv run --extra dev --extra eeg uvicorn app.main:create_app --factory --port 8000
```

另一个终端使用**相同环境、相同绝对输出路径**启动 Worker：

```powershell
uv run --extra dev --extra eeg python -m app.preprocessing.worker
```

API 需要已有 LLM 和凭据加密配置，配置方法沿用 README；Worker 的数值执行不调用 LLM。API 重启或对话断开不会停止独立 Worker。一个输出根只允许一个 Worker，操作系统文件锁在进程退出时释放，不会根据过期心跳抢占仍存活的进程。

Docker Compose 增加独立 `preprocessing-worker` 和共享持久化输出卷，`./data` 挂载为只读输入。镜像使用冻结锁文件安装 EEG 依赖。本次验证在 Windows 本地执行，未运行 Docker 容器。

## 上游如何交付

`POST /api/preprocessing/inputs` 接收一份 `PreprocessInput`，返回带哈希的不可变引用。完整结构由 `/docs` 的接口模式给出，也可用后面的合成验收脚本生成 `input.json` 样本。

- Survey：dataset_id/version、survey_run_id、任务、事件码与含义、既往处理历史、可核查事实；明确列出尚未解决的阻塞事实。
- Collection：标准化根目录、BIDS 版本、结构检查证据、筛选后记录 ID；各记录有 BrainVision 相对路径、完整文件组及 SHA-256、采样率、样点数、通道类型与**独立通道顺序**、参考信息。
- 拟合片段：以原记录零起点样点表示 `[start, stop)`，有唯一 ID 与 train/calibration/test 角色。首版只拟合一个连续区间，拒绝 test 范围。

首版支持本地 UTF-8 BrainVision 的 `.vhdr/.eeg/.vmrk` 文件组、记录级 `_eeg.json` / `_channels.tsv` / `_events.tsv`。还需 root/subject/session 的实际伴随文件；所有记录文件清单的并集应覆盖整个输入树。事件 `trial_type` 应在 Survey 定义中，`value`、`sample` 如存在则必须一致。继承解析由 MNE-BIDS 处理，执行需要的元数据必须包含在当前工作副本中。未支持的格式和不完整文件组会明确拒绝。

Data Collection 当前仍有占位业务逻辑；生产接入需要上游或调用方实际提交这份协议。开发样本必须标记 `development_fixture`，不能直接以 production 模式运行。

## 方法与一次运行

| 接口 | 用途 |
|---|---|
| GET `/api/preprocessing/units` | 50 项来源定义、已启用操作、参数模式、依赖与验证范围 |
| GET / POST `/api/preprocessing/methods` | 加载预定义模板 / 注册方法草案 |
| POST `/api/preprocessing/methods/research` | 显式调用 ClassicPipelineSurveyAgent 调研与提出草案 |
| POST `/api/preprocessing/evidence` | 保存原文证据；完整内容与给模型的摘要分开 |
| POST `/api/preprocessing/literature` | 接收 SurveyLiteratureBundle，提取方法或返回具名补充请求 |
| POST `/api/preprocessing/plans` | 参数绑定与初筛，返回冻结计划与筛选理由 |
| POST `/api/preprocessing/jobs` | 提交 plan_ref；立即返回 202 和 job_id |
| GET `/api/preprocessing/jobs/{job_id}` | 持久化状态、逐记录尝试、错误、产物索引 |
| POST `/api/preprocessing/jobs/{job_id}/cancel` 或 `/retry` | 步骤边界取消 / 重跑未完成记录 |
| POST `/api/preprocessing/methods/publish` | 用 method_ref 与成功验证 job_ids 发布 validated 版本 |

所有资源归属沿用现有 owner 机制。下载只能读取该用户已完成记录的产物索引，并验证文件哈希，不能传任意本地路径。

计划请求示意（替换真实引用；参数只是合成验收样例）：

```json
{
  "input_ref": {"id": "<64位内容哈希>", "sha256": "<相同哈希>"},
  "methods": [{"id": "<方法内容哈希>", "sha256": "<相同哈希>"}],
  "mode": "validation",
  "parameters": {"l_freq": 1, "h_freq": 35, "tmin": -0.2, "tmax": 0.5, "baseline": [-0.2, 0]},
  "selection": "diverse",
  "max_candidates": 3,
  "max_memory_mb": 2048,
  "max_disk_mb": 8192
}
```

生产模式检查方法验证收据、当前实现与环境以及实际验证过的参数配置。改变参数需新一轮验证。经典调研结果保留证据核对缺口；Survey 文献提取需要实际存储全文及逐字可定位的证据段落，只有搜索标题/摘要时会返回 paper_id、缺失项和补充位置。

## 结果和恢复

每个“方法 × 记录”有独立尝试目录，保存：FIF 数据、精确保留物理值的 `signal_V.npy`、实际参数和版本、诊断数组、EOG 模型与拟合集合、检测决定、事件/Epoch/Trial 映射、前后统计与失败信息。大数组不放进对话或数据库。

FIF 即使使用 double 数据仍会保存 float32 校准字段，因此检查读取后的误差界并报告实际最大误差，同时另存精确的伏特数组。事件映射保留原事件行号、绝对样点与时间量化误差；同一 Trial 的多个事件允许映射到多个 Epoch，统计分别列出全部保留与部分保留的 Trial。Epoch 时长统计为片段样点时长之和，重叠片段可能重复计时。

EOG 校准分支先截取原始校准区间，再重放滤波/参考操作，避免滤波把测试区间带入模型拟合。模型保存内容哈希、实际区间、通道/参考/投影签名。步骤只调用已登记代码，运行时不执行 CSV、LLM 代码或任意导入路径。

取消在步骤边界生效。中断后重新核验冻结输入和环境，整条未完成记录从头重跑，尝试编号递增。已完成记录通过文件校验与数据重读后复用，损坏结果重新计算。源数据与输出根必须分离；输入树在执行前后核验。

当前预算是保守的预执行内存与磁盘估算，包含 Epoch 扩张、工作副本与诊断产物，不是操作系统级资源限额。暂不提供跨方法缓存、逐步骤恢复、分布式 Worker 或自动质量排名。

## 可复现测试

```powershell
# backend
uv run --extra dev --extra eeg pytest -q
uv run --extra dev --extra eeg python scripts/preprocessing_smoke.py --root workspace/eeg-smoke

# frontend
pnpm test
pnpm build
```

合成验收脚本要求新输出目录，生成两名被试、真实 BIDS BrainVision 文件、两条候选流程，以及输入、计划、运行结果和验证发布收据。固定随机种子；不使用私人 EEG，不联网调研。单元与流程验收包含源文件完整性、已知合成伪迹、校准隔离、全空 Epoch 失败、模型和产物重读、初筛、用户归属、进程恢复以及对话进度。

这验证的是软件执行正确性和完整性。真实数据上的质量比较、最佳结果选择与最终交付仍分别由 Evaluation / Delivery 负责。
