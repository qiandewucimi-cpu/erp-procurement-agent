@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    echo [错误] 未找到 .venv，PATH 上也没有 python。
    echo 请先创建环境：py -3 -m venv .venv
    echo 然后安装依赖：.venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PY%" -c "import fastapi, streamlit" >nul 2>nul
if errorlevel 1 (
    echo [错误] 缺少依赖，这是发布副本吗？请到工作目录 rongheng-erp-agent 下运行。
    pause
    exit /b 1
)

echo 正在启动，请不要关闭本窗口。按 Ctrl+C 可退出。
"%PY%" launch_demo.py
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
    echo [启动失败] 退出码 %EXIT_CODE%，请截图反馈。
    pause
)
exit /b %EXIT_CODE%
