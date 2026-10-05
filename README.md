# Notas Estudiantes

Aplicación Flask para gestionar grupos, matrículas, asignaturas, notas por parciales, conducta y boletas académicas.

## Requisitos

- Python 3.10 o superior (recomendado 3.11+).
- SQLite incluido con Python.
- Para Docker: Docker Engine y Docker Compose.

## Instalación local

```bash
git clone https://github.com/ciprianotoor/notas-estudiantes.git
cd notas-estudiantes
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
DB_PATH=./data/notas.db SECRET_KEY=una-clave-segura .venv/bin/python app.py
```

Abre `http://127.0.0.1:5000`. La base de datos se crea en `data/notas.db`.

## Docker

```bash
docker compose up -d --build
docker compose logs -f notas
docker compose down
```

El servicio escucha en el puerto `5000` y conserva la información en el volumen configurado por `compose.yaml`.

## Flujo de uso

1. Admin crea usuarios y mantiene el catálogo de asignaturas.
2. El Docente guía crea su grupo, sección y matrícula.
3. Las asignaturas activas se aplican automáticamente a los estudiantes.
4. Cada docente registra sus notas en los cuatro parciales.
5. El Docente guía registra Conducta por parcial con cuantitativa, cualitativa automática, criterios, incidentes y observaciones.
6. Admin, Director y Secretaría consultan e imprimen boletas.

## Roles y permisos

- **Admin / Soporte:** usuarios, catálogo, configuración institucional, tema, reportes y respaldos. Consulta e imprime; no registra notas.
- **Director:** consulta estudiantes, notas y boletas; administra docentes y bajas. No edita calificaciones.
- **Secretaría:** consulta e imprime estudiantes, notas y boletas. No edita.
- **Docente guía:** gestiona sus grupos y matrículas, registra Conducta y administra bajas de sus estudiantes.
- **Docente de materia:** registra notas de las materias y estudiantes asignados. No edita Conducta ni matrículas.

## Evaluación

Cada asignatura tiene cuatro parciales. La boleta muestra materias por fila y cuantitativa/cualitativa por parcial. La equivalencia MINED es: `AA` (90–100), `AS` (76–89), `AF` (60–75) y `AI` (menos de 60). Conducta usa la correspondencia automática y documenta criterios, incidentes y observaciones por parcial.

## Bajas y reportes

Una baja conserva el expediente y las notas. Desde el filtro de estudiantes dados de baja se puede restablecer la matrícula, exportar el expediente CSV o eliminarlo definitivamente (solo Admin/Dirección y con confirmación). Para imprimir, filtra por nombre/código/grupo, selecciona estudiantes y parciales; cada estudiante se genera en su propia página.

## Pruebas

```bash
./.venv/bin/pytest -q
```

La guía completa está en [`docs/GUIA_USO.md`](docs/GUIA_USO.md) y [`docs/GUIA_USO.pdf`](docs/GUIA_USO.pdf).

## Despliegue

Para producción usa un servidor WSGI detrás de un proxy, define una `SECRET_KEY` segura, protege SQLite y realiza respaldos antes de migraciones o eliminaciones.

## Crear instalador para Windows

La compilación debe hacerse en Windows 10/11. Requiere Python 3.11+, Git e Inno Setup 6 (<https://jrsoftware.org/isinfo.php>).

1. En PowerShell clona el proyecto y prepara el entorno: `git clone https://github.com/ciprianotoor/notas-estudiantes.git`, `cd notas-estudiantes`, `py -3 -m venv .venv`, `.venv\Scripts\Activate.ps1`, `pip install -r requirements.txt` y `pip install pyinstaller`.
2. Crea `run_windows.py` en la raíz con este contenido:

```python
import os, threading, time, webbrowser
from app import app

def open_browser():
    time.sleep(2)
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
```

3. Genera el ejecutable desde PowerShell: `pyinstaller --noconfirm --clean --onedir --name NotasEstudiantes --add-data "templates;templates" --add-data "static;static" --add-data "data;data" run_windows.py`.
4. Prueba `dist\NotasEstudiantes\NotasEstudiantes.exe`. La base debe permanecer fuera del ejecutable en `dist\NotasEstudiantes\data\notas.db`.
5. En Inno Setup crea `installer.iss` con:

```ini
[Setup]
AppName=Notas Estudiantes
AppVersion=1.0.0
DefaultDirName={autopf}\Notas Estudiantes
DefaultGroupName=Notas Estudiantes
OutputDir=installer
OutputBaseFilename=NotasEstudiantes-Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\NotasEstudiantes\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Notas Estudiantes"; Filename: "{app}\NotasEstudiantes.exe"
Name: "{autodesktop}\Notas Estudiantes"; Filename: "{app}\NotasEstudiantes.exe"

[Run]
Filename: "{app}\NotasEstudiantes.exe"; Flags: nowait postinstall skipifsilent
```

6. Abre `installer.iss` en Inno Setup, pulsa **Compile** y distribuye `installer\NotasEstudiantes-Setup.exe`.
7. Prueba en un Windows sin Python: inicia la aplicación, crea datos, reinicia y confirma que `data\notas.db` conserva la información. Comprueba también PDF, exportación y respaldos.

Para usarlo en la red local cambia el host del lanzador a `0.0.0.0`, permite el puerto 5000 en el Firewall de Windows y accede desde otra computadora con `http://IP_DEL_EQUIPO:5000`.
