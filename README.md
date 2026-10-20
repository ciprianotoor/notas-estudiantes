# Notas Estudiantes

Aplicación Flask para gestionar grupos, matrículas, asignaturas, notas por parciales, conducta y boletas académicas.

![Estado: Delta / Prebeta](https://img.shields.io/badge/estado-Delta%20%2F%20Prebeta-orange)

> **Estado actual: Delta / Prebeta (`v0.9.0-beta.1`).**
> La aplicación es funcional y está en pruebas reales, pero todavía puede
> contener errores y cambios importantes. Realiza un respaldo de `data/` antes
> de actualizar o migrar la instalación.

## Licencia y autoría

Este proyecto fue creado y es mantenido por **Cipriano** (`ciprianotoor`). Se
distribuye bajo la [licencia MIT](LICENSE), que permite su uso, modificación y
distribución libre conservando el aviso de copyright. El desarrollo contó con
asistencia de **OpenAI Codex**. Consulta [NOTICE.md](NOTICE.md) para conocer
los términos de atribución.

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

## Módulo de matrícula

El módulo **Matrículas** centraliza la gestión de estudiantes en una sola pantalla.
Permite consultar grupos, ver estudiantes activos y dados de baja, revisar las
últimas matrículas y entrar al flujo de registro o actualización de materias.
Está disponible desde el menú principal en `/enrollment`.

Los permisos se mantienen separados: Admin tiene acceso total; Director y
Docente guía pueden gestionar según su alcance; Secretaría tiene consulta de
solo lectura.

## Roles y permisos

- **Admin / Soporte:** usuarios, catálogo, configuración institucional, tema, reportes y respaldos. Consulta e imprime; no registra notas.
- **Director:** consulta estudiantes, notas y boletas; administra docentes y bajas. No edita calificaciones.
- **Secretaría:** consulta e imprime estudiantes, notas y boletas. No edita.
- **Docente guía:** gestiona sus grupos y matrículas, registra Conducta y administra bajas de sus estudiantes.
- **Docente de materia:** registra notas de las materias y estudiantes asignados. No edita Conducta ni matrículas.

## Evaluación

Cada asignatura tiene cuatro parciales. La boleta muestra materias por fila y cuantitativa/cualitativa por parcial. La equivalencia MINED es: `AA` (90–100), `AS` (76–89), `AF` (60–75) y `AI` (menos de 60). Conducta usa la correspondencia automática y documenta criterios, incidentes y observaciones por parcial.

### Boletas escolares

La impresión individual genera nombres de archivo con estudiante y grado, por
ejemplo `boletin-Nombre_Estudiante-9no.pdf`. La versión A4 plegable agrega el
sufijo `-a4-plegable`.

La boleta A4 se organiza en cuatro caras: portada, información general,
evaluación académica/conducta y observaciones/cierre. Incluye año lectivo,
grupo, grado, sección, corte y la tabla de escala junto a los datos del
estudiante. Usa la nomenclatura `CN`, `CL`, `SC` y `NR`; las notas se imprimen
sin decimales, aunque los cálculos internos conservan su precisión.

Cada corte tiene casillas equilibradas para las firmas del docente guía,
padre/madre/tutor y estudiante. La boleta también incluye conducta, criterios,
incidentes, observaciones, recomendaciones y sello del centro.

El diseño está inspirado en referencias públicas de evaluación escolar de
Nicaragua, pero no representa una boleta oficial emitida por el MINED.

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

### Configuración de red del ejecutable

Al iniciar `NotasEstudiantes.exe` aparece un menú para elegir la dirección de
escucha: solo este equipo (`127.0.0.1`), todas las interfaces para LAN/Tailscale
(`0.0.0.0`) o una IP detectada identificada como **LAN** o **Tailscale**. También permite cambiar el
puerto. La selección se guarda en `network.json` junto al ejecutable y puede
modificarse en cada arranque. Para acceder desde otro equipo, permite el puerto
elegido en el Firewall de Windows y usa la IP LAN o Tailscale del equipo.

#### Uso paso a paso

1. Ejecuta `NotasEstudiantes.exe`.
2. En **Dirección de escucha**, selecciona una opción:
   - **Solo este equipo**: acceso únicamente desde esa computadora.
   - **LAN · 192.168.x.x**: acceso desde la red local.
   - **Tailscale · 100.x.x.x**: acceso desde equipos conectados a Tailscale.
   - **Todas las interfaces**: escucha por LAN y Tailscale al mismo tiempo.
   - **IP manual**: escribe una dirección específica.
3. Define el puerto, normalmente `5000`, y pulsa **Guardar y arrancar**.
4. Desde el mismo equipo abre `http://127.0.0.1:5000/login`.
5. Desde otro equipo usa `http://IP_ELEGIDA:5000/login`, por ejemplo:
   `http://192.168.1.25:5000/login` o `http://100.100.20.15:5000/login`.

Si Windows bloquea la conexión, permite el puerto seleccionado en el Firewall
(ejecuta PowerShell como administrador):

```powershell
New-NetFirewallRule -DisplayName "Notas Estudiantes 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
```

La selección queda guardada en `network.json`. Si necesitas cambiar de LAN a
Tailscale, cierra la aplicación y vuelve a abrirla para mostrar nuevamente el
menú de configuración.

### Compilar el instalador de Windows

La compilación se hace en Windows 10 u 11. En el equipo donde se compila se
necesitan Git, Python 3.11 o superior e
[Inno Setup 6](https://jrsoftware.org/isdl.php). El equipo que usará la
aplicación no necesita Python, Git ni Docker.

1. Clona el proyecto y entra en su carpeta:

   ```powershell
   git clone https://github.com/ciprianotoor/notas-estudiantes.git
   cd notas-estudiantes
   ```

2. Ejecuta el script de compilación:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
   ```

El script instala las dependencias de Python desde `requirements.txt`, crea el
ejecutable con PyInstaller y, si encuentra `ISCC.exe`, genera
`installer\NotasEstudiantes-Setup.exe` con Inno Setup. WiX es opcional y se
usa para producir también el MSI. El script usa las herramientas `heat.exe`,
`candle.exe` y `light.exe` de WiX v3; tener instalado `wix-cli-x64.msi` por sí
solo no garantiza que esas tres herramientas estén disponibles.

Los paquetes y enlaces oficiales para preparar el equipo están en
[`installer/appsrequeriments/README.md`](installer/appsrequeriments/README.md).
Se pueden descargar desde allí por separado o extraer los ZIP incluidos. No
es necesario descargar ni instalar WiX para generar el instalador EXE.

La compilación realizada generó `dist\NotasEstudiantes` y el instalador EXE
de aproximadamente 19 MB. El ejecutable es de tipo `onedir`: sus archivos de
soporte quedan dentro de la carpeta `_internal`, por lo que no se debe copiar
solo `NotasEstudiantes.exe`. La salida inspeccionada incluye `python314.dll`,
lo que confirma que esa compilación se hizo con Python 3.14. Al repetir el
proceso, el script limpia `build` y `dist` pero conserva
`installer/appsrequeriments`.

El instalador para docentes se distribuye en GitHub en **Actions**, dentro del
flujo **Instalador Windows**, o como MSI en **Releases** al publicar una
etiqueta `v*`. La base de datos y los archivos cargados se conservan en la
carpeta `data` junto al programa. Antes de actualizar una instalación,
realiza un respaldo desde la interfaz.

### Instalación con Docker Desktop

Como alternativa, descarga [`instalar_windows.bat`](instalar_windows.bat) y
ejecútalo. El script instala Docker Desktop mediante `winget` si está
disponible, clona o actualiza el proyecto y conserva la carpeta `data`.

Para usar la aplicación desde otros equipos de la red, cambia el host del
lanzador a `0.0.0.0`, permite el puerto 5000 en el Firewall de Windows y
accede con `http://IP_DEL_EQUIPO:5000`.
