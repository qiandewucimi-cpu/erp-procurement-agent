from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
import os
import webbrowser
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def wait_for_service(url: str, process: subprocess.Popen, label: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label} 启动失败，进程退出码：{process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"{label} 启动超时，请检查端口是否被占用")


def main() -> int:
    subprocess.run([sys.executable, "generate_samples.py"], cwd=BASE_DIR, check=True)
    api_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=BASE_DIR,
    )
    ui_process = None
    try:
        wait_for_service("http://127.0.0.1:8000/health", api_process, "API")
        print("API 已就绪：http://127.0.0.1:8000/docs")
        print("正在启动 Demo 页面；按 Ctrl+C 退出时，两个服务都会自动停止。")
        streamlit_env = os.environ.copy()
        streamlit_env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        try:
            ui_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "ui.py",
                    "--browser.gatherUsageStats=false",
                    "--server.headless=true",
                    "--server.address=127.0.0.1",
                ],
                cwd=BASE_DIR,
                env=streamlit_env,
            )
            wait_for_service("http://127.0.0.1:8501", ui_process, "Streamlit")
            url = "http://127.0.0.1:8501"
            print(f"Demo 已就绪：{url}")
            webbrowser.open(url)
            return ui_process.wait()
        except KeyboardInterrupt:
            print("\n正在停止 Demo...")
            return 130
    finally:
        if ui_process is not None and ui_process.poll() is None:
            ui_process.terminate()
            try:
                ui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ui_process.kill()
        if api_process.poll() is None:
            api_process.terminate()
            try:
                api_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                api_process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
