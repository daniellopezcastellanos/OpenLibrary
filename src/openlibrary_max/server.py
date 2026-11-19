"""Servidor local del puente: la app OpenLibrary habla con este 3ds Max por aquí.

- Escucha solo en 127.0.0.1, en el primer puerto libre de 47800-47809 (uno por
  cada 3ds Max abierto).
- Protocolo: una línea JSON por petición {"cmd": ..., "args": {...}} y una línea
  JSON de respuesta {"ok": true, "result": ...} o {"ok": false, "error": ...}.
- Solo acepta los comandos de COMMANDS: no hay forma de ejecutar código arbitrario.
- pymxs solo se toca en el hilo principal de Max: el hilo del socket encola la
  tarea con una señal Qt y espera a que termine.
"""
import gc
import json
import os
import socketserver
import threading

from PySide6 import QtCore

from . import ops

PROTOCOL = 5          # 2: materiales y texturas; 3: tamaño real X·Y·Z e interiores wParallax;
                      # 4: al soltar, el visor y el objeto bajo el ratón (con pantalla escalada);
                      # 5: materiales que ya están en la escena (check_drop, existing) y varios a Slate
PORTS = range(47800, 47810)

_server = None
_thread = None
_invoker = None
_state = {"engine": "other", "file": "", "folder": "", "selection": 0, "busy": False}
_state_lock = threading.Lock()


class _Job(object):
    def __init__(self, fn, args):
        self.fn = fn
        self.args = args
        self.done = threading.Event()
        self.result = None
        self.error = None

    def run(self):
        with _state_lock:
            _state["busy"] = True
        try:
            self.result = self.fn(**self.args)
        except Exception as exc:  # se devuelve a la app
            self.error = "%s" % exc
            exc.__traceback__ = None
            del exc
        finally:
            self.fn = self.args = None
            with _state_lock:
                _state["busy"] = False
            _refresh_state()
            # Los restos de la orden que tocan valores de MAXScript (p. ej. un error con su traza) se
            # liberan aquí, en el hilo de Max. Si los recogiera el recolector de Python en el hilo del
            # socket, MAXScript acabaría dando «unknown error ... garbage collection».
            gc.collect()
            self.done.set()


class _Invoker(QtCore.QObject):
    """Vive en el hilo principal de Max."""
    request = QtCore.Signal(object)

    def __init__(self):
        super(_Invoker, self).__init__()
        self.request.connect(self._run, QtCore.Qt.QueuedConnection)
        # El estado (motor, archivo, selección) lo ponen al día los callbacks de Max (olb_watchState);
        # esto es solo un repaso de seguridad, poco frecuente para no meterse en medio de Max.
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(_refresh_state)
        self.timer.start(10000)

    def _run(self, job):
        job.run()


def _refresh_state():
    try:
        st = ops.scene_state()
    except Exception:
        return
    with _state_lock:
        _state.update(st)


def _info():
    with _state_lock:
        st = dict(_state)
    st.update({"pid": os.getpid(), "protocol": PROTOCOL, "max_version": _MAX_VERSION,
               "port": _server.server_address[1] if _server else 0})
    return st


COMMANDS = {
    "merge": ops.merge,
    "merge_proxy": ops.merge_as_proxy,
    "make_preview": ops.make_preview,
    "relink_scene": ops.relink_scene,
    "relink_file": ops.relink_max_file,
    "open_file": ops.open_max_file,
    "focus": ops.focus_max,
    "apply_material": ops.apply_material,
    "apply_materials": ops.apply_materials,
    "check_drop": ops.check_drop,
    "apply_library": ops.apply_library,
    "add_textures": ops.add_textures,
    "apply_interior": ops.apply_interior,
}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            try:
                req = json.loads(raw.decode("utf-8"))
                cmd = req.get("cmd")
                if cmd == "ping":
                    resp = {"ok": True, "result": _info()}      # sin tocar Max: siempre responde
                elif cmd in COMMANDS and _state.get("busy"):
                    # p. ej. todavía colocando el asset anterior: no lo pisamos
                    resp = {"ok": False, "error": "3ds Max está ocupado con la orden anterior.", "busy": True}
                elif cmd in COMMANDS:
                    job = _Job(COMMANDS[cmd], req.get("args") or {})
                    _invoker.request.emit(job)
                    job.done.wait()
                    resp = {"ok": job.error is None, "result": job.result, "error": job.error}
                else:
                    resp = {"ok": False, "error": "Comando desconocido: %s" % cmd}
            except Exception as exc:
                resp = {"ok": False, "error": "Petición no válida: %s" % exc}
            try:
                self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))
                self.wfile.flush()
            except OSError:
                return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False   # en Windows permitiría robar el puerto


_MAX_VERSION = 0


def start():
    """Arranca el puente (idempotente). Llamar desde el hilo principal de Max."""
    global _server, _thread, _invoker, _MAX_VERSION
    if _server is not None:
        return _server.server_address[1]
    ops.load_core()
    _MAX_VERSION = ops.max_version()
    ops.watch_state(True)
    _invoker = _Invoker()
    _refresh_state()
    for port in PORTS:
        try:
            _server = _Server(("127.0.0.1", port), _Handler)
            break
        except OSError:
            continue
    if _server is None:
        print("OpenLibrary: no hay puertos libres (47800-47809)")
        return 0
    _thread = threading.Thread(target=_server.serve_forever, name="OpenLibraryBridge", daemon=True)
    _thread.start()
    print("OpenLibrary: puente activo en el puerto %d" % _server.server_address[1])
    return _server.server_address[1]


def stop():
    global _server, _thread
    try:
        ops.watch_state(False)
    except Exception:
        pass
    if _server is not None:
        _server.shutdown()
        _server.server_close()
    _server = None
    _thread = None
