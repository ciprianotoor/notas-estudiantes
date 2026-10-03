# Despliegue en un servidor Linux

1. Descarga o clona el proyecto en el servidor.
2. Entra a la carpeta del proyecto.
3. Copia `.env.example` a `.env` y define una clave privada en `SECRET_KEY`.
4. Ejecuta:

```bash
docker compose up -d --build
```

La aplicación quedará disponible en `http://DIRECCION_DEL_SERVIDOR:5000`.

Los datos se conservan en `./data`, donde están la base SQLite y las imágenes cargadas. Para respaldarlos:

```bash
cp data/notas.db data/notas-respaldo-$(date +%F).db
```

Para actualizar una instalación existente, reemplaza el código del proyecto sin borrar `data/` y vuelve a ejecutar `docker compose up -d --build`.
