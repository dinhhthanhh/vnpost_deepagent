param(
    [int]$Port = 8000,
    [string]$EnvironmentName = "vnpost-deepagent",
    [switch]$NoDocker = $false
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (!(Test-Path ".env")) { Copy-Item .env.example .env }

# ------------------------------------------------------------------------------
# Khởi động cơ sở dữ liệu Docker (PostgreSQL & Qdrant) để bảo toàn lịch sử chat
# ------------------------------------------------------------------------------
if (-not $NoDocker) {
    $docker = (Get-Command docker -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    if ($docker) {
        Write-Host "==========================================================" -ForegroundColor Cyan
        Write-Host " Đang kiểm tra và khởi động PostgreSQL & Qdrant qua Docker..." -ForegroundColor Cyan
        Write-Host "==========================================================" -ForegroundColor Cyan
        try {
            & docker compose up -d postgres qdrant
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Container PostgreSQL (5432) & Qdrant (6333) đã sẵn sàng." -ForegroundColor Green
            } else {
                Write-Host "[Cảnh báo] docker compose trả về lỗi. Hệ thống sẽ dùng SQLite fallback." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "[Cảnh báo] Không thể kết nối tới Docker Daemon: $_" -ForegroundColor Yellow
            Write-Host "          Hệ thống sẽ tạm thời sử dụng SQLite fallback cục bộ." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[Lưu ý] Không tìm thấy lệnh 'docker'. Hệ thống sẽ dùng SQLite fallback." -ForegroundColor Yellow
    }
}

$uv = (Get-Command uv -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if ($uv) {
    if (!(Test-Path ".venv")) {
        Write-Host "Khởi tạo môi trường bằng uv..."
        & $uv sync
    }
    & $uv run python -c "from app.core.config import Settings; s = Settings(); print('LLM Model:', s.llm_model)"
    if ($LASTEXITCODE -ne 0) { throw "Cấu hình không hợp lệ" }
    Write-Host "Mở http://127.0.0.1:$Port sau khi máy chủ khởi động. Dừng bằng Ctrl+C."
    & $uv run uvicorn app.api.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers
    exit $LASTEXITCODE
}

$conda = (Get-Command conda -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $conda) {
    $knownInstall = Join-Path $env:USERPROFILE "miniconda3\\condabin\\conda.bat"
    if (Test-Path $knownInstall) { $conda = $knownInstall }
}

if ($conda) {
    & $conda run --name $EnvironmentName python --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        & "$PSScriptRoot\scripts\setup-conda.ps1" -EnvironmentName $EnvironmentName
    }
    & $conda run --no-capture-output --name $EnvironmentName python -c "from app.core.config import Settings; s = Settings(); print('LLM Model:', s.llm_model)"
    if ($LASTEXITCODE -ne 0) { throw "Cấu hình không hợp lệ" }
    Write-Host "Mở http://127.0.0.1:$Port sau khi máy chủ khởi động. Dừng bằng Ctrl+C."
    & $conda run --no-capture-output --name $EnvironmentName python -m uvicorn app.api.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers
    exit $LASTEXITCODE
}

# Fallback only for machines without Conda; it is suitable for the CPU/demo path.
if (!(Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.12 -m venv .venv }
    else { python -m venv .venv }
}
& ".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Không cài được dependency" }
& ".venv\Scripts\python.exe" -c "from app.core.config import Settings; s = Settings(); print('LLM Model:', s.llm_model)"
if ($LASTEXITCODE -ne 0) { throw "Cấu hình không hợp lệ" }
Write-Host "Mở http://127.0.0.1:$Port sau khi máy chủ khởi động. Dừng bằng Ctrl+C."
& ".venv\Scripts\python.exe" -m uvicorn app.api.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers

