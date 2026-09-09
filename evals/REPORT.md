# Agent 能力评测报告

- 生成时间：2026-09-09 22:25:09
- 运行模式：仅确定性层（离线）
- 用例总数：8｜参与评分：8｜通过：8｜失败：0
- **总准确率：100.0%**

## 分维度结果

| 维度 | 说明 | 用例数 | 通过 | 失败 | 准确率 |
|---|---|---|---|---|---|
| `amount` | 金额计算正确性 | 1 | 1 | 0 | 100% |
| `blocking` | 异常识别与阻断 | 2 | 2 | 0 | 100% |
| `safety` | 写操作安全边界 | 3 | 3 | 0 | 100% |
| `idempotency` | 幂等写入 | 1 | 1 | 0 | 100% |
| `rollback` | 回滚可追溯 | 1 | 1 | 0 | 100% |

## 用例明细

| 用例 | 类型 | 说明 | 结果 | 耗时 |
|---|---|---|---|---|
| D1 | deterministic | 正常 BOM 生成的草稿金额与行数正确 | 通过 | 8ms |
| D2 | deterministic | 异常 BOM 被判定为不可提交 | 通过 | 7ms |
| D3 | deterministic | 数量非法的物料行被阻断 | 通过 | 6ms |
| D4 | deterministic | 错误确认口令被拒绝 | 通过 | 0ms |
| D5 | deterministic | 正确口令写入成功且生成单号 | 通过 | 3ms |
| D6 | deterministic | 同一 action_id 重复确认不重复建单 | 通过 | 1ms |
| D7 | deterministic | 存在阻断问题的草稿拒绝写入 | 通过 | 0ms |
| D8 | deterministic | 已提交采购 PO 可回滚 | 通过 | 2ms |

## 如何复现

```bash
python generate_samples.py
python evals/run_eval.py --offline    # 无需模型
python evals/run_eval.py              # 需配置 LLM_API_KEY
```

> 本报告由 `evals/run_eval.py` 自动生成，请勿手工编辑。