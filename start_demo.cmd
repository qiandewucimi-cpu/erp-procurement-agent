@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 优先使用项目自带的 .venv，避免依赖系统 PATH 上的 python
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set "PY=python"
    ) else (
        echo [错误] 未找到 .venv，PATH 上也没有 python。
        goto :show_hint
    )
)

rem 检查关键依赖是否已安装（避免发布副本无依赖时秒退）
"%PY%" -c "import fastapi, streamlit, openpyxl, pandas, requests" >nul 2>nul
if not %ERRORLEVEL%==0 (
    echo [错误] Python 缺少依赖 fastapi/streamlit 等。
    goto :show_hint
)

"%PY%" launch_demo.py
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [启动失败] 退出码 %EXIT_CODE%，请把上方错误信息截图反馈。
    echo.
    pause
)
endlocal & exit /b %EXIT_CODE%

:show_hint
echo.
echo ------------------------------------------------------------
echo  你现在打开的这个文件夹，可能是「发布副本」（无依赖）。
echo  请改到「工作目录」运行，路径是：
echo.
echo    rongheng-erp-agent\FDE_秋招8周冲刺\projects\erp_agent_assistant
echo.
echo  如果这确实是工作目录，请先安装依赖：
echo    py -3 -m venv .venv
echo    .venv\Scripts\python.exe -m pip install -r requirements.txt
echo ------------------------------------------------------------
echo.
pause
endlocal & exit /b 1
