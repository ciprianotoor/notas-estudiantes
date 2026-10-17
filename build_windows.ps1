$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Instala Python 3.11 o superior desde https://www.python.org/downloads/windows/"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3 -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
# Keep installer/appsrequeriments and other supporting files when rebuilding.
New-Item -ItemType Directory -Force "installer" | Out-Null

& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir `
    --name NotasEstudiantes --add-data "templates;templates" `
    --add-data "static;static" --hidden-import reportlab.pdfbase._fontdata run_windows.py
New-Item -ItemType Directory -Force "dist\NotasEstudiantes\data\uploads" | Out-Null

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $standardIscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path $standardIscc) { $iscc = $standardIscc }
}
if ($iscc) {
    & $iscc installer.iss
    Write-Host "Instalador creado en installer\NotasEstudiantes-Setup.exe"
} else { Write-Host "Ejecutable listo en dist\NotasEstudiantes" }

$heat = Get-Command heat.exe -ErrorAction SilentlyContinue
$candle = Get-Command candle.exe -ErrorAction SilentlyContinue
$light = Get-Command light.exe -ErrorAction SilentlyContinue
if ($heat -and $candle -and $light) {
    New-Item -ItemType Directory -Force installer | Out-Null
    & $heat dir "dist\NotasEstudiantes" -cg AppFiles -dr INSTALLFOLDER -var var.SourceDir -gg -srd -sfrag -out files.wxs
    & $candle Product.wxs files.wxs -dSourceDir="$((Get-Location).Path)\dist\NotasEstudiantes" -out build\
    & $light Product.wixobj files.wixobj -out installer\NotasEstudiantes-Setup.msi
    Write-Host "Instalador MSI creado en installer\NotasEstudiantes-Setup.msi"
} else { Write-Host "WiX no está instalado: no se generó el MSI." }
