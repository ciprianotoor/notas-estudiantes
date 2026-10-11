@echo off
setlocal EnableExtensions

title Notas Estudiantes - Instalador
set "REPO_URL=https://github.com/ciprianotoor/notas-estudiantes.git"
set "INSTALL_DIR=%USERPROFILE%\NotasEstudiantes"

echo.
echo ================================================
echo     Notas Estudiantes - Instalacion Windows
echo ================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: Git no esta instalado.
  echo Instala Git desde https://git-scm.com/download/win y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker no esta instalado.
  where winget >nul 2>&1
  if errorlevel 1 (
    echo Instala Docker Desktop desde https://www.docker.com/products/docker-desktop/ y vuelve a ejecutar este archivo.
    pause
    exit /b 1
  )
  choice /M "Quieres instalar Docker Desktop con winget ahora"
  if errorlevel 2 (
    echo Instala Docker Desktop y vuelve a ejecutar este archivo.
    pause
    exit /b 1
  )
  winget install --id Docker.DockerDesktop --exact --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo ERROR: No se pudo instalar Docker Desktop.
    pause
    exit /b 1
  )
  echo Abre Docker Desktop, espera a que indique que esta iniciado y ejecuta este archivo otra vez.
  pause
  exit /b 0
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop no esta iniciado.
  echo Abre Docker Desktop, espera a que termine de iniciar y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)

if not exist "%INSTALL_DIR%\.git" (
  if exist "%INSTALL_DIR%" (
    echo ERROR: Ya existe una carpeta que no es una instalacion Git:
    echo        %INSTALL_DIR%
    echo Muevela o elige otra ubicacion y vuelve a ejecutar este archivo.
    pause
    exit /b 1
  )
  echo Descargando el proyecto desde GitHub...
  git clone "%REPO_URL%" "%INSTALL_DIR%"
  if errorlevel 1 goto :error
) else (
  echo Actualizando el proyecto desde GitHub...
  git -C "%INSTALL_DIR%" pull --ff-only
  if errorlevel 1 (
    echo ERROR: No se pudo actualizar el proyecto. Revisa cambios locales o la conexion.
    pause
    exit /b 1
  )
)

if not exist "%INSTALL_DIR%\.env" (
  echo Creando configuracion inicial...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); 'SECRET_KEY=' + ([Convert]::ToBase64String($bytes) -replace '[^a-zA-Z0-9]', '') | Set-Content -Encoding ascii '%INSTALL_DIR%\.env'"
  if errorlevel 1 goto :error
)

echo Construyendo e iniciando la aplicacion...
cd /d "%INSTALL_DIR%"
docker compose up -d --build
if errorlevel 1 goto :error

echo.
echo Instalacion completada.
echo Proyecto: %INSTALL_DIR%
echo Abrir en el navegador: http://127.0.0.1:5000/login
echo Los datos se conservan en: %INSTALL_DIR%\data
start "" "http://127.0.0.1:5000/login"
pause
exit /b 0

:error
echo.
echo ERROR: La instalacion no pudo completarse.
echo Revisa Docker Desktop y vuelve a ejecutar este archivo.
pause
exit /b 1
