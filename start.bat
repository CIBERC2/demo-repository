@echo off
title OpenC2 v1.0 - Launcher
color 0A
echo.
echo  ============================================
echo       OPENC2 v1.0 - STARTING ALL SERVICES
echo  ============================================
echo.

cd /d "%~dp0"

:: ── Verificar dependencias ────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js 18+
    pause
    exit /b 1
)

:: ── Matar procesos anteriores de OpenC2 (reinicio limpio) ─────────────────
echo [0/3] Stopping previous OpenC2 processes...
taskkill /FI "WINDOWTITLE eq OpenC2-Server*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq OpenC2-Agent*"  /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq OpenC2-Dashboard*" /F >nul 2>&1

:: Matar por nombre de proceso en caso de que las ventanas hayan cambiado de título
for /f "tokens=2 delims=," %%a in ('tasklist /fi "IMAGENAME eq python.exe" /fo csv /nh 2^>nul') do (
    wmic process where "ProcessId=%%~a AND CommandLine LIKE '%%main.py%%'" delete >nul 2>&1
    wmic process where "ProcessId=%%~a AND CommandLine LIKE '%%agent.py%%'" delete >nul 2>&1
)

:: Liberar puerto 8000 si está ocupado
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: Liberar puerto 5173 si está ocupado
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

timeout /t 2 /nobreak >nul
echo [OK] Previous processes cleared.
echo.

:: ── Crear .env si no existe ───────────────────────────────────────────────
if not exist "server\.env" (
    echo [SETUP] Creating server\.env with defaults...
    echo C2_HOST=0.0.0.0> "server\.env"
    echo C2_PORT=8000>> "server\.env"
    echo C2_DNS_PORT=5353>> "server\.env"
    echo C2_LOG_LEVEL=INFO>> "server\.env"
    echo SERVER_PRIVATE_KEY_PATH=./keys/server_priv.pem>> "server\.env"
    echo SERVER_PUBLIC_KEY_PATH=./keys/server_pub.pem>> "server\.env"
    echo OPERATOR_TOKEN=openc2-dev-token>> "server\.env"
    echo JWT_SECRET=>> "server\.env"
    echo JWT_EXPIRE_HOURS=24>> "server\.env"
    echo DASHBOARD_ORIGIN=http://localhost:5173>> "server\.env"
    echo SOLANA_ANCHOR=true>> "server\.env"
    echo SOLANA_NETWORK=devnet>> "server\.env"
    echo SOLANA_WALLET_PATH=solana_wallet.json>> "server\.env"
    echo QUEUE_DB_PATH=pending_tasks.db>> "server\.env"
    echo HEARTBEAT_INTERVAL=10>> "server\.env"
    echo HEARTBEAT_JITTER=0.3>> "server\.env"
    echo [OK] .env created
)

:: ── Arrancar servicios ────────────────────────────────────────────────────
echo [1/3] Starting OpenC2 Server on :8000 ...
start "OpenC2-Server" /D "%~dp0server" cmd /c "python main.py & pause"

echo       Waiting for server to initialize...
timeout /t 5 /nobreak >nul

echo [2/3] Starting OpenC2 Agent...
start "OpenC2-Agent" /D "%~dp0agent" cmd /c "python agent.py --server ws://localhost:8000/ws & pause"

echo [3/3] Starting Dashboard on :5173 ...
start "OpenC2-Dashboard" /D "%~dp0dashboard" cmd /c "npm run dev & pause"

echo.
echo  ============================================
echo       OPENC2 v1.0 - ALL SERVICES RUNNING
echo  ============================================
echo.
echo   Server:     http://localhost:8000
echo   Dashboard:  http://localhost:5173
echo   Health:     http://localhost:8000/health
echo   Stage:      http://localhost:8000/api/stage
echo   Token:      openc2-dev-token
echo.
echo   Multi-agent (mismo host):
echo     python agent\agent.py --server ws://localhost:8000/ws --label agent-2
echo.
echo   Presiona cualquier tecla para DETENER todos los servicios...
pause >nul

:: ── Detener todo ──────────────────────────────────────────────────────────
echo.
echo [STOP] Stopping all OpenC2 services...
taskkill /FI "WINDOWTITLE eq OpenC2-Server*"    /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq OpenC2-Agent*"     /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq OpenC2-Dashboard*" /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173 "') do taskkill /PID %%a /F >nul 2>&1
echo [OK] All services stopped.
pause
