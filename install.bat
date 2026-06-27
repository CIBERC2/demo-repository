@echo off
setlocal EnableDelayedExpansion
title OpenC2 v1.0 - Installer
color 0B
echo.
echo  ============================================
echo       OPENC2 v1.0 - FULL INSTALLATION
echo  ============================================
echo.

cd /d "%~dp0"
set "BASE=%~dp0"

:: ── Estructura ────────────────────────────────────────────────────────────────
echo [CHECK] Verificando estructura...
set "MISSING=0"
for %%D in (server agent dashboard server\core agent\plugins dashboard\src) do (
    if not exist "%%D" ( echo   [ERROR] Falta carpeta: %%D & set "MISSING=1" )
)
for %%F in (server\main.py server\requirements.txt agent\agent.py agent\requirements.txt dashboard\package.json) do (
    if not exist "%%F" ( echo   [ERROR] Falta archivo: %%F & set "MISSING=1" )
)
if "!MISSING!"=="1" ( echo. & echo Repositorio incompleto. Descarga de nuevo. & pause & exit /b 1 )
echo   [OK] Estructura correcta

:: ── Python ────────────────────────────────────────────────────────────────────
echo.
echo [CHECK] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python no encontrado en PATH.
    echo          Instala Python 3.10+ desde https://python.org
    echo          MARCA "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)
for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
echo   [OK] Python !PYVER!

:: ── pip via python -m pip + ensurepip ────────────────────────────────────────
echo [CHECK] Verificando pip...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo   Instalando pip con ensurepip...
    python -m ensurepip --upgrade
    python -m pip --version >nul 2>&1
    if errorlevel 1 ( echo   [ERROR] pip no se pudo instalar. & pause & exit /b 1 )
)
echo   [OK] pip listo
python -m pip install --upgrade pip setuptools wheel

:: ── Node ──────────────────────────────────────────────────────────────────────
echo [CHECK] Verificando Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Node.js no encontrado. Instala desde https://nodejs.org
    pause
    exit /b 1
)
for /f %%V in ('node --version 2^>^&1') do set "NODEVER=%%V"
echo   [OK] Node.js !NODEVER!

npm --version >nul 2>&1
if errorlevel 1 ( echo [ERROR] npm no encontrado. & pause & exit /b 1 )
echo   [OK] npm disponible

:: ── Directorios ───────────────────────────────────────────────────────────────
echo.
echo [SETUP] Creando directorios...
if not exist "server\keys"  mkdir "server\keys"
if not exist "server\logs"  mkdir "server\logs"
if not exist "agent\logs"   mkdir "agent\logs"
echo   [OK] Directorios listos

:: ── 1. SERVIDOR (visible, sin --quiet) ────────────────────────────────────────
echo.
echo [1/4] Instalando dependencias del SERVIDOR...
cd /d "%BASE%server"
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo   [WARN] requirements.txt fallo. Forzando paquete por paquete...
    for %%P in (
        "fastapi==0.115.0"
        "uvicorn[standard]==0.32.0"
        "websockets>=13.1"
        "cryptography==43.0.3"
        "pydantic>=2.11.7"
        "python-dotenv==1.0.1"
        "rich==13.9.4"
        "typer==0.13.0"
        "dnslib==0.9.25"
        "PyJWT>=2.9.0"
        "httpx>=0.27.0"
        "psutil>=5.9.0"
    ) do python -m pip install %%P
)

:: Solana SDK opcional
echo [1b] Solana SDK...
python -m pip install "solana>=0.39.0" "solders>=0.27.0"
if errorlevel 1 echo   [WARN] Solana SDK no disponible

:: ── VERIFICAR Y REINTENTAR servidor ───────────────────────────────────────────
echo [VERIFY] Re-verificando modulos del servidor...
for %%M in (fastapi uvicorn websockets cryptography pydantic dotenv jwt dnslib psutil httpx rich typer) do (
    python -c "import %%M" 2>nul
    if errorlevel 1 (
        echo   Reinstalando: %%M
        if /i "%%M"=="dotenv" ( python -m pip install python-dotenv --force-reinstall ) else (
        if /i "%%M"=="jwt" ( python -m pip install PyJWT --force-reinstall ) else (
        python -m pip install %%M --force-reinstall ))
    )
)

:: ── 2. AGENTE ─────────────────────────────────────────────────────────────────
echo.
echo [2/4] Instalando dependencias del AGENTE...
cd /d "%BASE%agent"
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo   [WARN] agent/requirements.txt fallo. Forzando individual...
    for %%P in (
        "websockets==13.1"
        "cryptography==43.0.3"
        "pydantic>=2.11.7"
        "python-dotenv==1.0.1"
        "psutil==6.1.0"
        "dnslib==0.9.25"
    ) do python -m pip install %%P
)

echo [VERIFY] Re-verificando modulos del agente...
for %%M in (websockets cryptography pydantic dotenv psutil dnslib) do (
    python -c "import %%M" 2>nul
    if errorlevel 1 (
        echo   Reinstalando: %%M
        if /i "%%M"=="dotenv" ( python -m pip install python-dotenv --force-reinstall ) else (
        python -m pip install %%M --force-reinstall )
    )
)

:: ── 3. DASHBOARD ──────────────────────────────────────────────────────────────
echo.
echo [3/4] Instalando dependencias del DASHBOARD...
cd /d "%BASE%dashboard"

if exist "node_modules" (
    echo   Limpiando node_modules previo incompleto...
    rmdir /s /q "node_modules" 2>nul
)
if exist "package-lock.json" del /q "package-lock.json" 2>nul

call npm install
if errorlevel 1 (
    echo   [ERROR] npm install fallo. Reintentando con --legacy-peer-deps...
    call npm install --legacy-peer-deps
    if errorlevel 1 (
        echo   [ERROR] npm install fallo. Revisa tu conexion.
        pause
        exit /b 1
    )
)

:: Verificar que vite quedo instalado
if not exist "node_modules\vite" (
    echo   [WARN] vite no instalado. Instalando explicitamente...
    call npm install vite @vitejs/plugin-react typescript --save-dev
)
if not exist "node_modules\vite" (
    echo   [ERROR] vite sigue sin instalarse. npm install esta fallando.
    pause
    exit /b 1
)
echo   [OK] Dashboard listo (vite presente)

:: ── 4. .env ───────────────────────────────────────────────────────────────────
echo.
echo [4/4] Configurando .env...
cd /d "%BASE%server"
if not exist ".env" (
    (
        echo C2_HOST=0.0.0.0
        echo C2_PORT=8000
        echo C2_DNS_PORT=15353
        echo C2_LOG_LEVEL=INFO
        echo SERVER_PRIVATE_KEY_PATH=./keys/server_priv.pem
        echo SERVER_PUBLIC_KEY_PATH=./keys/server_pub.pem
        echo OPERATOR_TOKEN=openc2-dev-token
        echo JWT_SECRET=
        echo JWT_EXPIRE_HOURS=24
        echo DASHBOARD_ORIGIN=http://localhost:5173
        echo SOLANA_ANCHOR=true
        echo SOLANA_NETWORK=devnet
        echo SOLANA_WALLET_PATH=solana_wallet.json
        echo QUEUE_DB_PATH=pending_tasks.db
        echo DNS_SHARED_KEY=
        echo HEARTBEAT_INTERVAL=10
        echo HEARTBEAT_JITTER=0.3
    ) > ".env"
    echo   [OK] .env creado
) else (
    echo   [OK] .env ya existia
)

:: ── Verificacion final estricta ───────────────────────────────────────────────
echo.
echo [FINAL] Verificacion estricta...
set "FATAL=0"

cd /d "%BASE%server"
python -c "import fastapi, uvicorn, websockets, cryptography, pydantic, dotenv, jwt, dnslib, psutil, httpx, rich, typer"
if errorlevel 1 ( echo   [FAIL] Servidor incompleto & set "FATAL=1" ) else echo   [OK] Servidor completo

cd /d "%BASE%agent"
python -c "import websockets, cryptography, pydantic, dotenv, psutil, dnslib"
if errorlevel 1 ( echo   [FAIL] Agente incompleto & set "FATAL=1" ) else echo   [OK] Agente completo

if exist "%BASE%dashboard\node_modules\vite" (
    echo   [OK] Dashboard completo
) else (
    echo   [FAIL] Dashboard sin vite
    set "FATAL=1"
)

cd /d "%BASE%"
echo.
if "!FATAL!"=="1" (
    echo  ============================================
    echo    INSTALACION INCOMPLETA - revisa errores
    echo  ============================================
    pause
    exit /b 1
)

echo  ============================================
echo       OPENC2 v1.0 INSTALACION COMPLETA
echo  ============================================
echo.
echo   Siguiente paso:  start.bat
echo   Dashboard:       http://localhost:5173
echo   Servidor:        http://localhost:8000
echo   Token:           openc2-dev-token
echo.
pause
