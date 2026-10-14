param(
    [int]$Port = 8000,
    [string]$EnvironmentName = "vnpost-deepagent"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$conda = (Get-Command conda -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $conda) {
    $knownInstall = Join-Path $env:USERPROFILE "miniconda3\\condabin\\conda.bat"
    if (Test-Path $knownInstall) { $conda = $knownInstall }
}

if (!(Test-Path ".env")) { Copy-Item .env.example .env }

if ($conda) {
    & $conda run --name $EnvironmentName python --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        & "$PSScriptRoot\scripts\setup-conda.ps1" -EnvironmentName $EnvironmentName
    }
    & $conda run --no-capture-output --name $EnvironmentName python -c "from app.config import Settings; s = Settings(); print('LLM Model:', s.llm_model)"
    if ($LASTEXITCODE -ne 0) { throw "Cấu hình không hợp lệ" }
    Write-Host "Mở http://127.0.0.1:$Port sau khi máy chủ khởi động. Dừng bằng Ctrl+C."
    & $conda run --no-capture-output --name $EnvironmentName python -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers
    exit $LASTEXITCODE
}

# Fallback only for machines without Conda; it is suitable for the CPU/demo path.
if (!(Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.12 -m venv .venv }
    else { python -m venv .venv }
}
& ".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Không cài được dependency" }
& ".venv\Scripts\python.exe" -c "from app.config import Settings; s = Settings(); print('LLM Model:', s.llm_model)"
if ($LASTEXITCODE -ne 0) { throw "Cấu hình không hợp lệ" }
Write-Host "Mở http://127.0.0.1:$Port sau khi máy chủ khởi động. Dừng bằng Ctrl+C."
& ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers

