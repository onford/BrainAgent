# Brain Agent

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

然后编辑 `.env`。下面三个 LLM 配置必须填写：

```dotenv
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
```

项目使用 OpenAI-compatible Chat Completions API。自建服务或其他兼容服务需要提供：

```text
POST {LLM_BASE_URL}/chat/completions
```

并支持 JSON response format。

`LLM_API_KEY` 没有配置或为空时，后端会拒绝启动，并提示：

```text
LLM_API_KEY is not configured
```

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

## 7. Docker 打包运行

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

## 8. 常见启动问题

### 后端提示 `LLM_API_KEY is not configured`

确认项目根目录存在 `.env`，并且下面的值不是空字符串：

```dotenv
LLM_API_KEY=your-api-key
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
