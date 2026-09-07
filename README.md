# 外贸 ERP 安全操作 Agent

这是一个面向 FDE / AI 应用工程岗位的可运行作品：用完全合成的数据还原“BOM → 采购 PO”流程，展示 RAG 检索、工具调用、业务校验、写前确认、幂等、审计和回滚。

项目当前进度、问题、缺口和下一步统一记录在 `PROJECT_STATUS.md`。每次实质改动结束前都应同步更新该文件。

> 安全声明：项目不连接荣恒或任何企业生产系统；供应商、合同、物料、价格和单号均为虚构数据。工作区中的公司资料不会被程序自动加载。

## 一、3 分钟能看到什么

1. 选择 `正常示例_BOM.xlsx`，让 Agent 生成采购 PO。
2. 查看 Agent 的五步工具轨迹和 RAG 规则来源。
3. 查看三行采购明细、价格/包装费来源和总金额。
4. 输入 `确认提交` 后才写入模拟 ERP；重复点击不会重复建单。
5. 切到“订单与审计”查看操作记录，再演示回滚。
6. 换成 `异常示例_BOM.xlsx`，展示未建档物料和非法数量如何阻止写入。

## 二、架构

```text
Streamlit 工作台
      │ HTTP/JSON
      ▼
FastAPI Agent API
      ├─ 意图识别：可选 LLM（本地 Ollama / 云端千问·智谱），失败自动回退规则
      ├─ Markdown 规则库：检索并返回来源
      ├─ BOM 解析工具：XLSX / CSV
      ├─ 模拟 ERP 工具：SQLite 物料、价格、包装费
      ├─ 业务校验器：必填、档案、数量、供应商、币种
      └─ 安全执行层：预览 → 明文确认 → 幂等写入 → 审计/回滚
```

核心设计是“可靠工作流 Agent”：模型只用于理解业务意图（自然语言 → 结构化意图），关键金额计算、校验和写入权限不交给概率模型决定。因此当前 Demo 即使没有 Ollama、没有云端 Key，也能稳定运行。

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

- 意图识别：LLM 正常/白名单外/网络异常/回退规则；
- 正常 BOM 生成草稿并确认写入；
- 同一 action_id 重复确认不重复建单；
- 错误确认口令被拒绝；
- 异常 BOM 被阻断；
- 已提交采购 PO 可回滚且保留审计记录；
- BOM 解析（CSV、表头别名、空行、非法格式）；
- API 层（健康检查、确认幂等、404/409、缺文件 400）。

## 四·一、可选 LLM 意图识别（双链路）

Agent 的第一步会把自然语言任务识别为结构化意图。LLM 只做这一步，且**失败自动回退到确定性规则**，因此不配置也能跑。配置优先级：本地 Ollama → 云端千问/智谱。

### 方式一：本地 Ollama（默认，离线可用）

```powershell
ollama serve
ollama pull qwen2:1.5b
```

复制 `.env.example` 为 `.env`，确认：

```dotenv
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2:1.5b
```

### 方式二：云端千问 DashScope

```dotenv
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_API_KEY=sk-你的key
```

### 方式三：云端智谱

```dotenv
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4-flash
LLM_API_KEY=你的key
```

不配置 `LLM_BASE_URL` 时，Agent 走离线规则回退，功能不受影响。

意图识别的安全设计：模型输出会经过「白名单 + 中文别名归一化」校验——小模型即使把意图写成中文（如"生成采购PO"）也能正确映射回枚举；输出白名单之外或无法判断（`unknown`）时，自动交给确定性规则兜底。因此模型幻觉、误判或断网都不会影响金额、校验与写入。

## 五、主要接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 健康检查与演示模式声明 |
| POST | `/agent/prepare` | 检索规则、解析 BOM、查询档案并生成预览 |
| POST | `/agent/confirm` | 使用明确口令确认写入 |
| POST | `/agent/rollback` | 回滚已写入的采购 PO |
| GET | `/orders` | 查看模拟 ERP 单据 |
| GET | `/audit` | 查看审计日志 |

## 六、代码阅读顺序

1. `erp_agent/agent.py`：完整 Agent 编排。
2. `erp_agent/parser.py`：BOM 文件解析。
3. `erp_agent/knowledge.py`：离线 RAG 检索和来源返回。
4. `erp_agent/repository.py`：SQLite、预览、幂等、审计和回滚。
5. `api.py`：FastAPI 接口。
6. `ui.py`：Streamlit 演示页。

## 七、面试时要诚实说明的边界

- 真实经历：亲自完成过 BOM 到采购 PO 的业务流程，并基于一线体验识别痛点。
- 作品实现：使用合成数据与模拟 ERP 还原流程，没有接入公司生产系统。
- 当前 RAG：轻量本地检索，重点是可追溯和离线稳定；后续可替换为 BGE + Chroma/PGVector。
- 当前 Agent：受控工作流 Agent，不声称是完全自主智能体；企业写操作必须把确定性规则和权限放在 LLM 之外。
- 待生产化：SSO/RBAC、审批、密钥管理、队列、监控、真实 API 适配器、评测集与灰度发布。
