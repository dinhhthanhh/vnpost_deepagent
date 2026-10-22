param(
    [string]$EnvironmentName = "vnpost-deepagent",
    [switch]$Update
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$conda = (Get-Command conda -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $conda) {
    $knownInstall = Join-Path $env:USERPROFILE "miniconda3\\condabin\\conda.bat"
    if (Test-Path $knownInstall) { $conda = $knownInstall }
}
if (-not $conda) {
    throw "Không tìm thấy Conda. Hãy cài Miniforge/Miniconda, mở PowerShell mới, rồi chạy lại script này."
}

Push-Location $root
try {
    if ($Update) {
        & $conda env update --name $EnvironmentName --file environment.yml --prune
    }
    else {
        & $conda env create --name $EnvironmentName --file environment.yml
    }
    & $conda run --name $EnvironmentName python scripts/verify_gpu.py
}
finally {
    Pop-Location
}
