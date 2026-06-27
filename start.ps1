#!/usr/bin/env pwsh
# ============================================================
# C2 ALIGO — Script de inicio completo (Windows PowerShell)
# Uso: .\start.ps1
# ============================================================

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$SERVER_DIR   = Join-Path $ROOT "server"
$AGENT_DIR    = Join-Path $ROOT "agent"
$DASHBOARD_DIR= Join-Path $ROOT "dashboard"
$ENV_FILE     = Join-Path $ROOT ".env"

Write-Host ""
Write-Host " ██████╗██████╗      █████╗ ██╗     ██╗ ██████╗  ██████╗ " -ForegroundColor Cyan
Write-Host "██╔════╝╚════██╗    ██╔══██╗██║     ██║██╔════╝ ██╔═══██╗" -ForegroundColor Cyan
Write-Host "██║      █████╔╝    ███████║██║     ██║██║  ███╗██║   ██║" -ForegroundColor Cyan
Write-Host "██║     ██╔═══╝     ██╔══██║██║     ██║██║   ██║██║   ██║" -ForegroundColor Cyan
Write-Host "╚██████╗███████╗    ██║  ██║███████╗██║╚██████╔╝╚██████╔╝" -ForegroundColor Cyan
Write-Host " ╚═════╝╚══════╝    ╚═╝  ╚═╝╚══════╝╚═╝ ╚═════╝  ╚═════╝ " -ForegroundColor Cyan
Write-Host "              Command & Control — Lab Environment           " -ForegroundColor DarkGray
Write-Host ""

# ── Cargar .env si existe ─────────────────────────────────────────────────
if (Test-Path $ENV_FILE) {
    Get-Content $ENV_FILE | Where-Object { $_ -match "^[^#].*=.*" } | ForEach-Object {
        $parts = $_ -split "=", 2
        [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim())
    }
    Write-Host "[+] .env cargado" -ForegroundColor Green
} else {
    Copy-Item (Join-Path $ROOT ".env.example") $ENV_FILE -ErrorAction SilentlyContinue
    Write-Host "[!] .env creado desde .env.example — revisa la configuración" -ForegroundColor Yellow
}

$env:OPERATOR_TOKEN    = if ($env:OPERATOR_TOKEN)    { $env:OPERATOR_TOKEN }    else { "aligo-dev-token" }
$env:C2_PORT           = if ($env:C2_PORT)           { $env:C2_PORT }           else { "8000" }
$env:DASHBOARD_ORIGIN  = "http://localhost:5173"

# ── Matar procesos anteriores en los puertos ────────────────────────────────
function Kill-Port([int]$port) {
    $pids = netstat -ano | Select-String ":$port\s" | ForEach-Object {
        ($_ -split "\s+")[-1]
    } | Where-Object { $_ -match "^\d+$" } | Sort-Object -Unique
    foreach ($p in $pids) {
        try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch {}
    }
}
Write-Host "[*] Limpiando puertos 8000 / 5173..." -ForegroundColor DarkGray
Kill-Port 8000
Kill-Port 5173
Start-Sleep -Seconds 1

# ── 1. Servidor C2 ───────────────────────────────────────────────────────────
Write-Host "[+] Iniciando servidor C2 en :$($env:C2_PORT)..." -ForegroundColor Cyan
$serverJob = Start-Process -FilePath "python" `
    -ArgumentList "main.py" `
    -WorkingDirectory $SERVER_DIR `
    -WindowStyle Normal `
    -PassThru

Start-Sleep -Seconds 3
try {
    $health = Invoke-RestMethod "http://localhost:$($env:C2_PORT)/health" `
        -Headers @{"X-Operator-Token"=$env:OPERATOR_TOKEN} -TimeoutSec 5
    Write-Host "[✓] Servidor C2: $($health.status) (PID $($serverJob.Id))" -ForegroundColor Green
} catch {
    Write-Host "[✗] Servidor C2 no respondió — revisa errores arriba" -ForegroundColor Red
    exit 1
}

# ── 2. Agente de demo ────────────────────────────────────────────────────────
Write-Host "[+] Iniciando agente demo..." -ForegroundColor Cyan
$agentJob = Start-Process -FilePath "python" `
    -ArgumentList "agent.py --server ws://localhost:$($env:C2_PORT)/ws" `
    -WorkingDirectory $AGENT_DIR `
    -WindowStyle Normal `
    -PassThru

Start-Sleep -Seconds 2
Write-Host "[✓] Agente iniciado (PID $($agentJob.Id))" -ForegroundColor Green

# ── 3. Dashboard ─────────────────────────────────────────────────────────────
Write-Host "[+] Iniciando dashboard React en :5173..." -ForegroundColor Cyan
$dashJob = Start-Process -FilePath "npm" `
    -ArgumentList "run dev" `
    -WorkingDirectory $DASHBOARD_DIR `
    -WindowStyle Normal `
    -PassThru

Start-Sleep -Seconds 4
try {
    $code = (Invoke-WebRequest "http://localhost:5173" -UseBasicParsing -TimeoutSec 5).StatusCode
    if ($code -eq 200) {
        Write-Host "[✓] Dashboard: http://localhost:5173 (PID $($dashJob.Id))" -ForegroundColor Green
    }
} catch {
    Write-Host "[!] Dashboard arrancando... abre http://localhost:5173 en 5s" -ForegroundColor Yellow
}

# ── Resumen ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║           C2 ALIGO — SISTEMA LISTO                  ║" -ForegroundColor Cyan
Write-Host "╠══════════════════════════════════════════════════════╣" -ForegroundColor Cyan
Write-Host "║  Servidor C2  →  http://localhost:8000               ║" -ForegroundColor White
Write-Host "║  Dashboard    →  http://localhost:5173               ║" -ForegroundColor White
Write-Host "║  API Docs     →  http://localhost:8000/docs          ║" -ForegroundColor White
Write-Host "║  Audit Trail  →  http://localhost:8000/audit         ║" -ForegroundColor White
Write-Host "║  Métricas     →  http://localhost:8000/metrics       ║" -ForegroundColor White
Write-Host "╠══════════════════════════════════════════════════════╣" -ForegroundColor Cyan
Write-Host "║  Token op.    →  $($env:OPERATOR_TOKEN.PadRight(32))  ║" -ForegroundColor DarkGray
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "CLI del operador:" -ForegroundColor Yellow
Write-Host "  cd server && python -m operator.cli agents list" -ForegroundColor DarkGray
Write-Host "  cd server && python -m operator.cli task shell <agent_id> 'whoami'" -ForegroundColor DarkGray
Write-Host "  cd server && python -m operator.cli audit" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Presiona Ctrl+C para detener todo." -ForegroundColor DarkGray

# Abrir dashboard en el navegador
Start-Process "http://localhost:5173"

# Esperar
try { Wait-Process -Id $serverJob.Id } catch {}
