@echo off
chcp 65001 >nul
title 飞书机器人常驻（崩溃自动重启）
REM ============================================================
REM  飞书长连接机器人常驻启动器
REM  - 保留可见控制台窗口（能看到 connected / 收到消息）
REM  - 机器人崩溃或退出时，自动 3 秒后重启（保持常启）
REM  - 运行日志同时写入同目录 feishu_bot.log
REM  用法：双击本文件启动；关掉这个窗口 = 停止机器人
REM  注意：同一时间只能有一个实例连飞书，勿重复双击
REM ============================================================
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    echo [错误] 未找到 .venv，请先创建环境：
    echo     py -3 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PY%" -c "import lark_oapi" >nul 2>nul
if errorlevel 1 (
    echo [错误] 缺少 lark-oapi，请安装：
    echo     .venv\Scripts\python.exe -m pip install lark-oapi
    pause
    exit /b 1
)

:loop
echo ============================================================
echo  飞书长连接机器人启动中（无需公网，保持本窗口不关）
echo  崩溃会自动重启；关掉本窗口 = 停止机器人
echo  日志：feishu_bot.log
echo ============================================================
powershell -NoLogo -NoProfile -Command "& { & $env:PY -u feishu_bot.py 2>&1 | Tee-Object -FilePath 'feishu_bot.log' -Append; exit $LASTEXITCODE }"
set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] 机器人退出（code=%EXIT_CODE%），3 秒后重启...
echo [%date% %time%] 机器人退出（code=%EXIT_CODE%），3 秒后重启... >> "feishu_bot.log"
timeout /t 3 /nobreak >nul
goto loop
