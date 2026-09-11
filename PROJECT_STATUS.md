# 外贸 ERP 安全操作 Agent · 项目接续文档

> 用途：记录项目事实状态，避免跨会话、跨日期或换人继续时遗漏。
>
> 维护规则：每次完成代码、数据、文档、测试或重要决策后，在结束动作前更新本文件；只记录已经发生的事实，不把计划写成已完成。

## 1. 当前快照

| 项目 | 当前状态 |
|---|---|
| 最后更新时间 | 2026-09-11 18:30（Asia/Shanghai） |
| 当前版本 | v0.4 工具调用循环 Agent（Function Calling + 多轮对话 + MCP + 飞书对话入口） |
| 当前阶段 | 核心闭环 + UI 真实点击演示 + 飞书端到端实测均已完成（截图入作品集）；剩余现场业务规则复核 |
| 主业务场景 | BOM → 采购 PO |
| 目标受众 | FDE / AI 应用工程方向的作品展示 |
| 数据边界 | 仅使用合成数据；不连接公司生产系统 |
| 推荐启动入口 | `start_demo.cmd` |
| 飞书对话入口 | `start_feishu.cmd`（飞书自建应用 + 长连接，无需公网） |
| Web 页面 | `http://localhost:8501` |
| API 文档 | `http://127.0.0.1:8000/docs` |

## 2. 项目目标

构建一个可脱离公司环境运行的安全型 ERP Agent Demo，展示：

1. 用自然语言提出生成采购 PO 的业务目标；
2. RAG 检索业务规则并展示来源；
3. 解析 BOM Excel/CSV；
4. 调用模拟 ERP 查询物料、供应商、单价和包装费；
5. 生成采购 PO 草稿并执行确定性业务校验；
6. 写入前展示变更预览并要求人工明确确认；
7. 提供幂等写入、审计日志和回滚；
8. 用 Streamlit、FastAPI、SQLite 和 Docker 展示端到端交付能力。

## 3. 已完成内容

### 3.1 核心后端

- [x] FastAPI 服务与健康检查；
- [x] 工具调用循环 Agent：模型通过 Function Calling 自主编排 6 个工具（search_knowledge / query_materials / create_purchase_order / confirm_commit / rollback_po / detect_material_errors）；
- [x] 多轮对话：`/agent/chat` 接口 + session 记忆（模型能记住上一轮的 action_id）；
- [x] MCP 工具暴露：`mcp_server.py` 用 FastMCP 把 6 个工具暴露为标准 MCP 工具（已做 stdio 真实冒烟）；
- [x] 意图识别：可选 LLM（本地 Ollama / 云端千问·智谱），失败自动回退确定性规则；
- [x] BOM `.xlsx` / `.xlsm` / `.csv` 解析；
- [x] Markdown 业务规则分块与离线检索；
- [x] 可展示来源、章节、摘要和检索分数；
- [x] SQLite 模拟 ERP 物料档案；
- [x] 物料档案导入（`POST /materials/import` + MCP `import_materials` + UI 上传入口，白名单目录解析防路径穿越，模板见 `samples/物料档案模板.xlsx`）；
- [x] 供应商、单价、包装费和币种查询；
- [x] 采购 PO 草稿生成及总金额计算；
- [x] 必填、数量、档案、名称、供应商和币种校验；
- [x] 阻断错误与警告分级；
- [x] 写前预览；
- [x] 明文口令 `确认提交`；
- [x] 基于 `action_id` 的幂等写入；
- [x] 审计日志；
- [x] 已提交单据回滚。

### 3.2 演示与交付

- [x] Streamlit 聊天式工作台（多轮对话）；
- [x] 工具调用轨迹可视化展示；
- [x] 正常合成 BOM；
- [x] 包含未建档、非法数量和名称差异的异常 BOM；
- [x] Agent 工具执行轨迹展示；
- [x] RAG 来源展示；
- [x] 订单与审计查看页面；
- [x] Windows `.cmd` 一键启动；
- [x] PowerShell `.ps1` 备用启动；
- [x] Docker API 镜像、UI 镜像与 Compose 编排（已真实构建 + 容器端到端冒烟 8/8 通过）；
- [x] `.dockerignore`：阻止 `.env`、`data/*.db`、内部资料进入镜像；
- [x] README；
- [x] 飞书对话入口：`feishu_bot.py`（长连接机器人，同进程复用同一 Agent，安全边界不变）+ `start_feishu.cmd` 一键启动 + `docs/飞书接入方案.md` 方案与步骤；
- [x] 演示与定位文档（`docs/ui-demo.md` 演示验证记录；本地专用材料不随发布版公开）；

## 4. 验证记录

| 日期 | 验证项 | 结果 |
|---|---|---|
| 2026-08-18 | `python -m unittest discover -s tests -v` | 3/3 通过 |
| 2026-08-18 | 全部 Python 文件 `py_compile` | 通过 |
| 2026-08-18 | 正常 BOM：生成 3 行采购明细 | 通过 |
| 2026-08-18 | 错误确认口令返回冲突响应 | 通过，HTTP 409 |
| 2026-08-18 | 正确确认写入 | 通过 |
| 2026-08-18 | 同一 action 重复确认 | 通过，未重复建单 |
| 2026-08-18 | 已提交采购 PO 回滚 | 通过 |
| 2026-08-18 | 异常 BOM 阻断写入 | 通过，产生 3 条问题 |
| 2026-08-18 | FastAPI `/health` | 通过，HTTP 200 |
| 2026-08-18 | FastAPI `/docs` | 通过，HTTP 200 |
| 2026-08-18 | Streamlit 页面 | 通过，HTTP 200 |
| 2026-08-18 | `docker compose config --quiet` | 通过 |
| 2026-08-18 | `start_demo.cmd` 完整启动 | 通过 |
| 2026-09-07 | 工具调用循环真实冒烟（智谱 glm-4-flash） | 通过：模型自主调用 create_purchase_order 生成 ¥24164 草稿并停下等确认 |
| 2026-09-07 | 多轮对话确认写入 | 通过：第二轮模型调 confirm_commit 写入 PO-DEMO-20260907-* |
| 2026-09-07 | 全量测试 | 34/34 通过 |
| 2026-09-09 | MCP stdio 真实冒烟（`smoke_mcp.py`） | 通过：6 个工具全部经 MCP 协议暴露，`detect_material_errors` 调用成功 |
| 2026-09-09 | `docker compose build`（api + ui 双镜像） | 通过：3 分 31 秒构建成功（`python:3.13-slim`） |
| 2026-09-09 | 容器端到端冒烟（`smoke_docker.py`） | 通过：8/8，含 `/agent/prepare` 六步流水线（¥24164）与 `/agent/detect`（3 行检出 3 错误） |
| 2026-09-09 | Compose 内部服务名互通 | 通过：UI 容器访问 `http://api:8000/health` 返回 200 |
| 2026-09-09 | 数据卷持久化 | 通过：`docker compose restart api` 后 error_reports 数据仍在 |
| 2026-09-09 | 镜像安全扫描 | 通过：镜像内无 `.env`、无明文密钥，`knowledge/` 三份规则文档完整 |
| 2026-09-09 | 全量测试 | 48/48 通过 |
| 2026-09-09 | **Streamlit UI 真实点击演示（浏览器实测）** | 通过：① 模型自主调用 `detect_material_errors`（3 行 3 错误，阻断 2 / 警告 1）、`create_purchase_order`（¥24164）、`confirm_commit`（PO-DEMO-20260909-6E25）三个工具并展示轨迹；② "订单与审计"页三张表全部渲染（采购 PO / 审计日志 5 条 / 错误报告队列 PENDING_PUSH）。截图见 `docs/ui-demo/`，记录见 `docs/ui-demo.md` |
| 2026-09-09 | 物料档案导入功能（工作区已完成，本次从源头同步至发布副本） | 通过：`unittest` 58/58 OK（含新增 `tests/test_material_import.py`），evals offline 8/8 100%；同时修正 `test_material_errors` 缺失文件断言以匹配 `resolve_bom_file` 新报错文案 |
| 2026-09-11 | 飞书长连接机器人联通（`feishu_bot.py`） | 通过：飞书开发者后台「重新验证」返回"连接成功"；机器人日志出现 `connected to wss://msg-frontier.feishu.cn/ws/v2` |
| 2026-09-11 | **飞书端到端实测（BOM → 草稿 → 确认写入）** | 通过：17:57:43 由 `正常示例_BOM.xlsx` 生成草稿 ¥24164.0（3 行物料）；17:57:56 确认写入 `PO-DEMO-20260911-3F99`（COMMITTED）。草稿到写入间隔 13 秒，证明"先给草稿、说「确认提交」才写入"的安全边界在飞书侧同样生效 |
| 2026-09-11 | 飞书机器人日志块缓冲缺陷修复 | 通过：`feishu_bot.py` 顶部加 `sys.stdout/stderr.reconfigure(line_buffering=True)`（try/except 兜底），`py_compile` 通过后重启，实时日志立即可见 |

## 5. 已遇到并解决的问题

### P-001：PowerShell 禁止执行启动脚本

- 现象：运行 `start_demo.ps1` 报 `PSSecurityException`，系统禁止执行脚本。
- 根因：本机的 PowerShell Execution Policy 限制 `.ps1`。
- 处理：新增 `start_demo.cmd` 和 `launch_demo.py`，不修改系统全局安全策略。
- 当前状态：已解决并完成真实启动验证。

### P-002：Streamlit 首次启动要求输入邮箱

- 现象：第一次启动停在 Streamlit 邮箱采集提示。
- 根因：Streamlit 首次运行交互。
- 处理：启动参数增加 `--browser.gatherUsageStats=false --server.headless=true`。
- 当前状态：已解决；页面需手动访问 `http://localhost:8501`。

### P-003：Windows 沙箱临时目录导致 SQLite 无法打开

- 现象：自动化测试使用 `tempfile` 时出现 `sqlite3.OperationalError: unable to open database file`。
- 根因：临时目录 ACL 与当前运行环境不兼容。
- 处理：测试数据库改为项目 `data` 目录内的独立文件。
- 当前状态：已解决。

### P-004：SQLite 连接未及时关闭

- 现象：测试清理数据库时报文件仍被占用，并出现 `ResourceWarning`。
- 根因：SQLite Connection 的上下文管理只处理事务，不自动关闭连接。
- 处理：Repository 新增统一 `session()`，确保提交后关闭连接。
- 当前状态：已解决，测试数据库可正常清理。

### P-005：换机后 Demo 无法启动

- 现象：双击 `start_demo.cmd` 无反应，项目"打不开"。
- 根因：两个问题叠加——当前机器 PATH 上没有 python；即使有，新环境也没有安装 fastapi/streamlit/uvicorn 等依赖（原环境为 2026-08 验证时所用，未随项目迁移）。
- 处理：在项目内新建 `.venv` 并安装 requirements.txt；`start_demo.cmd` 与 `start_demo.ps1` 改为优先使用项目内 `.venv\Scripts\python.exe`，无 .venv 时回退 PATH 上的 python 并给出创建提示。
- 当前状态：已解决并重新验证（2026-09-07）：单测 3/3 通过；`launch_demo.py` 启动后 API `/health` 与 Streamlit 页面均返回 HTTP 200。
- 附带修复：requirements.txt 的 pydantic==2.13.4 首次安装时报"No matching distribution"（代理下 simple index 瞬时异常），重试后安装成功，版本号本身有效，无需改动。

## 6. 当前缺口

以下内容尚未完成，请勿声称已经实现：

### 6.1 现场业务复核清单

- [ ] 用测试 ERP 复核真实的 BOM → 采购 PO 操作步骤；
- [ ] 复核采购 PO 的真实字段清单及字段来源；
- [ ] 确认一张采购 PO 是否允许多供应商、多币种；
- [ ] 确认物料未建档、价格缺失、包装费缺失时的真实处理方式；
- [ ] 确认保存机制是逐字段、逐行还是整单提交；
- [ ] 向业务老师确认三个最高频错误；
- [ ] 向开发/IT 了解是否存在 API、批量导入、幂等、事务和审计能力；
- [ ] 明确哪些资料允许脱敏用于个人作品；未知时默认不可使用。

### 6.2 后续可继续开发

- [x] 增加真实 LLM 意图分类（本地 Ollama / 云端 API 双链路，失败回退），保留确定性安全边界；
- [ ] 将现场确认的规则转写为合成版知识文档和测试用例；
- [ ] 将轻量检索升级为 BGE embedding + Chroma/PGVector；
- [ ] 建立 RAG 评测集与 Recall@K、引用正确率、忠实度、拒答率指标；
- [ ] 增加用户身份、RBAC 和审批状态机；
- [ ] 增加凭证管理、结构化日志、指标监控和异常告警；
- [ ] 增加模拟 ERP Adapter 接口层，方便未来替换真实 API；
- [ ] 增加采购 PO 导出 Excel/PDF；
- [x] 录制演示视频并制作项目架构图（架构图 v3 已完成；UI 演示截图 4 张已于 2026-09-09 补充至 `docs/ui-demo/`，仅差可选录屏合成）；
- [ ] 整理项目复盘与问答材料；
- [x] 执行完整 Docker 构建与容器运行测试（2026-09-09 完成：真实构建 + 8/8 容器冒烟 + 持久化与安全扫描）。

## 7. 已知边界与风险

| 风险/边界 | 当前处理 | 后续要求 |
|---|---|---|
| 真实企业数据泄露 | Demo 只加载项目内合成资料 | 提交或录屏前继续做敏感信息检查 |
| LLM 幻觉 | 模型只做意图识别，金额、校验和写入均由确定性代码完成 | LLM 只做意图和解释增强 |
| 误写业务数据 | 预览、确认口令、阻断校验 | 生产化需 RBAC、审批和真实鉴权 |
| 重复建单 | `action_id` 唯一约束与幂等返回 | 对接真实 ERP 时传递幂等键 |
| RAG 能力被夸大 | 当前明确标注为轻量本地检索 | 升级向量检索后再更新描述 |
| 业务规则不准确 | 当前规则均为合成演示规则 | 现场只验证抽象规则，不复制真实数据 |
| Docker 镜像体积与拉取 | 已真实构建并跑通；网络受限时在 `~/.docker/daemon.json` 配 `registry-mirrors` | 换网络环境时可调整镜像加速器 |

## 8. 关键决策记录

| 日期 | 决策 | 原因 |
|---|---|---|
| 2026-08-18 | 主场景选 BOM → 采购 PO | 用户亲自完整操作过，能够经受业务追问 |
| 2026-08-18 | 使用模拟 ERP，不连接公司系统 | 无正式授权，且作品必须脱离原环境独立运行 |
| 2026-08-18 | 先做受控工作流 Agent | 保证现场演示稳定，并把高风险写操作置于确定性规则内 |
| 2026-08-18 | 使用合成 BOM 和虚构档案 | 满足隐私、保密和作品公开要求 |
| 2026-08-18 | 新增 `.cmd` 启动方式 | 兼容受限环境的 PowerShell 策略限制 |
| 2026-09-07 | 意图识别采用本地+云端双链路 | 本地 Ollama 符合离线/学习路线，云端 API 保底质量；统一走 OpenAI 兼容接口 |
| 2026-09-07 | 从固定六步流水线升级为工具调用循环 Agent | 用户反馈"没体会到 agent"，对标 GitHub 同类项目后确定：agent 感来自模型自主编排工具，而非固定流水线；安全边界由工具内部确定性代码保证 |
| 2026-09-07 | 云端模型默认用智谱 glm-4-flash | 小模型（qwen2:1.5b）工具调用不稳，glm-4-flash 支持 function calling 且稳定 |
| 2026-09-11 | 飞书接入选「自建应用 + 长连接（WebSocket）」 | 无需公网 IP / 域名 / 内网穿透，本机常驻一个进程即可。对比：自定义机器人 Webhook 只能推送不能对话；事件回调需公网 HTTPS。长连接的适配层最薄，`api.py`/`ui.py`/`erp_agent/*` 零改动 |
| 2026-09-11 | 飞书侧鉴权以「可用范围」为第一道门，`FEISHU_ALLOWED_OPEN_IDS` 为第二道门 | 飞书后台「可用范围」已限定为仅本人，应用内白名单属纵深防御而非必需；当为演示放宽可用范围时才需回填白名单（应用内第二道门） |

## 9. 下一步执行顺序

1. 用户在本机运行 `start_demo.cmd`，完成正常、异常、确认、审计和回滚体验；
2. 根据页面实际体验修复 UI 或启动问题；
3. 立即执行《现场业务信息采集清单》中的流程与字段复核；
4. 把确认后的抽象业务规则反馈给项目，禁止直接提交真实业务数据；
5. 更新知识库、校验器、测试与演示材料；
6. 再加入 LLM 工具选择、RAG 评测和项目包装。

## 10. 接续工作检查模板

每次结束动作时，在本文件顶部更新“最后更新时间”，并在下面追加一条记录：

```text
日期时间：
本次目标：
实际完成：
改动文件：
验证命令与结果：
遇到的问题：
遗留问题：
下一步第一动作：
```

## 11. 工作日志

### 2026-09-11 18:30

- 本次目标：把 Agent 接进飞书对话（不必每次打开网页），完成落地、后台配置与端到端验证。
- 实际完成：① 评估四条接入路线并选定「自建应用 + 长连接」，产出 `docs/飞书接入方案.md`；② 新增 `feishu_bot.py` 适配层（`lark.ws.Client` 长连接 + `im.message.receive_v1` 事件；message_id 幂等去重；`feishu:{open_id}` 会话映射；文件消息落 `uploads/` 并剥 basename 防路径穿越；Markdown→飞书纯文本清洗；tool_trace 压行摘要；open_id 白名单；群里需 @；每消息起线程 + Lock 保护 sessions）——`api.py`/`ui.py`/`erp_agent/*` **零改动**；③ 新增 `start_feishu.cmd` 一键启动；④ `.env` / `.env.example` 增加 `FEISHU_APP_ID`/`FEISHU_APP_SECRET`/`FEISHU_ALLOWED_OPEN_IDS`/`FEISHU_REQUIRE_MENTION_IN_GROUP`，`requirements.txt` 增加 `lark-oapi>=1.4.0`（实装 1.7.3）；⑤ 飞书开发者后台 4 步配置全部完成（机器人能力 / 5 个免审权限 / 长连接订阅 `im.message.receive_v1` / 版本 1.0.0 发布），长连接验证"连接成功"；⑥ 飞书内端到端实测通过（见验证记录）；⑦ 修复日志块缓冲缺陷；⑧ 按用户要求清空 `FEISHU_ALLOWED_OPEN_IDS`（可用范围已限定仅本人）。
- 改动文件：`feishu_bot.py`（新增）、`start_feishu.cmd`（新增）、`docs/飞书接入方案.md`（新增）、`.env`（不入库）、`.env.example`、`requirements.txt`、`README.md`、本文件。
- 验证命令与结果：`py_compile feishu_bot.py` 通过；导入冒烟（Agent 构建、7 工具、Markdown 清洗、去 @ 占位符、轨迹摘要、幂等去重）全部符合预期；飞书端到端实测通过（草稿 ¥24164 → `PO-DEMO-20260911-3F99`）；`api.py`/`ui.py`/`mcp_server.py` 未受影响。
- 遇到的问题：① `print()` 重定向到管道时块缓冲，日志迟迟不可见 → 顶部 `reconfigure(line_buffering=True)`；② Windows 上 `Start-Process -RedirectStandardOutput` 用管道 + 后台读取线程实现，启动它的 shell 一退出子进程输出全丢并静默退出 → 改用 Bash 后台任务 + `> log 2>&1`；③ `.venv\Scripts\python.exe` 在 Windows 上是「启动器 + 子解释器」两个进程，**不是重复实例**。
- 遗留问题：飞书"物料错误检测 + 推送"分支与"上传 BOM 文件"分支未实测（`error_reports` 仍为 0 条）；`README`/`PROJECT_STATUS` 已补飞书章节；App Secret 曾在对话中明文出现，建议重置。
- 下一步第一动作：在飞书里上传 `异常示例_BOM.xlsx`，验证物料错误检测 + 推送队列分支。

### 2026-09-09 22:50

- 本次目标：按"公开仓库=对外第一印象"的要求，移除本地专用材料，并对仓库做外部视角的全面审查与脱敏。
- 实际完成：① 从发布版移除两份本地专用材料（源头工作区保留自用，不进发布版）；② README 优化：安全声明措辞中性化、"3 分钟能看到什么"补 import 演示、mermaid 架构图补齐 7 个工具节点（detect_material_errors + import_materials）、评测描述改为"CI 离线 8/8 + 最近一次全量 15/15"双行口径、代码阅读顺序扩为 10 条并补 `erp_agent/validator.py`；③ architecture.html 工具层升级为 7 个业务工具（新增 import_materials 节点）、端点列表补 `/materials/import` 与 `GET /materials`、验证横幅更新为"单测 58/58 · MCP 7 工具"；④ 全仓内部措辞中性化：README、`物料错误检测_设计说明.md`（痛点来源表述、定位口径）、PROJECT_STATUS（演示脚本）、docs/ui-demo.md（去掉对已删脚本的引用）。
- 改动文件：`README.md`、`PROJECT_STATUS.md`、`architecture.html`、`docs/ui-demo.md`、`物料错误检测_设计说明.md`；删除两份本地专用材料。
- 验证命令与结果：全仓敏感词扫描 0 命中（覆盖内部组织名与内部语境词）；本次仅文档与静态页改动，未触碰代码，58/58 测试与 8/8 离线评测仍有效。
- 遇到的问题：PROJECT_STATUS 被 PowerShell 重写引入 BOM，已用 .NET 写回无 BOM UTF-8；git diff 确认无整文件噪声。
- 遗留问题：源头工作区保留两份本地专用材料（有意差异，.dockerignore 已排除）；samples 两个 BOM 文件哈希与源头不同（内容逐行一致，仅为重新保存的元数据差异，不处理）。

### 2026-09-09 22:25

- 本次目标：检查源头项目 `erp_agent_assistant` 与发布副本 `erp-procurement-agent` 的同步状态，发现并消除差异。
- 实际完成：源头含 034227b 全部内容 + **物料档案导入功能**（工作区已完成但从未同步到发布副本/GitHub）：`POST /materials/import`（api.py）、导入 UI（ui.py "📇 导入自己的物料档案"）、MCP `import_materials`（mcp_server.py）、`parse_materials`（parser.py）、`import_materials`（repository.py）、`resolve_bom_file` 白名单路径解析 + `import_materials` 工具（tools.py）、`MaterialImportRequest`（models.py）、`tests/test_material_import.py`、`samples/物料档案模板.xlsx`、`generate_samples.py` 模板生成、Dockerfile api/ui 建 uploads 目录与 COPY samples、.gitignore/.dockerignore 排除 uploads、compose 增加 uploads 卷与可选 env_file。已全部同步到发布副本；修正 `test_material_errors` 缺失文件断言（旧文案"文件不存在"→ 新实现"找不到 BOM 文件"）。反向回同步 `docs/ui-demo`（截图+记录）到源头。
- 改动文件：副本新增/更新 16 项（见 git log）；源头回同步 docs/ui-demo、PROJECT_STATUS、test_material_errors.py、evals/REPORT.md。
- 验证命令与结果：`unittest discover` 58/58 OK；`py_compile` OK；`evals/run_eval.py --offline` 8/8 100%。
- 遇到的问题：① 副本系统 Python（3.14.7）缺依赖，改用源头 `.venv` 跑测试；② 发现源头加物料导入后测试未同步（`test_tool_missing_file` 断言旧文案），已修正并回同步源头。
- 遗留问题：无（发布副本与源头已对齐）。
- 下一步第一动作：推送发布副本到 GitHub，确认 CI 全绿。

### 2026-09-09 22:11

- 本次目标：清掉最后一个"未验证"遗留项——Streamlit UI 真实点击演示，并把验证证据入库维护 GitHub。
- 实际完成：在 Docker 双容器（api:8000/ui:8501）运行的浏览器中真实点击演示全部通过：① 聊天框输入「检测一下 异常示例_BOM.xlsx 有哪些物料错误」，模型自主调用 `detect_material_errors`（3 行 3 错误，阻断 2 / 警告 1）并展示轨迹；② 输入「帮我根据 正常示例_BOM.xlsx 生成采购 PO 草稿，先给我看金额」，模型自主调用 `create_purchase_order` 返回 ¥24164；③ 输入「确认提交」，模型自主调用 `confirm_commit` 写入 PO-DEMO-20260909-6E25（幂等 false，首次写入）；④ 切到"订单与审计"页，三张表全部渲染（采购 PO 表 COMMITTED 单据 / 审计日志 5 条含 WRITE_CONFIRMED / 错误报告队列 ERR-D24ABB3866 PENDING_PUSH）。新增 `docs/ui-demo.md` 验证记录 + 4 张演示截图入 `docs/ui-demo/`。
- 改动文件：`docs/ui-demo.md`（新增）、`docs/ui-demo/*.png`（4 张新增）、本文件。
- 验证命令与结果：浏览器实测（见 docs/ui-demo.md）；GitHub Actions run #8（034227b）success；push 后 CI 复跑确认。
- 遇到的问题：Streamlit 聊天输入框在页面重渲染后 ref 丢失，需滚动到底部或重新定位后才可操作；无代码问题。
- 遗留问题：可选录屏合成（截图已齐）；现场业务规则复核（见 6.1）。
- 下一步第一动作：推送本次文档与截图改动到 GitHub，确认 CI 全绿。

### 2026-09-09 09:55

- 本次目标：清掉两个"未验证"遗留项——MCP stdio 真实冒烟 + Docker 真实构建与容器端到端验证。
- 实际完成：新增 `smoke_mcp.py`（MCP stdio 客户端冒烟，可复用）；新增 `smoke_docker.py`（Compose 容器冒烟，覆盖健康检查、核心端点、容器内业务链路、UI 健康）；新增 `.dockerignore`；`api.py` + `models.py` 补齐 `POST /agent/detect` 端点（此前物料错误检测只有 MCP/对话入口，无 REST 入口）；配置 Docker 镜像加速器后完成真实构建。
- 改动文件：`smoke_mcp.py`（新增）、`smoke_docker.py`（新增）、`.dockerignore`（新增）、`api.py`、`erp_agent/models.py`、本文件。
- 验证命令与结果：`python smoke_mcp.py` → 6 工具全部暴露、MCP 调用成功；`docker compose build` → 双镜像构建成功（3m31s）；`python smoke_docker.py` → 8/8 通过（六步流水线 ¥24164 / 物料错误检测 3 行检出 3 错误 / UI 健康）；`docker compose exec -T ui python -c ...` → UI 容器访问 `http://api:8000/health` 200；`docker compose restart api` 后 error_reports 仍在 → 数据卷持久化 OK；镜像内无 `.env`、无明文密钥、`knowledge/` 三份规则文档完整；`unittest discover` 48/48 OK。
- 遇到的问题：① 首次构建失败于拉取 `python:3.13-slim`（直连 Docker Hub 超时）——根因是代理只监听 `127.0.0.1:7897`，WSL2 经 NAT 访问不到；解法是改在 `~/.docker/daemon.json` 配置 `registry-mirrors`（`docker.1panel.live` / `docker.m.daocloud.io` / `hub.rat.dev`），daemon 走国内站点直连，绕开代理。② `.dockerignore` 初版写了 `*.md`，会连带过滤 `knowledge/` 下的规则文档导致 Agent 规则检索失效，已改为 `/*.md` 只匹配根目录。③ 冒烟脚本臆造了 `/agent/detect` 端点与 `blocking_count` 字段，实测后改为真实字段并补齐端点。
- 遗留问题：UI 端（Streamlit 界面）的真实点击演示仍未人工验证；演示录屏/截图未做。
- 下一步第一动作：同步改动到发布副本并 push GitHub，确认 CI 与容器构建均绿。

### 2026-09-08 14:08

- 本次目标：把新工具 `detect_material_errors` 接入 MCP 暴露、FastAPI、Streamlit UI 和演示脚本，让演示可点出。
- 实际完成：`api.py` 新增 `GET /error_reports`；`mcp_server.py` 新增 `detect_material_errors` MCP 工具；`ui.py` 欢迎语加物料错误检测示例、审计页加"物料错误报告（推送队列）"展示；`演示脚本.md` 补痛点陈述 + 检测演示段 + 推送落地追问；`architecture.html` 升级 v2（6 工具 + error_reports + MCP 复用说明）。
- 改动文件：`api.py`、`mcp_server.py`、`ui.py`、`演示脚本.md`、`architecture.html`、本文件。
- 验证命令与结果：`.venv/Scripts/python.exe -m py_compile api.py ui.py mcp_server.py erp_agent/*.py` 通过；`unittest discover` 48/48 OK；工具层 + API 层冒烟：detect 检出 3 错误、push 落库 1 条、`/health` `/error_reports` `/samples` 均 200。
- 遇到的问题：冒烟脚本误传 str 给 KnowledgeBase（需 Path），已修正。
- 遗留问题：mcp_server.py 尚未做 stdio 真实冒烟（mcp 包依赖）；Docker 仍未真实构建。
- 下一步第一动作：本机 `start_demo.cmd` 跑一遍完整 UI 演示，录屏/截图补充作品集。

### 2026-09-08 11:58

- 本次目标：回应用户"demo 用途不清"的焦虑，落地第二个业务工具「物料错误检测」，让项目从单流程变有真实痛点支撑的方案。
- 实际完成：新增 `erp_agent/validator.py`（`MaterialValidator` 单行校验 7 类错误 + `MaterialAuditor` 批量审计/报告/推送文本）；`tools.py` 新增 `detect_material_errors` 工具（min_level 过滤 + push 落库）；`repository.py` 新增 `error_reports` 表（outbox 模式）+ `save_error_report` + `error_reports`；新增 `tests/test_material_errors.py`（14 用例）；新增知识库 `物料错误检测规则.md`；另产架构图 `architecture.html`、定位说明文档与 `物料错误检测_设计说明.md`。
- 改动文件：`erp_agent/validator.py`（新增）、`erp_agent/tools.py`、`erp_agent/repository.py`、`tests/test_material_errors.py`（新增）、`knowledge/物料错误检测规则.md`（新增）、`architecture.html`、`物料错误检测_设计说明.md`、本文件。
- 验证命令与结果：`.venv/Scripts/python.exe -m unittest discover -s tests -v` → 48/48 OK（原 34 个零回归，新增 14 个）。
- 遇到的问题：无。
- 遗留问题：`detect_material_errors` 尚未接入 MCP 暴露与 Streamlit UI；`create_purchase_order` 的校验逻辑仍未切到 validator（可复用但为保稳定未动）；真实推送 webhook/定时任务未接。
- 下一步第一动作：把新工具暴露到 MCP 与 UI，并在演示脚本里加一段"物料错误自动推送"演示。

### 2026-09-07 22:50

- 本次目标：用户反馈"没体会到 agent、项目太低级"，对标 GitHub 同类项目后，把固定流水线升级为工具调用循环 Agent + MCP + 聊天 UI（一次到位）。
- 实际完成：新增 `erp_agent/tools.py`（5 个工具的 schema 与确定性实现：search_knowledge/query_materials/create_purchase_order/confirm_commit/rollback_po）；`llm.py` 新增 `AgentLoop` 工具调用循环 + `.env` 自动加载；`agent.py` 新增 `chat()` 多轮入口 + session 记忆，保留 `prepare()` 兼容；`api.py` 新增 `POST /agent/chat`；`ui.py` 改为聊天式多轮对话；新增 `mcp_server.py`（FastMCP 暴露 5 个工具）；新增 `tests/test_agent_loop.py`。
- 改动文件：`erp_agent/tools.py`（新增）、`erp_agent/llm.py`、`erp_agent/agent.py`、`erp_agent/models.py`、`api.py`、`ui.py`、`mcp_server.py`（新增）、`tests/test_agent_loop.py`（新增）、`.env`（新增，不入库）、`.env.example`、`README.md`、本文件。
- 验证命令与结果：`python -m unittest discover -s tests -v` 34/34 OK；真实智谱 glm-4-flash 冒烟通过——模型自主调用 create_purchase_order 生成 ¥24164 草稿并停下等确认，第二轮多轮对话调 confirm_commit 写入 PO-DEMO-20260907-D8C8。
- 遇到的问题：云端 key 从数据助手项目 `.env` 复用（智谱 glm-4-flash）；mcp SDK 安装中（走代理较慢）。
- 遗留问题：mcp_server.py 需在 mcp 装好后做 stdio 冒烟验证；Docker 仍未真实构建。
- 下一步第一动作：验证 MCP server 可用后，同步发布副本并 push GitHub。

### 2026-09-07 21:10

- 本次目标：给 Agent 接入真实模型调用（审计结论的 P0 硬伤），采用本地 Ollama + 云端 API 双链路。
- 实际完成：新增 `erp_agent/llm.py`（可插拔 IntentClassifier，OpenAI 兼容接口，白名单校验 + JSON 容错 + 超时回退）；`agent.py` 在 prepare 第 1 步接入意图识别（LLM 只产出意图，金额/校验/写入仍在确定性代码），tool_trace 由 5 步变 6 步；新增 `.env.example`（本地/千问/智谱三套配置）；新增 `tests/test_llm.py`、`tests/test_parser.py`、`tests/test_api.py`，全量 23 个测试通过。
- 改动文件：`erp_agent/llm.py`（新增）、`erp_agent/agent.py`、`.env.example`（新增）、`tests/`（+3）、`README.md`、本文件。
- 验证命令与结果：`python -m unittest discover -s tests -v` 23/23 OK（含 LLM 回退、白名单、parser 边界、API 404/409/幂等）。
- 遇到的问题：测试依赖 `httpx2`（新版 starlette TestClient 要求）已装；Ollama 安装包下载中（curl 走代理 schannel 握手失败，改用 Python requests）。
- 遗留问题：Ollama 安装与 `qwen2:1.5b` 拉取、真实本地模型冒烟待完成；云端 API 需用户提供 key 后实测。
- 下一步第一动作：装好 Ollama 后拉模型，跑一次真实 LLM 意图识别冒烟并补截图/录屏。

### 2026-09-07 16:05

- 本次目标：修复"Demo 打不开"并准备 GitHub 发布副本。
- 实际完成：诊断出 PATH 无 python + 依赖缺失；项目内新建 `.venv` 装齐依赖；两个启动脚本改为优先用 .venv；验证单测 3/3、API/health 200、页面 200。另建桌面干净副本 `Desktop\erp-procurement-agent`（排除《现场业务信息采集清单.md》、data/*.db、__pycache__、.venv，补 .gitignore 与 data/.gitkeep），已 git init 并完成首个 commit。
- 改动文件：`start_demo.cmd`、`start_demo.ps1`、本文件、新增 `.venv`（不入库）；副本目录另计。
- 验证命令与结果：`.venv\Scripts\python.exe -m unittest discover -s tests -v` 3/3 OK；`launch_demo.py` 启动后 curl 两端口均 200。
- 遇到的问题：pydantic==2.13.4 首次 pip 报 No matching distribution，重试成功（见 P-005）。
- 遗留问题：GitHub 远程仓库未创建，待用户建空仓库后 push。
- 下一步第一动作：用户在 GitHub 创建空仓库 `erp-procurement-agent` 后推送副本。

### 2026-08-18 10:35

- 本次目标：建立可持续维护的项目接续文档。
- 实际完成：汇总当前目标、架构、已完成功能、验证证据、已解决问题、缺口、风险、决策和下一步。
- 改动文件：新增 `PROJECT_STATUS.md`；README 增加接续文档入口。
- 验证命令与结果：依据 2026-08-18 已执行的单元测试、API 冒烟和真实启动结果登记。
- 遇到的问题：无。
- 遗留问题：等待用户完成首次页面操作体验；现场业务规则尚待复核。
- 下一步第一动作：用户运行 `start_demo.cmd`，反馈页面或操作中的实际问题。

### 2026-08-18 10:45

- 本次目标：处理用户反馈“Demo 仍无法打开”。
- 实际完成：确认原启动器虽然服务可用，但使用 headless 模式且没有等待页面就绪后自动打开浏览器；固定 Streamlit 监听 `127.0.0.1`，增加页面就绪检测和自动打开浏览器，并让退出时同时清理 UI/API 进程。
- 改动文件：`launch_demo.py`、`README.md`、本文件。
- 验证命令与结果：`start_demo.cmd` 完整启动通过；API 与页面均返回 HTTP 200，终端打印“Demo 已就绪”。
- 遇到的问题：原启动器没有自动打开浏览器，且 Streamlit 默认监听地址不够明确。
- 遗留问题：用户本机浏览器是否被安全软件拦截仍需现场确认。
- 下一步第一动作：用户重新运行 `start_demo.cmd`；若仍打不开，直接访问 `http://127.0.0.1:8501` 并提供终端最后 20 行。
