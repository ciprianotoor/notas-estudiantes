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

La boleta escolar A4 plegable se organiza en cuatro caras: portada, información general, evaluación académica con conducta y observaciones/cierre. La tabla de escalas usa la nomenclatura MINED: Aprendizaje Avanzado (AA, 90–100), Aprendizaje Satisfactorio (AS, 76–89), Aprendizaje Fundamental (AF, 60–75) y Aprendizaje Inicial (AI, menos de 60).

En la boleta, `CN` significa cuantitativa, `CL` cualitativa, `SC` sin calificación y `NR` no registrado. Las notas se imprimen sin decimales. Cada parcial incluye casillas de firma para docente guía, padre/madre/tutor y estudiante. La escala de equivalencias aparece junto a los datos generales del estudiante.

Conducta conserva cuantitativa, cualitativa, criterios, incidentes y observaciones por parcial. Los criterios orientativos son relaciones interpersonales, responsabilidad individual y compartida, participación extracurricular, solidaridad y colaboración, asistencia y puntualidad, orden y aseo.

## Bajas, consulta e impresión

La baja conserva notas y expediente. Desde “Dados de baja” se puede restablecer matrícula, exportar CSV, imprimir o eliminar definitivamente; esto último solo Admin/Dirección y con confirmación. Al imprimir una boleta individual o en lote puedes elegir clases y parciales, además de incluir u ocultar Conducta y seleccionar qué datos mostrar: cuantitativa, cualitativa, criterios utilizados, incidentes y observaciones. En “Imprimir notas” se pueden filtrar y seleccionar varios estudiantes; cada uno sale en su propia página del PDF. Las boletas individuales se descargan con nombre y grado, por ejemplo `boletin-Nombre_Estudiante-9no.pdf`; la versión plegable añade `-a4-plegable`.

## Sábana de notas

Desde “Sábana de notas” el docente guía consulta el consolidado de sus grupos. Los estudiantes aparecen en orden alfabético y las clases se muestran como columnas, cada una con sus cuatro parciales y promedio. La vista incluye número, código, año lectivo, docente, grupo y datos del colegio. Antes de imprimir se puede revisar la vista previa y escoger opciones. El formato recomendado es Legal horizontal; cuando el número de clases no permite una sola página, se generan varias páginas conservando los encabezados.

## Estadística académica y bajas

“Estadística” contiene dos consultas separadas. La primera identifica por estudiante las materias reprobadas, con nombre, código, grupo y nota anual. La nota anual es `(P1 + P2 + P3 + P4) / 4`; un parcial sin registro cuenta como cero y una materia menor de 60 se considera reprobada. La segunda lista estudiantes retirados o dados de baja, con fecha y motivo, sin borrar sus notas históricas. El docente guía ve únicamente sus grupos; Admin y Secretaría ven el alcance institucional autorizado.

## Límites, permisos y auditoría

Cada trabajo tiene un límite predeterminado de 10 puntos y el examen de 40 puntos. Un docente no puede superar esos valores desde el formulario. Si existe una justificación válida, la opción “Modificar valor máximo” solicita nuevos límites y una explicación; el cambio queda registrado con docente, fecha, hora, parcial, límites y motivo. Admin puede realizar tareas administrativas y sus modificaciones sensibles también quedan registradas.

## Tema, ayuda y pruebas

Admin configura identidad y colores desde “Configuración”. El Docente guía tiene selector personal Día/Noche. La ayuda está en la barra superior. Ejecutar las pruebas con `.venv/bin/pytest -q`. En producción usar WSGI, SECRET_KEY segura y respaldos cifrados.

## Uso desde PC, tablet y teléfono

La barra superior adapta sus botones a pantallas grandes y pequeñas. En teléfonos los enlaces se pueden desplazar horizontalmente; si no aparecen los últimos botones, desliza la barra de navegación hacia la izquierda. Si el navegador muestra estilos anteriores, realiza una recarga forzada (`Ctrl+F5` en PC) o cierra y abre nuevamente la página en Android.
