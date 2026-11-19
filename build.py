"""Empaqueta la app OpenLibrary para Windows.

    python build.py

Necesita PySide6 y PyInstaller en el Python con el que se ejecuta
(pip install -r requirements-dev.txt). Genera:
    dist/OpenLibrary/OpenLibrary.exe          (carpeta lista para usar)
    dist/OpenLibrary-<versión>-win64.zip      (para subir a la release)

El puente de 3ds Max (src/openlibrary_max) va dentro y se instala desde la app:
Ajustes > Instalación.
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
DIST = os.path.join(HERE, "dist")


def version():
    with open(os.path.join(SRC, "openlibrary", "config.py"), encoding="utf-8") as fh:
        return re.search(r'VERSION = "([^"]+)"', fh.read()).group(1)


def check_versions():
    """La app y el puente tienen que ir con la misma versión."""
    with open(os.path.join(SRC, "openlibrary_max", "__init__.py"), encoding="utf-8") as fh:
        bridge = re.search(r'VERSION = "([^"]+)"', fh.read()).group(1)
    if bridge != version():
        sys.exit("La versión del puente (%s) no coincide con la de la app (%s)" % (bridge, version()))


def build():
    check_versions()
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        sys.exit("Falta PyInstaller: pip install -r requirements-dev.txt")
    sep = os.pathsep
    icons = os.path.join(SRC, "openlibrary", "icons")
    ico = os.path.join(icons, "openlibrary.ico")
    sys.path.insert(0, SRC)
    from PySide6 import QtGui
    from openlibrary.iconfile import svg_to_ico
    _app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])  # noqa: F841 (Qt la necesita viva)
    svg_to_ico(os.path.join(icons, "openlibrary_app.svg"), ico)
    pyi.run([
        os.path.join(HERE, "run_openlibrary.py"),
        "--noconfirm", "--clean", "--windowed",
        "--name", "OpenLibrary",
        "--icon", ico,
        "--paths", SRC,
        "--distpath", DIST,
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", os.path.join(HERE, "build"),
        "--add-data", os.path.join(SRC, "openlibrary", "icons") + sep + "openlibrary/icons",
        "--add-data", os.path.join(SRC, "openlibrary_max") + sep + "openlibrary_max",
        "--exclude-module", "pymxs",
    ])
    out = os.path.join(DIST, "OpenLibrary-%s-win64.zip" % version())
    folder = os.path.join(DIST, "OpenLibrary")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(folder):
            for f in files:
                if f.endswith(".pyc") and "__pycache__" in root and "openlibrary_max" in root:
                    continue
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, DIST))
    return out


if __name__ == "__main__":
    print("OK ->", build())
