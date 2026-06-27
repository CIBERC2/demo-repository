@echo off
setlocal EnableDelayedExpansion
title OpenC2 - REPARACION RAPIDA
color 0E
echo.
echo  ============================================
echo    OPENC2 - REPARACION DE INSTALACION
echo  ============================================
echo.
echo  Reinstalando dependencias que fallaron...
echo.

cd /d "%~dp0"
set "BASE=%~dp0"

:: Asegurar pip
python -m pip --version >nul 2>&1
if errorlevel 1 python -m ensurepip --upgrade

echo [1/3] Reinstalando dependencias del servidor...
cd /d "%BASE%server"
python -m pip install --upgrade pip
python -m pip install fastapi==0.115.0 "uvicorn[standard]==0.32.0" "websockets>=13.1" cryptography==43.0.3 "pydantic>=2.11.7" python-dotenv==1.0.1 rich==13.9.4 typer==0.13.0 dnslib==0.9.25 "PyJWT>=2.9.0" "httpx>=0.27.0" "psutil>=5.9.0"
python -m pip install "solana>=0.39.0" "solders>=0.27.0"

echo.
echo [2/3] Reinstalando dependencias del agente...
cd /d "%BASE%agent"
python -m pip install websockets==13.1 cryptography==43.0.3 "pydantic>=2.11.7" python-dotenv==1.0.1 psutil==6.1.0 dnslib==0.9.25

echo.
echo [3/3] Reinstalando dashboard...
cd /d "%BASE%dashboard"
if exist "node_modules" rmdir /s /q "node_modules"
if exist "package-lock.json" del /q "package-lock.json"
call npm install
if not exist "node_modules\vite" call npm install vite @vitejs/plugin-react typescript --save-dev

echo.
echo  ============================================
echo    VERIFICACION
echo  ============================================
cd /d "%BASE%server"
python -c "import fastapi, uvicorn, websockets, cryptography, pydantic, dotenv, jwt, dnslib, psutil, httpx, rich, typer; print('[OK] Servidor completo')"
cd /d "%BASE%agent"
python -c "import websockets, cryptography, pydantic, dotenv, psutil, dnslib; print('[OK] Agente completo')"
if exist "%BASE%dashboard\node_modules\vite" ( echo [OK] Dashboard completo ) else ( echo [FAIL] Dashboard sin vite )

cd /d "%BASE%"
echo.
echo  Reparacion finalizada. Ejecuta: start.bat
echo.
pause
