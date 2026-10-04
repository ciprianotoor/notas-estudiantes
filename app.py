import io
import os
import shutil
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from openpyxl import Workbook, load_workbook
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from reportlab.platypus import Image as PDFImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")
# Use workspace-local data directory by default to avoid permission issues on /data
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "data", "notas.db"))
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(BASE_DIR, "data", "uploads"))
PARTIALS = range(1, 5)
GRADE_OPTIONS = ("Educación inicial", "1ro", "2do", "3ro", "4to", "5to", "6to", "7mo", "8vo", "9no", "10mo", "11mo", "12mo")
SECTION_OPTIONS = ("A", "B", "C", "D", "E", "F", "Libre")
SHIFT_OPTIONS = ("Matutino", "Vespertino", "Despertino", "Nocturno", "Sabatino", "Dominical")
LEVEL_OPTIONS = ("Inicial", "Primaria", "Secundaria", "Básica", "Multigrado", "Bachillerato")
TEACHER_LEVEL_OPTIONS = ("Educación inicial", "Primaria", "Secundaria")


def clean_choice(value, allowed, default=""):
    text = (value or "").strip()
    if text in allowed:
        return text
    return default


def is_primary_grade(value):
    normalized = (value or "").strip().lower()
    return normalized in {"primaria", "educación primaria", "educacion primaria",
                          "1ro", "2do", "3ro", "4to", "5to", "6to"}


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def sync_approved_subjects():
    with db() as connection:
        administrator = connection.execute(
            "SELECT id FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1",
        ).fetchone()
        approved_subjects = connection.execute(
            "SELECT name FROM subject_catalog WHERE active=1 ORDER BY name",
        ).fetchall()
        for subject in approved_subjects:
            exists = connection.execute(
                "SELECT 1 FROM subjects WHERE name=? COLLATE NOCASE LIMIT 1",
                (subject["name"],),
            ).fetchone()
            if not exists:
                connection.execute(
                    "INSERT INTO subjects(name,created_by) VALUES(?,?)",
                    (subject["name"], administrator["id"] if administrator else None),
                )


def ensure_group_subject_classes(group_id):
    """Create the active catalog classes for a group and return their ids.

    Every student in the group starts with these subjects. The group guide is
    the default teacher; Admin/Director only maintain the catalog itself.
    """
    with db() as connection:
        group = connection.execute(
            "SELECT name,grade,section,academic_year,teacher_id FROM groups WHERE id=?",
            (group_id,),
        ).fetchone()
        if not group:
            return []
        subjects = connection.execute(
            "SELECT id,name FROM subjects ORDER BY name",
        ).fetchall()
        class_ids = []
        for subject in subjects:
            existing = connection.execute(
                """SELECT id FROM classes
                   WHERE group_id=? AND subject_id=? ORDER BY id LIMIT 1""",
                (group_id, subject["id"]),
            ).fetchone()
            if existing:
                class_ids.append(existing["id"])
                continue
            cursor = connection.execute(
                """INSERT INTO classes(name,subject_id,grade,year,section,group_id,teacher_id)
                   VALUES(?,?,?,?,?,?,?)""",
                (subject["name"], subject["id"], group["grade"] or group["name"],
                 group["academic_year"], group["section"] or "", group_id, group["teacher_id"]),
            )
            class_ids.append(cursor.lastrowid)
        active_students = connection.execute(
            "SELECT id FROM students WHERE group_id=? AND enrollment_status='active'",
            (group_id,),
        ).fetchall()
        for student in active_students:
            connection.executemany(
                "INSERT OR IGNORE INTO student_classes(student_id,class_id) VALUES(?,?)",
                [(student["id"], class_id) for class_id in class_ids],
            )
        return class_ids


def init_db():
    with db() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK(id=1), teacher_name TEXT NOT NULL DEFAULT 'Docente',
            group_name TEXT NOT NULL DEFAULT 'Grupo', teacher_password TEXT NOT NULL,
            evaluation_criteria TEXT NOT NULL DEFAULT '', school_name TEXT NOT NULL DEFAULT 'Colegio',
            logo_filename TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, subject TEXT DEFAULT '', section TEXT DEFAULT '',
            conduct TEXT DEFAULT '', observations TEXT DEFAULT '', group_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS grade_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
            partial INTEGER NOT NULL, action TEXT NOT NULL, details TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS partial_grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
            partial INTEGER NOT NULL CHECK(partial BETWEEN 1 AND 4), work1 REAL DEFAULT 0,
            work2 REAL DEFAULT 0, work3 REAL DEFAULT 0, work4 REAL DEFAULT 0,
            work5 REAL DEFAULT 0, work6 REAL DEFAULT 0, exam REAL DEFAULT 0,
            exam_date TEXT DEFAULT '', recovery_type TEXT DEFAULT '', recovery_score REAL DEFAULT 0,
            recovery_date TEXT DEFAULT '', status TEXT DEFAULT 'En proceso',
            attendance REAL DEFAULT 0, comments TEXT DEFAULT '',
            UNIQUE(student_id, partial), FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS conduct_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            partial INTEGER NOT NULL CHECK(partial BETWEEN 1 AND 4),
            quantitative REAL DEFAULT NULL,
            qualitative TEXT NOT NULL DEFAULT '',
            criteria TEXT DEFAULT '', incidents TEXT DEFAULT '', observations TEXT DEFAULT '',
            UNIQUE(student_id, partial), FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(students)")}
        if "subject" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN subject TEXT DEFAULT ''")
        if "group_id" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN group_id INTEGER")
        for column, definition in (
            ("enrollment_status", "TEXT NOT NULL DEFAULT 'active'"),
            ("withdrawal_date", "TEXT DEFAULT ''"),
            ("withdrawal_note", "TEXT DEFAULT ''"),
        ):
            if column not in columns:
                connection.execute(f"ALTER TABLE students ADD COLUMN {column} {definition}")
        grade_columns = {row["name"] for row in connection.execute("PRAGMA table_info(partial_grades)")}
        for column in ("work5", "work6"):
            if column not in grade_columns:
                connection.execute(f"ALTER TABLE partial_grades ADD COLUMN {column} REAL DEFAULT 0")
        for column in ("work1_date", "work2_date", "work3_date", "work4_date", "work5_date", "work6_date"):
            if column not in grade_columns:
                connection.execute(f"ALTER TABLE partial_grades ADD COLUMN {column} TEXT DEFAULT ''")
        for column in ("exam_date", "recovery_type", "recovery_score", "recovery_date", "status", "attendance", "comments"):
            if column not in grade_columns:
                definition = "TEXT DEFAULT ''" if column in ("exam_date", "recovery_type", "recovery_date", "status", "comments") else "REAL DEFAULT 0"
                connection.execute(f"ALTER TABLE partial_grades ADD COLUMN {column} {definition}")
        connection.execute("UPDATE partial_grades SET recovery_score=40 WHERE recovery_score>40")
        setting_columns = {row["name"] for row in connection.execute("PRAGMA table_info(settings)")}
        if "evaluation_criteria" not in setting_columns:
            connection.execute("ALTER TABLE settings ADD COLUMN evaluation_criteria TEXT NOT NULL DEFAULT ''")
        if "school_name" not in setting_columns:
            connection.execute("ALTER TABLE settings ADD COLUMN school_name TEXT NOT NULL DEFAULT 'Colegio'")
        if "logo_filename" not in setting_columns:
            connection.execute("ALTER TABLE settings ADD COLUMN logo_filename TEXT NOT NULL DEFAULT ''")
        if not connection.execute("SELECT 1 FROM settings WHERE id=1").fetchone():
            connection.execute("INSERT INTO settings(id,teacher_name,group_name,teacher_password) VALUES(1,?,?,?)",
                               ("Docente", "Grupo", generate_password_hash("docente123")))
        default_group = connection.execute("SELECT id FROM groups ORDER BY id LIMIT 1").fetchone()
        if not default_group:
            # No crear grupos vacíos en una instalación limpia. Solo se conserva
            # el comportamiento legacy cuando ya existen estudiantes sin grupo.
            has_students = connection.execute("SELECT 1 FROM students LIMIT 1").fetchone()
            if has_students:
                group_name = connection.execute("SELECT group_name FROM settings WHERE id=1").fetchone()["group_name"]
                connection.execute("INSERT INTO groups(name) VALUES(?)", (group_name or "Grupo",))
                default_group = connection.execute("SELECT id FROM groups ORDER BY id LIMIT 1").fetchone()
        if default_group:
            connection.execute("UPDATE students SET group_id=? WHERE group_id IS NULL", (default_group["id"],))

        # Ensure teachers table and per-teacher settings
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '', password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_admin INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS teacher_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, teacher_id INTEGER NOT NULL UNIQUE,
            teacher_name TEXT NOT NULL DEFAULT 'Docente',
            group_name TEXT NOT NULL DEFAULT 'Grupo',
            evaluation_criteria TEXT NOT NULL DEFAULT '',
            school_name TEXT NOT NULL DEFAULT 'Colegio',
            logo_filename TEXT NOT NULL DEFAULT '',
            theme TEXT NOT NULL DEFAULT 'light',
            FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
        """)
        teacher_columns = {row["name"] for row in connection.execute("PRAGMA table_info(teachers)")}
        if "is_admin" not in teacher_columns:
            connection.execute("ALTER TABLE teachers ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        for column, definition in (("grade", "TEXT DEFAULT ''"), ("section", "TEXT DEFAULT ''"), ("academic_year", "INTEGER DEFAULT NULL")):
            if column not in teacher_columns:
                connection.execute(f"ALTER TABLE teachers ADD COLUMN {column} {definition}")
        for column, definition in (("first_name", "TEXT DEFAULT ''"), ("last_name", "TEXT DEFAULT ''"), ("hire_date", "TEXT DEFAULT ''")):
            if column not in teacher_columns:
                connection.execute(f"ALTER TABLE teachers ADD COLUMN {column} {definition}")
        for column, definition in (("employment_status", "TEXT NOT NULL DEFAULT 'Activo'"), ("status_start_date", "TEXT DEFAULT ''"), ("status_end_date", "TEXT DEFAULT ''"), ("reentry_date", "TEXT DEFAULT ''")):
            if column not in teacher_columns:
                connection.execute(f"ALTER TABLE teachers ADD COLUMN {column} {definition}")
        for column, definition in (("account_type", "TEXT NOT NULL DEFAULT 'Docente'"), ("teaching_level", "TEXT DEFAULT ''")):
            if column not in teacher_columns:
                connection.execute(f"ALTER TABLE teachers ADD COLUMN {column} {definition}")
        teacher_setting_columns = {row["name"] for row in connection.execute("PRAGMA table_info(teacher_settings)")}
        if "theme" not in teacher_setting_columns:
            connection.execute("ALTER TABLE teacher_settings ADD COLUMN theme TEXT NOT NULL DEFAULT 'light'")
        # Add teacher_id columns if missing
        group_columns = {row["name"] for row in connection.execute("PRAGMA table_info(groups)")}
        if "teacher_id" not in group_columns:
            connection.execute("ALTER TABLE groups ADD COLUMN teacher_id INTEGER")
        for column, definition in (("grade", "TEXT DEFAULT ''"), ("section", "TEXT DEFAULT ''"), ("academic_year", "INTEGER DEFAULT NULL")):
            if column not in group_columns:
                connection.execute(f"ALTER TABLE groups ADD COLUMN {column} {definition}")
        student_columns = {row["name"] for row in connection.execute("PRAGMA table_info(students)")}
        if "teacher_id" not in student_columns:
            connection.execute("ALTER TABLE students ADD COLUMN teacher_id INTEGER")
        for column, definition in (("conduct_score", "REAL DEFAULT NULL"), ("conduct_criteria", "TEXT DEFAULT ''"), ("conduct_incidents", "TEXT DEFAULT ''")):
            if column not in student_columns:
                connection.execute(f"ALTER TABLE students ADD COLUMN {column} {definition}")
        # If `groups` was created with a global UNIQUE(name) constraint (legacy),
        # recreate it so uniqueness is per-teacher: UNIQUE(teacher_id, name).
        row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='groups'").fetchone()
        if row:
            create_sql = (row['sql'] or '').upper()
            if 'UNIQUE' in create_sql and 'NAME' in create_sql and 'TEACHER_ID' not in create_sql:
                connection.execute("ALTER TABLE groups RENAME TO groups_old")
                connection.execute("""
                CREATE TABLE groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    teacher_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """)
                connection.execute("INSERT INTO groups(id,name,teacher_id,created_at) SELECT id,name,teacher_id,created_at FROM groups_old")
                connection.execute("DROP TABLE groups_old")
        # Ensure a per-teacher unique index on (teacher_id, name)
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_teacher_name ON groups(teacher_id,name)")
        # Create subjects, classes, teacher roles and assignments to support shared students and subjects
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            grade TEXT DEFAULT '', year INTEGER DEFAULT NULL, created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL,
            name TEXT NOT NULL, grade TEXT DEFAULT '', year INTEGER DEFAULT NULL, section TEXT DEFAULT '', group_id INTEGER,
            teacher_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS student_classes (
            student_id INTEGER NOT NULL, class_id INTEGER NOT NULL,
            PRIMARY KEY(student_id,class_id),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS teacher_roles (
            teacher_id INTEGER NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'teacher',
            FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS teacher_capabilities (
            teacher_id INTEGER NOT NULL, capability TEXT NOT NULL,
            PRIMARY KEY(teacher_id, capability),
            FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS teacher_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            previous_name TEXT NOT NULL DEFAULT '',
            new_name TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            changed_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS teacher_employment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            previous_status TEXT NOT NULL DEFAULT '',
            new_status TEXT NOT NULL,
            start_date TEXT DEFAULT '', end_date TEXT DEFAULT '', reentry_date TEXT DEFAULT '',
            reason TEXT DEFAULT '', changed_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS assignments (
            teacher_id INTEGER NOT NULL, subject_id INTEGER NOT NULL,
            PRIMARY KEY(teacher_id,subject_id),
            FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );
        """)
        class_columns = {row["name"] for row in connection.execute("PRAGMA table_info(classes)")}
        if "section" not in class_columns:
            connection.execute("ALTER TABLE classes ADD COLUMN section TEXT DEFAULT ''")
        class_columns = {row["name"] for row in connection.execute("PRAGMA table_info(classes)")}
        if "group_id" not in class_columns:
            connection.execute("ALTER TABLE classes ADD COLUMN group_id INTEGER")
        audit_columns = {row["name"] for row in connection.execute("PRAGMA table_info(grade_audit)")}
        if "actor_teacher_id" not in audit_columns:
            connection.execute("ALTER TABLE grade_audit ADD COLUMN actor_teacher_id INTEGER")
        # Migrate partial_grades to include subject_id and ensure uniqueness per (student, partial, subject)
        pg_columns = {row["name"] for row in connection.execute("PRAGMA table_info(partial_grades)")}
        if "subject_id" not in pg_columns:
            # copy existing rows
            old_rows = list(connection.execute("SELECT * FROM partial_grades"))
            connection.execute("ALTER TABLE partial_grades RENAME TO partial_grades_old")
            connection.execute("""
            CREATE TABLE partial_grades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                partial INTEGER NOT NULL CHECK(partial BETWEEN 1 AND 4),
                subject_id INTEGER,
                teacher_id INTEGER,
                work1 REAL DEFAULT 0, work2 REAL DEFAULT 0, work3 REAL DEFAULT 0, work4 REAL DEFAULT 0,
                work5 REAL DEFAULT 0, work6 REAL DEFAULT 0, exam REAL DEFAULT 0,
                exam_date TEXT DEFAULT '', recovery_type TEXT DEFAULT '', recovery_score REAL DEFAULT 0,
                recovery_date TEXT DEFAULT '', status TEXT DEFAULT 'En proceso', attendance REAL DEFAULT 0,
                comments TEXT DEFAULT '', work1_date TEXT DEFAULT '', work2_date TEXT DEFAULT '', work3_date TEXT DEFAULT '', work4_date TEXT DEFAULT '', work5_date TEXT DEFAULT '', work6_date TEXT DEFAULT '',
                UNIQUE(student_id, partial, subject_id),
                FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
            );
            """)
            for row in old_rows:
                # preserve existing columns, subject_id and teacher_id will be NULL for migrated rows
                cols = [row["student_id"], row["partial"], None, None, row["work1"], row["work2"], row["work3"], row["work4"], row.get("work5", 0), row.get("work6", 0), row.get("exam", 0), row.get("exam_date", ""), row.get("recovery_type", ""), row.get("recovery_score", 0), row.get("recovery_date", ""), row.get("status", "En proceso"), row.get("attendance", 0), row.get("comments", ""), row.get("work1_date", ""), row.get("work2_date", ""), row.get("work3_date", ""), row.get("work4_date", ""), row.get("work5_date", ""), row.get("work6_date", "")]
                connection.execute("""
                INSERT INTO partial_grades(student_id,partial,subject_id,teacher_id,work1,work2,work3,work4,work5,work6,exam,exam_date,recovery_type,recovery_score,recovery_date,status,attendance,comments,work1_date,work2_date,work3_date,work4_date,work5_date,work6_date)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, cols)
            connection.execute("DROP TABLE partial_grades_old")
        # Keep Director and Admin/Soporte as separate accounts. Older versions
        # used the first account for both roles; migrate that account to the
        # fixed Director and create a dedicated full-access support account.
        director = connection.execute(
            """SELECT t.id FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id
               WHERE r.role='director' ORDER BY t.id LIMIT 1""",
        ).fetchone()
        legacy_admin = connection.execute(
            """SELECT id FROM teachers
               WHERE is_admin=1 AND COALESCE(account_type,'') <> 'Admin / Soporte'
               ORDER BY id LIMIT 1""",
        ).fetchone()
        if not director and legacy_admin:
            director = legacy_admin
            connection.execute(
                "UPDATE teachers SET is_admin=0, account_type='Director' WHERE id=?",
                (director["id"],),
            )
            connection.execute(
                "INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'director') "
                "ON CONFLICT(teacher_id) DO UPDATE SET role='director'",
                (director["id"],),
            )

        support = connection.execute(
            """SELECT t.id FROM teachers t
               LEFT JOIN teacher_roles r ON r.teacher_id=t.id
               WHERE t.is_admin=1 OR r.role='admin_support' OR t.account_type='Admin / Soporte'
               ORDER BY t.id LIMIT 1""",
        ).fetchone()
        if not support:
            connection.execute(
                """INSERT INTO teachers(name,password,account_type,is_admin)
                   VALUES(?,?, 'Admin / Soporte', 1)""",
                ("admin", generate_password_hash("admin123")),
            )
            support = connection.execute(
                "SELECT id FROM teachers WHERE name='admin' AND is_admin=1 ORDER BY id DESC LIMIT 1",
            ).fetchone()
        else:
            connection.execute(
                "UPDATE teachers SET is_admin=1, account_type='Admin / Soporte' WHERE id=?",
                (support["id"],),
            )
        connection.execute(
            "INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'admin_support') "
            "ON CONFLICT(teacher_id) DO UPDATE SET role='admin_support'",
            (support["id"],),
        )
        if not connection.execute("SELECT 1 FROM teacher_settings WHERE teacher_id=?", (support["id"],)).fetchone():
            connection.execute("INSERT INTO teacher_settings(teacher_id,teacher_name,group_name) VALUES(?,?,?)",
                               (support["id"], "Admin / Soporte", "Grupo"))
        # Use the Director as owner for legacy records when available.
        teacher_id = (director or support)["id"]
        if not connection.execute("SELECT 1 FROM teacher_settings WHERE teacher_id=?", (teacher_id,)).fetchone():
            connection.execute("INSERT INTO teacher_settings(teacher_id,teacher_name,group_name) VALUES(?,?,?)",
                               (teacher_id, "Director", "Grupo"))
        connection.execute("""
            UPDATE teacher_roles SET role='secretary'
            WHERE teacher_id IN (
                SELECT id FROM teachers WHERE is_admin=0 AND account_type='Secretaría'
            )
        """)
        connection.execute("INSERT OR IGNORE INTO teacher_capabilities(teacher_id,capability) SELECT teacher_id,role FROM teacher_roles")
        # Assign existing groups and students to the default teacher if unset
        connection.execute("UPDATE groups SET teacher_id=? WHERE teacher_id IS NULL", (teacher_id,))
        connection.execute("UPDATE students SET teacher_id=? WHERE teacher_id IS NULL", (teacher_id,))

        # Academic architecture v2.  The legacy tables above remain temporarily
        # for route compatibility while the UI is migrated to this normalized model.
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS academic_years (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL UNIQUE,
            start_date TEXT DEFAULT '', end_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, code TEXT NOT NULL UNIQUE, level TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            academic_year_id INTEGER NOT NULL, grade_id INTEGER NOT NULL,
            name TEXT NOT NULL, shift TEXT DEFAULT '', teacher_guide_id INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(academic_year_id, grade_id, name),
            FOREIGN KEY(academic_year_id) REFERENCES academic_years(id),
            FOREIGN KEY(grade_id) REFERENCES grades(id),
            FOREIGN KEY(teacher_guide_id) REFERENCES teachers(id)
        );
        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL, academic_year_id INTEGER NOT NULL,
            section_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            enrollment_date TEXT DEFAULT '', withdrawal_date TEXT DEFAULT '',
            UNIQUE(student_id, academic_year_id),
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(academic_year_id) REFERENCES academic_years(id),
            FOREIGN KEY(section_id) REFERENCES sections(id)
        );
        CREATE TABLE IF NOT EXISTS subject_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, area TEXT DEFAULT '',
            description TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS academic_offerings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            academic_year_id INTEGER NOT NULL, grade_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL, modality TEXT DEFAULT '',
            display_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(academic_year_id, grade_id, subject_id, modality),
            FOREIGN KEY(academic_year_id) REFERENCES academic_years(id),
            FOREIGN KEY(grade_id) REFERENCES grades(id),
            FOREIGN KEY(subject_id) REFERENCES subject_catalog(id)
        );
        CREATE TABLE IF NOT EXISTS section_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL, academic_offering_id INTEGER NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(section_id, academic_offering_id),
            FOREIGN KEY(section_id) REFERENCES sections(id),
            FOREIGN KEY(academic_offering_id) REFERENCES academic_offerings(id)
        );
        CREATE TABLE IF NOT EXISTS evaluation_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            academic_year_id INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'period', display_order INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(academic_year_id, code),
            FOREIGN KEY(academic_year_id) REFERENCES academic_years(id)
        );
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enrollment_id INTEGER NOT NULL, section_subject_id INTEGER NOT NULL,
            evaluation_period_id INTEGER NOT NULL, numeric_value REAL,
            qualitative_code TEXT DEFAULT '', observations TEXT DEFAULT '',
            created_by INTEGER, updated_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(enrollment_id, section_subject_id, evaluation_period_id),
            CHECK(numeric_value IS NULL OR (numeric_value >= 0 AND numeric_value <= 100)),
            FOREIGN KEY(enrollment_id) REFERENCES enrollments(id),
            FOREIGN KEY(section_subject_id) REFERENCES section_subjects(id),
            FOREIGN KEY(evaluation_period_id) REFERENCES evaluation_periods(id)
        );
        CREATE TABLE IF NOT EXISTS final_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, enrollment_id INTEGER NOT NULL,
            section_subject_id INTEGER NOT NULL, numeric_value REAL,
            qualitative_code TEXT DEFAULT '', status TEXT DEFAULT '', observations TEXT DEFAULT '',
            UNIQUE(enrollment_id, section_subject_id),
            FOREIGN KEY(enrollment_id) REFERENCES enrollments(id),
            FOREIGN KEY(section_subject_id) REFERENCES section_subjects(id)
        );
        CREATE TABLE IF NOT EXISTS grade_change_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id INTEGER NOT NULL,
            user_id INTEGER, previous_numeric REAL, new_numeric REAL,
            previous_qualitative TEXT DEFAULT '', new_qualitative TEXT DEFAULT '',
            reason TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(assessment_id) REFERENCES assessments(id)
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, enrollment_id INTEGER NOT NULL,
            report_type TEXT NOT NULL, academic_year_id INTEGER NOT NULL,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP, generated_by INTEGER, version INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(enrollment_id) REFERENCES enrollments(id),
            FOREIGN KEY(academic_year_id) REFERENCES academic_years(id)
        );
        CREATE TABLE IF NOT EXISTS qualitative_scales (
            id INTEGER PRIMARY KEY AUTOINCREMENT, academic_year_id INTEGER,
            code TEXT NOT NULL, name TEXT NOT NULL, description TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(academic_year_id, code),
            FOREIGN KEY(academic_year_id) REFERENCES academic_years(id)
        );
        """)
        # Keep the initial catalog available, while leaving every entry fully
        # editable or deactivatable from the admin UI.
        default_subjects = [
            ('MAT', 'Matemática', 'Científica'),
            ('LL', 'Lengua y Literatura', 'Comunicativa'),
            ('CN', 'Ciencias Naturales', 'Científica'),
            ('CS', 'Ciencias Sociales', 'Social'),
            ('LE', 'Lengua Extranjera', 'Comunicativa'),
            ('EF', 'Educación Física y Práctica Deportiva', 'Desarrollo personal'),
            ('CV', 'Creciendo en Valores', 'Formación ciudadana'),
            ('AEP', 'Educación para Aprender, Emprender y Prosperar', 'Emprendimiento'),
            ('TAC', 'Talleres de Arte y Cultura', 'Arte y cultura'),
            ('CON', 'Conducta', 'Desempeño personal y ciudadano'),
        ]
        for code, name, area in default_subjects:
            connection.execute(
                'INSERT OR IGNORE INTO subject_catalog(code,name,area) VALUES(?,?,?)',
                (code, name, area),
            )


def settings():
    with db() as connection:
        teacher_id = session.get("teacher_id")
        admin_row = connection.execute("""
            SELECT ts.* FROM teacher_settings ts
            JOIN teachers t ON t.id=ts.teacher_id
            WHERE t.is_admin=1 ORDER BY t.id LIMIT 1
        """).fetchone()
        if teacher_id:
            row = connection.execute("SELECT * FROM teacher_settings WHERE teacher_id=?", (teacher_id,)).fetchone()
            if row:
                values = dict(row)
                if admin_row:
                    values["school_name"] = admin_row["school_name"]
                    values["logo_filename"] = admin_row["logo_filename"]
                    values["theme"] = admin_row["theme"]
                return values
        return admin_row or connection.execute("SELECT * FROM teacher_settings ORDER BY id LIMIT 1").fetchone()


def partial_name(partial):
    return f"Parcial {['', 'I', 'II', 'III', 'IV'][partial]}"


def qualitative_learning_label(value):
    """Equivalencia cualitativa oficial SNEPA/MINED para el aprendizaje."""
    if value is None:
        return "Sin registro"
    value = float(value)
    if value >= 90:
        return "AA"
    if value >= 76:
        return "AS"
    if value >= 60:
        return "AF"
    return "AI"


def grade_value(row):
    return round(sum(float(row[f"work{i}"] or 0) for i in range(1, 7)) + float(row["exam"] or 0), 2)


def accumulated_value(row):
    return round(sum(float(row[f"work{i}"] or 0) for i in range(1, 7)), 2)


def total_partials(partials):
    return round(sum(row["result"] for row in partials.values()), 2)


def applied_grade(row):
    accumulated = accumulated_value(row)
    original = grade_value(row)
    return round(accumulated + applied_exam(row), 2)


def applied_exam(row):
    original = float(row.get("exam", 0) or 0)
    recovery = float(row.get("recovery_score", 0) or 0)
    accumulated = accumulated_value(row)
    if row.get("recovery_type") and accumulated > 50:
        return round(max(original, min(recovery, 40)), 2)
    return round(original, 2)


def subject_summary(student_id, subject_id):
    with db() as connection:
        rows = connection.execute("SELECT * FROM partial_grades WHERE student_id=? AND subject_id=? ORDER BY partial", (student_id, subject_id)).fetchall()
    partials = {}
    for row in rows:
        item = {**dict(row), "accumulated": accumulated_value(row), "original_result": grade_value(row)}
        item["result"] = applied_grade(item)
        partials[row["partial"]] = item
    return partials, total_partials(partials)


def summary(student):
    with db() as connection:
        rows = connection.execute("SELECT * FROM partial_grades WHERE student_id=? ORDER BY subject_id, partial", (student["id"],)).fetchall()
    subjects = {}
    for row in rows:
        sid = row["subject_id"] or 0
        if sid not in subjects:
            subjects[sid] = {"partials": {}, "total": 0}
        item = {**dict(row), "accumulated": accumulated_value(row), "original_result": grade_value(row)}
        item["result"] = applied_grade(item)
        subjects[sid]["partials"][row["partial"]] = item
    # compute totals per subject and overall
    overall = 0
    for sid, data in subjects.items():
        total = sum(item["result"] for item in data["partials"].values())
        data["total"] = total
        overall += total
    return subjects, overall


def get_teacher_role(teacher_id):
    with db() as connection:
        row = connection.execute("SELECT role FROM teacher_roles WHERE teacher_id=?", (teacher_id,)).fetchone()
    return row["role"] if row else "teacher"


def teacher_has_capability(teacher_id, capability):
    if not teacher_id:
        return False
    if capability == "admin":
        return teacher_is_admin(teacher_id)
    with db() as connection:
        return bool(connection.execute("SELECT 1 FROM teacher_capabilities WHERE teacher_id=? AND capability=?", (teacher_id, capability)).fetchone())


def teacher_is_director(teacher_id=None):
    return teacher_has_capability(teacher_id or session.get("teacher_id"), "director")


def teacher_is_admin(teacher_id=None):
    teacher_id = teacher_id or session.get("teacher_id")
    if not teacher_id:
        return False
    with db() as connection:
        row = connection.execute("SELECT is_admin FROM teachers WHERE id=?", (teacher_id,)).fetchone()
    return bool(row and row["is_admin"])


def teacher_is_secretary(teacher_id=None):
    return get_teacher_role(teacher_id or session.get("teacher_id")) == "secretary"


def current_teacher_info():
    teacher_id = session.get("teacher_id")
    if not teacher_id or session.get("role") != "teacher":
        return None
    with db() as connection:
        row = connection.execute("SELECT t.name,t.email,t.is_admin,COALESCE(r.role,'teacher') AS role FROM teachers t LEFT JOIN teacher_roles r ON r.teacher_id=t.id WHERE t.id=?", (teacher_id,)).fetchone()
    if not row:
        return None
    role_label = "Admin / Soporte" if row["is_admin"] else {"director": "Director", "secretary": "Secretaría", "guide": "Docente guía", "teacher": "Docente guía"}.get(row["role"], "Docente")
    return {**dict(row), "role_label": role_label}


def is_guide_teacher(teacher_id=None):
    teacher_id = teacher_id or session.get("teacher_id")
    return bool(teacher_id and not teacher_is_admin(teacher_id) and teacher_has_capability(teacher_id, "guide"))


def teacher_has_class_access(student_id, teacher_id=None):
    teacher_id = teacher_id or session.get("teacher_id")
    if not teacher_id:
        return False
    with db() as connection:
        row = connection.execute("""
            SELECT 1 FROM student_classes sc
            JOIN classes c ON c.id=sc.class_id
            WHERE sc.student_id=? AND c.teacher_id=?
            LIMIT 1
        """, (student_id, teacher_id)).fetchone()
    return bool(row)


def teacher_scope_group_ids(teacher_id):
    with db() as connection:
        teacher = connection.execute(
            "SELECT grade,section FROM teachers WHERE id=?",
            (teacher_id,),
        ).fetchone()
        if not teacher:
            return []

        grades = {
            value.strip().lower()
            for value in (teacher["grade"] or "").split(",")
            if value.strip()
        }
        sections = {
            value.strip().upper()
            for value in (teacher["section"] or "").split(",")
            if value.strip()
        }
        primary_grades = {
            "primaria", "educación primaria", "educacion primaria",
            "1ro", "2do", "3ro", "4to", "5to", "6to",
        }
        groups = connection.execute(
            "SELECT id,grade,section,teacher_id FROM groups",
        ).fetchall()

    scoped_group_ids = []
    for group in groups:
        if group["teacher_id"] == teacher_id:
            scoped_group_ids.append(group["id"])
            continue
        group_grade = (group["grade"] or "").strip().lower()
        group_section = (group["section"] or "").strip().upper()
        matches_grade = (
            group_grade in grades
            or ("primaria" in grades and group_grade in primary_grades)
        )
        matches_section = not sections or group_section in sections
        if matches_grade and matches_section:
            scoped_group_ids.append(group["id"])
    return scoped_group_ids


def group_enrollment_class_options(group_id):
    with db() as connection:
        group = connection.execute(
            "SELECT grade, section, academic_year FROM groups WHERE id=?",
            (group_id,),
        ).fetchone()
        if not group:
            return []
        grade = (group["grade"] or "").strip()
        section = (group["section"] or "").strip().upper()
        year = group["academic_year"]
        rows = connection.execute(
            """
            SELECT DISTINCT c.id, c.name, c.grade, c.section, c.year AS academic_year,
                   s.name AS subject_name, t.name AS teacher_name
            FROM classes c
            JOIN subjects s ON s.id=c.subject_id
            LEFT JOIN teachers t ON t.id=c.teacher_id
            WHERE c.group_id=?
               OR (
                    c.year=?
                    AND c.grade=?
                    AND (? = '' OR c.section=? OR c.section IS NULL)
               )
            ORDER BY s.name, c.name
            """,
            (group_id, year, grade, section, section),
        ).fetchall()
    return rows


def teacher_can_access_student(student_id, teacher_id=None):
    teacher_id = teacher_id or session.get("teacher_id")
    if not teacher_id:
        return False
    if teacher_is_admin(teacher_id):
        return True
    if teacher_is_secretary(teacher_id):
        with db() as connection:
            return bool(connection.execute("SELECT 1 FROM students WHERE id=?", (student_id,)).fetchone())
    if get_teacher_role(teacher_id) not in ("guide", "teacher"):
        return False
    group_ids = teacher_scope_group_ids(teacher_id)
    with db() as connection:
        student = connection.execute(
            "SELECT group_id,teacher_id FROM students WHERE id=?",
            (student_id,),
        ).fetchone()
    return bool(
        student
        and (
            student["group_id"] in group_ids
            or (student["group_id"] is None and student["teacher_id"] == teacher_id)
        )
    )


def teacher_can_access_class(class_id, teacher_id=None):
    teacher_id = teacher_id or session.get("teacher_id")
    if not teacher_id:
        return False
    if teacher_is_admin(teacher_id):
        return True
    if get_teacher_role(teacher_id) == "guide":
        with db() as connection:
            row = connection.execute("""
                SELECT 1 FROM classes c JOIN groups g ON g.id=c.group_id
                WHERE c.id=? AND g.teacher_id=?
            """, (class_id, teacher_id)).fetchone()
        return bool(row)
    with db() as connection:
        row = connection.execute("SELECT teacher_id FROM classes WHERE id=?", (class_id,)).fetchone()
    return bool(row and row["teacher_id"] == teacher_id)


def get_teacher_subjects(teacher_id=None):
    teacher_id = teacher_id or session.get("teacher_id")
    if not teacher_id:
        return []
    with db() as connection:
        if teacher_is_admin(teacher_id):
            return connection.execute("""
                SELECT DISTINCT s.*
                FROM subjects s
                JOIN subject_catalog sc
                    ON sc.name=s.name COLLATE NOCASE AND sc.active=1
                ORDER BY s.name
            """).fetchall()
        if get_teacher_role(teacher_id) == "guide":
            assigned_subjects = connection.execute("""
                SELECT DISTINCT s.*
                FROM subjects s
                JOIN assignments a ON a.subject_id=s.id
                WHERE a.teacher_id=?
                ORDER BY s.name
            """, (teacher_id,)).fetchall()
            if assigned_subjects:
                return assigned_subjects
            return connection.execute("""
                SELECT DISTINCT s.*
                FROM subjects s
                JOIN classes c ON c.subject_id=s.id
                JOIN groups g ON g.id=c.group_id AND g.teacher_id=?
                ORDER BY s.name
            """, (teacher_id,)).fetchall()
        return connection.execute("""
            SELECT s.* FROM subjects s
            JOIN assignments a ON a.subject_id=s.id
            WHERE a.teacher_id=?
            ORDER BY s.name
        """, (teacher_id,)).fetchall()


def get_teacher_subjects_for_student(student_id, teacher_id=None):
    """Materias disponibles para registrar notas dentro del grupo del docente."""
    teacher_id = teacher_id or session.get("teacher_id")
    if not teacher_id:
        return []
    with db() as connection:
        if teacher_is_admin(teacher_id):
            return connection.execute("SELECT * FROM subjects ORDER BY name").fetchall()
        if teacher_is_secretary(teacher_id):
            return connection.execute("""
                SELECT DISTINCT s.*
                FROM subjects s
                WHERE EXISTS (
                    SELECT 1 FROM partial_grades pg
                    WHERE pg.subject_id=s.id AND pg.student_id=?
                ) OR EXISTS (
                    SELECT 1 FROM student_classes sc
                    JOIN classes c ON c.id=sc.class_id
                    WHERE sc.student_id=? AND c.subject_id=s.id
                )
                ORDER BY s.name
            """, (student_id, student_id)).fetchall()
        if get_teacher_role(teacher_id) in ("guide", "teacher"):
            return connection.execute("""
                SELECT DISTINCT s.*
                FROM subjects s
                WHERE EXISTS (
                    SELECT 1 FROM subject_catalog sc
                    WHERE sc.name=s.name COLLATE NOCASE AND sc.active=1
                ) OR EXISTS (
                    SELECT 1 FROM classes c
                    WHERE c.subject_id=s.id AND c.group_id=(
                        SELECT group_id FROM students WHERE id=?
                    )
                ) OR EXISTS (
                    SELECT 1 FROM partial_grades pg
                    WHERE pg.subject_id=s.id AND pg.student_id=?
                )
                ORDER BY s.name
            """, (student_id, student_id)).fetchall()
        return connection.execute("""
            SELECT DISTINCT s.*
            FROM subjects s
            JOIN classes c ON c.subject_id=s.id AND c.teacher_id=?
            JOIN student_classes sc ON sc.class_id=c.id AND sc.student_id=?
            ORDER BY s.name
        """, (teacher_id, student_id)).fetchall()


def teacher_can_access_subject_for_student(student_id, subject_id, teacher_id=None):
    teacher_id = teacher_id or session.get("teacher_id")
    if not teacher_id or not teacher_can_access_student(student_id, teacher_id):
        return False
    if teacher_is_admin(teacher_id):
        return True
    if teacher_is_secretary(teacher_id):
        return any(
            subject["id"] == subject_id
            for subject in get_teacher_subjects_for_student(student_id, teacher_id)
        )
    if get_teacher_role(teacher_id) not in ("guide", "teacher"):
        return False
    return any(
        subject["id"] == subject_id
        for subject in get_teacher_subjects_for_student(student_id, teacher_id)
    )


def teacher_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "teacher" or not session.get("teacher_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def report_access_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        teacher_id = session.get("teacher_id")
        if (session.get("role") != "teacher" or not teacher_id
                or not (teacher_is_admin(teacher_id) or is_guide_teacher(teacher_id)
                        or teacher_is_secretary(teacher_id))):
            flash("No tienes permiso para consultar o imprimir estos reportes.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def guide_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        teacher_id = session.get("teacher_id")
        if session.get("role") != "teacher" or not is_guide_teacher(teacher_id):
            flash("Acceso restringido al docente guía.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def academic_view_required(view):
    """Permite consultar información académica a cualquier cuenta docente."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "teacher" or not session.get("teacher_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        teacher_id = session.get("teacher_id")
        if session.get("role") != "teacher" or not teacher_is_admin(teacher_id):
            flash("Solo el administrador puede gestionar las cuentas docentes.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def director_or_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        teacher_id = session.get("teacher_id")
        if session.get("role") != "teacher" or not (teacher_is_admin(teacher_id) or teacher_is_director(teacher_id)):
            flash("Solo el administrador o el director pueden gestionar la estructura académica.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def create_database_backup(label="manual"):
    backup_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(backup_dir, f"notas-{label}-{stamp}.db")
    if os.path.isfile(DB_PATH):
        shutil.copy2(DB_PATH, backup_path)
    return backup_path


def reset_academic_data():
    with db() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        admin = connection.execute(
            "SELECT * FROM teachers WHERE is_admin=1 OR account_type='Admin / Soporte' ORDER BY is_admin DESC,id LIMIT 1",
        ).fetchone()
        if not admin:
            connection.execute("INSERT INTO teachers(name,email,password,is_admin) VALUES(?,?,?,1)", ("admin", "", generate_password_hash("admin123")))
            admin = connection.execute("SELECT * FROM teachers WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
        admin_id = admin["id"]
        for table in (
            "student_classes", "partial_grades", "grade_audit", "grade_change_audit",
            "grades", "final_results", "assessments", "reports", "enrollments",
            "assignments", "section_subjects", "classes", "students", "groups",
            "academic_offerings", "sections", "academic_years", "evaluation_periods",
            "qualitative_scales", "subjects", "subject_catalog",
        ):
            connection.execute(f"DELETE FROM {table}")
        connection.execute("DELETE FROM teacher_capabilities")
        connection.execute("DELETE FROM teacher_employment_history")
        connection.execute("DELETE FROM teacher_history")
        connection.execute("DELETE FROM teacher_settings WHERE teacher_id<>?", (admin_id,))
        connection.execute("DELETE FROM teacher_roles WHERE teacher_id<>?", (admin_id,))
        connection.execute("DELETE FROM teachers WHERE id<>?", (admin_id,))
        connection.execute("DELETE FROM sqlite_sequence")
        connection.execute("UPDATE teachers SET is_admin=1,account_type='Admin / Soporte' WHERE id=?", (admin_id,))
        connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'admin_support') ON CONFLICT(teacher_id) DO UPDATE SET role='admin_support'", (admin_id,))
        connection.execute("INSERT OR IGNORE INTO teacher_capabilities(teacher_id,capability) VALUES(?, 'admin_support')", (admin_id,))
        connection.execute("UPDATE teacher_settings SET teacher_name=?,group_name='Grupo',evaluation_criteria='',school_name='Colegio',logo_filename='' WHERE teacher_id=?", (admin["name"], admin_id))
        if not connection.execute("SELECT 1 FROM teacher_settings WHERE teacher_id=?", (admin_id,)).fetchone():
            connection.execute("INSERT INTO teacher_settings(teacher_id,teacher_name,group_name) VALUES(?,?,?)", (admin_id, admin["name"], "Grupo"))
        connection.execute("PRAGMA foreign_keys=ON")


def setup_level():
    """Nivel del asistente. Las cuentas deben quedar completas antes de lo académico."""
    with db() as connection:
        guides = connection.execute("SELECT COUNT(*) AS n FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id WHERE t.is_admin=0 AND r.role='guide'").fetchone()["n"]
        groups = connection.execute("SELECT COUNT(*) AS n FROM groups").fetchone()["n"]
        active_catalog_subjects = connection.execute("SELECT COUNT(*) AS n FROM subject_catalog WHERE active=1").fetchone()["n"]
        legacy_subjects = connection.execute("SELECT COUNT(*) AS n FROM subjects").fetchone()["n"]
        subjects = max(active_catalog_subjects, legacy_subjects)
        classes = connection.execute("SELECT COUNT(*) AS n FROM classes").fetchone()["n"]
        students = connection.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
    if guides == 0:
        return 0
    if groups == 0 or subjects == 0:
        return 1
    if classes == 0:
        return 2
    if students == 0:
        return 3
    return 4


def setup_required(level):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if teacher_is_admin(session.get("teacher_id")):
                return view(*args, **kwargs)
            current = setup_level()
            if current < level:
                destinations = {1: "teachers_view", 2: "groups", 3: "groups", 4: "groups"}
                flash("Completa primero el paso anterior del asistente para evitar datos incompletos.", "error")
                return redirect(url_for(destinations[level]))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def workflow_required(*allowed_levels):
    """Permite únicamente el menú correspondiente a la etapa actual."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if teacher_is_admin(session.get("teacher_id")):
                return view(*args, **kwargs)
            current = setup_level()
            if current != 4 and current not in allowed_levels:
                destinations = {0: "teachers_view", 1: "groups", 2: "classes_view", 3: "groups"}
                flash("Ese menú está bloqueado hasta completar la etapa actual.", "error")
                return redirect(url_for(destinations[current]))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def onboarding_accounts_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if setup_level() == 0:
            if request.args.get("onboarding") == "1":
                session["accounts_onboarding_access"] = True
            elif not session.get("accounts_onboarding_access"):
                flash("Accede a Docentes y cuentas desde el primer pendiente del checklist.", "error")
                return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped



@app.context_processor
def common():
    return {"partial_name": partial_name, "app_settings": settings(), "applied_exam": applied_exam, "get_teacher_role": get_teacher_role, "teacher_is_admin": teacher_is_admin, "get_workflow_level": setup_level, "current_teacher": current_teacher_info()}


@app.get("/login")
def login():
    if session.get("role") == "teacher":
        return redirect(url_for("index"))
    return render_template("login.html")


@app.get("/help")
@teacher_required
def help_view():
    return render_template("help.html")


@app.post("/login")
def login_post():
    role = request.form.get("role")
    password = request.form.get("password", "")
    if role == "teacher":
        identifier = request.form.get("identifier", "").strip()
        with db() as connection:
            teacher = None
            if identifier:
                teacher = connection.execute("SELECT * FROM teachers WHERE email=? OR name=?", (identifier, identifier)).fetchone()
                if teacher and check_password_hash(teacher["password"], password):
                    session.clear(); session["role"] = "teacher"; session["teacher_id"] = teacher["id"]
                    return redirect(url_for("index"))
        flash("Credenciales del docente incorrectas.", "error")
    else:
        flash("El acceso está disponible únicamente para docentes.", "error")
    return redirect(url_for("login"))


@app.route("/reset-admin-password", methods=["GET", "POST"])
def reset_admin_password_public():
    if request.method == "POST":
        if request.form.get("confirmation", "").strip().upper() != "RESTABLECER ADMIN":
            flash("Escribe RESTABLECER ADMIN para confirmar la recuperación.", "error")
            return redirect(url_for("reset_admin_password_public"))
        with db() as connection:
            connection.execute("UPDATE teachers SET password=? WHERE is_admin=1", (generate_password_hash("admin123"),))
        flash("La clave de admin fue restaurada a: admin123. Inicia sesión como admin.", "success")
        return redirect(url_for("login"))
    return render_template("reset_admin_password.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@teacher_required
def index():
    teacher_id = session.get("teacher_id")
    is_admin = teacher_is_admin(teacher_id)
    is_guide = is_guide_teacher(teacher_id)
    setup = None
    group_summary = []
    teacher_summary = []
    with db() as connection:
        if is_admin:
            students = connection.execute("SELECT s.*, g.name AS group_name FROM students s LEFT JOIN groups g ON g.id=s.group_id WHERE s.teacher_id=? OR g.teacher_id=? ORDER BY s.name", (teacher_id, teacher_id)).fetchall()
            count = connection.execute("SELECT COUNT(*) AS n FROM partial_grades").fetchone()["n"]
            group_summary = connection.execute("""
                SELECT g.id,g.name,COUNT(DISTINCT s.id) AS students,COUNT(DISTINCT c.id) AS classes
                FROM groups g LEFT JOIN students s ON s.group_id=g.id LEFT JOIN classes c ON c.group_id=g.id
                GROUP BY g.id ORDER BY g.name
            """).fetchall()
            teacher_summary = connection.execute("""
                SELECT t.id,t.name,t.email,r.role,
                       COUNT(DISTINCT c.id) AS classes,
                       GROUP_CONCAT(DISTINCT s.name) AS subjects
                FROM teachers t
                JOIN teacher_roles r ON r.teacher_id=t.id AND r.role='teacher'
                LEFT JOIN classes c ON c.teacher_id=t.id
                LEFT JOIN subjects s ON s.id=c.subject_id
                WHERE t.id<>? GROUP BY t.id ORDER BY t.name
            """, (teacher_id,)).fetchall()
        elif is_guide:
            students = connection.execute("""
                SELECT DISTINCT s.*, g.name AS group_name
                FROM students s LEFT JOIN groups g ON g.id=s.group_id
                WHERE g.teacher_id=? OR (s.group_id IS NULL AND s.teacher_id=?) ORDER BY s.name
            """, (teacher_id, teacher_id)).fetchall()
            group_summary = connection.execute("""
                SELECT g.id,g.name,COUNT(DISTINCT s.id) AS students,COUNT(DISTINCT c.id) AS classes
                FROM groups g
                LEFT JOIN students s ON s.group_id=g.id
                LEFT JOIN classes c ON c.group_id=g.id
                WHERE g.teacher_id=?
                GROUP BY g.id ORDER BY g.name
            """, (teacher_id,)).fetchall()
            count = connection.execute("""
                SELECT COUNT(DISTINCT pg.id) AS n FROM partial_grades pg
                JOIN students s ON s.id=pg.student_id
                LEFT JOIN groups g ON g.id=s.group_id
                WHERE g.teacher_id=? OR (s.group_id IS NULL AND s.teacher_id=?)
            """, (teacher_id, teacher_id)).fetchone()["n"]
        else:
            students = connection.execute("""
                SELECT DISTINCT s.*, g.name AS group_name
                FROM students s
                LEFT JOIN groups g ON g.id=s.group_id
                LEFT JOIN student_classes sc ON sc.student_id=s.id
                LEFT JOIN classes c ON c.id=sc.class_id
                WHERE s.teacher_id=? OR c.teacher_id=?
                ORDER BY s.name
            """, (teacher_id, teacher_id)).fetchall()
            count = connection.execute("""
                SELECT COUNT(*) AS n
                FROM partial_grades pg
                JOIN students s ON s.id=pg.student_id
                LEFT JOIN student_classes sc ON sc.student_id=s.id
                LEFT JOIN classes c ON c.id=sc.class_id
                WHERE s.teacher_id=? OR c.teacher_id=?
            """, (teacher_id, teacher_id)).fetchone()["n"]
    summaries = [(student, summary(student)[1]) for student in students]
    values = [final for _, final in summaries if final is not None]
    if teacher_is_secretary(teacher_id):
        with db() as connection:
            students = connection.execute("""
                SELECT s.*, g.name AS group_name
                FROM students s LEFT JOIN groups g ON g.id=s.group_id
                ORDER BY g.name, s.name
            """).fetchall()
            count = connection.execute("SELECT COUNT(*) AS n FROM partial_grades").fetchone()["n"]
        summaries = [(student, summary(student)[1]) for student in students]
        values = [final for _, final in summaries if final is not None]
    return render_template("dashboard.html", students=students, summaries=summaries,
                           average=round(sum(values) / len(values), 2) if values else 0, grade_count=count,
                           is_guide=is_guide, setup=setup, group_summary=group_summary,
                           teacher_summary=teacher_summary, is_admin=teacher_is_admin(teacher_id),
                           is_secretary=teacher_is_secretary(teacher_id))


@app.route("/groups", methods=["GET", "POST"])
@teacher_required
@workflow_required(0, 1, 2, 3)
def groups():
    teacher_id = session.get("teacher_id")
    if not (is_guide_teacher(teacher_id) or teacher_is_admin(teacher_id)):
        flash("Solo el administrador o el docente guía pueden consultar estos grupos.", "error")
        return redirect(url_for("index"))
    if request.method == "POST":
        if not is_guide_teacher(teacher_id) and not teacher_is_admin(teacher_id):
            flash("Solo el administrador o el docente guía pueden gestionar esta información.", "error")
            return redirect(url_for("groups"))
        if request.form.get("action") == "update_context":
            if not teacher_is_admin(teacher_id):
                flash("Solo el director puede organizar los grupos.", "error")
                return redirect(url_for("groups"))
            group_id = request.form.get("group_id", type=int)
            grade = request.form.get("grade", "").strip()
            section = request.form.get("section", "").strip().upper()
            academic_year = request.form.get("academic_year", type=int)
            with db() as connection:
                connection.execute("UPDATE groups SET grade=?,section=?,academic_year=? WHERE id=?", (grade, section, academic_year, group_id))
            flash("Datos académicos del grupo actualizados.", "success")
            return redirect(url_for("groups"))
        action = request.form.get("action")
        if action in ("add_student", "update_student"):
            group_id = request.form.get("group_id", type=int)
            code = request.form.get("code", "").strip()
            name = request.form.get("student_name", "").strip()
            section = request.form.get("section", "").strip().upper()
            class_ids = [int(value) for value in request.form.getlist("class_id") if value.isdigit()]
            student_id = request.form.get("student_id", type=int)
            if not group_id or not code or not name or (action == "update_student" and not student_id):
                flash("Grupo, código y nombre del estudiante son obligatorios.", "error")
                return redirect(url_for("groups"))
            try:
                sync_approved_subjects()
                default_class_ids = ensure_group_subject_classes(group_id)
                if not class_ids:
                    class_ids = default_class_ids
                with db() as connection:
                    valid_group = connection.execute(
                        "SELECT 1 FROM groups WHERE id=? AND teacher_id=?",
                        (group_id, teacher_id),
                    ).fetchone()
                    if not valid_group:
                        flash("El grupo no existe o no pertenece al docente guía.", "error")
                        return redirect(url_for("groups"))
                    duplicate_code = connection.execute(
                        """
                        SELECT 1 FROM students
                        WHERE code=? COLLATE NOCASE AND (? IS NULL OR id<>?)
                        """,
                        (code, student_id, student_id),
                    ).fetchone()
                    if duplicate_code:
                        flash("Ese código ya está registrado. Cada estudiante debe tener un código único.", "error")
                        return redirect(url_for("groups"))
                    if class_ids:
                        group = connection.execute(
                            "SELECT grade, section, academic_year FROM groups WHERE id=?",
                            (group_id,),
                        ).fetchone()
                        if not group:
                            flash("El grupo no existe o no pertenece al docente guía.", "error")
                            return redirect(url_for("groups"))
                        placeholders = ",".join("?" for _ in class_ids)
                        valid_classes = connection.execute(
                            f"""
                            SELECT COUNT(DISTINCT c.id) AS n
                            FROM classes c
                            JOIN teacher_roles tr ON tr.teacher_id=c.teacher_id AND tr.role IN ('teacher','guide')
                            WHERE c.id IN ({placeholders})
                              AND (
                                  c.group_id=?
                                  OR (
                                      c.year=?
                                      AND c.grade=?
                                      AND (? = '' OR c.section=? OR c.section IS NULL)
                                  )
                              )
                            """,
                            (*class_ids, group_id, group["academic_year"], group["grade"] or "", group["section"] or "", group["section"] or ""),
                        ).fetchone()["n"]
                        if valid_classes != len(set(class_ids)):
                            flash("Una o más materias no pertenecen al grupo ni a su nivel académico o docente asignado.", "error")
                            return redirect(url_for("groups"))
                    if action == "update_student":
                        belongs_to_group = connection.execute(
                            "SELECT 1 FROM students WHERE id=? AND group_id=? AND enrollment_status='active'",
                            (student_id, group_id),
                        ).fetchone()
                        if not belongs_to_group:
                            flash("El estudiante no pertenece a este grupo.", "error")
                            return redirect(url_for("groups"))
                        connection.execute(
                            "UPDATE students SET code=?,name=?,section=? WHERE id=?",
                            (code, name, section, student_id),
                        )
                        connection.execute(
                            "DELETE FROM student_classes WHERE student_id=?",
                            (student_id,),
                        )
                    else:
                        connection.execute(
                            "INSERT INTO students(code,name,section,group_id,teacher_id) VALUES(?,?,?,?,?)",
                            (code, name, section, group_id, teacher_id),
                        )
                        student_id = connection.execute(
                            "SELECT last_insert_rowid() AS id",
                        ).fetchone()["id"]
                    for class_id in class_ids:
                        connection.execute("""
                            INSERT OR IGNORE INTO student_classes(student_id,class_id)
                            SELECT ?,c.id FROM classes c
                            JOIN teachers t ON t.id=c.teacher_id
                            JOIN teacher_roles tr ON tr.teacher_id=t.id AND tr.role IN ('teacher','guide')
                            WHERE c.id=? AND c.group_id=?
                        """, (student_id, class_id, group_id))
                if action == "update_student":
                    flash("Matrícula actualizada correctamente.", "success")
                else:
                    flash("Matrícula confirmada. El código del estudiante es único.", "success")
            except sqlite3.IntegrityError:
                flash("Ese código ya está registrado. Cada estudiante debe tener un código único.", "error")
            return redirect(url_for("groups"))
        if setup_level() not in (1, 2, 3, 4):
            flash("La creación de grupos solo está disponible en la etapa de grupos y materias.", "error")
            return redirect(url_for("groups"))
        # Admin may create groups for any guide; a guide may create one for
        # their own matrícula workspace.
        name = request.form.get("name", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        hire_date = request.form.get("hire_date", "").strip()
        employment_status = request.form.get("employment_status", "Activo").strip() or "Activo"
        status_start_date = request.form.get("status_start_date", hire_date).strip()
        status_end_date = request.form.get("status_end_date", "").strip()
        reentry_date = request.form.get("reentry_date", "").strip()
        employment_reason = request.form.get("employment_reason", "").strip()
        grade = request.form.get("grade", "").strip()
        section = request.form.get("section", "").strip().upper()
        academic_year = request.form.get("academic_year", type=int)
        guide_id = request.form.get("guide_id", type=int)
        if is_guide_teacher(teacher_id):
            guide_id = teacher_id
        if not name:
            flash("Escribe un nombre para el grupo.", "error")
        else:
            try:
                with db() as connection:
                    guide = connection.execute("SELECT id FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id WHERE t.id=? AND t.is_admin=0 AND r.role='guide'", (guide_id,)).fetchone() if guide_id else None
                    if guide_id and not guide:
                        flash("El docente guía seleccionado no es válido.", "error")
                        return redirect(url_for("groups"))
                    connection.execute("INSERT INTO groups(name,grade,section,academic_year,teacher_id) VALUES(?,?,?,?,?)", (name, grade, section, academic_year, guide_id))
                    new_group_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                sync_approved_subjects()
                ensure_group_subject_classes(new_group_id)
                flash("Grupo creado correctamente.", "success")
            except sqlite3.IntegrityError:
                flash("Ese grupo ya existe.", "error")
            except sqlite3.Error as error:
                flash(f"No se pudo crear el grupo: {error}", "error")
        return redirect(url_for("groups"))
    sync_approved_subjects()
    with db() as connection:
        if teacher_is_admin(teacher_id):
            group_rows = connection.execute("SELECT g.*, COUNT(s.id) AS student_count FROM groups g LEFT JOIN students s ON s.group_id=g.id AND s.enrollment_status='active' GROUP BY g.id ORDER BY g.name").fetchall()
        else:
            group_rows = connection.execute("SELECT g.*, COUNT(s.id) AS student_count FROM groups g LEFT JOIN students s ON s.group_id=g.id AND s.enrollment_status='active' WHERE g.teacher_id=? GROUP BY g.id ORDER BY g.name", (teacher_id,)).fetchall()
        for group in group_rows:
            ensure_group_subject_classes(group["id"])
        group_data = []
        for group in group_rows:
            classes = group_enrollment_class_options(group["id"])
            students = connection.execute("""
                SELECT s.id,s.code,s.name,s.section,
                       GROUP_CONCAT(DISTINCT sc.class_id) AS enrolled_class_ids,
                       COALESCE(pg.grade_records,0) AS grade_records,
                       COALESCE(pg.pending_grade_records,0) AS pending_grade_records
                FROM students s
                LEFT JOIN student_classes sc ON sc.student_id=s.id
                LEFT JOIN (
                    SELECT student_id,COUNT(*) AS grade_records,
                           SUM(CASE WHEN COALESCE(status,'En proceso') NOT IN ('Entregado','Cerrado')
                                    THEN 1 ELSE 0 END) AS pending_grade_records
                    FROM partial_grades GROUP BY student_id
                ) pg ON pg.student_id=s.id
                WHERE s.group_id=? AND s.enrollment_status='active'
                GROUP BY s.id ORDER BY s.name
            """, (group["id"],)).fetchall()
            group_data.append({"group": group, "classes": classes, "students": students})
        subjects = connection.execute("""
            SELECT s.id,s.name,s.grade,s.year FROM subjects s
            WHERE NOT EXISTS (
                SELECT 1 FROM subject_catalog sc
                WHERE sc.active=0 AND sc.name=s.name COLLATE NOCASE
            )
            ORDER BY s.name,s.grade
        """).fetchall()
        teachers = connection.execute("""
            SELECT t.id,t.name,t.grade FROM teachers t
            JOIN teacher_roles tr ON tr.teacher_id=t.id AND tr.role IN ('teacher','guide')
            ORDER BY t.name
        """).fetchall()
        guides = connection.execute("""
            SELECT t.id,t.name FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id
            WHERE t.is_admin=0 AND r.role='guide' ORDER BY t.name
        """).fetchall()
    return render_template("groups.html", groups=group_data, subjects=subjects, teachers=teachers, guides=guides, workflow_level=setup_level(), can_manage=is_guide_teacher(teacher_id), is_admin=teacher_is_admin(teacher_id), read_only=teacher_is_admin(teacher_id))


@app.post("/groups/<int:group_id>/delete")
@admin_required
def delete_group(group_id):
    with db() as connection:
        teacher_id = session.get("teacher_id")
        count = connection.execute("SELECT COUNT(*) AS n FROM students WHERE group_id=?", (group_id,)).fetchone()["n"]
        classes = connection.execute("SELECT COUNT(*) AS n FROM classes WHERE group_id=?", (group_id,)).fetchone()["n"]
        if count or classes:
            flash("No se puede eliminar un grupo con estudiantes o materias asignadas.", "error")
        else:
            create_database_backup("antes-de-eliminar-grupo")
            connection.execute("DELETE FROM groups WHERE id=? AND teacher_id=?", (group_id, teacher_id))
            flash("Grupo eliminado.", "success")
    return redirect(url_for("groups"))


@app.route("/subjects", methods=["GET", "POST"])
@director_or_admin_required
@workflow_required(1)
def subjects_view():
    if teacher_is_admin(session.get('teacher_id')):
        return redirect(url_for('subject_catalog'))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        grade = request.form.get("grade", "").strip()
        year = request.form.get("year", type=int)
        if not name:
            flash("El nombre de la materia no puede estar vacío.", "error")
        else:
            with db() as connection:
                try:
                    connection.execute("INSERT INTO subjects(name,grade,year,created_by) VALUES(?,?,?,?)", (name, grade, year, session.get("teacher_id")))
                    flash("Materia creada correctamente.", "success")
                except sqlite3.IntegrityError:
                    flash("No se pudo crear la materia.", "error")
        return redirect(url_for("subjects_view"))
    with db() as connection:
        rows = connection.execute("SELECT s.*, t.name AS created_by_name FROM subjects s LEFT JOIN teachers t ON t.id=s.created_by ORDER BY s.name, s.grade, s.year").fetchall()
    return render_template("subjects.html", subjects=rows)


@app.route("/classes", methods=["GET", "POST"])
@director_or_admin_required
@workflow_required(2, 3)
def classes_view():
    teacher_id = session.get("teacher_id")
    if teacher_is_admin(teacher_id):
        sync_approved_subjects()
    available_subject_ids = {subject["id"] for subject in get_teacher_subjects(teacher_id)}
    with db() as connection:
        subjects = get_teacher_subjects(teacher_id)
        if teacher_is_admin(teacher_id) or get_teacher_role(teacher_id) == "guide":
            classes = connection.execute("SELECT c.*, s.name AS subject_name, t.name AS teacher_name, g.name AS group_name FROM classes c LEFT JOIN subjects s ON s.id=c.subject_id LEFT JOIN teachers t ON t.id=c.teacher_id LEFT JOIN groups g ON g.id=c.group_id ORDER BY g.name,c.name").fetchall()
        else:
            classes = connection.execute("SELECT c.*, s.name AS subject_name FROM classes c LEFT JOIN subjects s ON s.id=c.subject_id WHERE c.teacher_id=? ORDER BY c.name", (teacher_id,)).fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        subject_id = request.form.get("subject_id", type=int)
        assigned_teacher_id = request.form.get("teacher_id", type=int)
        group_id = request.form.get("group_id", type=int)
        grade = request.form.get("grade", "").strip()
        year = request.form.get("year", type=int)
        if not name or not subject_id or not assigned_teacher_id or not group_id:
            flash("Grupo, nombre, materia y docente son obligatorios para la clase.", "error")
            return redirect(url_for("classes_view"))
        if subject_id not in available_subject_ids:
            flash("La materia no está aprobada o disponible para crear clases.", "error")
            return redirect(url_for("classes_view"))
        with db() as connection:
            try:
                valid = connection.execute("""
                    SELECT t.id,t.name,t.grade,t.section,tr.role,
                           EXISTS(SELECT 1 FROM assignments a WHERE a.teacher_id=t.id) AS has_assignments,
                           EXISTS(SELECT 1 FROM assignments a WHERE a.teacher_id=t.id AND a.subject_id=?) AS subject_assigned
                    FROM teachers t
                    JOIN teacher_roles tr ON tr.teacher_id=t.id AND tr.role IN ('teacher','guide')
                    WHERE t.id=?
                """, (subject_id, assigned_teacher_id)).fetchone()
                if not valid:
                    flash("El docente seleccionado no existe.", "error")
                    return redirect(url_for("classes_view"))
                if valid["role"] == "guide" and valid["has_assignments"] and not valid["subject_assigned"]:
                    flash(f"{valid['name']} no tiene asignada la materia seleccionada.", "error")
                    return redirect(url_for("classes_view"))
                valid_group = connection.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone()
                if not valid_group:
                    flash("El grupo seleccionado no existe.", "error")
                    return redirect(url_for("classes_view"))
                group_context = connection.execute("SELECT grade,section,academic_year,name FROM groups WHERE id=?", (group_id,)).fetchone()
                allowed_grades = {item.strip().lower() for item in (valid["grade"] or "").split(",") if item.strip()}
                group_grade = (group_context["grade"] or "").strip().lower() if group_context else ""
                if group_grade and allowed_grades and group_grade not in allowed_grades:
                    flash(f"{valid['name']} no está autorizado para impartir {group_context['grade']}.", "error")
                    return redirect(url_for("classes_view"))
                allowed_sections = {item.strip().upper() for item in (valid["section"] or "").split(",") if item.strip()}
                group_section = (group_context["section"] or "").strip().upper() if group_context else ""
                if group_section and allowed_sections and "LIBRE" not in allowed_sections and group_section not in allowed_sections:
                    flash(f"{valid['name']} no está autorizado para la sección {group_context['section']}.", "error")
                    return redirect(url_for("classes_view"))
                subject_context = connection.execute("SELECT grade,year FROM subjects WHERE id=?", (subject_id,)).fetchone()
                grade = (subject_context["grade"] if subject_context and subject_context["grade"] else group_context["grade"] or group_context["name"]) if group_context else grade
                year = (subject_context["year"] if subject_context and subject_context["year"] else group_context["academic_year"]) if group_context else year
                section = group_context["section"] if group_context else ""
                connection.execute("INSERT INTO classes(name,subject_id,grade,year,section,group_id,teacher_id) VALUES(?,?,?,?,?,?,?)", (name, subject_id, grade, year, section, group_id, assigned_teacher_id))
                flash("Clase creada correctamente.", "success")
            except sqlite3.IntegrityError:
                flash("No se pudo crear la clase.", "error")
        return redirect(url_for("classes_view"))
    with db() as connection:
        teachers = connection.execute("""
            SELECT t.id,t.name FROM teachers t
            JOIN teacher_roles tr ON tr.teacher_id=t.id
            WHERE tr.role='teacher' OR (
                tr.role='guide' AND EXISTS (
                    SELECT 1 FROM assignments a WHERE a.teacher_id=t.id
                )
            )
            ORDER BY t.name
        """).fetchall()
        groups_for_class = connection.execute("SELECT id,name FROM groups ORDER BY name").fetchall()
    return render_template("classes.html", classes=classes, subjects=subjects, teachers=teachers, groups=groups_for_class)


@app.post("/classes/<int:class_id>/delete")
@admin_required
def delete_class(class_id):
    teacher_id = session.get("teacher_id")
    if not teacher_can_access_class(class_id, teacher_id):
        flash("No puedes eliminar esta clase.", "error")
        return redirect(url_for("classes_view"))
    create_database_backup("antes-de-eliminar-clase")
    with db() as connection:
        connection.execute("DELETE FROM classes WHERE id=?", (class_id,))
    flash("Clase eliminada.", "success")
    return redirect(url_for("classes_view"))


@app.route("/assignments", methods=["GET", "POST"])
@director_or_admin_required
def assignments_view():
    if request.method == "POST":
        teacher_id = request.form.get("teacher_id", type=int)
        subject_ids = list(dict.fromkeys(
            int(value) for value in request.form.getlist("subject_id") if value.isdigit()
        ))
        if not teacher_id:
            flash("Selecciona un docente guía.", "error")
            return redirect(url_for("assignments_view"))
        with db() as connection:
            guide = connection.execute("""
                SELECT 1 FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id
                WHERE t.id=? AND t.is_admin=0 AND r.role='guide'
            """, (teacher_id,)).fetchone()
            if not guide:
                flash("Solo se pueden asignar materias a docentes guía.", "error")
                return redirect(url_for("assignments_view"))
            if subject_ids:
                placeholders = ",".join("?" for _ in subject_ids)
                valid_ids = {
                    row["id"] for row in connection.execute(f"""
                        SELECT s.id FROM subjects s
                        JOIN subject_catalog sc ON sc.name=s.name COLLATE NOCASE AND sc.active=1
                        WHERE s.id IN ({placeholders})
                    """, subject_ids).fetchall()
                }
                if valid_ids != set(subject_ids):
                    flash("La selección contiene materias inactivas o inválidas.", "error")
                    return redirect(url_for("assignments_view"))
            connection.execute("DELETE FROM assignments WHERE teacher_id=?", (teacher_id,))
            connection.executemany(
                "INSERT INTO assignments(teacher_id,subject_id) VALUES(?,?)",
                [(teacher_id, subject_id) for subject_id in subject_ids],
            )
        flash("Materias asignadas al docente guía.", "success")
        return redirect(url_for("assignments_view"))
    with db() as connection:
        assignments = connection.execute("SELECT a.teacher_id, a.subject_id, t.name AS teacher_name, s.name AS subject_name FROM assignments a JOIN teachers t ON t.id=a.teacher_id JOIN subjects s ON s.id=a.subject_id ORDER BY t.name, s.name").fetchall()
        teachers = connection.execute("""
            SELECT t.* FROM teachers t
            JOIN teacher_roles tr ON tr.teacher_id=t.id AND tr.role='guide'
            ORDER BY t.name
        """).fetchall()
        teacher_assignments = {}
        for row in connection.execute(
            "SELECT teacher_id,subject_id FROM assignments ORDER BY teacher_id,subject_id",
        ).fetchall():
            teacher_assignments.setdefault(str(row["teacher_id"]), []).append(row["subject_id"])
        subjects = connection.execute("""
            SELECT s.* FROM subjects s
            JOIN subject_catalog sc ON sc.name=s.name COLLATE NOCASE AND sc.active=1
            ORDER BY s.name
        """).fetchall()
    return render_template("assignments.html", assignments=assignments, teachers=teachers, subjects=subjects, teacher_assignments=teacher_assignments)


@app.post("/assignments/<int:teacher_id>/<int:subject_id>/delete")
@director_or_admin_required
def delete_assignment(teacher_id, subject_id):
    with db() as connection:
        connection.execute("DELETE FROM assignments WHERE teacher_id=? AND subject_id=?", (teacher_id, subject_id))
    flash("Materia desasignada. Si el docente guía aún tiene otras materias asignadas, no podrá registrar notas en esta.", "success")
    return redirect(url_for("assignments_view"))


@app.route("/students", methods=["GET", "POST"])
@teacher_required
@workflow_required(3)
def students():
    teacher_id = session.get("teacher_id")
    if request.method == "POST":
        if not (teacher_is_admin(teacher_id) or teacher_is_director(teacher_id)):
            flash("Solo el director o administrador puede registrar estudiantes.", "error")
            return redirect(url_for("students"))
        data = {key: request.form.get(key, "").strip() for key in ("code", "name", "subject", "section")}
        group_id = request.form.get("group_id", type=int)
        class_ids = [int(value) for value in request.form.getlist("class_id") if value.isdigit()]
        if not data["code"] or not data["name"]:
            flash("Código y nombre son obligatorios.", "error")
        else:
            try:
                with db() as connection:
                    connection.execute("INSERT INTO students(code,name,subject,section,group_id,teacher_id) VALUES(?,?,?,?,?,?)", (*data.values(), group_id, teacher_id))
                    student_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                    for class_id in class_ids:
                        connection.execute("""
                            INSERT OR IGNORE INTO student_classes(student_id,class_id)
                            SELECT ?,c.id FROM classes c
                            JOIN teachers t ON t.id=c.teacher_id
                            JOIN teacher_roles tr ON tr.teacher_id=t.id AND tr.role='teacher'
                            WHERE c.id=? AND c.group_id=?
                        """, (student_id, class_id, group_id))
                flash("Estudiante registrado.", "success")
                return redirect(url_for("students"))
            except sqlite3.IntegrityError:
                flash("Ese código ya existe.", "error")
    search = request.args.get("q", "").strip()
    subject_search = request.args.get("subject", "").strip()
    record_filter = request.args.get("records", "").strip()
    status_filter = request.args.get("status", "active").strip()
    if status_filter not in ("active", "withdrawn", "all"):
        status_filter = "active"
    filter_group = request.args.get("group_id", type=int)
    is_guide = is_guide_teacher(teacher_id)
    is_admin = teacher_is_admin(teacher_id)
    is_secretary = teacher_is_secretary(teacher_id)
    can_withdraw = is_guide or is_admin or teacher_is_director(teacher_id)
    with db() as connection:
        if is_admin or is_secretary:
            query = """SELECT s.*, g.name AS group_name, MIN(sc.class_id) AS class_id,
                GROUP_CONCAT(DISTINCT c.name) AS class_name,
                GROUP_CONCAT(DISTINCT subj.name) AS enrolled_subjects,
                GROUP_CONCAT(DISTINCT sc.class_id) AS enrolled_class_ids,
                COUNT(DISTINCT pg.id) AS grade_records
                FROM students s LEFT JOIN groups g ON g.id=s.group_id
                LEFT JOIN student_classes sc ON sc.student_id=s.id
                LEFT JOIN classes c ON c.id=sc.class_id
                LEFT JOIN subjects subj ON subj.id=c.subject_id
                LEFT JOIN partial_grades pg ON pg.student_id=s.id WHERE 1=1"""
            params = []
        elif is_guide:
            query = """
                SELECT s.*, g.name AS group_name, MIN(sc.class_id) AS class_id,
                       GROUP_CONCAT(DISTINCT c.name) AS class_name,
                       GROUP_CONCAT(DISTINCT subj.name) AS enrolled_subjects,
                       GROUP_CONCAT(DISTINCT sc.class_id) AS enrolled_class_ids,
                       COUNT(DISTINCT pg.id) AS grade_records
                FROM students s LEFT JOIN groups g ON g.id=s.group_id
                LEFT JOIN student_classes sc ON sc.student_id=s.id
                LEFT JOIN classes c ON c.id=sc.class_id
                LEFT JOIN subjects subj ON subj.id=c.subject_id
                LEFT JOIN partial_grades pg ON pg.student_id=s.id
                WHERE (g.teacher_id=? OR (s.group_id IS NULL AND s.teacher_id=?))
            """
            params = [teacher_id, teacher_id]
        else:
            query = """
                SELECT s.*, g.name AS group_name, MIN(sc.class_id) AS class_id,
                       GROUP_CONCAT(DISTINCT c.name) AS class_name,
                       GROUP_CONCAT(DISTINCT subj.name) AS enrolled_subjects,
                       GROUP_CONCAT(DISTINCT sc.class_id) AS enrolled_class_ids,
                       COUNT(DISTINCT pg.id) AS grade_records
                FROM students s
                LEFT JOIN groups g ON g.id=s.group_id
                LEFT JOIN student_classes sc ON sc.student_id=s.id
                LEFT JOIN classes c ON c.id=sc.class_id
                LEFT JOIN subjects subj ON subj.id=c.subject_id
                LEFT JOIN partial_grades pg ON pg.student_id=s.id
                WHERE c.teacher_id=?
            """
            params = [teacher_id]
        if status_filter != "all":
            query += " AND s.enrollment_status=?"; params.append(status_filter)
        if search:
            query += " AND (s.name LIKE ? OR s.code LIKE ?)"; params += [f"%{search}%", f"%{search}%"]
        if subject_search:
            query += " AND EXISTS (SELECT 1 FROM student_classes fsc JOIN classes fc ON fc.id=fsc.class_id JOIN subjects fs ON fs.id=fc.subject_id WHERE fsc.student_id=s.id AND fs.name LIKE ?)"; params.append(f"%{subject_search}%")
        if filter_group:
            query += " AND s.group_id=?"; params.append(filter_group)
        if record_filter == "with":
            query += " AND EXISTS (SELECT 1 FROM partial_grades fpg WHERE fpg.student_id=s.id)"
        elif record_filter == "without":
            query += " AND NOT EXISTS (SELECT 1 FROM partial_grades fpg WHERE fpg.student_id=s.id)"
        query += " GROUP BY s.id ORDER BY s.name"
        rows = connection.execute(query, params).fetchall()
        group_rows = connection.execute("SELECT * FROM groups ORDER BY name" if is_admin or is_secretary else "SELECT * FROM groups WHERE teacher_id=? ORDER BY name", (() if is_admin or is_secretary else (teacher_id,))).fetchall()
        if is_guide:
            class_rows = connection.execute("""SELECT c.*, s.name AS subject_name, t.name AS teacher_name
                FROM classes c LEFT JOIN subjects s ON s.id=c.subject_id
                LEFT JOIN teachers t ON t.id=c.teacher_id
                JOIN groups g ON g.id=c.group_id AND g.teacher_id=? ORDER BY c.name""", (teacher_id,)).fetchall()
        elif is_admin or is_secretary:
            class_rows = connection.execute("""SELECT c.*, s.name AS subject_name, t.name AS teacher_name
                FROM classes c LEFT JOIN subjects s ON s.id=c.subject_id
                LEFT JOIN teachers t ON t.id=c.teacher_id ORDER BY c.name""").fetchall()
        else:
            class_rows = connection.execute("""SELECT c.*, s.name AS subject_name, t.name AS teacher_name
                FROM classes c LEFT JOIN subjects s ON s.id=c.subject_id
                LEFT JOIN teachers t ON t.id=c.teacher_id
                WHERE c.teacher_id=? ORDER BY c.name""", (teacher_id,)).fetchall()
    return render_template("students.html", students=rows, groups=group_rows, classes=class_rows, search=search, subject_search=subject_search, record_filter=record_filter, status_filter=status_filter, filter_group=filter_group, is_guide=is_guide, is_admin=is_admin, is_secretary=is_secretary, can_withdraw=can_withdraw, read_only=is_admin or is_secretary)


@app.post("/students/<int:student_id>/delete")
@teacher_required
def delete_student(student_id):
    teacher_id = session.get("teacher_id")
    if is_guide_teacher(teacher_id):
        if not teacher_can_access_student(student_id, teacher_id):
            flash("No puedes dar de baja a un estudiante fuera de tus grupos.", "error")
            return redirect(url_for("students"))
    elif not (teacher_is_admin(teacher_id) or teacher_is_director(teacher_id)):
        flash("Solo el docente guía, director o administrador puede dar de baja a un estudiante.", "error")
        return redirect(url_for("students"))

    note = request.form.get("withdrawal_note", "").strip()
    if not note:
        flash("Escribe una nota o motivo para registrar la baja.", "error")
        return redirect(url_for("students"))

    with db() as connection:
        student = connection.execute(
            "SELECT id,enrollment_status FROM students WHERE id=?",
            (student_id,),
        ).fetchone()
        if not student:
            flash("No se encontró al estudiante.", "error")
            return redirect(url_for("students"))
        if student["enrollment_status"] == "withdrawn":
            flash("Este estudiante ya está dado de baja.", "error")
            return redirect(url_for("students", status="withdrawn"))

        grade_summary = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN COALESCE(status,'En proceso') NOT IN ('Entregado','Cerrado')
                            THEN 1 ELSE 0 END) AS pending
            FROM partial_grades WHERE student_id=?
            """,
            (student_id,),
        ).fetchone()
        missing_subjects = connection.execute(
            """
            SELECT DISTINCT subj.name
            FROM student_classes sc
            JOIN classes c ON c.id=sc.class_id
            JOIN subjects subj ON subj.id=c.subject_id
            WHERE sc.student_id=?
              AND NOT EXISTS (
                  SELECT 1 FROM partial_grades pg
                  WHERE pg.student_id=sc.student_id AND pg.subject_id=c.subject_id
              )
            ORDER BY subj.name
            """,
            (student_id,),
        ).fetchall()
        total_grades = grade_summary["total"] or 0
        pending_grades = grade_summary["pending"] or 0
        academic_notes = []
        if total_grades:
            academic_notes.append(f"{total_grades} registro(s) de notas conservados.")
        else:
            academic_notes.append("Sin calificaciones registradas.")
        if pending_grades:
            academic_notes.append(f"{pending_grades} registro(s) de notas en proceso.")
        if missing_subjects:
            subjects = ", ".join(row["name"] for row in missing_subjects)
            academic_notes.append(f"Materias sin calificaciones registradas: {subjects}.")
        today = datetime.now().strftime("%Y-%m-%d")
        saved_note = f"{note}\n\nEstado académico al dar de baja: {' '.join(academic_notes)}"
        connection.execute(
            """
            UPDATE students
            SET enrollment_status='withdrawn',withdrawal_date=?,withdrawal_note=?
            WHERE id=?
            """,
            (today, saved_note, student_id),
        )
    flash("Baja registrada. La matrícula y todos los registros de notas se conservaron.", "success")
    return redirect(url_for("students"))


@app.post("/students/<int:student_id>/group")
@teacher_required
def change_student_group(student_id):
    teacher_id = session.get("teacher_id")
    if is_guide_teacher(teacher_id) and not teacher_can_access_student(student_id, teacher_id):
        flash("No puedes cambiar un estudiante fuera de tus grupos.", "error")
        return redirect(url_for("students"))
    if not (is_guide_teacher(teacher_id) or teacher_is_admin(teacher_id) or teacher_is_director(teacher_id)):
        flash("No tienes permiso para cambiar el grupo del estudiante.", "error")
        return redirect(url_for("students"))
    group_id = request.form.get("group_id", type=int)
    with db() as connection:
        valid_group = connection.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone()
        if not valid_group:
            flash("El grupo seleccionado no existe.", "error")
            return redirect(url_for("students"))
        connection.execute("UPDATE students SET group_id=? WHERE id=? AND enrollment_status='active'", (group_id, student_id))
        connection.execute("DELETE FROM student_classes WHERE student_id=?", (student_id,))
    flash("Grupo del estudiante actualizado.", "success")
    return redirect(url_for("students"))


@app.post("/students/<int:student_id>/classes")
@teacher_required
def change_student_classes(student_id):
    teacher_id = session.get("teacher_id")
    if is_guide_teacher(teacher_id) and not teacher_can_access_student(student_id, teacher_id):
        flash("No puedes cambiar materias fuera de tus grupos.", "error")
        return redirect(url_for("students"))
    if not (is_guide_teacher(teacher_id) or teacher_is_admin(teacher_id) or teacher_is_director(teacher_id)):
        flash("No tienes permiso para cambiar las materias del estudiante.", "error")
        return redirect(url_for("students"))
    class_ids = [int(value) for value in request.form.getlist("class_id") if value.isdigit()]
    with db() as connection:
        connection.execute("DELETE FROM student_classes WHERE student_id=?", (student_id,))
        student = connection.execute("SELECT group_id FROM students WHERE id=?", (student_id,)).fetchone()
        group = connection.execute("SELECT grade, section, academic_year FROM groups WHERE id=?", (student["group_id"] if student else None,)).fetchone() if student and student["group_id"] else None
        for class_id in class_ids:
            connection.execute("""
                INSERT OR IGNORE INTO student_classes(student_id,class_id)
                SELECT ?,c.id FROM classes c
                JOIN teachers t ON t.id=c.teacher_id
                JOIN teacher_roles tr ON tr.teacher_id=t.id AND tr.role='teacher'
                WHERE c.id=?
                  AND (
                      c.group_id=?
                      OR (
                          c.year=?
                          AND c.grade=?
                          AND (? = '' OR c.section=? OR c.section IS NULL)
                      )
                  )
            """, (student_id, class_id, student["group_id"] if student else None, group["academic_year"] if group else None, group["grade"] or "" if group else "", group["section"] or "" if group else "", group["section"] or "" if group else ""))
    flash("Materias y docentes del estudiante actualizados.", "success")
    return redirect(url_for("students"))


@app.route("/students/<int:student_id>/grades", methods=["GET", "POST"])
@teacher_required
def grades(student_id):
    teacher_id = session.get("teacher_id")
    can_edit_grades = (get_teacher_role(teacher_id) in ("teacher", "guide")
                       and not teacher_is_admin(teacher_id))
    if request.method == "POST" and not can_edit_grades:
        flash("Solo el docente de materia puede modificar las notas. Esta cuenta tiene acceso de lectura.", "error")
        return redirect(url_for("grades", student_id=student_id, subject_id=request.form.get("subject_id", type=int)))
    if not teacher_can_access_student(student_id, teacher_id):
        flash("No tienes acceso a este estudiante.", "error")
        return redirect(url_for("students"))
    with db() as connection:
        student = connection.execute("SELECT s.*, g.name AS group_name FROM students s LEFT JOIN groups g ON g.id=s.group_id WHERE s.id=?", (student_id,)).fetchone()
        if not student:
            return "Estudiante no encontrado", 404
        if request.method == "POST" and student["enrollment_status"] == "withdrawn":
            flash("No se pueden registrar nuevas notas a un estudiante dado de baja.", "error")
            return redirect(url_for("grades", student_id=student_id))
        subjects = get_teacher_subjects_for_student(student_id, teacher_id)
        selected_subject_id = request.args.get("subject_id", type=int)
        if request.method == "POST":
            selected_subject_id = request.form.get("subject_id", type=int)
        if not subjects and not is_secretary and not teacher_is_admin(teacher_id):
            flash("Este estudiante no tiene materias asignadas a tu docente mediante una clase.", "error")
            destination = "groups" if is_guide_teacher(teacher_id) else "subjects_view"
            return redirect(url_for(destination))
        if subjects and (selected_subject_id is None or not any(s["id"] == selected_subject_id for s in subjects)):
            selected_subject_id = subjects[0]["id"]
    if request.method == "POST":
        try:
            partial = int(request.form["partial"])
        except (KeyError, TypeError, ValueError):
            flash("Parcial inválido.", "error")
            return redirect(url_for("grades", student_id=student_id, subject_id=selected_subject_id))
        if partial not in PARTIALS:
            flash("Solo existen cuatro parciales.", "error")
            return redirect(url_for("grades", student_id=student_id, subject_id=selected_subject_id))
        subject_id = selected_subject_id
        if not teacher_can_access_subject_for_student(student_id, subject_id, teacher_id):
            flash("No tienes acceso a esta materia para el estudiante.", "error")
            return redirect(url_for("students"))
        with db() as connection:
            selected_subject = connection.execute("SELECT name FROM subjects WHERE id=?", (subject_id,)).fetchone()
        if selected_subject and selected_subject["name"].strip().lower() == "conducta":
            try:
                conduct_score = float(request.form.get("conduct_score", ""))
            except (TypeError, ValueError):
                conduct_score = None
            conduct_qualitative = qualitative_learning_label(conduct_score) if conduct_score is not None and 0 <= conduct_score <= 100 else ""
            if conduct_score is None or not 0 <= conduct_score <= 100:
                flash("La calificación cuantitativa de conducta debe estar entre 0 y 100.", "error")
            else:
                with db() as connection:
                    connection.execute("""INSERT INTO conduct_evaluations(student_id,partial,quantitative,qualitative,criteria,incidents,observations)
                        VALUES(?,?,?,?,?,?,?) ON CONFLICT(student_id,partial) DO UPDATE SET quantitative=excluded.quantitative,
                        qualitative=excluded.qualitative,criteria=excluded.criteria,incidents=excluded.incidents,observations=excluded.observations""",
                        (student_id, partial, conduct_score, conduct_qualitative, request.form.get("conduct_criteria", "").strip(), request.form.get("conduct_incidents", "").strip(), request.form.get("conduct_observations", "").strip()))
                flash(f"{partial_name(partial)} de conducta guardado.", "success")
            return redirect(url_for("grades", student_id=student_id, subject_id=subject_id))
        try:
            values = [float(request.form.get(f"work{i}", 0) or 0) for i in range(1, 7)]
            exam = float(request.form.get("exam", 0) or 0)
            recovery_score = float(request.form.get("recovery_score", 0) or 0)
            attendance = float(request.form.get("attendance", 0) or 0)
        except (TypeError, ValueError):
            flash("Las notas y la asistencia deben ser números válidos.", "error")
            return redirect(url_for("grades", student_id=student_id, subject_id=selected_subject_id))
        dates = [request.form.get(f"work{i}_date", "").strip() for i in range(1, 7)]
        recovery_type = request.form.get("recovery_type", "").strip()
        exam_date = request.form.get("exam_date", "").strip()
        recovery_date = request.form.get("recovery_date", "").strip()
        status = request.form.get("status", "En proceso").strip()
        comments = request.form.get("comments", "").strip()
        if any(value < 0 or value > 10 for value in values) or exam < 0 or exam > 40 or recovery_score < 0 or recovery_score > 40 or attendance < 0 or attendance > 100 or status not in ("En proceso", "Entregado", "Cerrado"):
            flash("Cada trabajo debe estar entre 0 y 10; el examen, entre 0 y 40.", "error")
        elif recovery_type and sum(values) <= 50:
            flash("El rescate o extraordinario requiere un acumulado mayor de 50 puntos.", "error")
        else:
            with db() as connection:
                connection.execute("""INSERT INTO partial_grades(student_id,partial,subject_id,teacher_id,work1,work2,work3,work4,work5,work6,exam,exam_date,recovery_type,recovery_score,recovery_date,status,attendance,comments,
                    work1_date,work2_date,work3_date,work4_date,work5_date,work6_date)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(student_id,partial,subject_id) DO UPDATE SET work1=excluded.work1,
                    work2=excluded.work2,work3=excluded.work3,work4=excluded.work4,work5=excluded.work5,
                    work6=excluded.work6,exam=excluded.exam,exam_date=excluded.exam_date,recovery_type=excluded.recovery_type,recovery_score=excluded.recovery_score,recovery_date=excluded.recovery_date,
                    status=excluded.status,attendance=excluded.attendance,comments=excluded.comments,
                    work1_date=excluded.work1_date,work2_date=excluded.work2_date,
                    work3_date=excluded.work3_date,work4_date=excluded.work4_date,work5_date=excluded.work5_date,
                    work6_date=excluded.work6_date""",
                    (student_id, partial, subject_id, teacher_id, *values, exam, exam_date, recovery_type, recovery_score, recovery_date, status, attendance, comments, *dates))
                connection.execute("INSERT INTO grade_audit(student_id,partial,action,details,actor_teacher_id) VALUES(?,?,?,?,?)",
                                   (student_id, partial, "Actualización", f"Nota parcial {grade_value({'work1': values[0], 'work2': values[1], 'work3': values[2], 'work4': values[3], 'work5': values[4], 'work6': values[5], 'exam': exam})} (subject_id={subject_id})", teacher_id))
            flash(f"{partial_name(partial)} guardado.", "success")
            return redirect(url_for("grades", student_id=student_id, subject_id=subject_id))
    partials, final = subject_summary(student_id, selected_subject_id)
    with db() as connection:
        history = connection.execute("""
            SELECT ga.*, t.name AS actor_name
            FROM grade_audit ga LEFT JOIN teachers t ON t.id=ga.actor_teacher_id
            WHERE ga.student_id=? ORDER BY ga.created_at DESC, ga.id DESC LIMIT 30
        """, (student_id,)).fetchall()
    selected_subject_name = next((row["name"] for row in subjects if row["id"] == selected_subject_id), "")
    return render_template("grades.html", student=student, partials=partials, final=final, history=history, subjects=subjects, current_subject_id=selected_subject_id, selected_subject_name=selected_subject_name, is_conduct=selected_subject_name.strip().lower() == "conducta", is_guide=is_guide_teacher(teacher_id), is_admin=teacher_is_admin(teacher_id), is_secretary=teacher_is_secretary(teacher_id), can_edit_grades=can_edit_grades)


@app.post("/students/<int:student_id>/profile")
@teacher_required
def update_profile(student_id):
    teacher_id = session.get("teacher_id")
    can_update_conduct = (
        teacher_is_admin(teacher_id)
        or teacher_is_director(teacher_id)
        or (
            is_guide_teacher(teacher_id)
            and teacher_can_access_student(student_id, teacher_id)
        )
    )
    if not can_update_conduct:
        flash("Solo el director, administrador o docente guía responsable pueden modificar la conducta.", "error")
        return redirect(url_for("grades", student_id=student_id))
    try:
        conduct_score = float(request.form.get("conduct_score", ""))
    except (TypeError, ValueError):
        conduct_score = None
    if conduct_score is None or conduct_score < 0 or conduct_score > 100:
        flash("La nota de conducta debe estar entre 0 y 100.", "error")
        return redirect(url_for("grades", student_id=student_id))
    conduct_criteria = request.form.get("conduct_criteria", "").strip()
    conduct_incidents = request.form.get("conduct_incidents", "").strip()
    observations = request.form.get("observations", "").strip()
    try:
        conduct_partial = int(request.form.get("conduct_partial", "1"))
    except (TypeError, ValueError):
        conduct_partial = 0
    if conduct_partial not in range(1, 5):
        flash("Selecciona un parcial válido para la conducta.", "error")
        return redirect(url_for("grades", student_id=student_id))
    with db() as connection:
        exists = connection.execute("SELECT 1 FROM students WHERE id=?", (student_id,)).fetchone()
        if not exists:
            flash("Estudiante no encontrado.", "error")
            return redirect(url_for("students"))
        connection.execute("""UPDATE students
                           SET conduct=?, conduct_score=?, conduct_criteria=?, conduct_incidents=?, observations=?
                           WHERE id=?""",
                           (f"{conduct_score:.2f}", conduct_score, conduct_criteria, conduct_incidents, observations, student_id))
        connection.execute("""INSERT INTO conduct_evaluations(student_id,partial,quantitative,qualitative,criteria,incidents,observations)
                           VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(student_id,partial) DO UPDATE SET quantitative=excluded.quantitative,
                           qualitative=excluded.qualitative,criteria=excluded.criteria,incidents=excluded.incidents,
                           observations=excluded.observations""",
                           (student_id, conduct_partial, conduct_score, request.form.get("conduct_qualitative", "").strip(), conduct_criteria, conduct_incidents, observations))
    flash("Conducta y observaciones guardadas.", "success")
    return redirect(url_for("grades", student_id=student_id))


@app.post("/students/<int:student_id>/grades/<int:partial>/delete")
@teacher_required
def delete_partial_grade(student_id, partial):
    teacher_id = session.get("teacher_id")
    if get_teacher_role(teacher_id) not in ("teacher", "guide") or teacher_is_admin(teacher_id):
        flash("Esta cuenta no puede eliminar registros de notas.", "error")
        return redirect(url_for("grades", student_id=student_id))
    subject_id = request.form.get("subject_id", type=int)
    if partial not in PARTIALS:
        flash("Solo existen cuatro parciales.", "error")
        return redirect(url_for("grades", student_id=student_id))
    if not teacher_can_access_student(student_id):
        flash("Estudiante no encontrado.", "error")
        return redirect(url_for("students"))
    if subject_id is None or not teacher_can_access_subject_for_student(student_id, subject_id):
        flash("Materia no especificada para la eliminación.", "error")
        return redirect(url_for("grades", student_id=student_id))
    with db() as connection:
        connection.execute("DELETE FROM partial_grades WHERE student_id=? AND partial=? AND subject_id=?", (student_id, partial, subject_id))
        connection.execute("INSERT INTO grade_audit(student_id,partial,action,details,actor_teacher_id) VALUES(?,?,?,?,?)",
                           (student_id, partial, "Eliminación", f"Registro del parcial eliminado para la materia {subject_id}", session.get("teacher_id")))
    flash(f"{partial_name(partial)} eliminado. Puedes volver a registrarlo.", "success")
    return redirect(url_for("grades", student_id=student_id, subject_id=subject_id))


@app.route("/settings", methods=["GET", "POST"])
@admin_required
def config():
    if request.method == "POST":
        name, group, password, criteria, school = (request.form.get(key, "").strip() for key in ("teacher_name", "group_name", "password", "evaluation_criteria", "school_name"))
        theme = request.form.get("theme", "light").strip().lower()
        if theme not in ("light", "dark"):
            theme = "light"
        logo = request.files.get("logo")
        logo_filename = None
        if logo and logo.filename:
            extension = os.path.splitext(secure_filename(logo.filename))[1].lower()
            if extension not in (".png", ".jpg", ".jpeg"):
                flash("El logo debe ser PNG o JPG.", "error")
                return redirect(url_for("config"))
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            logo_filename = f"school-logo{extension}"
            logo.save(os.path.join(UPLOAD_DIR, logo_filename))
        teacher_id = session.get("teacher_id")
        with db() as connection:
            # update teacher password if provided
            if password and teacher_id:
                connection.execute("UPDATE teachers SET password=? WHERE id=?", (generate_password_hash(password), teacher_id))
            # upsert teacher_settings for this teacher
            existing = connection.execute("SELECT 1 FROM teacher_settings WHERE teacher_id=?", (teacher_id,)).fetchone()
            if existing:
                query = "UPDATE teacher_settings SET teacher_name=?,group_name=?,evaluation_criteria=?,school_name=?,theme=?"
                params = [name or "Docente", group or "Grupo", criteria, school or "Colegio", theme]
                if logo_filename:
                    query += ",logo_filename=?"
                    params.append(logo_filename)
                query += " WHERE teacher_id=?"
                params.append(teacher_id)
                connection.execute(query, params)
            else:
                connection.execute("INSERT INTO teacher_settings(teacher_id,teacher_name,group_name,evaluation_criteria,school_name,logo_filename,theme) VALUES(?,?,?,?,?,?,?)",
                                   (teacher_id, name or "Docente", group or "Grupo", criteria, school or "Colegio", logo_filename or "", theme))
        flash("Configuración actualizada.", "success")
        return redirect(url_for("config"))
    return render_template("settings.html", current=settings())


@app.get("/school-logo")
def school_logo():
    current = settings()
    filename = current["logo_filename"] if current else ""
    path = os.path.join(UPLOAD_DIR, filename) if filename else ""
    if not path or not os.path.isfile(path):
        return "", 404
    return send_file(path)


@app.route("/teachers", methods=["GET", "POST"])
@admin_required
@workflow_required(0, 1)
@onboarding_accounts_required
def teachers_view():
    sync_approved_subjects()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        hire_date = request.form.get("hire_date", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        employment_status = request.form.get("employment_status", "Activo").strip() or "Activo"
        status_start_date = request.form.get("status_start_date", hire_date).strip()
        status_end_date = request.form.get("status_end_date", "").strip()
        reentry_date = request.form.get("reentry_date", "").strip()
        employment_reason = request.form.get("employment_reason", "").strip()
        role = request.form.get("role", "guide")
        account_type = request.form.get("account_type", "Docente").strip() or "Docente"
        teaching_level = clean_choice(request.form.get("teaching_level", ""), TEACHER_LEVEL_OPTIONS, "Primaria")
        is_director_account = account_type == "Director" or role == "director"
        is_secretary_account = account_type in ("Secretaría", "secretary") or role == "secretary"
        if is_director_account:
            with db() as connection:
                director = connection.execute(
                    """SELECT t.* FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id
                       WHERE r.role='director' ORDER BY t.id LIMIT 1""",
                ).fetchone()
                if not director and (not first_name or not last_name or not hire_date or not password):
                    flash("Nombres, apellidos, fecha de ingreso y contraseña son obligatorios para crear Director.", "error")
                elif not director:
                    final_name = " ".join((first_name, last_name))
                    cursor = connection.execute("""
                        INSERT INTO teachers(name,email,password,first_name,last_name,hire_date,
                            employment_status,status_start_date,status_end_date,reentry_date,
                            account_type,is_admin)
                        VALUES(?,?,?,?,?,?,?,?,?,?, 'Director',0)
                    """, (final_name, email, generate_password_hash(password), first_name, last_name,
                          hire_date, employment_status, status_start_date, status_end_date, reentry_date))
                    director_id = cursor.lastrowid
                    connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'director')", (director_id,))
                    connection.execute("INSERT OR IGNORE INTO teacher_capabilities(teacher_id,capability) VALUES(?, 'director')", (director_id,))
                    flash("Cuenta fija de Director creada.", "success")
                elif not hire_date:
                    flash("La fecha de ingreso es obligatoria.", "error")
                else:
                    # The account is fixed, but the Director's name may be
                    # updated by Admin/Soporte.
                    final_name = " ".join((first_name, last_name))
                    director_employment_status = request.form.get(
                        "employment_status", director["employment_status"] or "Activo",
                    ).strip() or "Activo"
                    director_status_start = request.form.get(
                        "status_start_date", director["status_start_date"] or hire_date,
                    ).strip()
                    director_status_end = request.form.get(
                        "status_end_date", director["status_end_date"] or "",
                    ).strip()
                    director_reentry = request.form.get(
                        "reentry_date", director["reentry_date"] or "",
                    ).strip()
                    connection.execute("""
                        UPDATE teachers
                        SET name=?, first_name=?, last_name=?, hire_date=?, account_type='Director',
                            employment_status=?, status_start_date=?, status_end_date=?, reentry_date=?
                        WHERE id=?
                    """, (final_name, first_name, last_name, hire_date, director_employment_status,
                          director_status_start, director_status_end, director_reentry, director["id"]))
                    if password:
                        connection.execute(
                            "UPDATE teachers SET password=? WHERE id=?",
                            (generate_password_hash(password), director["id"]),
                        )
                    connection.execute(
                        "INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'director') "
                        "ON CONFLICT(teacher_id) DO UPDATE SET role='director'",
                        (director["id"],),
                    )
                    if (director_employment_status, director_status_start, director_status_end, director_reentry) != (
                        director["employment_status"] or "Activo", director["status_start_date"] or "",
                        director["status_end_date"] or "", director["reentry_date"] or "",
                    ):
                        connection.execute(
                            "INSERT INTO teacher_employment_history(teacher_id,previous_status,new_status,start_date,end_date,reentry_date,reason,changed_by) VALUES(?,?,?,?,?,?,?,?)",
                            (director["id"], director["employment_status"] or "Activo", director_employment_status,
                             director_status_start, director_status_end, director_reentry, employment_reason,
                             session.get("teacher_id")),
                        )
                    if final_name != director["name"]:
                        connection.execute(
                            "INSERT INTO teacher_history(teacher_id,action,previous_name,new_name,reason,changed_by) VALUES(?,?,?,?,?,?)",
                            (director["id"], "Actualización de datos del Director", director["name"],
                             final_name, "Actualización de cuenta fija", session.get("teacher_id")),
                        )
                    flash("Datos de la cuenta fija de Director actualizados.", "success")
            return redirect(url_for("teachers_view", onboarding=1))
        if is_secretary_account:
            with db() as connection:
                existing_secretary = connection.execute(
                    "SELECT id FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id "
                    "WHERE t.is_admin=0 AND r.role='secretary' LIMIT 1",
                ).fetchone()
                if existing_secretary:
                    flash("La cuenta fija de Secretaría ya existe. Actualiza sus datos desde Editar.", "error")
                elif not first_name or not last_name or not hire_date or not password:
                    flash("Nombres, apellidos, fecha de ingreso y contraseña son obligatorios para crear Secretaría.", "error")
                else:
                    final_name = " ".join((first_name, last_name))
                    cursor = connection.execute("""
                        INSERT INTO teachers(name,email,password,first_name,last_name,hire_date,
                            employment_status,status_start_date,status_end_date,reentry_date,
                            account_type,is_admin)
                        VALUES(?,?,?,?,?,?,?,?,?,?, 'Secretaría',0)
                    """, (final_name, email, generate_password_hash(password), first_name, last_name,
                          hire_date, employment_status, status_start_date, status_end_date, reentry_date))
                    secretary_id = cursor.lastrowid
                    connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'secretary')", (secretary_id,))
                    connection.execute("INSERT OR IGNORE INTO teacher_capabilities(teacher_id,capability) VALUES(?, 'secretary')", (secretary_id,))
                    flash("Cuenta fija de Secretaría creada. Los datos laborales podrán actualizarse desde Editar.", "success")
            return redirect(url_for("teachers_view", onboarding=1))
        if is_director_account:
            role = "guide"
            account_type = "Director"
        elif account_type == "Secretaría":
            role = "guide"
            account_type = "Docente"
        else:
            # En la arquitectura actual todo docente es docente guía.
            role = "guide"
            account_type = "Docente"
        group_ids = [int(value) for value in request.form.getlist("group_id") if value.isdigit()]
        subject_ids = list(dict.fromkeys(
            int(value) for value in request.form.getlist("subject_id") if value.isdigit()
        ))
        new_subject_name = request.form.get("new_subject_name", "").strip()
        teacher_grades = [value.strip() for value in request.form.getlist("teacher_grade") if value.strip()]
        teacher_sections = [value.strip().upper() for value in request.form.getlist("teacher_section") if value.strip()]
        guide_grade = request.form.get("guide_grade", "").strip()
        guide_section = request.form.get("guide_section", "").strip().upper()
        guide_year = request.form.get("guide_year", type=int)
        with db() as state_connection:
            active_subject_ids = {
                row["id"] for row in state_connection.execute("""
                    SELECT s.id FROM subjects s
                    JOIN subject_catalog sc ON sc.name=s.name COLLATE NOCASE AND sc.active=1
                """).fetchall()
            }
        if not name or not password:
            flash("Nombre y contraseña son obligatorios para crear un docente guía.", "error")
        elif not set(subject_ids).issubset(active_subject_ids):
            flash("Selecciona únicamente materias activas del catálogo.", "error")
        elif active_subject_ids and not subject_ids and not is_primary_grade(guide_grade):
            flash("Selecciona al menos una materia para el docente guía.", "error")
        else:
            with db() as connection:
                try:
                    if is_primary_grade(guide_grade) and not subject_ids:
                        subject_ids = sorted(active_subject_ids)
                    cursor = connection.execute("INSERT INTO teachers(name,email,password,grade,section,academic_year,first_name,last_name,hire_date,employment_status,status_start_date,status_end_date,reentry_date,account_type,teaching_level,is_admin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                                (name, email, generate_password_hash(password), guide_grade, guide_section, guide_year, first_name, last_name, hire_date, employment_status, status_start_date, status_end_date, reentry_date, "Docente", teaching_level, 0))
                    new_teacher_id = cursor.lastrowid
                    connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?, 'guide')", (new_teacher_id,))
                    connection.execute("INSERT OR IGNORE INTO teacher_capabilities(teacher_id,capability) VALUES(?, 'guide')", (new_teacher_id,))
                    connection.executemany(
                        "INSERT INTO assignments(teacher_id,subject_id) VALUES(?,?)",
                        [(new_teacher_id, subject_id) for subject_id in subject_ids],
                    )
                    flash("Cuenta de docente guía creada con las materias seleccionadas.", "success")
                except sqlite3.IntegrityError:
                    flash("No se pudo crear el docente guía (posible duplicado).", "error")
        return redirect(url_for("teachers_view"))
    with db() as connection:
        rows = connection.execute("""
            SELECT t.id,t.name,t.email,t.created_at,t.is_admin,t.hire_date,t.employment_status,
            CASE WHEN t.is_admin=1 THEN 'admin_support' ELSE COALESCE(r.role,'teacher') END AS role
            FROM teachers t LEFT JOIN teacher_roles r ON r.teacher_id=t.id ORDER BY t.id
        """).fetchall()
        secretary_exists = connection.execute("""
            SELECT 1 FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id
            WHERE t.is_admin=0 AND r.role='secretary' LIMIT 1
        """).fetchone() is not None
        director_exists = connection.execute("""
            SELECT 1 FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id
            WHERE t.is_admin=0 AND r.role='director' LIMIT 1
        """).fetchone() is not None
        subjects = connection.execute("""
            SELECT s.id,s.name,s.grade,s.year FROM subjects s
            JOIN subject_catalog sc ON sc.name=s.name COLLATE NOCASE AND sc.active=1
            ORDER BY s.name
        """).fetchall()
    return render_template("teachers.html", teachers=rows, subjects=subjects, secretary_exists=secretary_exists, director_exists=director_exists, grade_options=GRADE_OPTIONS)


@app.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@admin_required
@onboarding_accounts_required
def delete_teacher(teacher_id):
    current = session.get("teacher_id")
    with db() as connection:
        total = connection.execute("SELECT COUNT(*) AS n FROM teachers").fetchone()["n"]
        if total <= 1:
            flash("No se puede eliminar al único docente registrado.", "error")
            return redirect(url_for("teachers_view"))
        if teacher_id == current:
            flash("No puedes eliminar la sesión docente actual.", "error")
            return redirect(url_for("teachers_view"))
        fixed_account = connection.execute(
            """
            SELECT 1
            FROM teachers t
            LEFT JOIN teacher_roles r ON r.teacher_id=t.id
            WHERE t.id=? AND (t.is_admin=1 OR r.role IN ('director', 'secretary'))
            LIMIT 1
            """,
            (teacher_id,),
        ).fetchone()
        if fixed_account:
            flash("Las cuentas fijas de Director y Secretaría no se pueden eliminar.", "error")
            return redirect(url_for("teachers_view"))
        create_database_backup("antes-de-eliminar-docente")
        connection.execute("DELETE FROM teachers WHERE id=?", (teacher_id,))
        # also remove settings and reassign groups/students if any
        connection.execute("DELETE FROM teacher_settings WHERE teacher_id=?", (teacher_id,))
        connection.execute("UPDATE groups SET teacher_id=? WHERE teacher_id=?", (current, teacher_id))
        connection.execute("UPDATE students SET teacher_id=? WHERE teacher_id=?", (current, teacher_id))
    flash("Docente eliminado.", "success")
    return redirect(url_for("teachers_view"))


@app.route("/teachers/<int:teacher_id>/edit", methods=["GET", "POST"])
@admin_required
@onboarding_accounts_required
def edit_teacher(teacher_id):
    with db() as connection:
        teacher = connection.execute("""
            SELECT t.*,COALESCE(r.role,'teacher') AS role
            FROM teachers t LEFT JOIN teacher_roles r ON r.teacher_id=t.id WHERE t.id=?
        """, (teacher_id,)).fetchone()
        if not teacher:
            flash("Docente no encontrado.", "error")
            return redirect(url_for("teachers_view"))
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "").strip()
            teaching_level = clean_choice(request.form.get("teaching_level", teacher["teaching_level"] or ""), TEACHER_LEVEL_OPTIONS, "Primaria")
            teacher_grade = request.form.get("teacher_grade", "").strip()
            teacher_section = request.form.get("teacher_section", "").strip().upper()
            teacher_year = request.form.get("teacher_year", type=int)
            assigned_subject_ids = list(dict.fromkeys(
                int(value) for value in request.form.getlist("subject_id") if value.isdigit()
            ))
            employment_status = request.form.get("employment_status", teacher["employment_status"] or "Activo").strip()
            status_start_date = request.form.get("status_start_date", teacher["status_start_date"] or "").strip()
            status_end_date = request.form.get("status_end_date", teacher["status_end_date"] or "").strip()
            reentry_date = request.form.get("reentry_date", teacher["reentry_date"] or "").strip()
            employment_reason = request.form.get("employment_reason", "").strip()
            change_reason = request.form.get("change_reason", "").strip()
            if teacher["is_admin"] or teacher["role"] == "admin_support":
                role = "admin_support"
            elif teacher["role"] == "director":
                role = "director"
            elif request.form.get("role") == "secretary":
                role = "secretary"
            else:
                role = "guide"
            if role not in ("guide", "secretary", "director", "admin_support"):
                flash("Tipo de docente inválido.", "error")
                return redirect(url_for("teachers_view"))
            if role == "secretary":
                existing = connection.execute("SELECT COUNT(*) AS n FROM teachers t JOIN teacher_roles r ON r.teacher_id=t.id WHERE t.is_admin=0 AND r.role='secretary' AND t.id<>?", (teacher_id,)).fetchone()["n"]
                if existing:
                    flash("Solo puede existir una cuenta fija de Secretaría.", "error")
                    return redirect(url_for("teachers_view"))
            if teacher["role"] == "guide" and role != "guide":
                remaining_guides = connection.execute("SELECT COUNT(*) AS n FROM teacher_roles WHERE role='guide' AND teacher_id<>?", (teacher_id,)).fetchone()["n"]
                if remaining_guides == 0:
                    flash("Debe existir al menos un docente guía.", "error")
                    return redirect(url_for("teachers_view"))
            first_name = request.form.get("first_name", teacher["first_name"] or "").strip()
            last_name = request.form.get("last_name", teacher["last_name"] or "").strip()
            hire_date = request.form.get("hire_date", teacher["hire_date"] or "").strip()
            if teacher["role"] == "director":
                first_name = teacher["first_name"] or ""
                last_name = teacher["last_name"] or ""
                final_name = teacher["name"]
            elif role in ("director", "secretary") and first_name and last_name:
                final_name = " ".join((first_name, last_name))
            else:
                final_name = name or teacher["name"]
            account_type = (
                "Admin / Soporte" if role == "admin_support"
                else "Director" if role == "director"
                else "Secretaría" if role == "secretary"
                else "Docente"
            )
            active_subject_ids = {
                row["id"] for row in connection.execute("""
                    SELECT s.id FROM subjects s
                    JOIN subject_catalog sc ON sc.name=s.name COLLATE NOCASE AND sc.active=1
                """).fetchall()
            }
            if role in ("guide", "teacher") and (
                not set(assigned_subject_ids).issubset(active_subject_ids)
                or (
                    role == "guide"
                    and active_subject_ids
                    and not assigned_subject_ids
                    and not is_primary_grade(teacher_grade)
                )
            ):
                flash("Revisa la selección de materias activas para este docente.", "error")
                return redirect(url_for("edit_teacher", teacher_id=teacher_id))
            if password:
                connection.execute("""
                    UPDATE teachers SET name=?,email=?,password=?,grade=?,section=?,academic_year=?,
                        employment_status=?,status_start_date=?,status_end_date=?,reentry_date=?,
                        first_name=?,last_name=?,hire_date=?,account_type=? WHERE id=?
                """, (final_name, email or teacher["email"], generate_password_hash(password), teacher_grade,
                      teacher_section, teacher_year, employment_status, status_start_date, status_end_date,
                      reentry_date, first_name, last_name, hire_date, account_type, teacher_id))
            else:
                connection.execute("""
                    UPDATE teachers SET name=?,email=?,grade=?,section=?,academic_year=?,
                        employment_status=?,status_start_date=?,status_end_date=?,reentry_date=?,
                        first_name=?,last_name=?,hire_date=?,account_type=?,teaching_level=? WHERE id=?
                """, (final_name, email or teacher["email"], teacher_grade, teacher_section, teacher_year,
                      employment_status, status_start_date, status_end_date, reentry_date, first_name,
                      last_name, hire_date, account_type, teaching_level, teacher_id))
            if (employment_status, status_start_date, status_end_date, reentry_date) != (
                teacher["employment_status"] or "Activo", teacher["status_start_date"] or "",
                teacher["status_end_date"] or "", teacher["reentry_date"] or "",
            ):
                connection.execute("INSERT INTO teacher_employment_history(teacher_id,previous_status,new_status,start_date,end_date,reentry_date,reason,changed_by) VALUES(?,?,?,?,?,?,?,?)", (teacher_id, teacher["employment_status"] or "Activo", employment_status, status_start_date, status_end_date, reentry_date, employment_reason, session.get("teacher_id")))
            if final_name != teacher["name"]:
                connection.execute("INSERT INTO teacher_history(teacher_id,action,previous_name,new_name,reason,changed_by) VALUES(?,?,?,?,?,?)", (teacher_id, "Sustitución o actualización de nombre", teacher["name"], final_name, change_reason or "Cambio registrado por administración", session.get("teacher_id")))
            connection.execute("INSERT INTO teacher_roles(teacher_id,role) VALUES(?,?) ON CONFLICT(teacher_id) DO UPDATE SET role=excluded.role", (teacher_id, role))
            connection.execute("DELETE FROM teacher_capabilities WHERE teacher_id=? AND capability IN ('guide','teacher','director','secretary')", (teacher_id,))
            connection.execute("INSERT OR IGNORE INTO teacher_capabilities(teacher_id,capability) VALUES(?,?)", (teacher_id, role))
            if role in ("guide", "teacher"):
                if role == "guide" and is_primary_grade(teacher_grade) and not assigned_subject_ids:
                    assigned_subject_ids = sorted(active_subject_ids)
                connection.execute("DELETE FROM assignments WHERE teacher_id=?", (teacher_id,))
                connection.executemany(
                    "INSERT INTO assignments(teacher_id,subject_id) VALUES(?,?)",
                    [(teacher_id, subject_id) for subject_id in assigned_subject_ids],
                )
            flash("Datos de la cuenta actualizados.", "success")
            return redirect(url_for("teachers_view"))
    history = connection.execute("SELECT h.*, t.name AS changed_by_name FROM teacher_history h LEFT JOIN teachers t ON t.id=h.changed_by WHERE h.teacher_id=? ORDER BY h.created_at DESC, h.id DESC", (teacher_id,)).fetchall()
    employment_history = connection.execute("SELECT h.*, t.name AS changed_by_name FROM teacher_employment_history h LEFT JOIN teachers t ON t.id=h.changed_by WHERE h.teacher_id=? ORDER BY h.created_at DESC, h.id DESC", (teacher_id,)).fetchall()
    subjects = connection.execute("""
        SELECT s.id,s.name,s.grade,s.year FROM subjects s
        JOIN subject_catalog sc ON sc.name=s.name COLLATE NOCASE AND sc.active=1
        ORDER BY s.name
    """).fetchall()
    assigned_subject_ids = {
        row["subject_id"] for row in connection.execute(
            "SELECT subject_id FROM assignments WHERE teacher_id=?",
            (teacher_id,),
        ).fetchall()
    }
    if teacher["role"] == "guide" and not assigned_subject_ids and is_primary_grade(teacher["grade"]):
        assigned_subject_ids = {subject["id"] for subject in subjects}
    return render_template("teachers_edit.html", teacher=teacher, history=history, employment_history=employment_history, subjects=subjects, assigned_subject_ids=assigned_subject_ids)


@app.get("/export.xlsx")
@guide_required
def export_xlsx():
    workbook = Workbook()
    students_sheet = workbook.active
    students_sheet.title = "Estudiantes"
    students_sheet.append(["Código", "Nombre", "Materia", "Grupo", "Sección", "Conducta", "Observaciones"])
    teacher_id = session.get("teacher_id")
    with db() as connection:
        students = connection.execute("""
            SELECT s.*, g.name AS group_name FROM students s
            LEFT JOIN groups g ON g.id=s.group_id
            WHERE g.teacher_id=? OR (s.group_id IS NULL AND s.teacher_id=?)
            ORDER BY s.name
        """, (teacher_id, teacher_id)).fetchall()
        grades = connection.execute("""
            SELECT s.code, pg.* FROM partial_grades pg
            JOIN students s ON s.id=pg.student_id
            LEFT JOIN groups g ON g.id=s.group_id
            WHERE g.teacher_id=? OR (s.group_id IS NULL AND s.teacher_id=?)
            ORDER BY s.name, pg.partial
        """, (teacher_id, teacher_id)).fetchall()
    for student in students:
        students_sheet.append([student["code"], student["name"], student["subject"], student["group_name"] or "", student["section"], student["conduct"], student["observations"]])
    grades_sheet = workbook.create_sheet("Notas")
    grades_sheet.append(["Código", "Parcial"] + [item for i in range(1, 7) for item in (f"Trabajo {i}", f"Fecha trabajo {i}")] + ["Acumulado", "Examen", "Fecha examen", "Tipo recuperación", "Nota recuperación", "Fecha recuperación", "Estado", "Asistencia", "Observación"])
    for row in grades:
        values = [row["code"], row["partial"]]
        values += [item for i in range(1, 7) for item in (row[f"work{i}"], row[f"work{i}_date"] or "")]
        values += [accumulated_value(row), row["exam"], row["exam_date"] or "", row["recovery_type"] or "", row["recovery_score"] or 0, row["recovery_date"] or "", row["status"] or "En proceso", row["attendance"] or 0, row["comments"] or ""]
        grades_sheet.append(values)
    config_sheet = workbook.create_sheet("Configuración")
    current = settings()
    config_sheet.append(["Campo", "Valor"])
    for key in ("school_name", "teacher_name", "group_name", "evaluation_criteria"):
        config_sheet.append([key, current[key]])
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 12), 38)
    output = io.BytesIO(); workbook.save(output); output.seek(0)
    return send_file(output, as_attachment=True, download_name="respaldo-notas.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/admin/database")
@admin_required
def database_admin():
    with db() as connection:
        tables = ("teachers", "groups", "subjects", "classes", "students", "partial_grades", "grade_audit")
        counts = [(table, connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]) for table in tables]
    backup_dir = os.path.join(BASE_DIR, "data", "backups")
    backups = []
    if os.path.isdir(backup_dir):
        backups = sorted((name for name in os.listdir(backup_dir) if name.endswith(".db")), reverse=True)
    return render_template("database.html", counts=counts, backups=backups)


@app.post("/admin/reset-default-password")
@admin_required
def reset_default_admin_password():
    with db() as connection:
        connection.execute("UPDATE teachers SET password=? WHERE is_admin=1", (generate_password_hash("admin123"),))
    flash("La clave del administrador fue restaurada a: admin123", "success")
    return redirect(url_for("index"))


@app.post("/admin/database/backup")
@admin_required
def create_database_backup_route():
    path = create_database_backup("manual")
    flash(f"Respaldo creado: {os.path.basename(path)}", "success")
    return redirect(url_for("database_admin"))


@app.post("/admin/database/reset")
@admin_required
def reset_database_route():
    if request.form.get("confirmation") != "LIMPIAR":
        flash("Escribe LIMPIAR para confirmar la eliminación de los datos académicos.", "error")
        return redirect(url_for("database_admin"))
    path = create_database_backup("antes-de-limpiar")
    reset_academic_data()
    session.pop("setup_complete", None)
    flash(f"Base limpiada. Se creó el respaldo automático {os.path.basename(path)}.", "success")
    return redirect(url_for("index"))


@app.get("/backup.db")
@admin_required
def backup_database():
    if not os.path.isfile(DB_PATH):
        return "Base de datos no encontrada", 404
    return send_file(DB_PATH, as_attachment=True, download_name="respaldo-notas.db", mimetype="application/octet-stream")


@app.post("/import.xlsx")
@guide_required
def import_xlsx():
    uploaded = request.files.get("workbook")
    if not uploaded or not uploaded.filename.lower().endswith((".xlsx", ".xlsm")):
        flash("Selecciona un archivo Excel .xlsx válido.", "error")
        return redirect(url_for("config"))
    try:
        workbook = load_workbook(uploaded, data_only=True)
        students_sheet = workbook["Estudiantes"]
        grades_sheet = workbook["Notas"]
        with db() as connection:
            teacher_id = session.get("teacher_id")
            student_ids = {}
            for row in students_sheet.iter_rows(min_row=2, values_only=True):
                code, name, subject, group_name, section, conduct, observations = (str(value or "").strip() for value in (list(row) + [""] * 7)[:7])
                if not code or not name:
                    continue
                group_name = group_name or "Grupo"
                connection.execute("INSERT OR IGNORE INTO groups(name,teacher_id) VALUES(?,?)", (group_name, teacher_id))
                group_id = connection.execute("SELECT id FROM groups WHERE name=? AND teacher_id=?", (group_name, teacher_id)).fetchone()["id"]
                connection.execute("""INSERT INTO students(code,name,subject,section,conduct,observations,teacher_id) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(code) DO UPDATE SET name=excluded.name,subject=excluded.subject,section=excluded.section,
                    conduct=excluded.conduct,observations=excluded.observations""",
                    (code, name, subject, section, conduct, observations, teacher_id))
                connection.execute("UPDATE students SET group_id=? WHERE code=? AND teacher_id=?", (group_id, code, teacher_id))
            for row in connection.execute("SELECT id,code FROM students WHERE teacher_id=?", (teacher_id,)):
                student_ids[row["code"]] = row["id"]
            for row in grades_sheet.iter_rows(min_row=2, values_only=True):
                if not row or not row[0] or not row[1] or row[0] not in student_ids:
                    continue
                values = list(row) + [""] * 22
                code, partial = str(values[0]).strip(), int(values[1])
                works = [values[index] or 0 for index in (2, 4, 6, 8, 10, 12)]
                dates = [str(values[index] or "").strip() for index in (3, 5, 7, 9, 11, 13)]
                exam = values[15] or 0
                exam_date = str(values[16] or "").strip()
                recovery_type = str(values[17] or "").strip()
                recovery_score = values[18] or 0
                recovery_date = str(values[19] or "").strip()
                status = str(values[20] or "En proceso").strip()
                attendance = values[21] or 0
                comments = str(values[22] or "").strip()
                if partial not in range(1, 5) or any(float(value) < 0 or float(value) > 10 for value in works) or float(exam) < 0 or float(exam) > 40 or float(recovery_score) < 0 or float(recovery_score) > 40 or float(attendance) < 0 or float(attendance) > 100 or (recovery_type and sum(float(value) for value in works) <= 50):
                    continue
                connection.execute("""INSERT INTO partial_grades(student_id,partial,subject_id,work1,work2,work3,work4,work5,work6,exam,exam_date,recovery_type,recovery_score,recovery_date,status,attendance,comments,work1_date,work2_date,work3_date,work4_date,work5_date,work6_date)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(student_id,partial,subject_id) DO UPDATE SET work1=excluded.work1,work2=excluded.work2,work3=excluded.work3,work4=excluded.work4,work5=excluded.work5,work6=excluded.work6,exam=excluded.exam,exam_date=excluded.exam_date,recovery_type=excluded.recovery_type,recovery_score=excluded.recovery_score,recovery_date=excluded.recovery_date,status=excluded.status,attendance=excluded.attendance,comments=excluded.comments,work1_date=excluded.work1_date,work2_date=excluded.work2_date,work3_date=excluded.work3_date,work4_date=excluded.work4_date,work5_date=excluded.work5_date,work6_date=excluded.work6_date""",
                    (student_ids[code], partial, None, *works, exam, exam_date, recovery_type, recovery_score, recovery_date, status, attendance, comments, *dates))
            if "Configuración" in workbook.sheetnames:
                imported_config = {str(row[0]).strip(): row[1] for row in workbook["Configuración"].iter_rows(min_row=2, values_only=True) if row[0]}
                connection.execute("UPDATE teacher_settings SET school_name=?,teacher_name=?,group_name=?,evaluation_criteria=? WHERE teacher_id=?",
                                   (str(imported_config.get("school_name", "Colegio") or "Colegio"),
                                    str(imported_config.get("teacher_name", "Docente") or "Docente"),
                                    str(imported_config.get("group_name", "Grupo") or "Grupo"),
                                    str(imported_config.get("evaluation_criteria", "") or ""), teacher_id))
        flash("Datos importados correctamente. Los registros existentes fueron actualizados por código.", "success")
    except Exception as error:
        flash(f"No se pudo importar el archivo: {error}", "error")
    return redirect(url_for("config"))


@app.get("/statistics")
@guide_required
def statistics():
    teacher_id = session.get("teacher_id")
    with db() as connection:
        students = connection.execute("""
            SELECT s.* FROM students s
            LEFT JOIN groups g ON g.id=s.group_id
            WHERE g.teacher_id=? OR (s.group_id IS NULL AND s.teacher_id=?)
            ORDER BY s.name
        """, (teacher_id, teacher_id)).fetchall()
        subject_rows = connection.execute("SELECT id,name FROM subjects").fetchall()
    subject_names = {row["id"]: row["name"] for row in subject_rows}
    summaries = []
    for student in students:
        subjects, final = summary(student)
        for sid, data in subjects.items():
            summaries.append({"student": student, "subject_id": sid, "subject_name": subject_names.get(sid, "General") if sid else "General", "partials": data["partials"], "total": data["total"], "overall": final})
    partial_stats = []
    for partial in PARTIALS:
        values = [item["partials"][partial]["result"] for item in summaries if partial in item["partials"]]
        partial_stats.append({"name": partial_name(partial), "average": round(sum(values) / len(values), 2) if values else 0,
                              "approved": sum(value >= 60 for value in values), "count": len(values)})
    return render_template("statistics.html", summaries=summaries, partial_stats=partial_stats)





@app.get("/print-reports")
@report_access_required
def print_reports():
    teacher_id = session.get("teacher_id")
    with db() as connection:
        if teacher_is_admin(teacher_id) or teacher_is_secretary(teacher_id):
            students = connection.execute("""
                SELECT s.*, g.name AS group_name FROM students s
                LEFT JOIN groups g ON g.id=s.group_id
                ORDER BY g.name, s.name
            """).fetchall()
        elif get_teacher_role(teacher_id) == "guide":
            students = connection.execute("""
                SELECT s.*, g.name AS group_name FROM students s
                LEFT JOIN groups g ON g.id=s.group_id
                WHERE g.teacher_id=? OR (s.group_id IS NULL AND s.teacher_id=?)
                ORDER BY g.name, s.name
            """, (teacher_id, teacher_id)).fetchall()
        else:
            students = connection.execute("""
                SELECT DISTINCT s.*, g.name AS group_name
                FROM students s
                LEFT JOIN groups g ON g.id=s.group_id
                LEFT JOIN student_classes sc ON sc.student_id=s.id
                LEFT JOIN classes c ON c.id=sc.class_id
                WHERE s.teacher_id=? OR c.teacher_id=?
                ORDER BY g.name, s.name
            """, (teacher_id, teacher_id)).fetchall()
    return render_template("print_reports.html", students=students)


def requested_partials(source):
    selected = []
    for value in source.getlist("partial"):
        try:
            number = int(value)
            if number in PARTIALS and number not in selected:
                selected.append(number)
        except (TypeError, ValueError):
            continue
    return sorted(selected) or list(PARTIALS)


@app.get("/reports/<int:student_id>/pdf")
@report_access_required
def teacher_pdf(student_id):
    return make_pdf([student_id], requested_partials(request.args))


@app.post("/reports/pdf")
@report_access_required
def teacher_selected_pdf():
    student_ids = []
    for value in request.form.getlist("student_id"):
        try:
            student_ids.append(int(value))
        except ValueError:
            continue
    if not student_ids:
        flash("Selecciona al menos un estudiante.", "error")
        return redirect(url_for("print_reports"))
    return make_pdf(student_ids, requested_partials(request.form))


@app.route('/academic-structure', methods=['GET', 'POST'])
@admin_required
def academic_structure():
    if request.method == 'POST':
        kind = request.form.get('kind')
        action = request.form.get('action')
        try:
            with db() as connection:
                if action == 'update_section':
                    section_id = request.form.get('section_id', type=int)
                    if not section_id:
                        raise ValueError('Debe indicar la sección que desea editar.')
                    name = request.form.get('name', '').strip()
                    shift_value = clean_choice(request.form.get('shift'), SHIFT_OPTIONS, 'Matutino')
                    academic_year_id = request.form.get('academic_year_id', type=int)
                    grade_id = request.form.get('grade_id', type=int)
                    teacher_guide_id = request.form.get('teacher_guide_id', type=int) or None
                    if not name:
                        raise ValueError('El nombre de la sección es obligatorio.')
                    connection.execute(
                        'UPDATE sections SET academic_year_id=?, grade_id=?, name=?, shift=?, teacher_guide_id=? WHERE id=?',
                        (academic_year_id, grade_id, name, shift_value, teacher_guide_id, section_id)
                    )
                elif action == 'delete_section':
                    section_id = request.form.get('section_id', type=int)
                    if not section_id:
                        raise ValueError('Debe indicar la sección que desea eliminar.')
                    connection.execute('DELETE FROM sections WHERE id=?', (section_id,))
                elif action == 'update_grade':
                    grade_id = request.form.get('grade_id', type=int)
                    level_value = clean_choice(request.form.get('level'), LEVEL_OPTIONS, 'Primaria')
                    connection.execute('UPDATE grades SET name=?, code=?, level=? WHERE id=?', (request.form.get('name','').strip(), request.form.get('code','').strip(), level_value, grade_id))
                elif action == 'update_year':
                    year_id = request.form.get('year_id', type=int)
                    year_value = int(request.form['year'])
                    existing_year = connection.execute('SELECT id FROM academic_years WHERE year=? AND id!=?', (year_value, year_id)).fetchone()
                    if existing_year:
                        raise ValueError(f'El año lectivo {year_value} ya existe.')
                    connection.execute('UPDATE academic_years SET year=?, start_date=?, end_date=?, status=? WHERE id=?', (year_value, request.form.get('start_date',''), request.form.get('end_date',''), request.form.get('status','open'), year_id))
                elif kind == 'structure':
                    year_value = int(request.form['year'])
                    existing_year = connection.execute('SELECT id FROM academic_years WHERE year=?', (year_value,)).fetchone()
                    if not existing_year:
                        connection.execute('INSERT INTO academic_years(year,start_date,end_date,status) VALUES(?,?,?,?)', (year_value, request.form.get('start_date',''), request.form.get('end_date',''), request.form.get('status','open')))
                    year_id = connection.execute('SELECT id FROM academic_years WHERE year=?', (year_value,)).fetchone()['id']
                    level_value = clean_choice(request.form.get('level'), LEVEL_OPTIONS, 'Primaria')
                    shift_value = clean_choice(request.form.get('shift'), SHIFT_OPTIONS, 'Matutino')
                    connection.execute('INSERT OR IGNORE INTO grades(name,code,level) VALUES(?,?,?)', (request.form['grade_name'].strip(), request.form['grade_code'].strip(), level_value))
                    grade_id = connection.execute('SELECT id FROM grades WHERE code=?', (request.form['grade_code'].strip(),)).fetchone()['id']
                    connection.execute('INSERT INTO sections(academic_year_id,grade_id,name,shift,teacher_guide_id) VALUES(?,?,?,?,?)', (year_id, grade_id, request.form['section_name'].strip(), shift_value, request.form.get('teacher_guide_id') or None))
                elif kind == 'year':
                    year_value = int(request.form['year'])
                    existing_year = connection.execute('SELECT id FROM academic_years WHERE year=?', (year_value,)).fetchone()
                    if existing_year:
                        raise ValueError(f'El año lectivo {year_value} ya existe.')
                    connection.execute('INSERT INTO academic_years(year,start_date,end_date,status) VALUES(?,?,?,?)', (year_value, request.form.get('start_date',''), request.form.get('end_date',''), request.form.get('status','open')))
                elif kind == 'grade':
                    level_value = clean_choice(request.form.get('level'), LEVEL_OPTIONS, 'Primaria')
                    connection.execute('INSERT INTO grades(name,code,level) VALUES(?,?,?)', (request.form['name'].strip(), request.form['code'].strip(), level_value))
                elif kind == 'section':
                    shift_value = clean_choice(request.form.get('shift'), SHIFT_OPTIONS, 'Matutino')
                    connection.execute('INSERT INTO sections(academic_year_id,grade_id,name,shift,teacher_guide_id) VALUES(?,?,?,?,?)', (request.form['academic_year_id'], request.form['grade_id'], request.form['name'].strip(), shift_value, request.form.get('teacher_guide_id') or None))
                else:
                    raise ValueError('Tipo inválido')
            if action == 'delete_section':
                flash('Sección eliminada.', 'success')
            elif action in ('update_section', 'update_grade', 'update_year'):
                flash('Registro académico actualizado.', 'success')
            else:
                flash('Registro académico creado.', 'success')
        except (sqlite3.IntegrityError, ValueError) as error:
            error_text = str(error)
            if 'academic_years' in error_text or 'year' in error_text.lower() and 'unique' in error_text.lower():
                year_value = request.form.get('year', '').strip()
                message = f'El año lectivo {year_value} ya existe.' if year_value else 'El año lectivo ya existe.'
            elif 'sections' in error_text and 'UNIQUE' in error_text.upper():
                message = 'Esa sección ya existe para el año y grado seleccionados.'
            else:
                message = str(error)
            flash(f'No se pudo guardar: {message}', 'error')
        return redirect(url_for('academic_structure'))
    with db() as connection:
        years = connection.execute('SELECT * FROM academic_years ORDER BY year DESC').fetchall()
        grades = connection.execute('SELECT * FROM grades WHERE active=1 ORDER BY name').fetchall()
        guides = connection.execute('SELECT id,name FROM teachers WHERE is_admin=0 ORDER BY name').fetchall()
        sections = connection.execute('SELECT s.*, ay.year, g.name AS grade_name, t.name AS guide_name FROM sections s JOIN academic_years ay ON ay.id=s.academic_year_id JOIN grades g ON g.id=s.grade_id LEFT JOIN teachers t ON t.id=s.teacher_guide_id WHERE s.active=1 ORDER BY ay.year DESC, g.name, s.name').fetchall()
    return render_template('academic_structure_v4.html', years=years, grades=grades, guides=guides, sections=sections, shift_options=SHIFT_OPTIONS, level_options=LEVEL_OPTIONS)


@app.get('/academic-structure/mined-reference')
@admin_required
def mined_reference():
    return render_template('mined_reference.html')


@app.route('/subject-catalog', methods=['GET', 'POST'])
@admin_required
def subject_catalog():
    if request.method == 'POST':
        action = request.form.get('action')
        subject_id = request.form.get('subject_id')
        try:
            with db() as connection:
                if action == 'replace':
                    old = connection.execute('SELECT name FROM subject_catalog WHERE id=?', (request.form['subject_id'],)).fetchone()
                    connection.execute('UPDATE subject_catalog SET code=?,name=?,area=?,description=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (request.form['code'].strip(), request.form['name'].strip(), request.form.get('area','').strip(), request.form.get('description','').strip(), request.form['subject_id']))
                    if old:
                        connection.execute('UPDATE subjects SET name=? WHERE name=?', (request.form['name'].strip(), old['name']))
                elif action == 'create':
                    connection.execute('INSERT INTO subject_catalog(code,name,area,description) VALUES(?,?,?,?)', (request.form['code'].strip(), request.form['name'].strip(), request.form.get('area','').strip(), request.form.get('description','').strip()))
                elif action == 'update':
                    old = connection.execute('SELECT name FROM subject_catalog WHERE id=?', (subject_id,)).fetchone()
                    connection.execute('UPDATE subject_catalog SET code=?,name=?,area=?,description=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (request.form['code'].strip(), request.form['name'].strip(), request.form.get('area','').strip(), request.form.get('description','').strip(), subject_id))
                    if old:
                        connection.execute('UPDATE subjects SET name=? WHERE name=?', (request.form['name'].strip(), old['name']))
                elif action == 'toggle':
                    connection.execute('UPDATE subject_catalog SET active=CASE active WHEN 1 THEN 0 ELSE 1 END,updated_at=CURRENT_TIMESTAMP WHERE id=?', (subject_id,))
                elif action == 'delete':
                    refs = connection.execute('SELECT (SELECT COUNT(*) FROM academic_offerings WHERE subject_id=?) + (SELECT COUNT(*) FROM section_subjects ss JOIN academic_offerings ao ON ao.id=ss.academic_offering_id WHERE ao.subject_id=?) AS n', (subject_id, subject_id)).fetchone()['n']
                    if refs:
                        raise ValueError('La asignatura tiene referencias académicas; desactívala en lugar de eliminarla.')
                    connection.execute('DELETE FROM subject_catalog WHERE id=?', (subject_id,))
            flash('Catálogo actualizado.', 'success')
        except sqlite3.IntegrityError:
            with db() as connection:
                duplicate = connection.execute('SELECT * FROM subject_catalog WHERE code=? COLLATE NOCASE OR name=? COLLATE NOCASE LIMIT 1', (request.form.get('code','').strip(), request.form.get('name','').strip())).fetchone()
            return render_template('subject_catalog_v3.html', subjects=_catalog_rows(), duplicate=duplicate, attempted=dict(request.form)), 409
        except (sqlite3.IntegrityError, ValueError) as error:
            flash(f'No se pudo guardar: {error}', 'error')
        return redirect(url_for('subject_catalog'))
    return render_template('subject_catalog_v3.html', subjects=_catalog_rows())


def _catalog_rows():
    with db() as connection:
        return connection.execute('SELECT * FROM subject_catalog ORDER BY active DESC, id').fetchall()


def make_pdf(student_ids, selected_partials):
    teacher_id = session.get("teacher_id")
    if not student_ids or any(not teacher_can_access_student(student_id, teacher_id) for student_id in student_ids):
        return "Estudiante no encontrado", 404
    with db() as connection:
        placeholders = ",".join("?" for _ in student_ids)
        students = connection.execute(
            f"SELECT s.*, g.name AS group_name FROM students s LEFT JOIN groups g ON g.id=s.group_id WHERE s.id IN ({placeholders}) ORDER BY s.name",
            tuple(student_ids)).fetchall()
        subject_rows = connection.execute("SELECT id, name FROM subjects").fetchall()
        conduct_rows = connection.execute("SELECT * FROM conduct_evaluations WHERE student_id IN ({})".format(placeholders), tuple(student_ids)).fetchall()
    if not students: return "Estudiante no encontrado", 404
    subject_names = {row["id"]: row["name"] for row in subject_rows}
    conduct_by_student = {}
    for row in conduct_rows:
        conduct_by_student.setdefault(row["student_id"], {})[row["partial"]] = dict(row)
    current = settings(); output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=landscape(letter), rightMargin=.45*inch, leftMargin=.45*inch, topMargin=.4*inch, bottomMargin=.4*inch)
    styles = getSampleStyleSheet(); center_style = ParagraphStyle("center", parent=styles["Normal"], alignment=TA_CENTER); story = []
    logo_path = os.path.join(UPLOAD_DIR, current["logo_filename"]) if current["logo_filename"] else ""
    header_style = TableStyle([("BACKGROUND", (0,0), (-1,0), "#17365d"), ("TEXTCOLOR", (0,0), (-1,0), "white"), ("GRID", (0,0), (-1,-1), .5, "#b7c3d0"), ("ALIGN", (0,0), (-1,0), "LEFT"), ("ALIGN", (1,1), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("FONTSIZE", (0,0), (-1,-1), 8), ("PADDING", (0,0), (-1,-1), 5)])
    for index, student in enumerate(students):
        if index: story.append(PageBreak())
        partials_by_subject, total = summary(student)
        if logo_path and os.path.isfile(logo_path): story.append(PDFImage(logo_path, width=.65*inch, height=.65*inch))
        subject_names_list = sorted({subject_names.get(sid, "General") if sid else "General" for sid in partials_by_subject.keys()})
        subject_label = ", ".join(subject_names_list) if subject_names_list else "Sin materias registradas"
        partials_label = ", ".join(partial_name(p) for p in selected_partials) if selected_partials else "Todos los parciales"
        story += [Paragraph(current["school_name"], styles["Title"]), Paragraph("REPORTE ACADÉMICO", styles["Heading2"]), Paragraph(f"Docente: {current['teacher_name']} · Grupo: {student['group_name'] or current['group_name']} · Estudiante: {student['name']} · Código: {student['code']}", styles["Normal"]), Paragraph(f"Materias: {subject_label}", styles["Normal"]), Paragraph(f"Parciales incluidos: {partials_label}", styles["Normal"]), Spacer(1, 10)]
        conduct_entries = conduct_by_student.get(student["id"], {})
        if not conduct_entries and student["conduct_score"] is not None:
            conduct_entries[1] = {"quantitative": student["conduct_score"], "qualitative": student["conduct"] or "Sin registrar", "criteria": student["conduct_criteria"], "incidents": student["conduct_incidents"], "observations": student["observations"]}
        conduct_label = conduct_entries.get(1, {}).get("qualitative") or student["conduct"] or "Sin registrar"
        conduct_quantitative = f"{conduct_entries.get(1, {}).get('quantitative', student['conduct_score']):.2f} / 100" if conduct_entries.get(1, {}).get('quantitative', student['conduct_score']) is not None else "Sin registrar"
        conduct_data = [["Parcial", "Cuantitativa", "Cualitativa", "Criterios utilizados", "Incidentes registrados", "Observaciones"]]
        for partial in range(1, 5):
            entry = conduct_entries.get(partial, {})
            conduct_data.append([
                partial_name(partial),
                f"{entry['quantitative']:.2f} / 100" if entry.get("quantitative") is not None else "Sin calificación",
                entry.get("qualitative") or "Sin valoración",
                entry.get("criteria") or "Sin registrar",
                entry.get("incidents") or "Ninguno registrado",
                entry.get("observations") or "Sin observaciones",
            ])
        # Matriz MINED: cada corte tiene cuantitativa y cualitativa en columnas
        # paralelas; los semestres y el cierre anual también se promedian.
        summary_data = [
            ["Asignatura / componente", "Parcial I", "", "Parcial II", "", "Parcial III", "", "Parcial IV", "", "Nota final", ""],
            ["", "Cuantitativa", "Cualitativa", "Cuantitativa", "Cualitativa", "Cuantitativa", "Cualitativa", "Cuantitativa", "Cualitativa", "Cuantitativa", "Cualitativa"],
        ]
        detail_data = [["Materia", "Parcial", "Evaluación", "Nota", "Fecha"]]
        extraordinary = [["Materia", "Parcial", "Tipo", "Fecha", "Nota / 40"]]
        selected_total = 0.0
        # La boleta debe incluir todo el catálogo de asignaturas, aunque aún
        # no existan registros de calificación para el estudiante.
        subject_ids = sorted(set(subject_names) | set(partials_by_subject), key=lambda sid: subject_names.get(sid, "General").lower())
        for sid in subject_ids:
            subject_data = partials_by_subject.get(sid, {"partials": {}})
            subject_name = subject_names.get(sid, "General") if sid else "General"
            subject_values = {}
            for p in sorted(subject_data["partials"]):
                row = subject_data["partials"][p]
                subject_values[p] = row["result"]
                if not selected_partials or p in selected_partials:
                    selected_total += row["result"]
                if selected_partials and p not in selected_partials:
                    continue
                recovery = f"{row['recovery_score']:.2f}" if row.get("recovery_type") else "-"
                for i in range(1, 7):
                    detail_data.append([subject_name, partial_name(p), f"Trabajo {i}", f"{row[f'work{i}']:.2f} / 10", row.get(f"work{i}_date") or "-"])
                detail_data.append([subject_name, partial_name(p), "Examen original", f"{row['exam']:.2f} / 40", row.get("exam_date") or "-"])
                if row.get("recovery_type"):
                    detail_data.append([subject_name, partial_name(p), row["recovery_type"], f"{row['recovery_score']:.2f} / 40", row.get("recovery_date") or "-"])
                    extraordinary.append([subject_name, partial_name(p), row["recovery_type"], row.get("recovery_date") or "-", f"{row['recovery_score']:.2f}"])
                detail_data.append([subject_name, partial_name(p), "Examen aplicado", f"{applied_exam(row):.2f} / 40", row.get("exam_date") or row.get("recovery_date") or "-"])
                detail_data.append([subject_name, partial_name(p), "Nota final del parcial", f"{row['result']:.2f} / 100", "-"])
            visible = {p: subject_values.get(p) for p in range(1, 5)}
            final_values = [value for p, value in subject_values.items() if not selected_partials or p in selected_partials]
            final_value = sum(final_values) / len(final_values) if final_values else None
            row_data = [subject_name]
            for value in [visible[1], visible[2], visible[3], visible[4], final_value]:
                row_data.extend([f"{value:.2f}" if value is not None else "Sin calificación", qualitative_learning_label(value) if value is not None else "Sin calificación"])
            summary_data.append(row_data)
        if len(summary_data) == 2:
            summary_data.append(["-"] + ["-"] * 10)
            detail_data.append(["-", "-", "Sin registros", "-", "-"])
        conduct_row = ["Conducta (desempeño personal y ciudadano)"]
        for partial in range(1, 5):
            entry = conduct_entries.get(partial, {})
            conduct_quantitative_short = f"{entry['quantitative']:.2f}" if entry.get("quantitative") is not None else "Sin calificación"
            conduct_row.extend([conduct_quantitative_short, entry.get("qualitative") or "Sin valoración"])
        final_conduct = conduct_entries.get(4) or conduct_entries.get(1) or {}
        conduct_row.extend(["-", final_conduct.get("qualitative") or "-"])
        summary_data.append(conduct_row)
        conduct_table = Table(conduct_data, colWidths=[.9*inch, 1.05*inch, 1.05*inch, 2.25*inch, 2.25*inch, 2.35*inch]); conduct_table.setStyle(header_style)
        summary_table = Table(summary_data, colWidths=[2.1*inch] + [.82*inch] * 10)
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), "#17365d"), ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
            ("BACKGROUND", (0, 1), (-1, 1), "#dbe7f3"), ("TEXTCOLOR", (0, 1), (-1, 1), "#17365d"),
            ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (2, 0)), ("SPAN", (3, 0), (4, 0)),
            ("SPAN", (5, 0), (6, 0)), ("SPAN", (7, 0), (8, 0)), ("SPAN", (9, 0), (10, 0)),
            ("GRID", (0, 0), (-1, -1), .4, "#b7c3d0"), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("FONTSIZE", (0, 0), (-1, -1), 6), ("PADDING", (0, 0), (-1, -1), 3),
        ]))
        detail_table = Table(detail_data, colWidths=[1.25*inch, .8*inch, 1.7*inch, 1.1*inch, 1.1*inch]); detail_table.setStyle(header_style)
        extraordinary_table = Table(extraordinary, colWidths=[1.2*inch, .75*inch, 1.7*inch, 1.2*inch, .9*inch]); extraordinary_table.setStyle(header_style)
        rules = "Referencia MINED: dos cortes por semestre y cuatro cortes anuales. La nota final de esta boleta es el promedio de los cuatro cortes registrados. Equivalencias: AA (90–100), AS (76–89), AF (60–75) y AI (menos de 60). La conducta se registra cualitativamente como desempeño personal y ciudadano. En este sistema, cada trabajo vale 0–10, el examen vale 0–40 y la nota del corte es acumulado + examen aplicado."
        story += [Paragraph("Resumen de notas por materia y cortes evaluativos", styles["Heading3"]), summary_table, Spacer(1, 6), Paragraph("La conducta se registra como desempeño personal y ciudadano, de forma cualitativa.", styles["Normal"]), Spacer(1, 8), Paragraph("Detalle de conducta", styles["Heading3"]), conduct_table, Spacer(1, 10)]
        if len(extraordinary) > 1:
            story += [Paragraph("Notas extraordinarias registradas", styles["Heading3"]), extraordinary_table, Spacer(1, 10)]
        if selected_partials:
            count = len(selected_partials)
            story += [Paragraph(f"Total de los parciales seleccionados: {selected_total:.2f} / {count * 100:.2f}", styles["Heading3"]), Paragraph(f"Promedio de los parciales seleccionados: {selected_total / max(count, 1):.2f} / 100", styles["Normal"])]
        else:
            story += [Paragraph(f"Total de los cuatro parciales: {total:.2f} / 400", styles["Heading3"]), Paragraph(f"Nota final del año: {total / 4:.2f} / 100", styles["Normal"])]
        story += [Paragraph(f"Criterios evaluativos: {current['evaluation_criteria'] or 'No registrados'}", styles["Normal"]), Spacer(1, 6), Paragraph("Reglas de evaluación", styles["Heading3"]), Paragraph(rules, styles["Normal"]), Spacer(1, 28), Paragraph("______________________________                         ______________________________", center_style), Paragraph("Firma del docente                                                        Firma del estudiante/tutor", center_style)]
    document.build(story); output.seek(0)
    return send_file(output, mimetype="application/pdf", as_attachment=True, download_name="reportes-academicos.pdf")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
