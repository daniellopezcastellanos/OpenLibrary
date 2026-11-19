"""OpenLibrary - puente dentro de 3ds Max.

Lo instala la app OpenLibrary en
%LOCALAPPDATA%\\Autodesk\\3dsMax\\<versión>\\ENU\\scripts\\OpenLibrary y lo arranca
el script de inicio openlibrary_bridge.ms. No tiene interfaz, salvo la barra
opcional con el botón para abrir la app (toolbar.py).
"""
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "0.2.1"


def _config():
    try:
        with open(os.path.join(os.path.dirname(HERE), "app.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def start():
    from . import server
    ok = server.start()
    if _config().get("toolbar"):
        try:
            from PySide6 import QtCore
            from . import toolbar
            QtCore.QTimer.singleShot(0, toolbar.show)
        except Exception as exc:
            print("OpenLibrary: no se pudo crear la barra: %s" % exc)
    return ok


def stop():
    from . import server
    server.stop()


def _app_window():
    """La ventana principal de OpenLibrary si ya está abierta (título «OpenLibrary», ventana de Qt)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _each(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(64)
        u.GetWindowTextW(hwnd, buf, 64)
        if buf.value == "OpenLibrary":
            cls = ctypes.create_unicode_buffer(128)
            u.GetClassNameW(hwnd, cls, 128)
            if cls.value.startswith("Qt") and (u.IsWindowVisible(hwnd) or u.IsIconic(hwnd)):
                found.append(hwnd)
                return False
        return True
    u.EnumWindows(proto(_each), 0)
    return found[0] if found else None


def _raise_window(hwnd):
    """La pone delante de todo. Max está delante (se acaba de pulsar su botón), así que Windows lo deja."""
    import ctypes
    u = ctypes.windll.user32
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)                          # SW_RESTORE
    else:
        u.ShowWindow(hwnd, 5)                          # SW_SHOW
    u.BringWindowToTop(hwnd)
    if not u.SetForegroundWindow(hwnd):
        # plan B: subirla un instante por encima de todo y devolverla a su sitio
        flags = 0x0001 | 0x0002 | 0x0040              # NOSIZE | NOMOVE | SHOWWINDOW
        u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)   # HWND_TOPMOST
        u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)   # HWND_NOTOPMOST
        u.SetForegroundWindow(hwnd)


def launch_app():
    """Botón de Max: si OpenLibrary ya está abierta, la trae delante; si no, la abre."""
    try:
        hwnd = _app_window()
        if hwnd:
            _raise_window(hwnd)
            return True
    except Exception as exc:
        print("OpenLibrary: %s" % exc)
    cmd = _config().get("command")
    if not cmd or not os.path.isfile(cmd[0]):
        print("OpenLibrary: no encuentro la app. Ábrela una vez (se vuelve a apuntar sola) o reinstala el "
              "puente desde la app (Ajustes > Instalación).")
        return False
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # que la app nueva pueda ponerse delante
    except Exception:
        pass
    subprocess.Popen(cmd, close_fds=True, cwd=os.path.dirname(cmd[-1]),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True
