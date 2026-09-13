from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)


def run(label: str, command: list[str], preserve: tuple[str, ...] = ()) -> bool:
    print(f"\n=== {label} ===")
    snapshots = {
        relative: (ROOT / relative).read_bytes()
        for relative in preserve
        if (ROOT / relative).exists()
    }
    try:
        completed = subprocess.run(command, cwd=ROOT, check=False)
    finally:
        for relative, content in snapshots.items():
            (ROOT / relative).write_bytes(content)
    if completed.returncode == 0:
        print(f"[PASS] {label}")
        return True
    print(f"[FAIL] {label} (exit={completed.returncode})")
    return False


def scan_tracked_files() -> bool:
    print("\n=== 跟踪文件敏感信息扫描 ===")
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=False, capture_output=True
    )
    if listed.returncode != 0:
        print("[FAIL] 无法读取 Git 跟踪文件")
        return False
    patterns = [
        re.compile(rb"sk-[A-Za-z0-9_-]{16,}"),
        re.compile(rb"Bearer\s+[A-Za-z0-9._-]{16,}"),
        re.compile(rb"(?:LLM_API_KEY|FEISHU_APP_SECRET)\s*=\s*[^<\s][^\r\n\s]+"),
    ]
    allowed_placeholders = (b"=your", b"=your-key", "=你的".encode("utf-8"))
    hits: list[str] = []
    for raw_path in listed.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = ROOT / raw_path.decode("utf-8")
        if path.name.endswith(".example"):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for line_number, line in enumerate(data.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns) and not any(x in line.lower() for x in allowed_placeholders):
                hits.append(f"{path.relative_to(ROOT)}:{line_number}")
    if hits:
        print("[FAIL] 疑似敏感值：" + ", ".join(hits))
        return False
    print("[PASS] 未发现真实 API Key、Bearer Token 或飞书 Secret")
    return True


def main() -> int:
    checks = [
        run("单元测试", [str(PYTHON), "-m", "unittest", "discover", "-s", "tests"]),
        run("面试证据烟测", [str(PYTHON), "smoke_interview.py"]),
        run(
            "Agent 确定性评测",
            [str(PYTHON), "evals/run_eval.py", "--offline"],
            ("evals/REPORT.md", "evals/results.json"),
        ),
        run(
            "RAG 质量门禁",
            [str(PYTHON), "evals/run_rag_eval.py"],
            ("evals/RAG_REPORT.md", "evals/rag_results.json"),
        ),
        run("编译检查", [str(PYTHON), "-m", "compileall", "-q", "api.py", "ui.py", "mcp_server.py", "erp_agent", "evals"]),
        run("Git diff 检查", ["git", "diff", "--check"]),
        scan_tracked_files(),
    ]
    passed = sum(checks)
    print(f"\n面试前预检：{passed}/{len(checks)} 通过")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
