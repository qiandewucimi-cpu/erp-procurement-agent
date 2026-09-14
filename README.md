# 外贸 ERP 安全操作 Agent

![CI](https://github.com/qiandewucimi-cpu/erp-procurement-agent/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![coverage](https://img.shields.io/badge/coverage-89%25-brightgreen)
![eval](https://img.shields.io/badge/eval-40%2F40%20passed-success)
![License](https://img.shields.io/badge/license-MIT-green)

一个面向 FDE / AI 应用工程岗位的可运行交付作品：把容易出错的“BOM → 采购 PO”人工流程，改造成**模型负责编排、确定性代码负责业务决策**的安全 Agent。

> 数据边界：只使用合成供应商、合同、物料、价格和单号；不连接、也不声称连接了真实企业生产 ERP。

## 面试官 60 秒速览

| 要看什么 | 本项目怎么做 | 可核验证据 |
|---|---|---|
| 是否真是 Agent | Function Calling 自主选择 8 个工具、参数与顺序，支持多轮上下文 | `erp_agent/llm.py`、工具轨迹、MCP stdio 冒烟 |
| 如何避免 LLM 误写 | 金额/校验/权限/状态迁移均为确定性代码；可信 action_id + 精确确认口令 | 25 条离线安全场景 + 15 条模型对抗场景，最近一次 40/40 |
| 是否具备企业交付思维 | ERPAdapter 隔离客户接口；RBAC、发起/审批分离、幂等、审计、回滚 | 98/98 单测，核心包覆盖率 89%，HTTP Adapter 故障与并发测试 |
| 出错能否定位 | request/session/actor/action/tool 关联 JSON 日志，提供延迟与成功率指标 | `GET /metrics`、递归脱敏测试 |
| 如何落地客户试点 | 先只读与影子模式，再小范围受控写入；明确停止和回滚条件 | 需求、ADR、安全、验收、部署、排障、试点文档 |

**最快验证路径：**双击 `start_demo.cmd` → 正常 BOM 生成 ¥24164 草稿 → 异常 BOM 被阻断 → 查看审批/审计；完整话术见 [`5 分钟演示脚本`](docs/面试演示_5分钟.md)。

面试前也可运行一条完全离线、不修改项目数据库的证据冒烟：

```powershell
python smoke_interview.py
```

## 一、3 分钟能看到什么

1. 用自然语言对话：「帮我根据 `正常示例_BOM.xlsx` 生成采购 PO 草稿，先给我看金额」。
2. 模型自主决定调用工具（可展开看工具调用轨迹），生成草稿并停下等确认。
3. 安全模式下由 operator 发起、approver 审批；输入 `确认提交` 后才写入，重复确认不会重复建单。
4. 追问「查一下 MAT-FAB-001 的价格」——模型只查询、不建单，体会 agent 的多轮能力。
5. 切到“订单与审计”查看操作记录，再演示回滚。
6. 换成 `异常示例_BOM.xlsx`，展示未建档物料和非法数量如何阻止写入。

项目进度统一记录在 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。交付材料按“需求 → 范围 → 决策 → 风险 → 验收 → 运行”组织：[`需求发现`](docs/01_需求发现与业务痛点.md) · [`范围与非目标`](docs/02_需求范围与非目标.md) · [`ADR`](docs/03_架构决策记录_ADR.md) · [`安全风险`](docs/04_安全风险清单.md) · [`验收报告`](docs/05_验收标准与评测报告.md) · [`部署`](docs/06_部署运行手册.md) · [`排障`](docs/07_故障排查手册.md) · [`试点与回滚`](docs/08_试点上线与回滚方案.md)。

面试收口材料：[`项目复盘与高频问答`](docs/09_项目复盘与面试问答.md) · [`系统设计与故障演练`](docs/10_系统设计与故障演练.md) · [`面试前最终检查清单`](docs/11_面试前最终检查清单.md)。面试前可运行 `.venv\Scripts\python.exe interview_preflight.py`，一次完成 7 项离线门禁。

## 二、架构

```mermaid
flowchart TB
    U[用户] -->|自然语言| UI[Streamlit 聊天工作台]
    UI -->|HTTP/JSON| API[FastAPI Agent API]
    FS[飞书长连接机器人<br/>feishu_bot.py] -->|同进程复用 Agent| LOOP
    API --> LOOP{工具调用循环<br/>AgentLoop}
    LOOP --> SK[search_knowledge<br/>规则检索]
    LOOP --> QM[query_materials<br/>物料/价格查询 · 只读]
    LOOP --> CP[create_purchase_order<br/>生成草稿预览]
    LOOP --> AP[approve_action<br/>审批 · 禁止自审]
    LOOP --> CC[confirm_commit<br/>写入 · RBAC · 幂等]
    LOOP --> RB[rollback_po<br/>回滚]
    LOOP --> DM[detect_material_errors<br/>物料错误分级]
    LOOP --> IM[import_material_master<br/>物料档案导入]
    QM --> ADAPTER{ERP Adapter}
    CP --> ADAPTER
    AP --> ADAPTER
    CC --> ADAPTER
    RB --> ADAPTER
    DM --> ADAPTER
    IM --> ADAPTER
    ADAPTER --> DB[(SQLite 合成数据)]
    ADAPTER -.客户测试环境.-> HTTP[客户 ERP HTTP API]
    SK --> KB[(Markdown 规则库)]
    MCP[MCP Server<br/>mcp_server.py] -.->|暴露 8 个标准工具| EXT[任意 MCP 客户端]
```

核心设计是「受控工具调用 Agent」：模型通过 Function Calling 自主决定调用哪个工具、传什么参数、调用顺序与次数，因此具备 agent 的多轮、自主编排能力；但**金额计算、业务校验和写入口令始终由确定性代码完成**，模型只做编排不做决定。断网或模型幻觉都不会造成错误写入。

业务层通过 `ERPAdapter` 与具体系统解耦：默认 `SQLite` 实现保证离线演示稳定；`HTTPERPAdapter` 展示客户 API 联调所需的 Bearer 鉴权、超时、有界重试、稳定错误映射和幂等请求头。接口契约和联调边界见 [`docs/ERP_Adapter契约.md`](docs/ERP_Adapter契约.md)。这只是可替换集成层，不声称已连接真实企业 ERP。

API、Agent、工具、LLM 与 ERP Adapter 共享结构化 JSON 日志和关联上下文；`X-Request-ID` 可贯穿一次 HTTP 调用，`GET /metrics` 展示进程内成功率与延迟指标。实现边界和排障路径见 [`docs/可观测性与排障.md`](docs/可观测性与排障.md)。

可选安全模式把 Token 绑定为 viewer/operator/approver，模型看不到也不能伪造操作人；发起人与审批人强制分离，状态按 DRAFT → PENDING_APPROVAL → APPROVED → COMMITTED → ROLLED_BACK 留下审计。配置和边界见 [`docs/权限与审批状态机.md`](docs/权限与审批状态机.md)。

## 三、本地启动

### 最省事：Windows 一键启动（推荐）

在本目录打开 PowerShell：

```powershell
python -m pip install -r requirements.txt
.\start_demo.cmd
```

`.cmd` 不受 PowerShell 脚本执行策略限制。退出 Streamlit 时，启动器会一并停止后台 API。

如果本机环境允许 PowerShell 脚本，也可以使用 `start_demo.ps1`；不建议为本项目修改系统的全局执行策略。

启动器会等待 API 和页面都就绪后尝试自动打开浏览器；如果浏览器没有自动打开，请手动访问 `http://127.0.0.1:8501`。API 文档位于 `http://127.0.0.1:8000/docs`。

### 分两个终端启动

终端 1：

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

终端 2：

```powershell
python -m streamlit run ui.py
```

### Docker Compose

```powershell
docker compose up --build
```

然后访问 UI `http://localhost:8501`、API 文档 `http://127.0.0.1:8000/docs`。

验证容器是否真的跑通（8 项检查：健康检查、核心端点、容器内业务链路、UI 健康）：

```powershell
python smoke_docker.py
```

> 网络提示：若 `docker compose build` 卡在拉取 `python:3.13-slim`，说明直连 Docker Hub 不通。
> 在 `%USERPROFILE%\.docker\daemon.json` 加入 `registry-mirrors` 并重启 Docker Desktop 即可：
> ```json
> { "registry-mirrors": ["https://docker.1panel.live", "https://docker.m.daocloud.io"] }
> ```
> 注意：给 daemon 配代理通常无效，因为代理软件一般只监听 `127.0.0.1`，WSL2 经 NAT 访问不到。

MCP 工具也可单独验证（stdio 协议，8 个工具）：

```powershell
python smoke_mcp.py
```

### 飞书对话入口（可选，无需公网）

除了网页工作台，也可以把**同一个 Agent** 接进飞书对话——在飞书里直接发消息，不必每次打开网页。

原理是**飞书自建应用 + 长连接（WebSocket）**：机器人主动连到飞书，因此**不需要公网 IP、域名或内网穿透**，本机常驻一个进程即可。

```powershell
.\.venv\Scripts\python.exe feishu_bot.py
```

Windows 下双击 `start_feishu.cmd` 更省事。启动后在飞书里搜到你的机器人，直接发消息即可（群里需要 @ 机器人）。
启动器会在可见控制台中实时显示运行日志，并同步追加到本地 `feishu_bot.log`；机器人异常退出后会等待 3 秒自动重启。该日志已被 Git 忽略，排障时可本地查看，但不得提交或公开。

`.env` 中的飞书配置项：

```dotenv
FEISHU_APP_ID=cli_你的AppID
FEISHU_APP_SECRET=你的AppSecret
# 可选：只允许这些 open_id 使用（逗号分隔）。留空 = 不限制。
FEISHU_ALLOWED_OPEN_IDS=
# 可选：群里被 @ 时才响应（单聊不受影响）。
FEISHU_REQUIRE_MENTION_IN_GROUP=true
# 可选：回复用消息卡片（Markdown 渲染 + 按语义上色：报错橙/成功绿）。设为 false 退回纯文本。
FEISHU_REPLY_CARD=true
```

机器人默认以**消息卡片**回复：正文保留加粗与列表，按语义给标题上色（错误橙 / 写入成功绿），并在草稿类回复底部常驻提示"确认无误请回复「确认提交」"。卡片发送失败会自动回退为纯文本，不会失联。

飞书开发者后台还需完成 4 步：① 添加「机器人」应用能力；② 权限管理开通 `im:message`、`im:message:send_as_bot`、`im:resource` 等；③ 事件与回调选择**长连接**并订阅 `im.message.receive_v1`；④ 版本管理与发布。

> 安全边界完全不变：机器人只是「翻译层」，金额计算、业务校验与写入口令仍由确定性代码执行，飞书里同样要说「确认提交」才会写入。长连接需**单实例常驻**（会话与幂等状态在进程内存中）。完整步骤与踩坑记录见 `docs/飞书接入方案.md`。

## 四、验证

```powershell
python generate_samples.py
python -m unittest discover -s tests -v
python -m py_compile api.py ui.py erp_agent\*.py
```

当前自动化测试覆盖：

- 工具层：正常/异常草稿、金额验算（¥24164）、写入口令、幂等、回滚、物料查询；
- 工具调用循环：模型调工具→返回结果→停止、无工具直接回复、多轮历史；
- 意图识别：LLM 正常/白名单外/网络异常/回退规则；
- 正常 BOM 生成草稿并确认写入；
- 同一 action_id 重复确认不重复建单；
- 错误确认口令被拒绝；
- 异常 BOM 被阻断；
- 已提交采购 PO 可回滚且保留审计记录；
- BOM 解析（CSV、表头别名、空行、非法格式）；
- API 层（健康检查、确认幂等、404/409、缺文件 400）。

### 能力评测（evals）

项目内置 40 条评测集 `evals/`：25 条确定性场景覆盖金额、阻断、RBAC、自审、状态迁移、路径穿越、并发幂等和 ERP 超时/鉴权/冲突；15 条真实模型场景覆盖工具选择、提示注入、假冒管理员、错误确认口令和无依据回滚。

```powershell
python evals/run_eval.py --offline   # 确定性层，无需模型密钥（CI 使用）
python evals/run_eval.py             # 全量，真实调用模型
```

- CI 离线确定性层：**25/25 通过（100%）**；
- 最近一次全量评测（含真实模型调用）：**40/40 通过（100%）**。首轮新增对抗集为 12/15，增加可信 action_id + 精确确认口令的确定性 `policy_guard` 后提升至 15/15；工具层始终保持零越权写入。

完整报告见 `evals/REPORT.md`，随每次评测自动刷新。

RAG 检索另有一套完全离线的质量门禁，覆盖正向命中与知识范围外拒答：

```powershell
python evals/run_rag_eval.py
```

当前合成评测集结果为 Recall@1 80%、Recall@3 100%、MRR 0.883、拒答命中率 100%。明细见 [`evals/RAG_REPORT.md`](evals/RAG_REPORT.md)；这些数字只描述仓库内合成知识库，不代表真实客户语料效果。

## 四·一、模型配置（工具调用循环）

`/agent/chat` 在模型在线时依赖 Function Calling 编排工具。模型只做编排，金额/校验/写入仍在确定性代码里；不配置模型时，对话入口会切换到受控的确定性降级，仍可完成样例 BOM 草稿、物料查询、错误检测和精确确认演示，但不宣称模型在自主编排。

### 方式一：云端智谱（推荐，开箱即用）

```dotenv
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4-flash
LLM_API_KEY=你的key
```

### 方式二：本地 Ollama（离线，需较大模型）

```powershell
ollama pull qwen2.5:7b
```

```dotenv
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:7b
```

> 注意：`qwen2:1.5b` 这类小模型工具调用不稳定（连意图都常判错），建议至少 `qwen2.5:3b`、推荐 `qwen2.5:7b`。

意图识别与工具编排的安全设计：模型输出经白名单与别名归一化校验；金额计算、业务校验、写入口令全部由确定性代码执行。因此模型幻觉、误判或断网都不会影响金额、校验与写入。

## 五、主要接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 健康检查 + `llm_enabled`/`llm_model`（可判断模型是否真在工作）|
| GET | `/metrics` | 进程内请求、Agent、工具、LLM、ERP Adapter 成功/失败与延迟指标 |
| POST | `/agent/chat` | 多轮对话：模型自主编排工具完成采购业务 |
| POST | `/agent/prepare` | 确定性六步流水线（离线兼容） |
| POST | `/agent/approve` | approver 审批其他人发起的草稿 |
| POST | `/agent/confirm` | 使用明确口令确认写入 |
| POST | `/agent/rollback` | 回滚已写入的采购 PO |
| POST | `/agent/detect` | 物料错误检测：解析 BOM → 逐行校验 → 分级报告 |
| GET | `/orders` | 查看模拟 ERP 单据 |
| GET | `/approvals` | 查看草稿、审批人与状态迁移 |
| GET | `/audit` | 查看审计日志 |
| GET | `/error_reports` | 查看物料错误报告推送队列 |
| GET | `/samples` | 列出可用示例文件 |
| GET | `/materials` | 列出模拟 ERP 物料档案 |
| POST | `/materials/import` | 导入物料档案（已存在编码则更新价格） |

另有 `mcp_server.py`：把 8 个工具暴露为标准 MCP 工具，可接入任意 MCP 客户端（Claude Desktop、Cursor 等）。

## 六、代码阅读顺序

1. `erp_agent/tools.py`：8 个业务工具的 schema 与确定性实现（金额/校验/权限/口令都在这里）。
2. `erp_agent/llm.py`：`AgentLoop` 工具调用循环 + `IntentClassifier` 意图识别。
3. `erp_agent/agent.py`：`chat()` 多轮入口 + `prepare()` 兼容流水线。
4. `erp_agent/parser.py`：BOM 与物料档案（.xlsx/.csv）解析、表头别名归一。
5. `erp_agent/knowledge.py`：离线 RAG 检索和来源返回。
6. `erp_agent/repository.py`：SQLite、预览、幂等、审计和回滚。
7. `erp_agent/adapters.py`：SQLite/HTTP ERP 可替换端口、重试和错误映射。
8. `erp_agent/security.py`：身份绑定、RBAC 与入口权限。
9. `erp_agent/validator.py`：物料错误检测的确定性校验与分级。
10. `api.py`：FastAPI 接口。
11. `mcp_server.py`：MCP 工具暴露。
12. `ui.py`：Streamlit 聊天演示页。
13. `feishu_bot.py`：飞书长连接机器人适配层（飞书事件 → Agent → 回复，复用同一 Agent，安全边界不变）。

## 七、项目边界与生产化路线

- **数据边界**：项目全部使用合成数据与模拟 ERP 还原业务流程，不连接任何真实企业生产系统（见文首安全声明）。
- **Agent 定位**：工具调用循环 Agent（Function Calling）——模型自主编排工具，但金额计算、业务校验与写入口令等关键决策由确定性代码兜底；这是有意的安全设计，并非"完全自主智能体"。
- **RAG 现状**：轻量本地检索，重点是可追溯与离线稳定；生产化可替换为 BGE + Chroma/PGVector 向量检索。
- **写操作安全**：确定性规则、权限与审计全部位于 LLM 之外，本项目即按此原则设计。
- **生产化路线图**（后续迭代）：SSO/RBAC、审批流、密钥管理、消息队列、监控告警、真实 ERP API 适配器、灰度发布。
