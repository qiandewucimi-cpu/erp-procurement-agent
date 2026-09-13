# ERP Adapter 接口与联调契约

## 1. 为什么增加 Adapter

Agent 的工具编排、金额校验、写前确认不应依赖某一家 ERP 的 URL、鉴权方式或错误文案。`ERPAdapter` 把业务层需要的最小能力固定下来：本地演示使用 SQLite，客户联调时切换 HTTP 实现，工具 schema 与安全规则无需重写。

当前默认仍是完全离线的合成数据模式，不代表已经连接任何真实企业系统。

## 2. 切换方式

```dotenv
ERP_BACKEND=sqlite
```

客户测试环境联调时改为：

```dotenv
ERP_BACKEND=http
ERP_API_BASE_URL=https://customer.example/erp-agent-api
ERP_API_TOKEN=由客户密钥系统注入
ERP_API_TIMEOUT=5
ERP_API_MAX_RETRIES=2
```

Token 只从环境变量读取，不进入源码、日志、测试夹具或提交历史。

## 3. HTTP 契约

| 方法 | 路径 | 用途 | 幂等策略 |
|---|---|---|---|
| GET | `/materials/{code}` | 查询单个物料 | 只读 |
| GET | `/materials` | 查询物料列表 | 只读 |
| POST | `/materials/import` | 导入物料主数据 | 请求内容哈希 |
| POST | `/actions/preview` | 保存写前预览 | 预览内容与操作人哈希 |
| POST | `/actions/{action_id}/approve` | 审批其他人发起的草稿 | `action_id` |
| POST | `/actions/{action_id}/confirm` | 确认写入 | `action_id` |
| POST | `/actions/{action_id}/rollback` | 回滚 | `action_id` |
| GET | `/orders` | 查询采购单 | 只读 |
| GET | `/approvals` | 查询草稿与审批状态 | 只读 |
| GET | `/audit` | 查询审计日志 | 只读 |
| POST | `/error-reports` | 保存错误报告 | 报告内容哈希 |
| GET | `/error-reports` | 查询错误报告 | 只读 |

所有写请求通过 `Idempotency-Key` 传递稳定幂等键；鉴权使用 `Authorization: Bearer <token>`。

## 4. 失败语义

| 外部现象 | Adapter 行为 | 上层处理建议 |
|---|---|---|
| 超时、断连 | 指数退避重试，耗尽后抛 `ERPUnavailableError` | 告知暂不可用，不继续写入 |
| HTTP 429/5xx | 有界重试 | 保护客户服务，禁止无限重试 |
| HTTP 401/403 | `ERPAuthenticationError` | 停止请求并检查凭证/权限 |
| HTTP 404 | `ERPNotFoundError` | 查询物料时转换为未建档 |
| HTTP 409 | `ERPConflictError` | 展示状态或幂等冲突，不重复写入 |
| 非 JSON/其他 4xx | `ERPAdapterError` | 记录稳定错误类型，隐藏厂商内部细节 |

## 5. 客户联调检查清单

1. 与客户确认真实字段映射、必填项、币种和供应商拆单规则。
2. 在测试租户验证 Token 权限最小化，禁止使用生产管理员账号。
3. 确认客户 ERP 是否原生支持幂等键、事务、审批和审计；不支持时由中间层补偿。
4. 用脱敏或合成数据完成正常、重复、超时、冲突和回滚测试。
5. 记录接口版本、限流、SLA、错误码映射和回退联系人。
6. 正式接入前必须完成安全评审；本项目当前只提供可替换接口和模拟验证。
