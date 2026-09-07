# 运行和查看 Data Preprocess 演示

演示使用固定种子生成的两名合成 EEG 被试，执行两条真实预处理流程。预期结果为 `completed: 4/4`。它验证软件执行与产物保存，不代表真实数据上的方法质量排名。

## 1. 运行合成示例

以下命令适用于本机已经安装好的 `.venv-eeg` 环境。在 PowerShell 中运行：

```powershell
cd E:\work\BrainAgent\backend
.\.venv-eeg\Scripts\python.exe scripts/preprocessing_smoke.py --root workspace/eeg-demo
```

`workspace/eeg-demo` 必须是新目录。再次运行请换一个目录名，并同步修改下面服务的输入和输出路径。首次安装依赖时，在 backend 目录使用 `uv`：

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-eeg'
uv sync --python 3.12 --extra dev --extra eeg
```

脚本不需要启动网页、不调用 LLM，会在 `backend/workspace/eeg-demo` 下生成：

- `bids/`：合成的标准 EEG 文件。
- `acceptance.json`：4 项运行是否完成、运行环境和方法验证收据。
- `plan.json`：两条流程的实际步骤、参数和初筛结果。
- `result.json`：各被试与方法的状态、前后统计和产物位置。
- `output/runs/`：处理后的 FIF、伏特数组、事件映射、模型和执行记录。

## 2. 启动网页和执行服务

保留三个 PowerShell 窗口。API 沿用项目根目录 `.env` 中已有的模型与加密配置；数值 Worker 不调用 LLM。端口 8000、5173 需要空闲。

窗口一，启动 API：

```powershell
cd E:\work\BrainAgent\backend
$env:DATABASE_URL_OVERRIDE = 'sqlite+aiosqlite:///./brain_agent_dev.db'
$env:DEFAULT_OWNER_ID = 'smoke-fixture'
$env:FRONTEND_ORIGIN = 'http://127.0.0.1:5173'
$env:PREPROCESSING_ROOT = 'E:/work/BrainAgent/backend/workspace/eeg-demo/output'
$env:PREPROCESSING_INPUT_ROOTS = '["E:/work/BrainAgent/backend/workspace/eeg-demo/bids"]'
$env:NO_PROXY = '*'
$env:PYTHONUTF8 = '1'
.\.venv-eeg\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

`smoke-fixture` 是示例脚本创建的资源归属。真实数据接入时应使用实际用户及其输入根目录。上述代理设置只影响这个终端及其子进程，用于本机开发服务直连。

窗口二，启动独立 Worker：

```powershell
cd E:\work\BrainAgent\backend
.\.venv-eeg\Scripts\python.exe -m app.preprocessing.worker --root E:/work/BrainAgent/backend/workspace/eeg-demo/output --input-root E:/work/BrainAgent/backend/workspace/eeg-demo/bids
```

窗口三，启动网页：

```powershell
cd E:\work\BrainAgent\frontend
$env:VITE_PROXY_TARGET = 'http://127.0.0.1:8000'
pnpm dev:web --host 127.0.0.1 --port 5173 --strictPort
```

停止时在三个窗口中分别按 Ctrl+C。API 与 Worker 必须使用同一个输出根；这里使用 `dev:web`，避免另起一个缺少 EEG 配置的后端。

## 3. 查看任务与下载结果

打开 [本地网页](http://127.0.0.1:5173/)，新建对话。先在另一个 PowerShell 窗口获取示例任务编号：

```powershell
(Get-Content -Raw E:\work\BrainAgent\backend\workspace\eeg-demo\result.json | ConvertFrom-Json).job_id
```

将编号填入下面的消息并发送：

> 请调用 data_preprocessing 查询任务〈任务编号〉的状态，展示预处理任务卡片和可下载产物。这是已经完成的合成示例，仅查询已有结果，查完后结束。

页面应显示「EEG 预处理 · 处理完成」和「已完成 4 / 4 项方法与记录组合」。展开「记录与产物」，再展开对应记录的「下载产物」：

- `data-epo.fif`：处理后的 EEG Epochs，可用 MNE 读取。
- `signal_V.npy`：精确保留物理值的数组，单位 V。
- `delta.json`：处理前后的通道、事件、Trial 与时长统计。
- `events.json`：原事件与输出 Epoch 的对应关系和丢弃原因。
- `provenance.json`：实际执行的步骤、参数及版本。

查询对话会调用配置的 LLM。若只查看已有状态，可直接打开 `http://127.0.0.1:8000/api/preprocessing/jobs/〈任务编号〉`，或使用 [API 文档](http://127.0.0.1:8000/docs)，不需要调用 LLM。

当前网页提供流程任务卡片与文件下载，尚未提供 EEG 波形对比页面。完整支持范围和真实数据输入协议见 [实现说明](data-preprocessing-implementation.md)。
