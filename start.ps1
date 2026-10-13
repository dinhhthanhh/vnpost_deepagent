param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (!(Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.12 -m venv .venv
    } else {
        python -m venv .venv
    }
}
& ".venv\Scripts\python.exe" -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "Không cài được dependency" }
if (!(Test-Path ".env")) { Copy-Item .env.example .env }
& ".venv\Scripts\python.exe" -c "from app.config import Settings; s = Settings(); print('LLM Model:', s.llm_model)"
if ($LASTEXITCODE -ne 0) { throw "Cấu hình không hợp lệ" }
Write-Host "Mở http://127.0.0.1:$Port sau khi máy chủ khởi động. Dừng bằng Ctrl+C."
& ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers

