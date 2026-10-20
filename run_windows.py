"""Launcher for the Windows desktop package."""

import os
import json
import ipaddress
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk


def application_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def local_ipv4_addresses() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addresses.add(item[4][0])
    except OSError:
        pass
    return sorted(addresses, key=lambda value: (value != "127.0.0.1", value))


def address_label(address: str) -> str:
    if address == "127.0.0.1":
        return "Solo este equipo"
    try:
        ip = ipaddress.ip_address(address)
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return "Tailscale"
        if ip.is_private:
            return "LAN"
    except ValueError:
        pass
    return "Red"


def network_settings(base_dir: Path) -> tuple[str, int, str]:
    config_path = base_dir / "network.json"
    defaults = {"host": "127.0.0.1", "port": 5000}
    try:
        defaults.update(json.loads(config_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        pass

    addresses = local_ipv4_addresses()
    root = tk.Tk()
    root.title("Notas Estudiantes · Red")
    root.resizable(False, False)
    root.columnconfigure(1, weight=1)
    selected = tk.StringVar(value=defaults["host"] if defaults["host"] in addresses else "127.0.0.1")
    port = tk.StringVar(value=str(defaults.get("port", 5000)))
    result: dict[str, object] = {}

    ttk.Label(root, text="Configuración de red", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, padx=22, pady=(18, 4))
    ttk.Label(root, text="Elige cómo podrán acceder a Notas Estudiantes.").grid(row=1, column=0, columnspan=2, padx=22, pady=(0, 14))
    ttk.Label(root, text="Dirección de escucha:").grid(row=2, column=0, sticky="w", padx=(22, 10), pady=5)
    choices = [
        ("Solo este equipo · 127.0.0.1", "127.0.0.1"),
        ("Todas las interfaces · LAN/Tailscale · 0.0.0.0", "0.0.0.0"),
    ] + [(f"{address_label(address)} · {address}", address) for address in addresses if address != "127.0.0.1"]
    labels = {label: value for label, value in choices}
    label_by_value = {value: label for label, value in choices}
    address_box = ttk.Combobox(root, state="readonly", width=34, values=list(labels), textvariable=tk.StringVar(value=label_by_value.get(selected.get(), choices[0][0])))
    address_box.grid(row=2, column=1, sticky="ew", padx=(0, 22), pady=5)
    ttk.Label(root, text="IP manual (opcional):").grid(row=3, column=0, sticky="w", padx=(22, 10), pady=5)
    manual = ttk.Entry(root, width=36)
    manual.grid(row=3, column=1, sticky="ew", padx=(0, 22), pady=5)
    ttk.Label(root, text="Puerto:").grid(row=4, column=0, sticky="w", padx=(22, 10), pady=5)
    ttk.Entry(root, textvariable=port, width=10).grid(row=4, column=1, sticky="w", padx=(0, 22), pady=5)
    ttk.Label(root, text="Para LAN/Tailscale, permite este puerto en el Firewall de Windows.", foreground="#52677f").grid(row=5, column=0, columnspan=2, padx=22, pady=(4, 14))

    def save() -> None:
        chosen = manual.get().strip() or labels.get(address_box.get(), "127.0.0.1")
        try:
            chosen_port = int(port.get().strip())
            if not 1 <= chosen_port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Puerto inválido", "Escribe un puerto entre 1 y 65535.", parent=root)
            return
        browser_target = next((address for address in addresses if address != "127.0.0.1"), "127.0.0.1") if chosen == "0.0.0.0" else chosen
        result.update(host=chosen, port=chosen_port, browser_host=browser_target)
        try:
            config_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("No se pudo guardar", str(error), parent=root)
            return
        root.destroy()

    def cancel() -> None:
        result.update(host=defaults["host"], port=int(defaults.get("port", 5000)), browser_host=defaults.get("browser_host", defaults["host"]))
        root.destroy()

    buttons = ttk.Frame(root)
    buttons.grid(row=6, column=0, columnspan=2, pady=(0, 18))
    ttk.Button(buttons, text="Guardar y arrancar", command=save).pack(side="left", padx=5)
    ttk.Button(buttons, text="Cancelar", command=cancel).pack(side="left", padx=5)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    return str(result.get("host", defaults["host"])), int(result.get("port", defaults.get("port", 5000))), str(result.get("browser_host", defaults.get("browser_host", defaults["host"])))


def main() -> None:
    base_dir = application_dir()
    host, port, browser_host = network_settings(base_dir)
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DB_PATH", str(data_dir / "notas.db"))
    os.environ.setdefault("UPLOAD_DIR", str(data_dir / "uploads"))
    os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(32))

    from app import app

    def open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(f"http://{browser_host}:{port}/login")

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
