@echo off
title OpenC2 v1.0 - Installer
color 0B
echo.
echo  ============================================
echo       OPENC2 v1.0 - FULL INSTALLATION
echo  ============================================
echo.

:: Asegurar que estamos en el directorio del batch
cd /d "%~dp0"

:: Verificar estructura de carpetas (quien clona solo el .bat falla aquí)
if not exist "server" (
    echo [ERROR] Carpeta 'server' no encontrada.
    echo         Asegurate de clonar TODO el repositorio, no solo este archivo.
    echo         git clone https://github.com/CIBERC2/demo-repository.git
    pause
    exit /b 1
)
if not exist "agent" (
    echo [ERROR] Carpeta 'agent' no encontrada. Clona el repositorio completo.
    pause
    exit /b 1
)
if not exist "dashboard" (
    echo [ERROR] Carpeta 'dashboard' no encontrada. Clona el repositorio completo.
    pause
    exit /b 1
)

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.10+ desde python.org
    pause
    exit /b 1
)
echo [OK] Python found

:: Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js no encontrado. Instala Node.js 18+ desde nodejs.org
    pause
    exit /b 1
)
echo [OK] Node.js found

:: ── 1. Server dependencies ───────────────────────────────────────────────────
echo.
echo [1/4] Installing server dependencies...
cd /d "%~dp0server"
if not exist "requirements.txt" (
    echo [ERROR] server\requirements.txt no encontrado.
    pause
    exit /b 1
)
pip install -r requirements.txt
if errorlevel 1 (
    echo [WARN] Algunos paquetes fallaron. Instalando individualmente...
    pip install fastapi==0.115.0 "uvicorn[standard]==0.32.0" "websockets>=13.1" cryptography==43.0.3 "pydantic>=2.11.7" python-dotenv==1.0.1 rich==13.9.4 dnslib==0.9.25 "PyJWT>=2.9.0" "httpx>=0.27.0"
)

:: Solana SDK (opcional)
echo [1b/4] Installing Solana SDK (opcional, para blockchain)...
pip install "solana>=0.39.0" "solders>=0.27.0" >nul 2>&1
if errorlevel 1 (echo [WARN] Solana SDK no disponible - blockchain anchoring desactivado)

:: ── 2. Agent dependencies ────────────────────────────────────────────────────
echo.
echo [2/4] Installing agent dependencies...
cd /d "%~dp0agent"
pip install psutil websockets cryptography

:: ── 3. Dashboard dependencies ────────────────────────────────────────────────
echo.
echo [3/4] Installing dashboard dependencies...
cd /d "%~dp0dashboard"
call npm install
if errorlevel 1 (
    echo [ERROR] npm install fallo. Verifica que Node.js 18+ este instalado.
    pause
    exit /b 1
)

:: ── 4. Configurar .env ───────────────────────────────────────────────────────
echo.
echo [4/4] Configuring environment...
cd /d "%~dp0server"
if not exist ".env" (
    echo C2_HOST=0.0.0.0> ".env"
    echo C2_PORT=8000>> ".env"
    echo C2_DNS_PORT=15353>> ".env"
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
    echo [OK] .env creado con valores por defecto
) else (
    echo [OK] .env ya existe - omitiendo
)

cd /d "%~dp0"
echo.
echo  ============================================
echo       OPENC2 v1.0 INSTALLATION COMPLETE
echo  ============================================
echo.
echo   Siguiente paso: ejecuta start.bat
echo   Dashboard:  http://localhost:5173
echo   Servidor:   http://localhost:8000
echo   Token:      openc2-dev-token
echo.
pause
