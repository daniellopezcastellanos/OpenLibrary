"""Instala / quita el puente OpenLibrary en cada 3ds Max del usuario.

Archivos que pone (y quita) por versión, dentro de
%LOCALAPPDATA%\\Autodesk\\3dsMax\\<versión>\\ENU:
    scripts\\OpenLibrary\\openlibrary_max\\...     (el puente)
    scripts\\OpenLibrary\\app.json                 (cómo abrir la app desde Max y si poner su barra)
    scripts\\startup\\openlibrary_bridge.ms        (lo arranca al abrir Max)
"""
import glob
import json
import os
import re
import shutil
import sys

STARTUP_NAME = "openlibrary_bridge.ms"
MIN_VERSION = 2025          # PySide6 en Max


def bridge_source():
    """Carpeta openlibrary_max (en el .exe empaquetado o en el código fuente)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "openlibrary_max")
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "openlibrary_max"))


def bridge_version(folder):
    try:
        with open(os.path.join(folder, "__init__.py"), encoding="utf-8") as fh:
            m = re.search(r'VERSION = "([^"]+)"', fh.read())
            return m.group(1) if m else None
    except OSError:
        return None


def app_command():
    """Línea de comandos para abrir esta app (la usa el botón de Max)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    built = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                          "dist", "OpenLibrary", "OpenLibrary.exe"))
    if os.path.isfile(built):                 # desde el código, pero con la app ya construida: esa
        return [built]
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(w):
        exe = w
    entry = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                          "run_openlibrary.py"))
    return [exe, entry]


def toolbar_icon():
    """Icono del botón dentro de Max: el de la app (azulejo oscuro con los libros)."""
    from . import icon_path
    p = icon_path("openlibrary_app")
    return p if os.path.isfile(p) else None


class MaxTarget(object):
    def __init__(self, enu):
        self.enu = enu
        name = os.path.basename(os.path.dirname(enu))         # "2026 - 64bit"
        m = re.match(r"(\d{4})", name)
        self.year = int(m.group(1)) if m else 0
        self.label = "3ds Max %s" % (self.year or name)
        self.scripts = os.path.join(enu, "scripts", "OpenLibrary")
        self.bridge = os.path.join(self.scripts, "openlibrary_max")
        self.startup = os.path.join(enu, "scripts", "startup", STARTUP_NAME)

    @property
    def supported(self):
        return self.year >= MIN_VERSION

    def installed_version(self):
        if not os.path.isfile(self.startup):
            return None
        return bridge_version(self.bridge)

    def outdated(self):
        """¿El puente instalado es distinto del que trae esta app? (la versión no cambia entre arreglos,
        así que se comparan los archivos: los .py y el .ms del puente)."""
        if not self.installed_version():
            return False
        src = bridge_source()
        try:
            names = [n for n in os.listdir(src) if n.endswith((".py", ".ms", ".mcr")) and n != STARTUP_NAME]
        except OSError:
            return False
        for n in names:
            try:
                with open(os.path.join(src, n), "rb") as a, open(os.path.join(self.bridge, n), "rb") as b:
                    if a.read() != b.read():
                        return True
            except OSError:
                return True
        return False

    @property
    def app_json(self):
        return os.path.join(self.scripts, "app.json")

    def toolbar_enabled(self):
        """¿Pone el puente la barra con el botón de OpenLibrary dentro de Max?"""
        try:
            with open(self.app_json, encoding="utf-8") as fh:
                return bool(json.load(fh).get("toolbar", False))
        except (OSError, ValueError):
            return False

    def install(self, toolbar=None):
        """Copia el puente. toolbar=None conserva lo que se hubiera elegido antes."""
        if toolbar is None:
            toolbar = self.toolbar_enabled()
        src = bridge_source()
        if not os.path.isdir(src):
            raise RuntimeError("No encuentro los archivos del puente en %s" % src)
        if os.path.isdir(self.bridge):
            shutil.rmtree(self.bridge)
        shutil.copytree(src, self.bridge, ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                                         STARTUP_NAME))
        os.makedirs(os.path.dirname(self.startup), exist_ok=True)
        shutil.copyfile(os.path.join(src, STARTUP_NAME), self.startup)
        ico = toolbar_icon()
        if ico:
            shutil.copyfile(ico, os.path.join(self.bridge, "openlibrary.svg"))
        with open(self.app_json, "w", encoding="utf-8") as fh:
            json.dump({"command": app_command(), "toolbar": bool(toolbar)}, fh, indent=2)

    def fix_command(self):
        """Si el botón de Max apunta a otra cosa (p. ej. se instaló desde el código o la app se movió),
        lo vuelve a apuntar a esta app. Devuelve True si lo ha cambiado."""
        try:
            with open(self.app_json, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False
        cmd = app_command()
        if data.get("command") == cmd:
            return False
        data["command"] = cmd
        with open(self.app_json, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        return True

    def uninstall(self):
        if os.path.isfile(self.startup):
            os.remove(self.startup)
        if os.path.isdir(self.scripts):
            shutil.rmtree(self.scripts)
        # Macro que creó el botón (Max la copia en usermacros)
        for m in glob.glob(os.path.join(self.enu, "usermacros", "OpenLibrary-OpenLibrary*.mcr")):
            try:
                os.remove(m)
            except OSError:
                pass


def find_targets():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Autodesk", "3dsMax")
    out = [MaxTarget(enu) for enu in glob.glob(os.path.join(base, "*", "ENU"))]
    out.sort(key=lambda t: -t.year)
    return out
