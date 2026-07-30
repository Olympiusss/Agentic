# ============================================================
# Sentry Agentic — Windows Startup Script
# Equivalent of start_web.sh for PowerShell
# Usage: .\start.ps1
# ============================================================

$ROOT = "C:\Users\Favour.ESENTRY\Desktop\Automation\SentryAgentic"
Set-Location $ROOT

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Sentry Agentic v2.0 — Starting Up" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# ── 1. Kill any stale processes ─────────────────────────────
Write-Host "`n[1/5] Cleaning up stale processes..." -ForegroundColor Yellow
Get-Process -Name python  -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# ── 2. Load .env exactly as start_web.sh does ───────────────
Write-Host "[2/5] Loading environment..." -ForegroundColor Yellow
$env:PYTHONPATH        = $ROOT
$env:PYTHONIOENCODING  = "utf-8"
Get-Content "$ROOT\.env" | ForEach-Object {
    if ($_ -match "^([^#=][^=]*)=(.*)$") {
        $k = $Matches[1].Trim()
        $v = $Matches[2].Trim().Trim('"')
        [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}
# Override Bifrost URL for native (non-Docker) run — same as start_web.sh
$env:BIFROST_URL = "http://localhost:8080"
Write-Host "  BIFROST_URL  = $env:BIFROST_URL" -ForegroundColor DarkGray
Write-Host "  DATABASE_URL = $env:DATABASE_URL" -ForegroundColor DarkGray

# ── 3. Start Docker containers ───────────────────────────────
Write-Host "`n[3/5] Starting Docker containers..." -ForegroundColor Yellow
Set-Location "$ROOT\docker"

# Remove any stopped sentry containers from previous runs
docker rm -f sentry-postgres sentry-redis sentry-bifrost 2>$null | Out-Null

# Start fresh
docker compose up -d postgres redis bifrost | Out-Null

Write-Host "  Waiting for containers to be healthy..." -ForegroundColor DarkGray
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    $redis  = docker inspect --format "{{.State.Health.Status}}" sentry-redis   2>$null
    $pg     = docker inspect --format "{{.State.Health.Status}}" sentry-postgres 2>$null
    if ($redis -eq "healthy" -and $pg -eq "healthy") { $healthy = $true; break }
}
if (-not $healthy) { Write-Host "  WARNING: Containers may not be fully healthy yet" -ForegroundColor Red }

Set-Location $ROOT
docker ps --format "table {{.Names}}`t{{.Status}}" | Write-Host

# ── 4. Start Backend (port 6987) ─────────────────────────────
Write-Host "`n[4/5] Starting backend API on port 6987..." -ForegroundColor Yellow
$backendJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location $root
    $env:PYTHONPATH       = $root
    $env:PYTHONIOENCODING = "utf-8"
    Get-Content "$root\.env" | ForEach-Object {
        if ($_ -match "^([^#=][^=]*)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim().Trim('"'), "Process")
        }
    }
    $env:BIFROST_URL = "http://localhost:8080"
    & "$root\venv\Scripts\uvicorn.exe" backend.main:app --host 127.0.0.1 --port 6987 2>&1
} -ArgumentList $ROOT

Start-Sleep -Seconds 5

# ── 5. Start ARQ LLM Worker ──────────────────────────────────
Write-Host "[5/5] Starting ARQ LLM worker..." -ForegroundColor Yellow
$workerJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location $root
    $env:PYTHONPATH       = $root
    $env:PYTHONIOENCODING = "utf-8"
    Get-Content "$root\.env" | ForEach-Object {
        if ($_ -match "^([^#=][^=]*)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim().Trim('"'), "Process")
        }
    }
    $env:BIFROST_URL = "http://localhost:8080"
    & "$root\venv\Scripts\python.exe" -m services.run_llm_worker 2>&1
} -ArgumentList $ROOT

Start-Sleep -Seconds 3

# ── Optional: Start Frontend ─────────────────────────────────
if (Test-Path "$ROOT\frontend\node_modules") {
    Write-Host "`nStarting frontend dev server..." -ForegroundColor Yellow
    $frontendJob = Start-Job -ScriptBlock {
        param($root)
        Set-Location "$root\frontend"
        npm run dev 2>&1
    } -ArgumentList $ROOT
    Start-Sleep -Seconds 4
}

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "  Sentry Agentic v2.0 — Ready!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Backend API : http://localhost:6987"
Write-Host "  API Docs    : http://localhost:6987/docs"
Write-Host "  Frontend    : http://localhost:6990  (or 6988/6989)"
Write-Host ""
Write-Host "  Login: admin / SentryAdmin2024!"
Write-Host ""
Write-Host "Press Ctrl+C to stop all services."
Write-Host "==========================================" -ForegroundColor Green

# Keep alive and stream logs
try {
    while ($true) {
        Start-Sleep -Seconds 5
        $backendJob, $workerJob | ForEach-Object {
            if ($_ -and $_.HasMoreData) {
                Receive-Job $_ | Write-Host -ForegroundColor DarkGray
            }
        }
    }
} finally {
    Write-Host "`nShutting down..." -ForegroundColor Yellow
    $backendJob, $workerJob | Stop-Job
    $backendJob, $workerJob | Remove-Job
    docker stop sentry-postgres sentry-redis sentry-bifrost 2>$null | Out-Null
    Write-Host "All services stopped." -ForegroundColor Green
}
