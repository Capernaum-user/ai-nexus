# ai-nexus  chat server launcher
param(
    [int]$Port = 8765,
    [switch]$Open
)

$ServerDir = Join-Path $PSScriptRoot "server"
$ReqFile   = Join-Path $ServerDir "requirements.txt"

Write-Host "=== ai-nexus chat server ===" -ForegroundColor Cyan

# ── 1. check python ──────────────────────────────────────────────
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[ERROR] Python not found. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

# ── 2. install deps if needed ────────────────────────────────────
$uvicornOk = python -c "import uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    python -m pip install -r $ReqFile --quiet
}

# ── 3. open browser ──────────────────────────────────────────────
if ($Open) {
    Start-Sleep -Milliseconds 1500
    Start-Process "http://localhost:$Port"
}

# ── 4. launch server ─────────────────────────────────────────────
Write-Host "Starting server at http://localhost:$Port  (Ctrl+C to stop)" -ForegroundColor Green
Set-Location $ServerDir
python -m uvicorn main:app --host 0.0.0.0 --port $Port --reload
