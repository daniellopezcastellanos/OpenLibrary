"""Cliente del puente: encuentra los 3ds Max abiertos y les manda órdenes.

Cada 3ds Max con el puente instalado escucha en 127.0.0.1:47800-47809
(ver openlibrary_max/server.py). Python puro, sin Qt: se puede probar fuera.
"""
import ctypes
import json
import socket
from ctypes import wintypes

PORTS = range(47800, 47810)
PROTOCOL = 5          # 2: materiales y texturas; 3: tamaño real X·Y·Z e interiores wParallax;
                      # 4: al soltar, el visor y el objeto bajo el ratón (con pantalla escalada);
                      # 5: materiales que ya están en la escena (check_drop, existing) y varios a Slate


class MaxLinkError(Exception):
    pass


class MaxInstance(object):
    def __init__(self, info):
        self.port = int(info.get("port", 0))
        self.pid = int(info.get("pid", 0))
        self.version = int(info.get("max_version", 0))
        self.engine = info.get("engine", "other")
        self.file = info.get("file", "")
        self.folder = info.get("folder", "")
        self.selection = int(info.get("selection", 0))
        self.busy = bool(info.get("busy", False))
        self.protocol = int(info.get("protocol", 0))

    @property
    def label(self):
        name = self.file or "escena sin guardar"
        return "3ds Max %s · %s" % (self.version or "?", name)

    def call(self, cmd, timeout=None, **args):
        return call(self.port, cmd, args, timeout)


def _request(port, payload, timeout):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4) as s:
            s.settimeout(timeout)
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except socket.timeout:
        raise MaxLinkError("3ds Max no responde. Puede que esté renderizando o que tenga una ventana abierta "
                           "esperando respuesta: ciérrala y vuelve a intentarlo.")
    except OSError as exc:
        raise MaxLinkError("No hay conexión con 3ds Max: %s" % exc)
    if not buf:
        raise MaxLinkError("3ds Max cerró la conexión.")
    return json.loads(buf.decode("utf-8"))


def call(port, cmd, args=None, timeout=None):
    """Ejecuta un comando y devuelve su resultado. timeout=None espera lo que haga falta
    (colocar un asset con el ratón puede durar minutos)."""
    resp = _request(port, {"cmd": cmd, "args": args or {}}, timeout)
    if not resp.get("ok"):
        raise MaxLinkError(resp.get("error") or "Error desconocido en 3ds Max")
    return resp.get("result")


def discover(timeout=0.5):
    """Lista de MaxInstance con el puente activo."""
    found = []
    for port in PORTS:
        try:
            info = _request(port, {"cmd": "ping"}, timeout)
        except (MaxLinkError, ValueError):
            continue
        if info.get("ok") and isinstance(info.get("result"), dict):
            res = info["result"]
            res.setdefault("port", port)
            found.append(MaxInstance(res))
    return found


# ---------------------------------------------------------------------------
# Windows: qué ventana hay bajo el ratón y permiso para pasarle el foco
# ---------------------------------------------------------------------------
def _user32():
    try:
        return ctypes.windll.user32
    except AttributeError:  # no Windows
        return None


def pid_under_cursor(x, y):
    """PID del proceso dueño de la ventana en la posición de pantalla (x, y)."""
    u = _user32()
    if u is None:
        return 0
    u.WindowFromPoint.restype = wintypes.HWND
    u.WindowFromPoint.argtypes = [wintypes.POINT]
    u.GetAncestor.restype = wintypes.HWND
    u.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    hwnd = u.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return 0
    root = u.GetAncestor(hwnd, 2) or hwnd      # GA_ROOT
    pid = wintypes.DWORD(0)
    u.GetWindowThreadProcessId(root, ctypes.byref(pid))
    return int(pid.value)


def window_under_cursor(x, y):
    """(PID, [títulos de la ventana bajo el ratón y de sus madres]) en la posición de pantalla."""
    u = _user32()
    if u is None:
        return 0, []
    u.WindowFromPoint.restype = wintypes.HWND
    u.WindowFromPoint.argtypes = [wintypes.POINT]
    u.GetParent.restype = wintypes.HWND
    u.GetParent.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    hwnd = u.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return 0, []
    pid = wintypes.DWORD(0)
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    titles = []
    for _ in range(40):
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, buf, 256)
        if buf.value:
            titles.append(buf.value)
        hwnd = u.GetParent(hwnd)
        if not hwnd:
            break
    return int(pid.value), titles


def is_slate(titles):
    """¿Alguno de esos títulos es el editor de materiales Slate?"""
    return any("slate" in t.lower() or "material editor" in t.lower() for t in titles)


def allow_focus(pid):
    """Deja que 3ds Max se ponga delante cuando le mandamos un asset."""
    u = _user32()
    if u is not None and pid:
        try:
            u.AllowSetForegroundWindow(int(pid))
        except Exception:
            pass


def cursor_pos():
    u = _user32()
    if u is None:
        return None
    p = wintypes.POINT()
    if not u.GetCursorPos(ctypes.byref(p)):
        return None
    return p.x, p.y


def front_pid(pids, own_pid=0):
    """De esos procesos (los 3ds Max conectados), el que manda: el que tiene el ratón encima o, si no,
    el que está más arriba en el orden de las ventanas (el último que se usó)."""
    pids = set(int(p) for p in pids if p)
    if not pids:
        return 0
    if len(pids) == 1:
        return next(iter(pids))
    u = _user32()
    if u is None:
        return 0
    pos = cursor_pos()
    if pos:
        pid = pid_under_cursor(*pos)
        if pid in pids:
            return pid
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _each(hwnd, _lp):
        if not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) in pids:
            found.append(int(pid.value))
            return False                     # EnumWindows va de arriba abajo: el primero manda
        return True
    try:
        u.EnumWindows(proto(_each), 0)
    except Exception:
        return 0
    return found[0] if found else 0
