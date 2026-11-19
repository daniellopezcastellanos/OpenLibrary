"""Tests del puente sin 3ds Max: cliente (maxlink) contra un servidor falso,
e instalación del puente en una carpeta de usuario de Max simulada."""
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from openlibrary import bridge_install, maxlink  # noqa: E402


class _FakeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            req = json.loads(raw.decode("utf-8"))
            if req["cmd"] == "ping":
                resp = {"ok": True, "result": {"pid": 1234, "max_version": 2026, "engine": "corona",
                                               "file": "escena.max", "protocol": 1}}
            elif req["cmd"] == "merge":
                resp = {"ok": True, "result": len(req["args"]["asset_name"])}
            else:
                resp = {"ok": False, "error": "Comando desconocido"}
            self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))


class MaxLinkTests(unittest.TestCase):
    def setUp(self):
        self.server = None
        for port in maxlink.PORTS:
            try:
                self.server = socketserver.ThreadingTCPServer(("127.0.0.1", port), _FakeHandler)
                break
            except OSError:
                continue
        if self.server is None:
            self.skipTest("Sin puertos libres")
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def test_discover_and_call(self):
        found = [m for m in maxlink.discover() if m.port == self.port]
        self.assertEqual(len(found), 1)
        m = found[0]
        self.assertEqual((m.pid, m.version, m.engine), (1234, 2026, "corona"))
        self.assertIn("escena.max", m.label)
        self.assertEqual(m.call("merge", asset_name="Silla"), 5)
        with self.assertRaises(maxlink.MaxLinkError):
            m.call("borrar_todo")

    def test_no_server(self):
        with self.assertRaises(maxlink.MaxLinkError):
            maxlink.call(1, "ping", timeout=0.5)


class BridgeInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp
        for v in ("2026 - 64bit", "2023 - 64bit"):
            os.makedirs(os.path.join(self.tmp, "Autodesk", "3dsMax", v, "ENU", "scripts", "startup"))

    def tearDown(self):
        if self.old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_install_uninstall(self):
        targets = bridge_install.find_targets()
        self.assertEqual([t.year for t in targets], [2026, 2023])
        t26, t23 = targets
        self.assertTrue(t26.supported)
        self.assertFalse(t23.supported)
        self.assertIsNone(t26.installed_version())
        t26.install()
        self.assertTrue(os.path.isfile(t26.startup))
        self.assertTrue(os.path.isfile(os.path.join(t26.bridge, "server.py")))
        self.assertTrue(os.path.isfile(os.path.join(t26.bridge, "openlibrary_core.ms")))
        self.assertEqual(t26.installed_version(), bridge_install.bridge_version(bridge_install.bridge_source()))
        with open(os.path.join(t26.scripts, "app.json"), encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["command"])
        t26.install()                     # reinstalar no falla
        t26.uninstall()
        self.assertIsNone(t26.installed_version())
        self.assertFalse(os.path.exists(t26.scripts))

    def test_outdated(self):
        t26 = bridge_install.find_targets()[0]
        self.assertFalse(t26.outdated())                  # sin instalar no se dice nada
        t26.install()
        self.assertFalse(t26.outdated())
        with open(os.path.join(t26.bridge, "ops.py"), "a", encoding="utf-8") as fh:
            fh.write("\n# viejo\n")
        self.assertTrue(t26.outdated())                   # misma versión, archivos distintos
        t26.install()
        self.assertFalse(t26.outdated())

    def test_toolbar_option(self):
        t26 = bridge_install.find_targets()[0]
        self.assertFalse(t26.toolbar_enabled())
        t26.install(toolbar=True)
        self.assertTrue(t26.toolbar_enabled())
        self.assertTrue(os.path.isfile(os.path.join(t26.bridge, "openlibrary.svg")))
        self.assertTrue(os.path.isfile(os.path.join(t26.bridge, "toolbar.py")))
        t26.install()                     # actualizar sin decir nada conserva la elección
        self.assertTrue(t26.toolbar_enabled())
        t26.install(toolbar=False)
        self.assertFalse(t26.toolbar_enabled())

    def test_fix_command(self):
        t26 = bridge_install.find_targets()[0]
        self.assertFalse(t26.fix_command())               # sin instalar no hay nada que arreglar
        t26.install(toolbar=True)
        self.assertFalse(t26.fix_command())               # ya apunta a esta app
        with open(t26.app_json, "w", encoding="utf-8") as fh:
            json.dump({"command": [r"C:\otro\pythonw.exe", "x.py"], "toolbar": True}, fh)
        self.assertTrue(t26.fix_command())
        with open(t26.app_json, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["command"], bridge_install.app_command())
        self.assertTrue(data["toolbar"])                  # la barra se conserva

    def test_front_pid_trivial(self):
        self.assertEqual(maxlink.front_pid([]), 0)
        self.assertEqual(maxlink.front_pid([4321]), 4321)   # uno solo: ese


if __name__ == "__main__":
    unittest.main()
