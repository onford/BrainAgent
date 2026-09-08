# 六模块训练数据流程

输入本地 EEGMMIDB 目录，输出带左右手运动想象标签的 Epoch 数组、被试分组、报告与可核验的数据包。当前候选随机选择，`quality_evaluated=false`，不产生 best output 或质量排名。

## 运行入口

本机应用：[数据流程](http://127.0.0.1:5173/workflows)。启动脚本 `E:/work/BrainAgent/.local/start.ps1` 同时启动 API、前端与独立 Worker；停止使用同目录的 `stop.ps1`。页面填写目录和被试数后点击“开始完整流程”，可查看六模块进度、失败原因、报告和下载链接。

也可从 `E:/work/BrainAgent/backend` 单独执行：

```powershell
.\.venv-eeg\Scripts\python.exe -m app.workflows --source-root E:/dataset/eeg/EEGMMIDB --subjects S001 S002 S003
```

命令会启动独立计算进程，并在完成后停止该进程；不需要 LLM、聊天数据库或外部检索凭据。默认输出在 `backend/workspace/training-cli/`。终端打印流程 ID、状态和交付目录；退出码 0 表示全部完成。支持 `--runs 4 8 12`、`--seed 42`、`--tmin 0`、`--tmax 2`、`--root PATH`、`--timeout 1800`；续跑时传入相同的 `--root`、`--source-root` 和 `--resume WORKFLOW_ID`。同一存储目录同时运行一个 Worker。

Python 环境需安装 `backend/pyproject.toml` 中的 `eeg` 依赖；验收环境为 Python 3.12、MNE 1.10.2、NumPy 1.26.4。新环境可在 backend 中用 `uv sync --python 3.12 --extra eeg --extra dev` 安装，然后通过 `uv run python -m app.workflows ...` 运行。

Web 服务与 Worker 共用以下配置。路径建议使用绝对路径，源目录和输出目录必须分离：

```dotenv
PREPROCESSING_ROOT=E:/work/BrainAgent/backend/workspace/training-workflow/preprocessing
WORKFLOW_ROOT=E:/work/BrainAgent/backend/workspace/training-workflow/workflows
WORKFLOW_INPUT_ROOTS=["E:/dataset/eeg/EEGMMIDB"]
```

Worker 启动命令为 `python -m app.preprocessing.worker`，默认允许读取 `WORKFLOW_ROOT` 下的标准副本。显式使用 `--input-root` 时应包含该目录。Docker Compose 已增加共享 workflow 卷及 Worker 输入目录，容器方式未在本机验收。

## 各模块的实际工作

运行页的“全部产出文件”按模块列出文件名、大小和下载链接，包括 BIDS 标准副本、两种候选的全部处理记录及交付溯源。模块完成后即可下载已有产物；Worker 完成的记录会在轮询时加入，失败及历史尝试的诊断文件也保留入口。原始数据和 Worker 临时输入副本不作为重复产物列出。下载继续检查所属用户和文件哈希。旧版已完成运行会补齐文件入口，保留原报告；旧版未完成运行续跑时转为结构协议，并复用已有数值结果。

## 过程结构与报告模板

过程输出由 `backend/app/workflows/contracts.py` 定义 Pydantic 模型，在 Agent 返回处和流程接收处校验。缺失必需字段、附加未声明字段、悬空通道引用或不在候选集合中的选择都会使当前模块失败，无法被标记为完成或传给下游。无需用提示词维持输出格式。

每次运行的 `process/schema.json` 导出同源 JSON Schema。`process/index.json` 保存请求、阶段状态、结构记录路径及 schema 引用；路径以本次运行目录为基准。各模块只保存一份主记录：

| 模块 | 主记录 | 主要内容 |
|---|---|---|
| 调研 | `survey/survey.json` | 数据集资料、公共通道表、逐记录读取结果、统计、来源、未确定字段 |
| 接入 | `collection/collection.json` | 标准副本引用、保留统计、排除原因、验证范围、格式适配 |
| 预处理 | `preprocessing/summary.json` | 候选方法与参数、逐记录状态/尝试次数/事件数/数组形状、产物目录 |
| 选择 | `evaluation/selection.json` | 完整候选、排除候选、随机种子及所选方法 |
| 报告 | `report/output.json` | 报告入口和格式 |
| 交付 | `delivery/output.json` | 数据包入口、形状、类别、分组和完整性结果 |

主记录使用缩进 JSON；相同的通道列表只保存一次，逐记录引用通道表。`workflow.json` 保存调度状态、事件和主记录路径，不再嵌入整份模块数据。TSV 适合逐行查看文件清单、事件映射和筛选变化；数值执行的原始证据仍可逐文件下载。

报告生成链路为：**已校验的模块 JSON → ReportData 字段摘取 → HTML 模板**。`report/report.json` 是精简的模板输入，`backend/app/workflows/templates/report.html` 负责章节和样式，`reporting.py` 负责转义及表格填充。报告生成不访问数值数据库、不重新计算过程统计。可仅复制索引和前四个模块主记录来重建报告；之后更换用户提供的模板时可复用这些结构化数据。

`delivery/output.json` 是数据包封装完成后的模块回执，位于压缩包外；包内完整文件列表和哈希以 `delivery/manifest.json` 为准。

## 模块职责

| 模块 | 输入与产物 |
|---|---|
| Data Survey | 使用版本化 EEGMMIDB 资料配置，扫描本地 EDF 清单；检查选定记录的采样率、通道、事件、时长和哈希；保存来源、Trigger 表和未确定字段 |
| Data Collection | 转为 BrainVision BIDS 工作副本，统一通道名并使用标准电极模板；检查信号有限值、转换前后误差和源文件哈希；输出 mapping、anomalies、exclusions、pre-screen、post-screen、delta |
| Data Preprocessing | 复用基本单元、方法库、规划器和独立 Worker，执行两条明确参数的工程训练预设，保存各候选信号、事件、参数及执行证据 |
| Data Evaluation | 对覆盖全部保留记录且产物完整的候选，以指定 seed 随机选择；保存可选与排除候选、选择原因；不计算质量优劣 |
| Data Report | 自动生成 HTML 报告与 JSON 摘要，列出数据、任务、接入统计、所选方法、逐记录 Epoch 数、来源与限制 |
| Data Delivery | 导出 X、y、subjects、split、标签、通道、Trial 索引、实际处理记录及训练示例；逐文件哈希、数组重读、ZIP 完整性核验 |

两条候选均为连续 EEG 带通 → 平均参考 → 事件分段，频带分别为 **1–40 Hz** 和 **8–30 Hz**。滤波采用 Butterworth 设计阶数 4、双向零相位 IIR；分段默认任务开始后 0–2 秒，包含终点，共 321 个采样点，不做基线扣除。它们在 `exploratory` 模式中执行，属于可运行的工程预设，未发布为经过科学验证的经典方法；不改变原有 `production` 模式的验证要求。

仅 Run 4、8、12 被接受，其含义为左右手运动想象，T1=左手、T2=右手；T0 休息不进入训练 Trial。Run 3、7、11 是实际运动，不被该适配器接受。事件说明见 [MNE 1.10.2 运行编号表](https://mne.tools/1.10/generated/mne.datasets.eegbci.load_data.html)，采集与资料来源见 [PhysioNet 数据集页](https://physionet.org/content/eegmmidb/1.0.0/)。

## 训练交付

`training-data.zip` 解压后包含：

| 文件 | 含义 |
|---|---|
| `X.npy` | float32，Trial × 通道 × 时间，单位 V |
| `y.npy` | int64，0=left_hand，1=right_hand |
| `subjects.npy`、`split.npy` | 每个 Trial 的被试及 train / validation / test 分组 |
| `trial-index.tsv` | 数组行到源记录、源样点、任务事件、Epoch 和分组的映射 |
| `labels.json`、`channels.json` | 类别含义、通道顺序、采样率、单位和时间窗口 |
| `method.json`、`selection.json`、`sources.json` | 方法定义、随机选择、资料与源文件哈希 |
| `provenance/` | 逐记录实际参数、环境版本、数据变化、保留/删除事件及原因 |
| `report.html`、`README.md`、`manifest.json` | 数据报告、读取说明、交付清单与哈希 |
| `train_example.py` | 仅用 train 拟合通道对数方差特征、StandardScaler 与逻辑回归的运行示例 |

被试用固定随机种子打乱；3 人及以上时最后一人分配到 test、倒数第二人分配到 validation，其余分配到 train。2 人时没有 validation，1 人时仅有 train；空分组写入清单限制。标准化和模型拟合仅使用 train。当前划分是小规模验收默认值，未设计通用的训练划分策略。

在解压目录中运行 `python train_example.py` 可检查训练与预测是否跑通；需 NumPy 和 scikit-learn。输出训练样本数、特征数和预测数，不给出准确率或候选排名。

## API 与恢复

- `GET /api/workflows/sources`：允许的源目录与适配器。
- `POST /api/workflows`：提交 `source_root`、`subjects` 或 `max_subjects`、`runs`、`seed`、`tmin/tmax`，返回 202 和流程 ID。
- `GET /api/workflows`、`GET /api/workflows/{id}`：列表、逐模块状态、事件与结果。
- `POST /api/workflows/{id}/retry`：重试失败或中断流程，复用已经完成的模块。
- `GET /api/workflows/{id}/artifacts/{name}`：检查归属及哈希后下载；HTML 支持 `?download=false` 预览。

后台编排调用注册的六个领域 Agent，等待预处理作业完成后再接续后面三个模块。API 返回“已提交”不等于完成。状态保存到 `workflow.json`，服务重启恢复 queued/running/interrupted；计算状态由已有 Worker 持久化保存。报告阶段失败后的重试不会重跑已完成的预处理。

归属沿用现有本地开发用户机制；这不是多租户生产认证。错误隔离和恢复为首版能力，不包括完整异常分类、任意输入格式、逐步骤断点或多 Worker 调度。

## 验收与后续范围

2026-09-08 使用本地 `E:/dataset/eeg/EEGMMIDB` 中 S001–S003 的 Run 4/8：6 条 EDF，746 秒，90 个任务事件。两条候选共 12 个方法×记录任务全部完成；交付形状 `[90,64,321]`，类别 0/1 为 46/44，三组各 30 Trial，源文件哈希保持不变。

页面提交的验收流程 ID 为 `f3ab0aa7bd484ceaa7025c5c09e8dfb4`，输出位于 `backend/workspace/training-workflow/workflows/`。已逐行对照原始 EDF 事件核对 90 个标签、对照所选候选核对 90 行信号、核验 31 个交付文件和 API 下载的 ZIP。训练示例仅在 S002 的 30 个 Trial 上拟合，并成功预测全部 90 个 Trial；没有用预测结果评选预处理方法。验证回执为 `.local/training-workflow-verification.json`。

最终自动检查：后端 81 项测试通过，前端 11 项测试通过，TypeScript 检查和 Vite 生产构建通过；新流程 Python 文件的 Ruff 检查通过。浏览器完成真实提交、完成态与 HTML 报告预览检查。测试中的 18 条警告来自已有依赖弃用提示和故意丢弃全部 Epoch 的异常用例。

测试覆盖真实 BIDS 转换、独立数值 Worker 调用、六 Agent 衔接、报告失败重试、服务重启恢复、数组/标签/源样点对应、按被试分组、训练拟合、随机选择复现、损坏候选排除、ZIP 哈希、下载归属与文件损坏。自动测试中的 EDF 解码用固定信号替代；真实 EDF 另通过命令行和页面完整验收。前端测试覆盖提交、重试、完成态、报告和下载入口。

完整自动文献综述、任意数据集的资料核对、复杂伪迹处理、质量评价与最优候选选择仍待扩展。首版 Survey 使用已核对的版本化资料配置，不声称每次运行都重新检索全文。报告模板位于 `backend/app/workflows/templates/report.html`，内容汇总在 `outputs.py`；后续可以在该边界替换报告样式和章节。
