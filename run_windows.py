"""Launcher for the Windows desktop package."""

import os
import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path


def application_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def main() -> None:
    data_dir = application_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DB_PATH", str(data_dir / "notas.db"))
    os.environ.setdefault("UPLOAD_DIR", str(data_dir / "uploads"))
    os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(32))

    from app import app

    def open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:5000/login")

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
