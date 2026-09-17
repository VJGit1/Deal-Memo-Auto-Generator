# DMAG - Unified Windows Demo Launcher
# Starts Redis (Docker), RQ Worker (SimpleWorker for Windows), FastAPI, and React Frontend.

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   DMAG - Deal Memo Auto Generator      " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Ensure Redis is running via Docker
Write-Host "`n[1/4] Checking Redis..." -ForegroundColor Yellow
try {
    docker compose unpause 2>$null
    docker compose up -d
    Write-Host "Redis is running on localhost:6379" -ForegroundColor Green
} catch {
    Write-Host "Warning: Could not start docker compose. Ensure Docker Desktop is running." -ForegroundColor Red
}

# Find Python in venv
$PythonExe = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = Join-Path $PSScriptRoot "backend\.venv\Scripts\python.exe"
}
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

# 2. Start RQ Worker (SimpleWorker on Windows)
Write-Host "`n[2/4] Starting RQ Worker (SimpleWorker)..." -ForegroundColor Yellow
$BackendDir = Join-Path $PSScriptRoot "backend"
$WorkerProcess = Start-Process -FilePath $PythonExe -ArgumentList "-m", "api.worker" -WorkingDirectory $BackendDir -PassThru -NoNewWindow

# 3. Start FastAPI backend
Write-Host "`n[3/4] Starting FastAPI backend on http://localhost:8000..." -ForegroundColor Yellow
$ApiProcess = Start-Process -FilePath $PythonExe -ArgumentList "-m", "uvicorn", "api.main:app", "--port", "8000" -WorkingDirectory $BackendDir -PassThru -NoNewWindow

# 4. Start Frontend
Write-Host "`n[4/4] Starting Frontend dev server..." -ForegroundColor Yellow
$FrontendDir = Join-Path $PSScriptRoot "frontend"
$FrontendProcess = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory $FrontendDir -PassThru -NoNewWindow

Start-Sleep -Seconds 3

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "   DMAG is ready!                      " -ForegroundColor Green
Write-Host "   API Health: http://localhost:8000/api/health" -ForegroundColor Cyan
Write-Host "   Open your browser to the URL printed by Vite above" -ForegroundColor Cyan
Write-Host "   (usually http://localhost:5173 or http://localhost:5174)" -ForegroundColor Cyan
Write-Host "   Press Ctrl+C in this window to stop all services." -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Green

# Wait and cleanup on exit
try {
    while ($true) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "`nShutting down DMAG services..." -ForegroundColor Yellow
    if ($WorkerProcess -and -not $WorkerProcess.HasExited) { Stop-Process -Id $WorkerProcess.Id -Force -ErrorAction SilentlyContinue }
    if ($ApiProcess -and -not $ApiProcess.HasExited) { Stop-Process -Id $ApiProcess.Id -Force -ErrorAction SilentlyContinue }
    if ($FrontendProcess -and -not $FrontendProcess.HasExited) { Stop-Process -Id $FrontendProcess.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "All services stopped." -ForegroundColor Green
}
