# 外贸 ERP 安全操作 Agent

这是一个面向 FDE / AI 应用工程岗位的可运行作品：用完全合成的数据还原“BOM → 采购 PO”流程，展示**工具调用循环 Agent**（Function Calling）、多轮对话、MCP 工具暴露、RAG 检索、业务校验、写前确认、幂等、审计和回滚。

项目当前进度、问题、缺口和下一步统一记录在 `PROJECT_STATUS.md`。每次实质改动结束前都应同步更新该文件。

> 安全声明：项目不连接荣恒或任何企业生产系统；供应商、合同、物料、价格和单号均为虚构数据。工作区中的公司资料不会被程序自动加载。

## 一、3 分钟能看到什么

1. 用自然语言对话：「帮我根据 `正常示例_BOM.xlsx` 生成采购 PO 草稿，先给我看金额」。
2. 模型自主决定调用工具（可展开看工具调用轨迹），生成草稿并停下等确认。
3. 输入 `确认提交`，模型才会调用写入工具；重复确认不会重复建单。
4. 追问「查一下 MAT-FAB-001 的价格」——模型只查询、不建单，体会 agent 的多轮能力。
5. 切到“订单与审计”查看操作记录，再演示回滚。
6. 换成 `异常示例_BOM.xlsx`，展示未建档物料和非法数量如何阻止写入。

## 二、架构

```text
Streamlit 聊天工作台（多轮对话）
      │ HTTP/JSON
      ▼
FastAPI Agent API
      ├─ /agent/chat：工具调用循环（模型自主编排）
      │     ├─ search_knowledge  规则检索
      │     ├─ query_materials   物料/价格查询（只读）
      │     ├─ create_purchase_order  生成草稿预览
      │     ├─ confirm_commit    写入（需口令，幂等）
      │     └─ rollback_po       回滚
      └─ /agent/prepare：确定性六步流水线（离线兼容）

MCP Server（mcp_server.py）
      └─ 把上述 5 个工具暴露为标准 MCP 工具，供任意 MCP 客户端调用
```

核心设计是「受控工具调用 Agent」：模型通过 Function Calling 自主决定调用哪个工具、传什么参数、调用顺序与次数，因此具备 agent 的多轮、自主编排能力；但**金额计算、业务校验和写入口令始终由确定性代码完成**，模型只做编排不做决定。断网或模型幻觉都不会造成错误写入。

## 三、本地启动

### 最省事：Windows 一键启动（推荐）

在本目录打开 PowerShell：

```powershell
python -m pip install -r requirements.txt
.\start_demo.cmd
```

`.cmd` 不受 PowerShell 脚本执行策略限制。退出 Streamlit 时，启动器会一并停止后台 API。

如果公司电脑允许 PowerShell 脚本，也可以使用 `start_demo.ps1`；不建议为本项目修改系统的全局执行策略。

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

然后访问 `http://localhost:8501`。

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

## 四·一、模型配置（工具调用循环）

`/agent/chat` 依赖具备工具调用（Function Calling）能力的模型来编排工具。模型只做编排，金额/校验/写入仍在确定性代码里；不配置模型时 `/agent/chat` 返回不可用提示，`/agent/prepare` 仍可离线运行。

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
| GET | `/health` | 健康检查与演示模式声明 |
| POST | `/agent/chat` | 多轮对话：模型自主编排工具完成采购业务 |
| POST | `/agent/prepare` | 确定性六步流水线（离线兼容） |
| POST | `/agent/confirm` | 使用明确口令确认写入 |
| POST | `/agent/rollback` | 回滚已写入的采购 PO |
| GET | `/orders` | 查看模拟 ERP 单据 |
| GET | `/audit` | 查看审计日志 |

另有 `mcp_server.py`：把 5 个工具暴露为标准 MCP 工具，可接入任意 MCP 客户端（Claude Desktop、Cursor 等）。

## 六、代码阅读顺序

1. `erp_agent/tools.py`：5 个业务工具的 schema 与确定性实现（金额/校验/口令都在这里）。
2. `erp_agent/llm.py`：`AgentLoop` 工具调用循环 + `IntentClassifier` 意图识别。
3. `erp_agent/agent.py`：`chat()` 多轮入口 + `prepare()` 兼容流水线。
4. `erp_agent/parser.py`：BOM 文件解析。
5. `erp_agent/knowledge.py`：离线 RAG 检索和来源返回。
6. `erp_agent/repository.py`：SQLite、预览、幂等、审计和回滚。
7. `api.py`：FastAPI 接口。
8. `mcp_server.py`：MCP 工具暴露。
9. `ui.py`：Streamlit 聊天演示页。

## 七、面试时要诚实说明的边界

- 真实经历：亲自完成过 BOM 到采购 PO 的业务流程，并基于一线体验识别痛点。
- 作品实现：使用合成数据与模拟 ERP 还原流程，没有接入公司生产系统。
- 当前 Agent：工具调用循环 Agent（Function Calling），模型自主编排但关键决策由确定性代码兜底；不是完全自主智能体。
- 当前 RAG：轻量本地检索，重点是可追溯和离线稳定；后续可替换为 BGE + Chroma/PGVector。
- 企业写操作必须把确定性规则、权限和审计放在 LLM 之外——本项目正是按此原则设计的。
- 待生产化：SSO/RBAC、审批、密钥管理、队列、监控、真实 API 适配器、评测集与灰度发布。
