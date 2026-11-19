"""Espacio de trabajo compartido: varias personas con la misma carpeta (NAS) y sus ajustes locales."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from openlibrary import config  # noqa: E402


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "nas", "OpenLibrary")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def person(self, name):
        return config.Settings(os.path.join(self.tmp, name, "settings.json"))

    def test_create_join_and_merge(self):
        ana = self.person("ana")
        ana.data["libraries"] = [{"name": "Modelos", "kind": "models", "paths": [r"\\NAS\BIBLIO\3D"]}]
        ana.data["thumb_size"] = 220                           # personal
        ana.set_workspace(self.ws, take_theirs=False)          # crea el espacio con lo suyo
        self.assertEqual(ana.ws_state, "ok")
        self.assertTrue(os.path.isfile(os.path.join(self.ws, config.WORKSPACE_FILE)))

        ben = self.person("ben")
        ben.set_workspace(self.ws, take_theirs=True)           # se une y recibe las pestañas de Ana
        self.assertEqual(ben.libraries[0]["paths"], [r"\\NAS\BIBLIO\3D"])
        self.assertNotEqual(ben.data["thumb_size"], 220)        # lo personal no se comparte

        # los dos ponen medidas a la vez, a materiales distintos: no se pisan
        ana.data["surface_sizes"] = {"POLI/a|pbr": [100, 100, 100]}
        ben.data["surface_sizes"] = {"POLI/b|pbr": [50, 50, 50]}
        ana.save()
        ben.save()
        with open(os.path.join(self.ws, config.WORKSPACE_FILE), encoding="utf-8") as fh:
            shared = json.load(fh)
        self.assertEqual(set(shared["surface_sizes"]), {"POLI/a|pbr", "POLI/b|pbr"})
        self.assertNotIn("thumb_size", shared)

        # Ana ve lo de Ben sin reiniciar
        changed = ana.refresh_shared()
        self.assertIn("surface_sizes", changed)
        self.assertIn("POLI/b|pbr", ana.data["surface_sizes"])

        # Ben quita su medida y Ana añade una pestaña: se conservan las dos cosas
        ben.data["surface_sizes"] = {k: v for k, v in ben.data["surface_sizes"].items() if k != "POLI/b|pbr"}
        ben.save()
        ana.data["libraries"] = ana.data["libraries"] + [{"name": "Materiales", "kind": "materials", "paths": []}]
        ana.save()
        ben.refresh_shared()
        self.assertEqual([l["name"] for l in ben.libraries], ["Modelos", "Materiales"])
        self.assertNotIn("POLI/b|pbr", ben.data["surface_sizes"])
        self.assertIn("POLI/a|pbr", ben.data["surface_sizes"])

    def test_new_key_from_other_person(self):
        # Ana nunca ha tenido «surface_mapping»; Ben lo crea: al volver a la app, Ana lo recibe
        ana = self.person("ana")
        ana.set_workspace(self.ws, take_theirs=False)
        ben = self.person("ben")
        ben.set_workspace(self.ws, take_theirs=True)
        ben.data["surface_mapping"] = {"V/a|pbr": "uvw"}
        ben.save()
        self.assertIn("surface_mapping", ana.refresh_shared())
        self.assertEqual(ana.data["surface_mapping"], {"V/a|pbr": "uvw"})
        ana.save()                                              # y al guardar Ana no se lo borra
        ben.refresh_shared()
        self.assertEqual(ben.data["surface_mapping"], {"V/a|pbr": "uvw"})

    def test_offline_keeps_last_copy(self):
        ana = self.person("ana")
        ana.data["libraries"] = [{"name": "NAS", "kind": "models", "paths": [r"\\NAS\X"]}]
        ana.set_workspace(self.ws, take_theirs=False)
        shutil.rmtree(os.path.join(self.tmp, "nas"))            # el NAS no está
        again = self.person("ana")
        self.assertEqual(again.ws_state, "offline")
        self.assertEqual(again.libraries[0]["name"], "NAS")     # la última copia local
        again.data["thumb_size"] = 300
        again.save()                                            # guardar en local sigue funcionando
        self.assertEqual(again.ws_state, "offline")

    def test_tab_show_mode_kept(self):
        ana = self.person("ana")
        ana.data["libraries"] = [{"name": "Mat", "kind": "materials", "paths": ["X"], "show": "favorites"},
                                 {"name": "Tex", "kind": "textures", "paths": ["Y"], "show": "raro"}]
        ana.save()
        again = self.person("ana")
        self.assertEqual(again.libraries[0].get("show"), "favorites")
        self.assertNotIn("show", again.libraries[1])            # un valor desconocido no se guarda

    def test_measures_dir(self):
        ana = self.person("ana")
        self.assertTrue(ana.measures_dir().startswith(config.app_data_dir()) or "medidas" in ana.measures_dir())
        ana.set_workspace(self.ws, take_theirs=False)
        self.assertEqual(ana.measures_dir(), os.path.join(self.ws, "medidas"))


if __name__ == "__main__":
    unittest.main()
