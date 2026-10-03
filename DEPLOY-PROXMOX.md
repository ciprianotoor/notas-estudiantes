# Despliegue en Proxmox

1. Descarga y descomprime el ZIP en el servidor.
2. Entra a la carpeta del proyecto.
3. Cambia `SECRET_KEY` en `compose.yaml` por una clave privada.
4. Ejecuta:

```bash
docker compose up -d --build
```

La aplicación quedará disponible en `http://IP_DEL_SERVIDOR:5000`.

Los datos se conservan en `./data`, donde están la base SQLite y las imágenes cargadas. Para respaldarlos:

```bash
cp data/notas.db data/notas-respaldo-$(date +%F).db
```

Para actualizar una instalación existente, reemplaza el código del proyecto sin borrar `data/` y vuelve a ejecutar `docker compose up -d --build`.
