@echo off
title OpenC2 v1.0 - Installer
color 0B
echo.
echo  ============================================
echo       OPENC2 v1.0 - FULL INSTALLATION
echo  ============================================
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)
echo [OK] Python found

:: Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js 18+ from nodejs.org
    pause
    exit /b 1
)
echo [OK] Node.js found

:: Install server dependencies
echo.
echo [1/4] Installing server dependencies...
cd /d "%~dp0server"
pip install -r requirements.txt
if errorlevel 1 (
    echo [WARN] Some packages may have failed. Trying individual install...
    pip install fastapi==0.115.0 uvicorn[standard]==0.32.0 websockets>=13.1 cryptography==43.0.3 pydantic>=2.11.7 python-dotenv==1.0.1 rich==13.9.4 dnslib==0.9.25 PyJWT>=2.9.0 httpx>=0.27.0
)

:: Solana SDK (optional)
echo [1b/4] Installing Solana SDK (optional, for blockchain anchoring)...
pip install solana>=0.39.0 solders>=0.27.0 2>nul
if errorlevel 1 echo [WARN] Solana SDK failed - blockchain anchoring disabled

:: Install agent dependencies
echo.
echo [2/4] Installing agent dependencies...
cd /d "%~dp0agent"
pip install psutil websockets cryptography

:: Install dashboard dependencies
echo.
echo [3/4] Installing dashboard dependencies...
cd /d "%~dp0dashboard"
call npm install

:: Setup .env
echo.
echo [4/4] Configuring environment...
cd /d "%~dp0server"
if not exist ".env" (
    echo C2_HOST=0.0.0.0> ".env"
    echo C2_PORT=8000>> ".env"
    echo C2_DNS_PORT=5353>> ".env"
    echo C2_LOG_LEVEL=INFO>> ".env"
    echo SERVER_PRIVATE_KEY_PATH=./keys/server_priv.pem>> ".env"
    echo SERVER_PUBLIC_KEY_PATH=./keys/server_pub.pem>> ".env"
    echo OPERATOR_TOKEN=openc2-dev-token>> ".env"
    echo JWT_SECRET=>> ".env"
    echo JWT_EXPIRE_HOURS=24>> ".env"
    echo DASHBOARD_ORIGIN=http://localhost:5173>> ".env"
    echo SOLANA_ANCHOR=true>> ".env"
    echo SOLANA_NETWORK=devnet>> ".env"
    echo SOLANA_WALLET_PATH=solana_wallet.json>> ".env"
    echo QUEUE_DB_PATH=pending_tasks.db>> ".env"
    echo DNS_SHARED_KEY=>> ".env"
    echo HEARTBEAT_INTERVAL=10>> ".env"
    echo HEARTBEAT_JITTER=0.3>> ".env"
    echo [OK] .env created with default values
) else (
    echo [OK] .env already exists - skipping
)

cd /d "%~dp0"
echo.
echo  ============================================
echo       OPENC2 v1.0 INSTALLATION COMPLETE
echo  ============================================
echo.
echo   Next step: run start.bat to launch all services.
echo   Dashboard: http://localhost:5173
echo   Server:    http://localhost:8000
echo   Token:     openc2-dev-token (change in server\.env)
echo.
pause
