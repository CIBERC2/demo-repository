@echo off
setlocal EnableDelayedExpansion
title OpenC2 v1.0 - Installer
color 0B
echo.
echo  ============================================
echo       OPENC2 v1.0 - FULL INSTALLATION
echo  ============================================
echo.

:: ── Posicionarse en el directorio del .bat sin importar desde donde se ejecute
cd /d "%~dp0"
set "BASE=%~dp0"

:: ── Verificar estructura completa del repositorio ────────────────────────────
echo [CHECK] Verificando estructura del repositorio...
set "MISSING=0"
for %%D in (server agent dashboard server\core agent\plugins dashboard\src) do (
    if not exist "%%D" (
        echo   [ERROR] Falta la carpeta: %%D
        set "MISSING=1"
    )
)
for %%F in (server\main.py server\requirements.txt agent\agent.py agent\requirements.txt dashboard\package.json) do (
    if not exist "%%F" (
        echo   [ERROR] Falta el archivo: %%F
        set "MISSING=1"
    )
)
if "!MISSING!"=="1" (
    echo.
    echo  El repositorio esta incompleto. Clona con:
    echo    git clone https://github.com/CIBERC2/demo-repository.git
    echo    cd demo-repository
    echo    install.bat
    pause
    exit /b 1
)
echo   [OK] Estructura correcta

:: ── Verificar Python ─────────────────────────────────────────────────────────
echo.
echo [CHECK] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python no encontrado en PATH.
    echo          Instala Python 3.10+ desde https://python.org
    echo          IMPORTANTE: marca "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)
for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
echo   [OK] Python !PYVER!

:: ── Verificar Node.js ────────────────────────────────────────────────────────
echo [CHECK] Verificando Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Node.js no encontrado en PATH.
    echo          Instala Node.js 18+ desde https://nodejs.org
    pause
    exit /b 1
)
for /f %%V in ('node --version 2^>^&1') do set "NODEVER=%%V"
echo   [OK] Node.js !NODEVER!

:: ── Verificar npm ────────────────────────────────────────────────────────────
npm --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] npm no encontrado. Reinstala Node.js desde https://nodejs.org
    pause
    exit /b 1
)
echo   [OK] npm disponible

:: ── Crear directorios necesarios ─────────────────────────────────────────────
echo.
echo [SETUP] Creando directorios necesarios...
if not exist "server\keys"  mkdir "server\keys"
if not exist "server\logs"  mkdir "server\logs"
echo   [OK] Directorios listos

:: ── 1. Dependencias del servidor ─────────────────────────────────────────────
echo.
echo [1/4] Instalando dependencias del servidor (Python)...
cd /d "%BASE%server"

pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo   [WARN] pip con requirements.txt fallo. Instalando paquete por paquete...
    set "FAILED=0"
    for %%P in (
        "fastapi==0.115.0"
        "uvicorn[standard]==0.32.0"
        "websockets>=13.1"
        "cryptography==43.0.3"
        "pydantic>=2.11.7"
        "python-dotenv==1.0.1"
        "rich==13.9.4"
        "dnslib==0.9.25"
        "PyJWT>=2.9.0"
        "httpx>=0.27.0"
        "psutil>=5.9.0"
    ) do (
        pip install %%P --quiet
        if errorlevel 1 (
            echo   [WARN] No se pudo instalar: %%P
            set "FAILED=1"
        )
    )
    if "!FAILED!"=="1" (
        echo   [WARN] Algunos paquetes no se instalaron. El servidor puede tener errores.
    ) else (
        echo   [OK] Todos los paquetes instalados individualmente
    )
) else (
    echo   [OK] Dependencias del servidor instaladas
)

:: ── 1b. Solana SDK (opcional) ────────────────────────────────────────────────
echo [1b/4] Instalando Solana SDK (opcional, para blockchain)...
pip install "solana>=0.39.0" "solders>=0.27.0" --quiet >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Solana SDK no disponible - blockchain anchoring desactivado
) else (
    echo   [OK] Solana SDK instalado
)

:: ── 2. Dependencias del agente ───────────────────────────────────────────────
echo.
echo [2/4] Instalando dependencias del agente (Python)...
cd /d "%BASE%agent"
pip install -r requirements.txt --quiet 2>nul
if errorlevel 1 (
    pip install psutil websockets cryptography --quiet
)
echo   [OK] Dependencias del agente instaladas

:: ── 3. Dependencias del dashboard ───────────────────────────────────────────
echo.
echo [3/4] Instalando dependencias del dashboard (Node.js)...
cd /d "%BASE%dashboard"
call npm install --prefer-offline 2>nul
if errorlevel 1 (
    echo   Reintentando npm install con red...
    call npm install
    if errorlevel 1 (
        echo   [ERROR] npm install fallo. Verifica tu conexion a internet.
        pause
        exit /b 1
    )
)
echo   [OK] Dashboard Node.js listo

:: ── 4. Configurar .env ───────────────────────────────────────────────────────
echo.
echo [4/4] Configurando variables de entorno...
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
    echo   [OK] .env creado con valores por defecto
) else (
    echo   [OK] .env ya existe - omitiendo
)

:: ── Verificacion final ───────────────────────────────────────────────────────
echo.
echo [VERIFY] Verificando instalacion...
cd /d "%BASE%server"
python -c "import fastapi, uvicorn, websockets, cryptography, pydantic, jwt, dnslib, psutil; print('  [OK] Todos los modulos Python disponibles')" 2>nul
if errorlevel 1 (
    echo   [WARN] Algunos modulos Python pueden faltar. Revisa los warnings arriba.
)

cd /d "%BASE%"

echo.
echo  ============================================
echo       OPENC2 v1.0 INSTALACION COMPLETA
echo  ============================================
echo.
echo   Las claves RSA y la wallet Solana se generan
echo   automaticamente al primer inicio del servidor.
echo.
echo   Siguiente paso:  start.bat
echo   Dashboard:       http://localhost:5173
echo   Servidor:        http://localhost:8000
echo   Token:           openc2-dev-token
echo.
pause
