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
        echo 请先创建环境：  py -3 -m venv .venv
        echo 然后安装依赖：  .venv\Scripts\python.exe -m pip install -r requirements.txt
        exit /b 1
    )
)

"%PY%" launch_demo.py
set EXIT_CODE=%ERRORLEVEL%
endlocal & exit /b %EXIT_CODE%
