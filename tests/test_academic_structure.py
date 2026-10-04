import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


def test_student_enrollment_lists_same_grade_classes_even_when_group_has_none(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    importlib.reload(app_module)

    with app_module.db() as connection:
        admin = connection.execute("SELECT id FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
        connection.execute("INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)", ("Guía", "guia@test", "pass"))
        guide = connection.execute("SELECT id FROM teachers WHERE email=?", ("guia@test",)).fetchone()
        connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'guide')", (guide["id"],))
        connection.execute("INSERT OR IGNORE INTO subject_catalog(code,name,active) VALUES(?,?,1)", ("MAT", "Matemática"))
        connection.execute("INSERT INTO subject_catalog(code,name,active) VALUES(?,?,1)", ("BIO", "Biología"))
        connection.execute("INSERT INTO subjects(name,grade,year,created_by) VALUES(?,?,?,?)", ("Matemática", "7mo", 2026, admin["id"]))
        connection.execute("INSERT INTO subjects(name,grade,year,created_by) VALUES(?,?,?,?)", ("Biología", "7mo", 2026, admin["id"]))
        math = connection.execute("SELECT id FROM subjects WHERE name=?", ("Matemática",)).fetchone()
        bio = connection.execute("SELECT id FROM subjects WHERE name=?", ("Biología",)).fetchone()
        connection.execute("INSERT INTO groups(name,grade,section,academic_year,teacher_id) VALUES(?,?,?, ?, ?)", ("7mo A", "7mo", "A", 2026, guide["id"]))
        group_a = connection.execute("SELECT id FROM groups WHERE name=?", ("7mo A",)).fetchone()
        connection.execute("INSERT INTO groups(name,grade,section,academic_year,teacher_id) VALUES(?,?,?, ?, ?)", ("7mo B", "7mo", "A", 2026, guide["id"]))
        group_b = connection.execute("SELECT id FROM groups WHERE name=?", ("7mo B",)).fetchone()
        connection.execute("INSERT INTO classes(name,subject_id,grade,year,section,group_id,teacher_id) VALUES(?,?,?,?,?,?,?)", ("Matemática", math["id"], "7mo", 2026, "A", group_b["id"], guide["id"]))
        connection.execute("INSERT INTO classes(name,subject_id,grade,year,section,group_id,teacher_id) VALUES(?,?,?,?,?,?,?)", ("Biología", bio["id"], "7mo", 2026, "A", group_b["id"], guide["id"]))
        connection.execute("INSERT INTO students(code,name,section,group_id,teacher_id) VALUES(?,?,?,?,?)", ("001", "Ana López", "A", group_a["id"], guide["id"]))

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = admin["id"]

    response = client.get("/groups", follow_redirects=True)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Matemática" in html
    assert "Biología" in html


def test_duplicate_year_is_handled_cleanly(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    importlib.reload(app_module)

    with app_module.db() as connection:
        connection.execute(
            "INSERT INTO academic_years(year,start_date,end_date,status) VALUES(?,?,?,?)",
            (2025, "2025-01-01", "2025-12-31", "open"),
        )

    client = app_module.app.test_client()
    with app_module.db() as connection:
        admin = connection.execute("SELECT id FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
        assert admin is not None

    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = admin["id"]

    response = client.post(
        "/academic-structure",
        data={
            "kind": "year",
            "year": "2025",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "status": "open",
        },
        follow_redirects=True,
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "No se pudo guardar" in html
    assert "año lectivo" in html.lower()
    assert "2025" in html
    assert "UNIQUE constraint failed" not in html

    get_response = client.get("/academic-structure")
    get_html = get_response.get_data(as_text=True)
    assert get_response.status_code == 200
    assert "Matutino" in get_html
    assert "Nocturno" in get_html
    assert "Inicial" in get_html
    assert "Primaria" in get_html

    with app_module.db() as connection:
        connection.execute("INSERT INTO teachers(name, email, password, is_admin) VALUES(?,?,?,0)", ("Guía nueva", "guia@local", "pass"))
        teacher = connection.execute("SELECT id FROM teachers WHERE name=? ORDER BY id DESC LIMIT 1", ("Guía nueva",)).fetchone()
        connection.execute("INSERT INTO academic_years(year,start_date,end_date,status) VALUES(?,?,?,?)", (2027, "2027-01-01", "2027-12-31", "open"))
        year = connection.execute("SELECT id FROM academic_years WHERE year=?", (2027,)).fetchone()
        connection.execute("INSERT INTO grades(name,code,level,active) VALUES(?,?,?,1)", ("8.º grado", "8", "Secundaria"))
        grade = connection.execute("SELECT id FROM grades WHERE code=?", ("8",)).fetchone()
        connection.execute("INSERT INTO sections(academic_year_id,grade_id,name,shift,teacher_guide_id,active) VALUES(?,?,?,?,?,1)", (year["id"], grade["id"], "A", "Matutino", None))
        section = connection.execute("SELECT id FROM sections WHERE academic_year_id=? AND grade_id=? AND name=?", (year["id"], grade["id"], "A")).fetchone()

    update_response = client.post(
        "/academic-structure",
        data={
            "action": "update_section",
            "section_id": section["id"],
            "academic_year_id": year["id"],
            "grade_id": grade["id"],
            "name": "B",
            "shift": "Nocturno",
            "teacher_guide_id": teacher["id"],
        },
        follow_redirects=True,
    )

    assert update_response.status_code == 200
    with app_module.db() as connection:
        updated = connection.execute("SELECT name, shift, teacher_guide_id FROM sections WHERE id=?", (section["id"],)).fetchone()
        assert updated["name"] == "B"
        assert updated["shift"] == "Nocturno"
        assert updated["teacher_guide_id"] == teacher["id"]


def test_teacher_guide_can_open_assigned_groups_page(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    importlib.reload(app_module)

    with app_module.db() as connection:
        connection.execute("INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)", ("Docente guía", "guia@test", "pass"))
        teacher = connection.execute("SELECT id FROM teachers WHERE name=? ORDER BY id DESC LIMIT 1", ("Docente guía",)).fetchone()
        connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)", (teacher["id"], "guide"))
        connection.execute("INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)", (teacher["id"], "guide"))

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = teacher["id"]

    response = client.get("/groups", follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Aún no hay grupos" in html


def test_edit_teacher_can_update_subject_assignments(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    importlib.reload(app_module)
    monkeypatch.setattr(app_module, "setup_level", lambda: 4)

    with app_module.db() as connection:
        admin = connection.execute(
            "SELECT id FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1",
        ).fetchone()
        connection.execute(
            "INSERT INTO teachers(name,email,password,grade,academic_year) VALUES(?,?,?,?,?)",
            ("Docente de materia", "materia@test", "pass", "7mo", 2026),
        )
        teacher = connection.execute(
            "SELECT id FROM teachers WHERE email=?",
            ("materia@test",),
        ).fetchone()
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)",
            (teacher["id"], "teacher"),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO subject_catalog(code,name,active) VALUES(?,?,1)",
            [("MAT", "Matemática"), ("LEN", "Lengua")],
        )
        connection.executemany(
            "INSERT INTO subjects(name,created_by) VALUES(?,?)",
            [("Matemática", admin["id"]), ("Lengua", admin["id"])],
        )
        subject_ids = {
            row["name"]: row["id"]
            for row in connection.execute("SELECT id,name FROM subjects")
        }

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = admin["id"]

    edit_page = client.get(f"/teachers/{teacher['id']}/edit")
    assert edit_page.status_code == 200
    assert "Materias que imparte este docente" in edit_page.get_data(as_text=True)

    response = client.post(
        f"/teachers/{teacher['id']}/edit",
        data={
            "name": "Docente de materia",
            "email": "materia@test",
            "role": "teacher",
            "teacher_grade": "7mo",
            "teacher_section": "A",
            "teacher_year": "2026",
            "subject_id": str(subject_ids["Lengua"]),
            "employment_status": "Activo",
            "status_start_date": "",
            "status_end_date": "",
            "reentry_date": "",
        },
    )
    assert response.status_code == 302

    with app_module.db() as connection:
        assigned_subject_ids = {
            row["subject_id"]
            for row in connection.execute(
                "SELECT subject_id FROM assignments WHERE teacher_id=?",
                (teacher["id"],),
            )
        }
    assert assigned_subject_ids == {subject_ids["Lengua"]}

    refreshed_page = client.get(f"/teachers/{teacher['id']}/edit")
    assert f'value="{subject_ids["Lengua"]}" checked' in refreshed_page.get_data(as_text=True)


def test_director_can_assign_multiple_groups_before_classes_exist(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    importlib.reload(app_module)

    with app_module.db() as connection:
        admin = connection.execute("SELECT id FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
        connection.execute(
            "INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)",
            ("Docente guía", "guia@test", "pass"),
        )
        guide = connection.execute("SELECT id FROM teachers WHERE email=?", ("guia@test",)).fetchone()
        connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)", (guide["id"], "guide"))
        connection.execute(
            "INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)",
            (guide["id"], "guide"),
        )
        connection.execute(
            "INSERT INTO subjects(name,grade,year,created_by) VALUES(?,?,?,?)",
            ("Matemática", "7mo", 2026, admin["id"]),
        )
        connection.execute(
            "INSERT INTO groups(name,grade,section,academic_year,teacher_id) VALUES(?,?,?,?,?)",
            ("7mo A", "7mo", "A", 2026, guide["id"]),
        )

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = admin["id"]

    response = client.post(
        "/groups",
        data={
            "name": "7mo B",
            "grade": "7mo",
            "section": "B",
            "academic_year": "2026",
            "guide_id": str(guide["id"]),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Grupo creado correctamente" in response.get_data(as_text=True)
    with app_module.db() as connection:
        assigned_group = connection.execute(
            "SELECT id FROM groups WHERE name=? AND teacher_id=?",
            ("7mo B", guide["id"]),
        ).fetchone()
        assert assigned_group is not None


def test_guide_can_enroll_without_classes_and_update_unique_student_code(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    importlib.reload(app_module)

    with app_module.db() as connection:
        connection.execute(
            "INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)",
            ("Docente guía", "guia@test", "pass"),
        )
        guide = connection.execute(
            "SELECT id FROM teachers WHERE email=?",
            ("guia@test",),
        ).fetchone()
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)",
            (guide["id"], "guide"),
        )
        connection.execute(
            "INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)",
            (guide["id"], "guide"),
        )
        connection.execute(
            "INSERT INTO groups(name,grade,section,academic_year,teacher_id) VALUES(?,?,?,?,?)",
            ("7mo A", "7mo", "A", 2026, guide["id"]),
        )
        group = connection.execute(
            "SELECT id FROM groups WHERE name=?",
            ("7mo A",),
        ).fetchone()
        connection.execute(
            "INSERT INTO students(code,name,section,group_id,teacher_id) VALUES(?,?,?,?,?)",
            ("EXISTING-01", "Otro estudiante", "A", group["id"], guide["id"]),
        )

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = guide["id"]

    group_page = client.get("/groups")
    html = group_page.get_data(as_text=True)
    assert group_page.status_code == 200
    assert "Código único / carnet" in html
    assert 'name="class_id"' in html

    enrollment = client.post(
        "/groups",
        data={
            "action": "add_student",
            "group_id": str(group["id"]),
            "code": "STU-001",
            "student_name": "Estudiante Nuevo",
            "section": "A",
        },
        follow_redirects=True,
    )
    assert "Matrícula confirmada" in enrollment.get_data(as_text=True)
    with app_module.db() as connection:
        student = connection.execute(
            "SELECT id FROM students WHERE code=?",
            ("STU-001",),
        ).fetchone()
        assert student is not None

    duplicate = client.post(
        "/groups",
        data={
            "action": "add_student",
            "group_id": str(group["id"]),
            "code": "EXISTING-01",
            "student_name": "Código duplicado",
            "section": "A",
        },
        follow_redirects=True,
    )
    assert "Cada estudiante debe tener un código único" in duplicate.get_data(as_text=True)

    update = client.post(
        "/groups",
        data={
            "action": "update_student",
            "group_id": str(group["id"]),
            "student_id": str(student["id"]),
            "code": "STU-002",
            "student_name": "Estudiante Nuevo Actualizado",
            "section": "A",
        },
        follow_redirects=True,
    )
    assert "Matrícula actualizada correctamente" in update.get_data(as_text=True)
    with app_module.db() as connection:
        updated = connection.execute(
            "SELECT code,name FROM students WHERE id=?",
            (student["id"],),
        ).fetchone()
        assert updated["code"] == "STU-002"
        assert updated["name"] == "Estudiante Nuevo Actualizado"


def test_active_admin_subjects_are_available_for_group_approval_and_guide_enrollment(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    importlib.reload(app_module)

    with app_module.db() as connection:
        admin = connection.execute(
            "SELECT id FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1",
        ).fetchone()
        connection.execute(
            "INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)",
            ("Docente guía", "guia@test", "pass"),
        )
        guide = connection.execute(
            "SELECT id FROM teachers WHERE email=?",
            ("guia@test",),
        ).fetchone()
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)",
            (guide["id"], "guide"),
        )
        connection.execute(
            "INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)",
            (guide["id"], "guide"),
        )
        connection.execute(
            "INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)",
            ("Docente de materia", "materia@test", "pass"),
        )
        subject_teacher = connection.execute(
            "SELECT id FROM teachers WHERE email=?",
            ("materia@test",),
        ).fetchone()
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)",
            (subject_teacher["id"], "teacher"),
        )
        connection.execute(
            "INSERT INTO groups(name,grade,section,academic_year,teacher_id) VALUES(?,?,?,?,?)",
            ("7mo A", "7mo", "A", 2026, guide["id"]),
        )
        group = connection.execute(
            "SELECT id FROM groups WHERE name=?",
            ("7mo A",),
        ).fetchone()
        connection.executemany(
            "INSERT OR IGNORE INTO subject_catalog(code,name,active) VALUES(?,?,1)",
            [("MAT", "Matemática"), ("LEN", "Lengua")],
        )
        connection.execute(
            "INSERT INTO subject_catalog(code,name,active) VALUES(?,?,0)",
            ("CIE", "Ciencias"),
        )
        connection.execute("INSERT INTO subjects(name) VALUES(?)", ("Ciencias",))

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = admin["id"]

    admin_groups = client.get("/groups")
    assert "Aprobar materia para este grupo" in admin_groups.get_data(as_text=True)
    class_options = client.get("/classes").get_data(as_text=True)
    assert "Matemática" in class_options
    assert "Lengua" in class_options
    assert 'value="3">Ciencias</option>' not in class_options

    with app_module.db() as connection:
        subjects = {
            row["name"]: row["id"]
            for row in connection.execute("SELECT id,name FROM subjects")
        }

    create_class = client.post(
        "/classes",
        data={
            "name": "Matemática 7mo A",
            "subject_id": str(subjects["Matemática"]),
            "group_id": str(group["id"]),
            "teacher_id": str(subject_teacher["id"]),
        },
    )
    assert create_class.status_code == 302
    create_second_class = client.post(
        "/classes",
        data={
            "name": "Lengua 7mo A",
            "subject_id": str(subjects["Lengua"]),
            "group_id": str(group["id"]),
            "teacher_id": str(subject_teacher["id"]),
        },
    )
    assert create_second_class.status_code == 302
    with app_module.db() as connection:
        math_class = connection.execute(
            "SELECT id FROM classes WHERE group_id=? AND subject_id=?",
            (group["id"], subjects["Matemática"]),
        ).fetchone()
        language_class = connection.execute(
            "SELECT id FROM classes WHERE group_id=? AND subject_id=?",
            (group["id"], subjects["Lengua"]),
        ).fetchone()

    with client.session_transaction() as session:
        session["teacher_id"] = guide["id"]

    guide_groups = client.get("/groups").get_data(as_text=True)
    assert "Matemática" in guide_groups
    assert "Lengua" in guide_groups
    assert guide_groups.count('name="class_id"') >= 2

    enrollment = client.post(
        "/groups",
        data={
            "action": "add_student",
            "group_id": str(group["id"]),
            "code": "S-SELECT",
            "student_name": "Estudiante Selectivo",
            "section": "A",
            "class_id": str(math_class["id"]),
        },
        follow_redirects=True,
    )
    assert "Matrícula confirmada" in enrollment.get_data(as_text=True)
    with app_module.db() as connection:
        student = connection.execute(
            "SELECT id FROM students WHERE code=?",
            ("S-SELECT",),
        ).fetchone()
        enrolled_classes = connection.execute(
            "SELECT class_id FROM student_classes WHERE student_id=?",
            (student["id"],),
        ).fetchall()
        assert math_class["id"] in [row["class_id"] for row in enrolled_classes]
        assert language_class["id"] in [row["class_id"] for row in enrolled_classes]


def test_director_assigns_group_and_guide_can_register_its_students_grades(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    importlib.reload(app_module)

    with app_module.db() as connection:
        admin = connection.execute("SELECT id FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
        connection.execute(
            "INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)",
            ("Docente guía", "guia@test", "pass"),
        )
        guide = connection.execute("SELECT id FROM teachers WHERE email=?", ("guia@test",)).fetchone()
        connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)", (guide["id"], "guide"))
        connection.execute(
            "INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)",
            (guide["id"], "guide"),
        )
    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = admin["id"]

    create_group = client.post(
        "/groups",
        data={
            "name": "7mo A",
            "grade": "7mo",
            "section": "A",
            "academic_year": "2026",
            "guide_id": str(guide["id"]),
        },
        follow_redirects=True,
    )
    assert create_group.status_code == 200
    with app_module.db() as connection:
        group = connection.execute(
            "SELECT id FROM groups WHERE name=? AND teacher_id=?",
            ("7mo A", guide["id"]),
        ).fetchone()
        assert group is not None, create_group.get_data(as_text=True)
        connection.execute(
            "INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)",
            ("Docente de materia", "materia@test", "pass"),
        )
        subject_teacher = connection.execute(
            "SELECT id FROM teachers WHERE email=?",
            ("materia@test",),
        ).fetchone()
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)",
            (subject_teacher["id"], "teacher"),
        )
        connection.execute(
            "INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)",
            ("Otra guía", "otra-guia@test", "pass"),
        )
        other_guide = connection.execute(
            "SELECT id FROM teachers WHERE email=?",
            ("otra-guia@test",),
        ).fetchone()
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)",
            (other_guide["id"], "guide"),
        )
        connection.execute(
            "INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)",
            (other_guide["id"], "guide"),
        )
        connection.execute(
            "INSERT INTO groups(name,grade,section,academic_year,teacher_id) VALUES(?,?,?,?,?)",
            ("8vo B", "8vo", "B", 2026, other_guide["id"]),
        )
        other_group = connection.execute(
            "SELECT id FROM groups WHERE name=?",
            ("8vo B",),
        ).fetchone()
        connection.execute(
            "INSERT INTO students(code,name,section,group_id,teacher_id) VALUES(?,?,?,?,?)",
            ("S-02", "Estudiante de otro grupo", "B", other_group["id"], other_guide["id"]),
        )
        other_student = connection.execute(
            "SELECT id FROM students WHERE code='S-02'",
        ).fetchone()
        connection.execute(
            "INSERT INTO subjects(name,grade,year,created_by) VALUES(?,?,?,?)",
            ("Matemática", "7mo", 2026, admin["id"]),
        )
        subject = connection.execute("SELECT id FROM subjects WHERE name=?", ("Matemática",)).fetchone()
        connection.execute(
            "INSERT INTO classes(name,subject_id,grade,year,section,group_id,teacher_id) VALUES(?,?,?,?,?,?,?)",
            ("Matemática 7mo A", subject["id"], "7mo", 2026, "A", group["id"], subject_teacher["id"]),
        )
        class_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    with client.session_transaction() as session:
        session["teacher_id"] = guide["id"]

    enrollment = client.post(
        "/groups",
        data={
            "action": "add_student",
            "group_id": str(group["id"]),
            "code": "S-01",
            "student_name": "Estudiante Asignado",
            "section": "A",
            "class_id": str(class_id),
        },
        follow_redirects=True,
    )
    assert "Matrícula confirmada" in enrollment.get_data(as_text=True)
    with app_module.db() as connection:
        student = connection.execute(
            "SELECT id FROM students WHERE code=?",
            ("S-01",),
        ).fetchone()

    group_page = client.get("/groups")
    assert group_page.status_code == 200
    assert "7mo A" in group_page.get_data(as_text=True)
    assert "8vo B" not in group_page.get_data(as_text=True)
    dashboard = client.get("/").get_data(as_text=True)
    assert "Grupos y matrículas" in dashboard
    assert "Estudiante de otro grupo" not in dashboard
    assert client.get(f"/students/{other_student['id']}/grades").status_code == 302
    assert client.get(f"/reports/{other_student['id']}/pdf").status_code == 404

    grade_page = client.get(f"/students/{student['id']}/grades")
    assert grade_page.status_code == 200
    assert "Registrar notas" in grade_page.get_data(as_text=True)
    save_grade = client.post(
        f"/students/{student['id']}/grades",
        data={
            "partial": "1",
            "subject_id": str(subject["id"]),
            "work1": "8",
            "exam": "30",
        },
        follow_redirects=True,
    )
    assert save_grade.status_code == 200
    with app_module.db() as connection:
        grade = connection.execute(
            "SELECT work1,exam FROM partial_grades WHERE student_id=? AND partial=1 AND subject_id=?",
            (student["id"], subject["id"]),
        ).fetchone()
        assert grade["work1"] == 8
        assert grade["exam"] == 30


def test_guide_can_update_conduct_only_for_assigned_students(tmp_path, monkeypatch):
    db_path = tmp_path / "notas.db"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    importlib.reload(app_module)

    with app_module.db() as connection:
        connection.execute("INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)", ("Docente guía", "guia@test", "pass"))
        teacher = connection.execute("SELECT id FROM teachers WHERE email=?", ("guia@test",)).fetchone()
        connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)", (teacher["id"], "guide"))
        connection.execute("INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)", (teacher["id"], "guide"))
        connection.execute("INSERT INTO groups(name,teacher_id) VALUES(?,?)", ("7A", teacher["id"]))
        group = connection.execute("SELECT id FROM groups WHERE name=?", ("7A",)).fetchone()
        connection.execute("INSERT INTO subjects(name,grade,year,created_by) VALUES(?,?,?,?)", ("Matemática", "7.º", 2026, teacher["id"]))
        subject = connection.execute("SELECT id FROM subjects WHERE name=?", ("Matemática",)).fetchone()
        connection.execute("INSERT INTO classes(name,subject_id,group_id,teacher_id) VALUES(?,?,?,?)", ("Matemática 7A", subject["id"], group["id"], teacher["id"]))
        class_id = connection.execute("SELECT id FROM classes WHERE name=?", ("Matemática 7A",)).fetchone()["id"]
        connection.execute("INSERT INTO students(code,name,group_id,teacher_id) VALUES(?,?,?,?)", ("S-01", "Estudiante Uno", group["id"], teacher["id"]))
        student = connection.execute("SELECT id FROM students WHERE code=?", ("S-01",)).fetchone()
        connection.execute("INSERT INTO student_classes(student_id,class_id) VALUES(?,?)", (student["id"], class_id))
        connection.execute("INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,0)", ("Otra guía", "otra-guia@test", "pass"))
        other_guide = connection.execute("SELECT id FROM teachers WHERE email=?", ("otra-guia@test",)).fetchone()
        connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?)", (other_guide["id"], "guide"))
        connection.execute("INSERT INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)", (other_guide["id"], "guide"))
        connection.execute("INSERT INTO students(code,name,teacher_id) VALUES(?,?,?)", ("S-02", "Estudiante de otro grupo", other_guide["id"]))
        other_student = connection.execute("SELECT id FROM students WHERE code=?", ("S-02",)).fetchone()

    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = teacher["id"]

    dashboard = client.get("/").get_data(as_text=True)
    assert "Buscar estudiantes" in dashboard
    assert "Grupos y matrículas" in dashboard

    student_records = client.get("/students").get_data(as_text=True)
    assert "Ver notas" in student_records
    assert "Gestionar desde el grupo" not in student_records
    assert "entra a la tarjeta del grupo" not in student_records

    grade_page = client.get(f"/students/{student['id']}/grades")
    assert grade_page.status_code == 200
    assert "Evaluación cuantitativa de conducta" in grade_page.get_data(as_text=True)

    profile_response = client.post(
        f"/students/{student['id']}/profile",
        data={
            "conduct_score": "95",
            "conduct_criteria": "Respeto y responsabilidad",
            "conduct_incidents": "Ninguno",
            "observations": "Buen comportamiento",
        },
        follow_redirects=True,
    )
    assert profile_response.status_code == 200
    assert "Conducta y observaciones guardadas." in profile_response.get_data(as_text=True)
    with app_module.db() as connection:
        updated_student = connection.execute(
            "SELECT conduct_score,conduct_criteria,conduct_incidents,observations FROM students WHERE id=?",
            (student["id"],),
        ).fetchone()
        assert updated_student["conduct_score"] == 95
        assert updated_student["conduct_criteria"] == "Respeto y responsabilidad"
        assert updated_student["conduct_incidents"] == "Ninguno"
        assert updated_student["observations"] == "Buen comportamiento"

    unauthorized_response = client.post(
        f"/students/{other_student['id']}/profile",
        data={"conduct_score": "12", "conduct_criteria": "", "conduct_incidents": "", "observations": ""},
        follow_redirects=True,
    )
    assert "Solo el director, administrador o docente guía responsable" in unauthorized_response.get_data(as_text=True)
    with app_module.db() as connection:
        unauthorized_student = connection.execute(
            "SELECT conduct_score FROM students WHERE id=?",
            (other_student["id"],),
        ).fetchone()
        assert unauthorized_student["conduct_score"] is None


def test_fixed_director_and_secretary_roles_are_read_only_for_grades(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notas.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    importlib.reload(app_module)

    with app_module.db() as connection:
        connection.execute(
            "INSERT INTO teachers(name,password,account_type,is_admin) VALUES(?,?,?,0)",
            ("Director fijo", "pass", "Director"),
        )
        director_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'director')",
            (director_id,),
        )
        director = connection.execute(
            "SELECT t.id FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id "
            "WHERE r.role='director' ORDER BY t.id LIMIT 1",
        ).fetchone()
        original_director = connection.execute(
            "SELECT name,hire_date FROM teachers WHERE id=?", (director["id"],)
        ).fetchone()
        connection.execute(
            "INSERT INTO students(code,name) VALUES(?,?)",
            ("SEC-001", "Estudiante para boleta"),
        )
        student = connection.execute(
            "SELECT id FROM students WHERE code=?",
            ("SEC-001",),
        ).fetchone()
        connection.execute(
            "INSERT INTO subjects(name,created_by) VALUES(?,?)",
            ("Matemática", director["id"]),
        )
        subject = connection.execute(
            "SELECT id FROM subjects WHERE name=?",
            ("Matemática",),
        ).fetchone()
        connection.execute(
            "INSERT INTO partial_grades(student_id,partial,subject_id,work1,exam) VALUES(?,?,?,?,?)",
            (student["id"], 1, subject["id"], 8, 30),
        )

    client = app_module.app.test_client()
    with app_module.db() as connection:
        support = connection.execute("SELECT id FROM teachers WHERE is_admin=1 LIMIT 1").fetchone()
    with client.session_transaction() as session:
        session["role"] = "teacher"
        session["teacher_id"] = support["id"]

    director_update = client.post(
        "/teachers?onboarding=1",
        data={
            "account_type": "Director",
            "role": "director",
            "first_name": "Dirección",
            "last_name": "Colegio",
            "hire_date": "2020-01-15",
            "employment_status": "Activo",
            "status_start_date": "2020-01-15",
        },
    )
    assert director_update.status_code == 302

    secretary_create = client.post(
        "/teachers?onboarding=1",
        data={
            "account_type": "Secretaría",
            "role": "secretary",
            "first_name": "Ana",
            "last_name": "Secretaria",
            "hire_date": "2022-02-01",
            "password": "secretary-pass",
            "employment_status": "Activo",
            "status_start_date": "2022-02-01",
        },
    )
    assert secretary_create.status_code == 302

    with app_module.db() as connection:
        secretary_id = connection.execute(
            "SELECT id FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id WHERE r.role='secretary'",
        ).fetchone()["id"]

    monkeypatch.setattr(app_module, "setup_level", lambda: 4)
    secretary_edit = client.post(
        f"/teachers/{secretary_id}/edit",
        data={
            "name": "Ana Secretaria",
            "first_name": "Ana",
            "last_name": "Secretaria",
            "hire_date": "2022-02-01",
            "role": "secretary",
            "employment_status": "Subsidio",
            "status_start_date": "2026-09-01",
            "status_end_date": "2026-10-01",
            "reentry_date": "",
            "employment_reason": "Subsidio temporal",
            "change_reason": "",
            "email": "",
            "password": "",
        },
    )
    assert secretary_edit.status_code == 302

    with app_module.db() as connection:
        director_record = connection.execute(
            "SELECT name,hire_date,account_type FROM teachers WHERE id=?",
            (director["id"],),
        ).fetchone()
        assert tuple(director_record) == ("Dirección Colegio", "2020-01-15", "Director")
        secretary = connection.execute(
            "SELECT t.id,t.hire_date,t.account_type,r.role FROM teachers t "
            "JOIN teacher_roles r ON r.teacher_id=t.id WHERE r.role='secretary'",
        ).fetchone()
        assert secretary is not None
        assert secretary["id"] == secretary_id
        assert secretary["account_type"] == "Secretaría"
        assert secretary["hire_date"] == "2022-02-01"
        updated_secretary = connection.execute(
            "SELECT employment_status,status_start_date,status_end_date FROM teachers WHERE id=?",
            (secretary["id"],),
        ).fetchone()
        assert tuple(updated_secretary) == ("Subsidio", "2026-09-01", "2026-10-01")
        employment_event = connection.execute(
            "SELECT reason FROM teacher_employment_history WHERE teacher_id=? ORDER BY id DESC LIMIT 1",
            (secretary["id"],),
        ).fetchone()
        assert employment_event["reason"] == "Subsidio temporal"

    duplicate_secretary = client.post(
        "/teachers?onboarding=1",
        data={
            "account_type": "Secretaría",
            "role": "secretary",
            "first_name": "Otra",
            "last_name": "Persona",
            "hire_date": "2024-01-01",
            "password": "another-pass",
        },
        follow_redirects=True,
    )
    assert "cuenta fija de Secretaría ya existe" in duplicate_secretary.get_data(as_text=True)
    accounts_page = client.get("/teachers?onboarding=1")
    assert accounts_page.status_code == 200
    assert "Secretaría · consulta e impresión" in accounts_page.get_data(as_text=True)
    assert 'option>Secretaría</option>' not in accounts_page.get_data(as_text=True)
    edit_page = client.get(f"/teachers/{secretary_id}/edit")
    assert edit_page.status_code == 200
    assert 'name="status_end_date"' in edit_page.get_data(as_text=True)
    protected_delete = client.post(
        f"/teachers/{secretary_id}/delete",
        follow_redirects=True,
    )
    assert "cuentas fijas de Director y Secretaría no se pueden eliminar" in protected_delete.get_data(as_text=True)
    with app_module.db() as connection:
        assert connection.execute("SELECT 1 FROM teachers WHERE id=?", (secretary_id,)).fetchone() is not None

    with client.session_transaction() as session:
        session["teacher_id"] = secretary_id
    students_page = client.get("/students")
    assert "Estudiante para boleta" in students_page.get_data(as_text=True)
    assert "Imprimir boleta PDF" in students_page.get_data(as_text=True)

    grade_page = client.get(f"/students/{student['id']}/grades")
    assert grade_page.status_code == 200
    assert "Consulta de notas" in grade_page.get_data(as_text=True)
    assert "Guardar o actualizar" not in grade_page.get_data(as_text=True)
    grades_post = client.post(
        f"/students/{student['id']}/grades",
        data={"partial": "1", "subject_id": str(subject["id"]), "work1": "1", "exam": "2"},
    )
    assert grades_post.status_code == 302
    with app_module.db() as connection:
        grade = connection.execute(
            "SELECT work1,exam FROM partial_grades WHERE student_id=? AND subject_id=?",
            (student["id"], subject["id"]),
        ).fetchone()
        assert (grade["work1"], grade["exam"]) == (8, 30)

    report_list = client.get("/print-reports")
    assert "Estudiante para boleta" in report_list.get_data(as_text=True)
    pdf = client.get(f"/reports/{student['id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
