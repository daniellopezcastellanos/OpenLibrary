"""Datos de los .max (caras, vértices, desplazamiento, animación) y la carpeta común _OpenLibrary."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from openlibrary import config, modelstats  # noqa: E402


class ModelStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_and_log(self):
        a = os.path.join(self.tmp, "a.max")
        b = os.path.join(self.tmp, "b.max")
        log = os.path.join(self.tmp, "log.txt")
        with open(log, "w", encoding="utf-8-sig") as fh:          # Max escribe el registro con BOM
            fh.write("ok\t1\t972\t490\t2\t1\t1\t0\t100\nfail\t2\n")
        res = modelstats.read_log(log, [a, b])
        self.assertEqual(list(res), [a])
        self.assertEqual(res[a]["polys"], 972)
        self.assertTrue(res[a]["disp"] and res[a]["anim"])
        self.assertEqual(modelstats.summary(res[a]), "972 caras · 490 vértices · 2 objetos")
        self.assertIsNone(modelstats.parse_stats(["1", "2"]))

    def test_cache_invalidates_when_file_changes(self):
        f = os.path.join(self.tmp, "m.max")
        with open(f, "wb") as fh:
            fh.write(b"x")
        c = modelstats.StatsCache(os.path.join(self.tmp, "stats.json"))
        c.put(f, {"polys": 10, "verts": 8, "objects": 1, "disp": False, "anim": False, "start": 0, "end": 100})
        c.save()
        again = modelstats.StatsCache(os.path.join(self.tmp, "stats.json"))
        self.assertEqual(again.get(f)["polys"], 10)
        with open(f, "wb") as fh:
            fh.write(b"otro contenido")
        self.assertIsNone(again.get(f))

    def test_workspace_dir(self):
        nas = os.path.join(self.tmp, "BIBLIO")
        os.makedirs(nas)
        ws = config.workspace_dir(nas)
        self.assertEqual(ws, os.path.join(nas, "_OpenLibrary"))
        self.assertEqual(config.workspace_dir(ws), ws)            # elegir la propia _OpenLibrary
        self.assertFalse(config.prepare_workspace(ws))
        self.assertTrue(os.path.isdir(os.path.join(ws, "medidas")))
        self.assertTrue(os.path.isfile(os.path.join(ws, "LEEME.txt")))
        old = os.path.join(self.tmp, "viejo")                     # un espacio de antes con otro nombre
        os.makedirs(old)
        open(os.path.join(old, config.WORKSPACE_FILE), "w").close()
        self.assertEqual(config.workspace_dir(old), old)
        self.assertTrue(config.prepare_workspace(old))


if __name__ == "__main__":
    unittest.main()
