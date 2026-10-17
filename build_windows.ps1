$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Instala Python 3.11 o superior desde https://www.python.org/downloads/windows/"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3 -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
if (Test-Path installer) { Remove-Item installer -Recurse -Force }

& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir `
    --name NotasEstudiantes --add-data "templates;templates" `
    --add-data "static;static" --hidden-import reportlab.pdfbase._fontdata run_windows.py
New-Item -ItemType Directory -Force "dist\NotasEstudiantes\data\uploads" | Out-Null

if (Get-Command ISCC.exe -ErrorAction SilentlyContinue) {
    & ISCC.exe installer.iss
    Write-Host "Instalador creado en installer\NotasEstudiantes-Setup.exe"
} else { Write-Host "Ejecutable listo en dist\NotasEstudiantes" }
