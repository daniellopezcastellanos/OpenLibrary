"""Ventana principal de la app OpenLibrary."""
import sys

from . import app_icon, theme
from .qt import QtCore, QtNetwork, QtWidgets

SINGLE_INSTANCE_KEY = "OpenLibraryApp-single-instance"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        from .ui_browser import BrowserPanel
        self.setWindowTitle("OpenLibrary")
        self.setWindowIcon(app_icon())
        self.panel = BrowserPanel(self)
        self.setCentralWidget(self.panel)
        self.panel.pin_toggled.connect(self._set_on_top)
        s = self.panel.settings.data
        geo = s.get("window_geometry")
        if geo:
            try:
                self.restoreGeometry(QtCore.QByteArray.fromHex(geo.encode("ascii")))
            except Exception:
                self.resize(980, 720)
        else:
            self.resize(980, 720)
        if s.get("always_on_top"):
            self._set_on_top(True)
        theme.dark_title_bar(self)

    def _set_on_top(self, on):
        was_visible = self.isVisible()
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, bool(on))
        if was_visible:
            self.show()
            theme.dark_title_bar(self)

    def first_run(self):
        """Primera vez: accesos directos de Windows y puente/botón en 3ds Max."""
        from .ui_setup import SetupDialog
        dlg = SetupDialog(self.panel.settings, self)
        dlg.exec()
        if dlg.workspace_changed:           # se ha unido a un espacio del equipo: sus pestañas
            self.panel._reload_tabs()
            self.panel._ws_notice()

    def bring_to_front(self):
        """Otra copia (acceso directo, botón de Max) pide que se enseñe: delante de todo."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        if sys.platform == "win32":
            try:
                import ctypes
                u = ctypes.windll.user32
                hwnd = int(self.winId())
                if not u.SetForegroundWindow(hwnd):
                    flags = 0x0001 | 0x0002 | 0x0040       # NOSIZE | NOMOVE | SHOWWINDOW
                    if not self.windowFlags() & QtCore.Qt.WindowStaysOnTopHint:
                        u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)   # un instante por encima de todo
                        u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)
                    u.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def changeEvent(self, event):
        # al volver a la app: lo que hayan cambiado los compañeros en el espacio de trabajo compartido
        if event.type() == QtCore.QEvent.ActivationChange and self.isActiveWindow():
            QtCore.QTimer.singleShot(0, self.panel.refresh_shared)
        super(MainWindow, self).changeEvent(event)

    def closeEvent(self, event):
        s = self.panel.settings
        s.data["window_geometry"] = bytes(self.saveGeometry().toHex()).decode("ascii")
        s.save()
        self.panel.shutdown()
        super(MainWindow, self).closeEvent(event)


def _already_running():
    """Si ya hay una OpenLibrary abierta, le pedimos que se enseñe y salimos."""
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if sock.waitForConnected(1500):
        if sys.platform == "win32":
            try:            # le pasamos a la que ya está abierta el permiso de ponerse delante
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _fix_max_buttons():
    """El botón de OpenLibrary en cada Max apunta a esta app (si se movió o se instaló desde otro sitio)."""
    from . import bridge_install
    for t in bridge_install.find_targets():
        try:
            if t.installed_version():
                t.fix_command()
        except Exception:
            pass


def run(argv):
    QtCore.QCoreApplication.setApplicationName("OpenLibrary")
    QtCore.QCoreApplication.setOrganizationName("OpenLibrary")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    if _already_running():
        return 0
    from .config import Settings
    theme.set_mode(Settings().data.get("theme", "light"))
    theme.apply(app)
    app.setWindowIcon(app_icon())
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        # Desde el código fuente, para que Windows no la agrupe con Python en la barra de tareas.
        # El .exe no lo necesita y así se ancla a la barra sin más.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenLibrary.App")
        except Exception:
            pass

    win = MainWindow()
    server = QtNetwork.QLocalServer()
    QtNetwork.QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server.listen(SINGLE_INSTANCE_KEY)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.bring_to_front()))
    win.show()
    if win.panel.settings.data.get("setup_done"):
        from . import shortcuts
        QtCore.QTimer.singleShot(3000, lambda: shortcuts.refresh_icons(win.panel.settings))
        QtCore.QTimer.singleShot(2000, _fix_max_buttons)
    if not win.panel.settings.data.get("setup_done"):
        QtCore.QTimer.singleShot(500, win.first_run)
    return app.exec()


if __name__ == "__main__":
    sys.exit(run(sys.argv))
