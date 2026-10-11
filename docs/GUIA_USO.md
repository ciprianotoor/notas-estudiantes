# Guía de instalación y uso

## Requisitos e instalación

Requiere Python 3.10+, SQLite y, opcionalmente, Docker Compose. Instalación local: crear un entorno virtual, ejecutar `.venv/bin/pip install -r requirements.txt` y arrancar con `DB_PATH=./data/notas.db SECRET_KEY=una-clave-segura .venv/bin/python app.py`. Abrir `http://127.0.0.1:5000`. Con Docker usar `docker compose up -d --build`.

## Lógica de uso

1. Admin mantiene usuarios, catálogo de asignaturas, configuración, tema y reportes.
2. El Docente guía crea grupo, año, grado, sección y matrícula desde “Grupos y matrículas”.
3. Las asignaturas activas se aplican automáticamente a los estudiantes.
4. El docente de materia registra notas en cuatro parciales.
5. Conducta es una asignatura especial: el Docente guía registra cuantitativa, cualitativa automática, criterios, incidentes y observaciones por parcial.
6. Director, Secretaría y Admin consultan e imprimen boletas sin editar calificaciones.

## Roles y permisos

- Admin / Soporte: usuarios, catálogo, configuración, tema, reportes y respaldos; consulta notas y matrículas.
- Director: administra docentes, consulta estudiantes/notas/boletas y gestiona bajas; no edita calificaciones.
- Secretaría: consulta estudiantes, notas y boletas; no edita.
- Docente guía: crea grupos, matricula, gestiona bajas y evalúa Conducta.
- Docente de materia: registra notas de sus materias y estudiantes asignados.

## Evaluación y boleta

La boleta contiene materias por fila y columnas paralelas cuantitativa/cualitativa para cada parcial. La nota final promedia los cuatro parciales. Equivalencias: AA 90–100, AS 76–89, AF 60–75, AI menos de 60.

Conducta conserva cuantitativa, cualitativa, criterios, incidentes y observaciones por parcial. Los criterios orientativos son relaciones interpersonales, responsabilidad individual y compartida, participación extracurricular, solidaridad y colaboración, asistencia y puntualidad, orden y aseo.

## Bajas, consulta e impresión

La baja conserva notas y expediente. Desde “Dados de baja” se puede restablecer matrícula, exportar CSV, imprimir o eliminar definitivamente; esto último solo Admin/Dirección y con confirmación. Al imprimir una boleta individual o en lote puedes elegir clases y parciales, además de incluir u ocultar Conducta y seleccionar qué datos mostrar: cuantitativa, cualitativa, criterios utilizados, incidentes y observaciones. En “Imprimir notas” se pueden filtrar y seleccionar varios estudiantes; cada uno sale en su propia página del PDF.

## Tema, ayuda y pruebas

Admin configura identidad y colores desde “Configuración”. El Docente guía tiene selector personal Día/Noche. La ayuda está en la barra superior. Ejecutar las pruebas con `.venv/bin/pytest -q`. En producción usar WSGI, SECRET_KEY segura y respaldos cifrados.
