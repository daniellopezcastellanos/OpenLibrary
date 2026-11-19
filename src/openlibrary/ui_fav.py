"""Favoritos: el corazón (dibujo e icono), la clave portable de cada elemento y los ajustes de la pestaña.

Los favoritos son de cada persona (ajuste «favorites», no va al espacio de trabajo compartido). Cada
pestaña decide en sus ajustes si su árbol enseña «Favoritos» y «Todos» (`tree_fav`, `tree_all`) y qué se
abre al entrar (`show`: «both» todos con los favoritos primero, «favorites», «all»).
"""
import os

from . import theme
from .qt import QtCore, QtGui


def heart_color():
    return theme.color(theme.ACCENT)


def heart_path(rect):
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QtGui.QPainterPath()
    path.moveTo(x + w / 2, y + h * 0.95)
    path.cubicTo(x - w * 0.15, y + h * 0.45, x + w * 0.12, y - h * 0.12, x + w / 2, y + h * 0.28)
    path.cubicTo(x + w * 0.88, y - h * 0.12, x + w * 1.15, y + h * 0.45, x + w / 2, y + h * 0.95)
    return path


def paint_heart(p, rect, on, off_color):
    """Corazón relleno (favorito) o solo el contorno."""
    p.save()
    p.setPen(QtGui.QPen(heart_color() if on else off_color, 1.4))
    p.setBrush(heart_color() if on else QtCore.Qt.NoBrush)
    p.drawPath(heart_path(rect))
    p.restore()


def heart_icon():
    pm = QtGui.QPixmap(32, 32)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(heart_color())
    p.drawPath(heart_path(QtCore.QRectF(3, 4, 26, 24)))
    p.end()
    return QtGui.QIcon(pm)


def rel_key(roots, full, suffix=""):
    """«RAIZ/sub/nombre» + suffix: igual abriendo la biblioteca como B:\\ o como \\\\SERVIDOR\\..."""
    full = os.path.normcase(full)
    for r in roots:
        rn = os.path.normcase(r).rstrip("\\/")
        if full == rn or full.startswith(rn + os.sep):
            return os.path.basename(rn) + "/" + os.path.relpath(full, rn).replace(os.sep, "/") + suffix
    return full + suffix


class _ShiftCollapse(QtCore.QObject):
    def __init__(self, tree):
        super(_ShiftCollapse, self).__init__(tree)
        self.tree = tree

    def eventFilter(self, obj, ev):
        if (ev.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick)
                and ev.button() == QtCore.Qt.LeftButton and ev.modifiers() & QtCore.Qt.ShiftModifier):
            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
            idx = self.tree.indexAt(pos)
            # en la flechita (a la izquierda del texto) de una carpeta con subcarpetas
            if idx.isValid() and self.tree.model().hasChildren(idx) and pos.x() < self.tree.visualRect(idx).left():
                self.tree.collapseAll()
                return True
        return False


def shift_collapse(tree):
    """Shift + clic en la flecha de una carpeta del árbol: se cierran todas."""
    f = _ShiftCollapse(tree)
    tree.viewport().installEventFilter(f)
    tree._shift_collapse = f


def show_mode(lib):
    return (lib or {}).get("show", "both")


def tree_nodes(lib):
    """(se ve «Favoritos», se ve «Todos») en el árbol de la pestaña."""
    lib = lib or {}
    return bool(lib.get("tree_fav", True)), bool(lib.get("tree_all", True))


def open_on_fav(lib):
    """¿La pestaña se abre en «Favoritos»?"""
    fav, every = tree_nodes(lib)
    return fav and (show_mode(lib) == "favorites" or not every)
