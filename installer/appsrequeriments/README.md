# Herramientas para compilar en Windows

Esta carpeta reúne los instaladores usados para preparar un equipo Windows.
Los archivos están agrupados en dos ZIP para poder extraerlos con el
Explorador de archivos de Windows (clic derecho → **Extraer todo**).

## Paquetes incluidos

- `python-manager.zip`: contiene `python-manager-26.4.msix`, el instalador de
  Python Install Manager. La versión 26.4 es una beta; para un equipo de
  compilación nuevo, se recomienda descargar una versión estable desde
  [Python para Windows](https://www.python.org/downloads/windows/). El
  proyecto requiere Python 3.11 o superior. Tras instalarlo, comprueba que
  `py -3 --version` funcione.
- `windows-build-tools.zip`: contiene Inno Setup 6.7.3, Wix CLI y Wix
  Additional Tools. Inno Setup genera el instalador EXE. WiX es opcional y
  sirve para la ruta MSI descrita abajo.

También se pueden obtener los instaladores desde sus fuentes oficiales:

- [Python para Windows](https://www.python.org/downloads/windows/)
- [Descargas de Inno Setup](https://jrsoftware.org/isdl.php)
- [Versiones de WiX Toolset](https://github.com/wixtoolset/wix/releases)

Las versiones dentro de los ZIP son copias para conveniencia y pueden quedar
desactualizadas. Descarga las versiones estables más recientes en los sitios
oficiales cuando prepares un equipo nuevo. Verifica el editor y la firma
digital del instalador antes de ejecutarlo.

## Compilar

Desde la raíz del repositorio, con Git, Python 3.11+ e Inno Setup instalados:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

El script instala los paquetes indicados en `requirements.txt`, construye la
carpeta de aplicación con PyInstaller y llama a `ISCC.exe` para producir
`installer\NotasEstudiantes-Setup.exe`. Se necesita conexión a Internet para
instalar dependencias de Python si aún no están en la caché de pip.

WiX es opcional. El script actual busca `heat.exe`, `candle.exe` y `light.exe`
(herramientas de WiX v3) para crear `installer\NotasEstudiantes-Setup.msi`.
Los paquetes Wix CLI incluidos pertenecen a la línea CLI moderna y puede que
no proporcionen esos ejecutables; si el script no los encuentra, informa que
no se generó MSI y conserva la compilación EXE.

## Observaciones de la compilación

- La compilación que produjo `NotasEstudiantes-Setup.exe` terminó
  correctamente. El EXE resultante fue de aproximadamente 19 MB.
- PyInstaller genera una aplicación `onedir`: `NotasEstudiantes.exe` necesita
  los archivos de `dist\NotasEstudiantes\_internal`; el instalador de Inno
  Setup los incluye todos.
- La carpeta compilada observada contiene `python314.dll`, señal de que esa
  compilación se hizo con Python 3.14.
- El script limpia `build` y `dist` al volver a compilar. Se ajustó para
  conservar esta carpeta de requisitos; antes eliminaba completa la carpeta
  `installer` y con ella también los instaladores auxiliares.
- La carpeta se llama `appsrequeriments` por compatibilidad con la ruta
  existente en el repositorio.
