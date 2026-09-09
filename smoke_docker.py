"""Docker Compose 冒烟测试：验证容器化后的 API 与 UI 真实可用。

用途
----
在 `docker compose up -d` 之后运行，确认：
1. API 容器健康，核心端点返回 200；
2. UI 容器（Streamlit）健康；
3. 容器内确实能跑通业务链路（六步确定性流水线 /agent/prepare，
   不依赖 LLM，因此无 key 也能验证镜像内的代码与数据是好的）。

用法
----
    python smoke_docker.py                    # 默认 http://127.0.0.1:8000 / 8501
    python smoke_docker.py --api http://x:8000 --ui http://x:8501

退出码：0 = 全部通过；1 = 有失败项。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_UI = "http://127.0.0.1:8501"

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def _get(url: str, timeout: int = 10):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _post(url: str, payload: dict, timeout: int = 60):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def check(name: str, fn) -> None:
    """执行一个检查项，记录结果但不中断流程。"""
    try:
        detail = fn()
        _results.append((PASS, name, detail))
        print(f"  [{PASS}] {name} -> {detail}")
    except urllib.error.HTTPError as exc:
        _results.append((FAIL, name, f"HTTP {exc.code}"))
        print(f"  [{FAIL}] {name} -> HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001 - 冒烟脚本要吞掉所有异常继续跑
        _results.append((FAIL, name, f"{type(exc).__name__}: {exc}"))
        print(f"  [{FAIL}] {name} -> {type(exc).__name__}: {exc}")


def wait_ready(base: str, path: str, attempts: int = 30) -> bool:
    """轮询等待服务就绪，容器冷启动需要时间。"""
    for _ in range(attempts):
        try:
            status, _ = _get(f"{base}{path}", timeout=5)
            if status == 200:
                return True
        except Exception:  # noqa: BLE001 - 未就绪时忽略，继续重试
            pass
        time.sleep(2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Docker Compose 冒烟测试")
    parser.add_argument("--api", default=DEFAULT_API, help="API 基地址")
    parser.add_argument("--ui", default=DEFAULT_UI, help="UI 基地址")
    args = parser.parse_args()

    print("=" * 62)
    print("Docker Compose 冒烟测试")
    print(f"API: {args.api}   UI: {args.ui}")
    print("=" * 62)

    # ---------- 1. 等待服务就绪 ----------
    print("\n[1] 等待服务就绪")
    api_ready = wait_ready(args.api, "/health")
    print(f"  API 就绪: {'是' if api_ready else '否'}")
    ui_ready = wait_ready(args.ui, "/_stcore/health")
    print(f"  UI  就绪: {'是' if ui_ready else '否'}")

    # ---------- 2. API 核心端点 ----------
    print("\n[2] API 核心端点")

    def _health():
        status, body = _get(f"{args.api}/health")
        return f"{status} {body[:80]}"

    def _samples():
        status, body = _get(f"{args.api}/samples")
        data = json.loads(body)
        return f"{status} 样例 {len(data)} 个: {data}"

    def _orders():
        status, body = _get(f"{args.api}/orders")
        return f"{status} 订单 {len(json.loads(body))} 条"

    def _error_reports():
        status, body = _get(f"{args.api}/error_reports")
        return f"{status} 错误报告 {len(json.loads(body))} 条"

    def _audit():
        status, body = _get(f"{args.api}/audit")
        return f"{status} 审计 {len(json.loads(body))} 条"

    check("GET /health", _health)
    check("GET /samples", _samples)
    check("GET /orders", _orders)
    check("GET /error_reports", _error_reports)
    check("GET /audit", _audit)

    # ---------- 3. 容器内业务链路（确定性流水线，不依赖 LLM） ----------
    print("\n[3] 容器内业务链路（/agent/prepare，无需 LLM key）")

    def _prepare():
        status, body = _post(
            f"{args.api}/agent/prepare",
            {"task": "根据 BOM 生成采购 PO 草稿", "filename": "正常示例_BOM.xlsx"},
            timeout=90,
        )
        data = json.loads(body)
        # PrepareResponse: action_id / status / draft.total_amount / issues
        return (
            f"{status} status={data.get('status')} "
            f"总额={data.get('draft', {}).get('total_amount')} "
            f"阻断={sum(1 for i in data.get('issues', []) if i.get('level') == 'blocking')}"
        )

    def _detect():
        status, body = _post(
            f"{args.api}/agent/detect",
            {"filename": "异常示例_BOM.xlsx", "push": True},
            timeout=60,
        )
        data = json.loads(body)
        summary = data.get("summary", {})
        return (
            f"{status} 共 {summary.get('total_rows')} 行，"
            f"检出 {summary.get('error_count')} 个错误"
            f"（阻断 {summary.get('blocking')} / 警告 {summary.get('warning')}）"
            f" report_id={data.get('report_id')}"
        )

    check("POST /agent/prepare（六步流水线）", _prepare)
    check("POST /agent/detect（物料错误检测）", _detect)

    # ---------- 4. UI 健康 ----------
    print("\n[4] UI 健康")

    def _ui_health():
        status, body = _get(f"{args.ui}/_stcore/health")
        return f"{status} {body.strip()}"

    check("GET /_stcore/health", _ui_health)

    # ---------- 汇总 ----------
    failed = [r for r in _results if r[0] == FAIL]
    print("\n" + "=" * 62)
    print(f"结果：{len(_results) - len(failed)}/{len(_results)} 通过")
    if failed:
        print("失败项：")
        for _, name, detail in failed:
            print(f"  - {name}: {detail}")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
