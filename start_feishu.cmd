@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    echo [错误] 未找到 .venv。
    echo 请先创建环境：py -3 -m venv .venv
    echo 然后安装依赖：.venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PY%" -c "import lark_oapi" >nul 2>nul
if errorlevel 1 (
    echo [错误] 缺少 lark-oapi，请安装：
    echo     .venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple lark-oapi
    pause
    exit /b 1
)

echo ============================================================
echo  飞书长连接机器人启动中（无需公网，保持本窗口不关）
echo  在飞书里搜到你的机器人，直接发消息即可。
echo  按 Ctrl+C 可退出。
echo ============================================================
"%PY%" feishu_bot.py
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
    echo [启动失败] 退出码 %EXIT_CODE%，请截图反馈。
    pause
)
exit /b %EXIT_CODE%
