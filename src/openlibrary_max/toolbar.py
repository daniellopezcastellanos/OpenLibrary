"""Barra "OpenLibrary" dentro de 3ds Max con un solo botón que abre la app.

Solo se crea si se eligió al instalar el puente (app.json -> "toolbar": true).
Se puede mover y acoplar como cualquier otra barra de Max.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OBJECT_NAME = "OpenLibraryToolbar"
_toolbar = None


def show():
    global _toolbar
    from PySide6 import QtCore, QtGui, QtWidgets
    import qtmax

    main = qtmax.GetQMaxMainWindow()
    if main is None:
        return False
    tb = main.findChild(QtWidgets.QToolBar, OBJECT_NAME)
    if tb is None:
        from . import launch_app
        tb = QtWidgets.QToolBar("OpenLibrary", main)
        tb.setObjectName(OBJECT_NAME)
        ico = os.path.join(HERE, "openlibrary.svg")
        act = QtGui.QAction(QtGui.QIcon(ico) if os.path.isfile(ico) else QtGui.QIcon(), "OpenLibrary", tb)
        act.setToolTip("Abrir OpenLibrary")
        act.triggered.connect(lambda *_: launch_app())
        tb.addAction(act)
        if hasattr(main, "addToolBar"):
            main.addToolBar(QtCore.Qt.TopToolBarArea, tb)
    tb.show()
    _toolbar = tb
    return True


def hide():
    global _toolbar
    if _toolbar is not None:
        try:
            _toolbar.hide()
            _toolbar.deleteLater()
        except RuntimeError:
            pass
        _toolbar = None
