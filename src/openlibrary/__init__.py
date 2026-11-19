"""OpenLibrary - biblioteca de modelos 3D para 3ds Max, como app independiente.

Se navega, busca y organiza sin tener 3ds Max abierto. Cuando hay un Max con
el puente instalado (openlibrary_max), se le arrastran los assets.

    python run_openlibrary.py
"""
import os
import sys

from .config import VERSION  # noqa: F401


def resource_dir():
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "openlibrary")
    return os.path.dirname(os.path.abspath(__file__))


def icon_path(name="openlibrary"):
    return os.path.join(resource_dir(), "icons", name + ".svg")


def icon(name="openlibrary", tint=None):
    """Icono de la interfaz, adaptado al modo claro u oscuro (o teñido de un color)."""
    from . import theme
    return theme.icon(name, tint)


def app_icon_file():
    """Icono .ico de la app (ventana, barra de tareas, accesos directos)."""
    return os.path.join(resource_dir(), "icons", "openlibrary.ico")


def app_icon():
    from .qt import QtGui
    ic = QtGui.QIcon(app_icon_file())
    return ic if not ic.isNull() else icon("openlibrary_app")


def main(argv=None):
    from .app import run
    return run(argv if argv is not None else sys.argv)
