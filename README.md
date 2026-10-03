# Notas Estudiantes — instrucciones rápidas

Este proyecto es una aplicación Flask para gestionar estudiantes, grupos y notas.

Requisitos
- Python 3.10+ (se recomienda 3.11+)
- `python -m venv` para crear un entorno virtual

Instalación y ejecución local
```bash
cd /ruta/al/proyecto/notas-estudiantes
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Inicializar DB y ejecutar (usa ./data/notas.db por defecto)
DB_PATH=./data/notas.db SECRET_KEY=clave-local-de-desarrollo .venv/bin/python3 app.py
```

Migración desde la versión de un único docente
```bash
# Crea tablas y asigna un docente por defecto a los datos existentes
DB_PATH=./data/notas.db .venv/bin/python3 -c "import app; print('DB initializada')"
DB_PATH=./data/notas.db .venv/bin/python3 migrate_to_multi_teachers.py
```

Flujo básico
- Accede a `http://127.0.0.1:5000`
- En una instalación nueva, utiliza la cuenta administrativa creada por el instalador y cambia la contraseña inmediatamente.
- En `Configuración -> Gestionar docentes` crea nuevos docentes.
- Cada docente tiene sus propios grupos y estudiantes (filtrado por `teacher_id`).

Notas de seguridad y despliegue
- No uses el servidor de desarrollo en producción; usa un WSGI (gunicorn/uvicorn) detrás de un proxy.
- Cambia `SECRET_KEY` en producción.
- Considera cifrar backups y proteger accesos.

Si quieres, puedo:
- Añadir pruebas automatizadas (pytest) que verifiquen flujos CRUD.
- Preparar un `docker-compose` listo para producción con volumenes y un `gunicorn`.

Docker (despliegue rápido)
-------------------------

El proyecto incluye un `compose.yaml` con un servicio `notas` que expone el puerto `5000` y monta un volumen llamado `datos-notas` en el contenedor en `/data`.

- Servicio: `notas`
- Nombre del contenedor: `notas-estudiantes`
- Puerto: host `5000` -> contenedor `5000`
- Volumen: `datos-notas` montado en `/data` dentro del contenedor
- Ruta del DB dentro del contenedor: `/data/notas.db`

Comandos Docker útiles:

```bash
# Levantar servicio (reconstruye imagen si hay cambios)
docker compose up -d --build

# Entrar al contenedor (shell) para inspeccionar /data
docker compose exec notas sh
ls -la /data

# Ver tablas SQLite dentro del contenedor
docker compose exec notas sh -c "sqlite3 /data/notas.db '.tables'"

# Hacer backup del DB del volumen al host
docker run --rm -v datos-notas:/data -v "$(pwd)":/backup alpine sh -c "cp /data/notas.db /backup/"

# Parar y remover servicios
docker compose down
```

Notas importantes:
- Antes de ejecutar la migración en un entorno con datos reales, realiza un backup del volumen (`cp /data/notas.db` fuera del contenedor).
- Si prefieres montar el archivo DB en un directorio del host (para facilitar backups), modifica `compose.yaml` para usar un bind mount en lugar del volumen gestionado.

Si quieres, preparo un `docker-compose.prod.yaml` con `gunicorn`, manejo de variables de entorno y un `Dockerfile` optimizado para producción.
