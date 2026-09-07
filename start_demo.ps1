$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

# 优先使用项目自带的 .venv，避免依赖系统 PATH 上的 python
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Py = $VenvPython
} else {
    $Py = "python"
}

& $Py generate_samples.py
$ApiProcess = Start-Process -FilePath $Py -ArgumentList "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru
Write-Host "API 已启动，PID=$($ApiProcess.Id)，文档：http://127.0.0.1:8000/docs"
Write-Host "关闭 Streamlit 后，可执行 Stop-Process -Id $($ApiProcess.Id) 停止 API。"
& $Py -m streamlit run ui.py --browser.gatherUsageStats=false --server.headless=true
