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

Una baja conserva el expediente y las notas. Desde el filtro de estudiantes dados de baja se puede restablecer la matrícula, exportar el expediente CSV o eliminarlo definitivamente (solo Admin/Dirección y con confirmación). Al imprimir una boleta individual o en lote, puedes elegir clases y parciales y personalizar Conducta: incluirla u ocultarla y seleccionar datos cuantitativos, cualitativos, criterios, incidentes y observaciones. En la impresión por lote, cada estudiante se genera en su propia página.

## Pruebas

```bash
./.venv/bin/pytest -q
```

La guía completa está en [`docs/GUIA_USO.md`](docs/GUIA_USO.md) y [`docs/GUIA_USO.pdf`](docs/GUIA_USO.pdf).

## Despliegue

Para producción usa un servidor WSGI detrás de un proxy, define una `SECRET_KEY` segura, protege SQLite y realiza respaldos antes de migraciones o eliminaciones.

## Instalación en Windows

### Instalador autónomo recomendado

El instalador funciona en Windows 10 y 11 sin requerir Python, Git ni Docker
en el equipo docente. La versión compilada se genera en Windows con Python
3.11+ e [Inno Setup 6](https://jrsoftware.org/isinfo.php).

1. Clona el proyecto y entra en su carpeta:

   ```powershell
   git clone https://github.com/ciprianotoor/notas-estudiantes.git
   cd notas-estudiantes
   ```

2. Ejecuta el compilador:

   ```powershell
   PowerShell -ExecutionPolicy Bypass -File .\build_windows.ps1
   ```

El instalador generado queda en
`installer\NotasEstudiantes-Setup.exe`. La aplicación se instala por usuario
en `%LOCALAPPDATA%\Notas Estudiantes`, crea accesos directos y abre
`http://127.0.0.1:5000/login`.

También se puede descargar desde GitHub en **Actions**, dentro del flujo
**Instalador Windows**, como artefacto `NotasEstudiantes-Setup`. Para dejarlo
como descarga permanente en **Releases**, crea una etiqueta como `v1.0.0`; el
flujo compilará y adjuntará automáticamente el archivo `.exe`.

La base de datos y los archivos cargados se conservan en la carpeta `data`
junto al programa. Para actualizar una instalación, realiza primero un
respaldo desde la interfaz y vuelve a instalar la nueva versión.

### Instalación con Docker Desktop

Como alternativa, descarga [`instalar_windows.bat`](instalar_windows.bat) y
ejecútalo. El script instala Docker Desktop mediante `winget` si está
disponible, clona o actualiza el proyecto y conserva la carpeta `data`.

Para usar la aplicación desde otros equipos de la red, cambia el host del
lanzador a `0.0.0.0`, permite el puerto 5000 en el Firewall de Windows y
accede con `http://IP_DEL_EQUIPO:5000`.
