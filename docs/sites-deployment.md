# Sites 部署

Sites 项目标识保存在 `frontend/.openai/hosting.json`。访问权限设为 `public`，网页和 API 不发起 ChatGPT 登录。

2026-09-11 网页已发布至 https://brain-agent-eeg-workbench.shrewd-root-6935.chatgpt.site 。后端运行在本机，由 Cloudflare Tunnel 连接至 Sites；用户无需 GPT/ChatGPT 登录。

前端仍使用 Vue/Vite。`frontend/sites/build.mjs` 在现有构建后生成 Cloudflare Worker，提供所有页面、静态资源和同源 API 转发。构建命令为 `pnpm build`，转发验证为 `pnpm test:sites`。

新建工作流页面从后端读取预算默认值，展示候选数、搜索/方法调研/模型调用时限和资源上限。模型调用总时限从工作流创建时开始，包含数值等待；重试不会续期。预算只影响新建运行，历史运行保留冻结值。部署时须同时提供带有预算默认值接口的后端；不兼容服务仍可查看已有运行，新建按钮保持禁用。

## 后端连接

完整 Python、EEG 和训练运行环境仍需独立服务器或持续运行的本机服务。Sites 不承载 Python 科学计算进程。部署前在 Sites 设置：

| 环境变量 | 用途 |
| --- | --- |
| `BRAIN_AGENT_BACKEND_URL` | 后端 HTTPS origin，例如 `https://brain-backend.example.com`，不带路径 |
| `BRAIN_AGENT_BACKEND_TOKEN` | 可选服务间 Bearer token，必须保存为 Sites secret，并由后端入口验证 |
| `BRAIN_AGENT_OWNER_ID` | 可选固定 owner；默认 `sites-public` |
| `BRAIN_AGENT_STREAM_BRIDGE` | 本机临时隧道设为 `websocket`，保持聊天实时输出 |

未设置后端地址时，网页可以访问，但 API 返回 503，明确提示“Agent 后端尚未连接”。后端必须支持流式响应和长任务；临时隧道不等同于持续托管。

公开网站上的匿名访问者共用 `sites-public` 工作区。代理会丢弃浏览器提交的 owner、Cookie 和 Authorization，避免匿名访问者冒充本机已有 owner。原本的本机历史及工具凭据不会自动共享给网站。LLM 和凭据加密密钥继续只保存在后端。

## 本机运行与恢复

- 公开站点使用 `127.0.0.1:8001` 的独立 API 和 EEG Worker，数据库为 `.local/sites-connection/public.db`，任务目录为该目录下的 `workflows`、`preprocessing` 和 `offline-search`。原本 8000 端口的开发服务及其数据库保持独立。
- 连接网关监听 `127.0.0.1:8788`，只允许持有服务间密钥的 Sites Worker 访问；匿名直接访问隧道会返回 401。网关始终固定 owner 为 `sites-public`。
- `scripts/start-sites-connection.ps1` 启动网关和隧道，必要时调用 `scripts/start-sites-backend.ps1` 启动公开后端。连接前需准备官方 cloudflared Windows 可执行文件至 `.local/sites-connection/cloudflared.exe`。
- 后端启动脚本将本地提交检出至 `.local/service-builds/<完整提交>`，API 与 Worker 显式从同一干净副本导入；默认使用 HEAD，也可传入 `-Commit`。凭据继续在原本的本地环境文件读取，不复制进构建。构建目录不可在运行期间编辑，状态文件保存实际提交和路径。
- 新工作流记录执行构建绑定：全部登记应用源码/模板、登记依赖版本及 Python 平台。其他构建或缺少绑定的历史流程只读；开始、重试、自动恢复及直接阶段执行均在写锁前核对，阶段间再次检查。Git 文档提交和进程启动时间不单独改变执行身份；运行时配置、第三方原生工具和数据仍由各自原有合同约束。这不支持把活动进程热升级到另一构建。
- `scripts/stop-sites-connection.ps1` 只停止网关和隧道。公开后端进程记录在 `.local/sites-connection/backend-state.json`；停止前核对 PID、创建时间和可执行路径，避免终止复用 PID 的其他进程。
- 密钥保存在被 Git 忽略的 `.local/sites-connection/secret.json`，并保存为 Sites secret。不要把该文件或日志提交到源码。
- 当前采用临时 Quick Tunnel：保持电脑开机、联网、不休眠以及后台进程运行。隧道重新启动后会得到新的 HTTPS origin，需要让 Codex 更新 Sites 的 `BRAIN_AGENT_BACKEND_URL` 并重新部署已有版本。不是开机自启服务。
- 电脑重启后，旧状态文件中的 PID 可能已失效；先核对并归档旧状态，再运行启动脚本。脚本遇到已有状态会停止，避免重复启动或误停其他服务。

Cloudflare [Quick Tunnel 文档](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)说明临时隧道不保证可用性，且不支持直接 SSE。聊天通过经过认证的 WebSocket 桥传输，Sites Worker 再输出浏览器原本使用的 SSE 格式；普通 API 与文件仍走 HTTP 转发。

## 连接验证

2026-09-11 已通过线上健康、Agent、workflow、数据源、search 和 integration 六个接口检查，均返回 200。通过公开 Sites URL 创建测试会话、调用真实 LLM 聊天，并收到 `run_started`、`thought`、`run_completed` 和 `stream_completed`；测试会话已删除。网关 3 项测试、Sites Worker 5 项测试通过，公开 API 与 EEG Worker 进程在运行，配置的 1 个数据源目录存在。未启动完整 EEG 处理或训练任务。验证记录保存在 `.local/sites-connection/verification.json`。

## 发布源代码

发布时从 `frontend` 创建独立的干净部署副本，包含当前前端源代码、锁文件和 `.openai/hosting.json`，排除依赖、缓存、本地环境文件。不要把整个研究仓库、数据集、数据库或本地凭据推送到 Sites。构建产物必须对应实际推送的完整提交。
