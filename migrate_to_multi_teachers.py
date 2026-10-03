#!/usr/bin/env python3
import os
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("DB_PATH", "/data/notas.db")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate():
    with connect() as conn:
        # ensure teachers and teacher_settings exist (init_db should do it, but keep idempotent)
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '', password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS teacher_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, teacher_id INTEGER NOT NULL UNIQUE,
            teacher_name TEXT NOT NULL DEFAULT 'Docente',
            group_name TEXT NOT NULL DEFAULT 'Grupo',
            evaluation_criteria TEXT NOT NULL DEFAULT '',
            school_name TEXT NOT NULL DEFAULT 'Colegio',
            logo_filename TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
        ''')

        # make sure teacher_id columns exist
        def has_column(table, column):
            return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})").fetchall())

        if not has_column("groups", "teacher_id"):
            conn.execute("ALTER TABLE groups ADD COLUMN teacher_id INTEGER")
        if not has_column("students", "teacher_id"):
            conn.execute("ALTER TABLE students ADD COLUMN teacher_id INTEGER")

        # if no teachers exist, create one from settings
        teacher = conn.execute("SELECT id FROM teachers ORDER BY id LIMIT 1").fetchone()
        if not teacher:
            settings = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
            settings = dict(settings) if settings else {}
            if settings:
                password = settings.get("teacher_password") or generate_password_hash("docente123")
                name = settings.get("teacher_name") or "Docente"
            else:
                name = "Docente"
                password = generate_password_hash("docente123")
            conn.execute("INSERT INTO teachers(name,password) VALUES(?,?)", (name, password))
            teacher = conn.execute("SELECT id FROM teachers ORDER BY id LIMIT 1").fetchone()

        teacher_id = teacher["id"]

        # insert or update teacher_settings from settings table
        if conn.execute("SELECT 1 FROM teacher_settings WHERE teacher_id=?", (teacher_id,)).fetchone():
            # update
            settings = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
            settings = dict(settings) if settings else {}
            if settings:
                conn.execute("UPDATE teacher_settings SET teacher_name=?,group_name=?,evaluation_criteria=?,school_name=?,logo_filename=? WHERE teacher_id=?",
                             (settings.get("teacher_name"), settings.get("group_name"), settings.get("evaluation_criteria", ""), settings.get("school_name", "Colegio"), settings.get("logo_filename", ""), teacher_id))
        else:
            settings = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
            settings = dict(settings) if settings else {}
            if settings:
                conn.execute("INSERT INTO teacher_settings(teacher_id,teacher_name,group_name,evaluation_criteria,school_name,logo_filename) VALUES(?,?,?,?,?,?)",
                             (teacher_id, settings.get("teacher_name"), settings.get("group_name"), settings.get("evaluation_criteria", ""), settings.get("school_name", "Colegio"), settings.get("logo_filename", "")))

        # assign existing groups and students to this teacher where missing
        conn.execute("UPDATE groups SET teacher_id=? WHERE teacher_id IS NULL", (teacher_id,))
        conn.execute("UPDATE students SET teacher_id=? WHERE teacher_id IS NULL", (teacher_id,))

    print(f"Migración completada. Teacher id: {teacher_id}")


if __name__ == "__main__":
    migrate()
