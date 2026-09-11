# Brain Agent

EEGMMIDB 工作流将本地调研、资料核对、标准化接入、诊断驱动的预处理策略搜索、报告与训练交付连接起来。LLM 根据实测诊断提出共享策略及实验预测；数值工具按被试隔离计算开发效用，选择规则确定胜者。页面入口为 `/workflows`，见[运行说明](docs/training-workflow.md)。

[预处理策略搜索](docs/offline-preprocessing-search.md)支持公共处理、逐被试统一尺度、无标签 EA 与条件 EA；默认全部任务被试参加分组交叉验证。主评价器为 EEGNet（种子 17、42、2026 的被试宏平均 BA 等权均值），CSP＋收缩 LDA 仅为经典对照，适配数组及变换记录随选中策略交付。搜索页支持自适应、一次性提案、随机顺序与枚举对照。

Data Preprocess 首版已接入真实 EEG 执行。功能范围、上游协议、独立 Worker 和验收脚本见 [实现与运行说明](docs/data-preprocessing-implementation.md)。EEG 路径使用 Python 3.12，并安装 `--extra eeg`；原有对话开发环境可单独使用。

## 1. 开发环境要求

日常开发不需要 Docker，也不需要本机安装 MySQL。开发环境使用 SQLite，运行时会自动创建 `backend/brain_agent_dev.db`。

请先安装：

- Python 3.11 或更高版本
- Node.js 20 或更高版本
- pnpm 11
- uv

检查版本：

```bash
python3 --version
node --version
pnpm --version
uv --version
```

### 安装 pnpm

Node.js 自带 Corepack 时：

```bash
corepack enable
corepack prepare pnpm@11.19.0 --activate
```

如果系统没有 Corepack：

```bash
npm install -g pnpm@11.19.0
```

### 安装 uv

macOS 使用 Homebrew：

```bash
brew install uv
```

也可以使用官方安装脚本：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. 配置环境变量

在项目根目录执行：

```bash
cp .env.example .env
```

然后编辑 `.env`。LLM 配置和凭据加密主密钥都必须填写：

```dotenv
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY=your-fernet-key
```

生成凭据加密主密钥：

```bash
openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
```

将输出完整复制到 `BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY`。这个主密钥用于加密
GitHub token、学术 API key 等用户凭据。更换或丢失它会导致已有凭据无法解密，
请在部署环境的 secret manager 中妥善备份，且不要提交到 Git。

项目使用 OpenAI-compatible Chat Completions API。自建服务或其他兼容服务需要提供：

```text
POST {LLM_BASE_URL}/chat/completions
```

并支持 JSON response format。

`LLM_API_KEY` 没有配置或为空时，后端会拒绝启动，并提示：

```text
LLM_API_KEY is not configured
```

`BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY` 没有配置或格式错误时，后端也会拒绝启动。

当前项目尚未接入正式登录。开发环境默认 owner 为 `local-development-user`，可通过
`.env` 的 `DEFAULT_OWNER_ID` 修改；API 也支持 `X-Brain-Agent-Owner-ID` 请求头，供后续
认证中间件注入可信用户 ID。生产环境接入认证前，不应向公网开放该请求头。

不要将包含真实密钥的 `.env` 提交到 Git。

## 3. 安装项目依赖

### 安装前端依赖

```bash
cd frontend
pnpm install
```

### 安装后端依赖

回到项目根目录，然后执行：

```bash
cd backend
uv sync --extra dev
```

`uv` 会自动创建 `backend/.venv`，不需要手动运行 `python -m venv` 或 `pip install`。

## 4. 日常开发启动

进入前端目录运行：

```bash
cd frontend
pnpm dev
```

该命令会同时启动：

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- Swagger：http://localhost:8000/docs
- SQLite 数据库：`backend/brain_agent_dev.db`

按 `Ctrl+C` 会同时停止前端和后端。

### 分别启动前端或后端

只启动前端：

```bash
cd frontend
pnpm dev:web
```

只启动后端和 SQLite：

```bash
cd frontend
pnpm dev:backend
```

也可以直接从后端目录启动：

```bash
cd backend
DATABASE_URL_OVERRIDE=sqlite+aiosqlite:///./brain_agent_dev.db \
  uv run --extra dev uvicorn app.main:create_app --factory --reload --port 8000
```

## 5. 验证是否启动成功

检查后端：

```bash
curl http://localhost:8000/health
```

正常响应：

```json
{"status":"ok","llm_mode":"configured"}
```

然后打开前端：

```text
http://localhost:5173
```

主界面采用双栏对话布局：左侧保存并切换 session，右侧显示完整的
user-agent 对话。执行期间，orchestrator 的规划、Agent 调用和 observation
会通过 SSE 持续更新当前 assistant 消息；`Cmd/Ctrl + K` 可新建对话。

可以输入：

```text
请执行 EEG 数据的完整流程
```

左侧进入 `Tool integrations` 可配置 GitHub、Semantic Scholar、OpenAlex、Crossref、
Europe PMC、arXiv 和 Unpaywall。保存与“验证连接”是两个独立操作；secret 字段重新
打开后只显示掩码，留空保存不会覆盖旧值。

## 6. 运行测试

```bash
cd backend
uv run --extra dev pytest
```

测试使用测试目录内注入的 LLM test double，不读取真实 API，也不会改变正式运行行为。

前端类型检查和构建：

```bash
cd frontend
pnpm build
```

前端测试：

```bash
cd frontend
pnpm test
```

## 7. 后端日志

后端启动后会自动创建 `backend/logs/`，同时保留终端日志输出：

- `brain_agent.log`：ReAct orchestration、Planner、领域 Agent、tool call/result 和持久化错误。
- `llm.log`：LLM 模型、provider、消息数量、输入/输出字符数、token usage、request ID、耗时和异常堆栈。

两个文件默认达到 10 MiB 后轮转并保留 5 份历史文件。可以通过环境变量调整：

```dotenv
LOG_DIR=./logs
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
```

日志不会记录 API key、完整 prompt、完整 LLM response 或工具原始返回内容。
`backend/logs/` 已加入 `.gitignore`。Docker 启动时该目录会挂载到宿主机的
`backend/logs/`。

## 8. Docker 打包运行

Docker 用于打包、集成验证或部署，日常开发不需要使用。

Docker 环境使用 MySQL。确认 `.env` 已填写 LLM 配置后，在项目根目录执行：

```bash
docker compose up --build
```

容器服务：

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- Swagger：http://localhost:8000/docs
- MySQL：`localhost:3306`

停止容器：

```bash
docker compose down
```

如果需要同时删除开发容器创建的 MySQL volume：

```bash
docker compose down -v
```

该命令会删除容器数据库数据，请谨慎使用。

## 9. 常见启动问题

### 后端提示 `LLM_API_KEY is not configured`

确认项目根目录存在 `.env`，并且下面的值不是空字符串：

```dotenv
LLM_API_KEY=your-api-key
```

### 后端提示凭据加密密钥未配置

重新生成并填写：

```bash
openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
```

```dotenv
BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY=上一步的完整输出
```

### 找不到 `uv`

重新安装 uv，并重启终端：

```bash
brew install uv
```

### 找不到 `pnpm`

```bash
corepack enable
corepack prepare pnpm@11.19.0 --activate
```

### 端口已被占用

默认端口是：

- 前端：5173
- 后端：8000

关闭占用端口的旧进程后，重新执行 `pnpm dev`。
