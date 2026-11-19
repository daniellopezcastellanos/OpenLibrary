"""Tests de lo que no necesita 3ds Max:  python -m unittest discover tests"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from openlibrary import archives, catalog, library, maxfile  # noqa: E402
from openlibrary.config import Settings  # noqa: E402


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class EngineNamesTest(unittest.TestCase):
    def test_fstorm_suffix_and_score(self):
        self.assertEqual(library.split_engine_suffix("Silla_fstorm"), ("Silla", "fstorm"))
        self.assertEqual(maxfile._winner(maxfile._score("FStormMtl FStormLight")), "fstorm")
        self.assertEqual(maxfile._winner(maxfile._score("CoronaMtl VRayMtl")), "corona")
        self.assertIsNone(maxfile._winner(maxfile._score("Standardmaterial")))


class SuffixTests(unittest.TestCase):
    def test_suffixes(self):
        s = library.split_engine_suffix
        self.assertEqual(s("Silla_corona"), ("Silla", "corona"))
        self.assertEqual(s("Silla-VRay"), ("Silla", "vray"))
        self.assertEqual(s("Silla v-ray"), ("Silla", "vray"))
        self.assertEqual(s("Mesa_CR"), ("Mesa", "corona"))
        self.assertEqual(s("Mesa_vr"), ("Mesa", "vray"))
        self.assertEqual(s("Corona"), ("Corona", None))
        self.assertEqual(s("Arbol"), ("Arbol", None))


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        r = self.root
        touch(os.path.join(r, "Sillas", "Eames_corona.max"))
        touch(os.path.join(r, "Sillas", "Eames_vray.max"))
        touch(os.path.join(r, "Sillas", "Eames.jpg"))
        touch(os.path.join(r, "Sillas", "Tulip.max"))
        touch(os.path.join(r, "Sillas", "previews", "Tulip.png"))
        touch(os.path.join(r, "Sillas", "_proxies", "x", "Eames.cgeo"))
        touch(os.path.join(r, "Sillas", "_proxies", "x", "Fake.max"))
        touch(os.path.join(r, "Edificios", "Torre", "Torre_vray.max"))
        touch(os.path.join(r, "Edificios", "Torre", "preview.jpg"))
        touch(os.path.join(r, "Vacia", "readme.txt"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_scan(self):
        idx = library.LibraryIndex(self.root).scan()
        names = sorted(a.name for a in idx.assets)
        self.assertEqual(names, ["Eames", "Torre", "Tulip"])      # _proxies ignorado
        eames = [a for a in idx.assets if a.name == "Eames"][0]
        self.assertEqual(set(eames.versions), {"corona", "vray"})
        self.assertTrue(eames.preview.endswith("Eames.jpg"))
        tulip = [a for a in idx.assets if a.name == "Tulip"][0]
        self.assertEqual(len(tulip.auto_files), 1)
        self.assertTrue(tulip.preview.endswith("Tulip.png"))
        torre = [a for a in idx.assets if a.name == "Torre"][0]
        self.assertTrue(torre.preview.endswith("preview.jpg"))
        self.assertIn(os.path.join(self.root, "Vacia"), idx.folders)

    def test_folder_filter_and_search(self):
        idx = library.LibraryIndex(self.root).scan()
        ed = os.path.join(self.root, "Edificios")
        self.assertEqual([a.name for a in idx.assets_in(ed, recursive=True)], ["Torre"])
        self.assertEqual(idx.assets_in(ed, recursive=False), [])
        self.assertEqual([a.name for a in idx.search("eam")], ["Eames"])
        self.assertEqual([a.name for a in idx.search("sillas tul")], ["Tulip"])   # nombre de carpeta
        self.assertEqual(idx.search("nada"), [])

    def test_file_for_engine(self):
        idx = library.LibraryIndex(self.root).scan()
        eames = [a for a in idx.assets if a.name == "Eames"][0]
        self.assertTrue(eames.file_for_engine("vray").endswith("Eames_vray.max"))
        self.assertIsNone(eames.file_for_engine("other"))

    def test_cache_and_incremental(self):
        cache_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache_dir, True)
        cache = os.path.join(cache_dir, "cache.json")
        idx = library.LibraryIndex([self.root]).scan()
        self.assertGreater(idx.stats["listed"], 0)
        idx.save(cache)
        # Caché cargada sin tocar las carpetas
        idx2 = library.LibraryIndex([self.root])
        self.assertTrue(idx2.load(cache))
        self.assertEqual(sorted(a.name for a in idx2.assets), ["Eames", "Torre", "Tulip"])
        # Sin cambios: todo se reutiliza
        idx2.scan()
        self.assertEqual(idx2.stats["listed"], 0)
        # Asset nuevo en una carpeta: solo se vuelve a listar esa
        sillas = os.path.join(self.root, "Sillas")
        old = os.stat(sillas).st_mtime
        touch(os.path.join(sillas, "Nueva_corona.max"))
        os.utime(sillas, (old + 5, old + 5))
        idx2.scan()
        self.assertEqual(idx2.stats["listed"], 1)
        self.assertIn("Nueva", [a.name for a in idx2.assets])
        # Otra raíz distinta no reutiliza esta caché
        self.assertFalse(library.LibraryIndex([sillas]).load(cache))

    def test_multiple_roots(self):
        a = os.path.join(self.root, "Sillas")
        b = os.path.join(self.root, "Edificios")
        idx = library.LibraryIndex([a, b]).scan()
        self.assertEqual(sorted(x.name for x in idx.assets_in(None)), ["Eames", "Torre", "Tulip"])

    def test_settings_migration(self):
        from openlibrary.config import migrate_libraries
        out = migrate_libraries([{"name": "Estudio", "path": "N:\\Biblio"}, {"name": "Casa", "path": "D:\\Lib"}])
        self.assertEqual([l["name"] for l in out], ["Modelos", "Materiales", "Texturas"])
        self.assertEqual(out[0]["paths"], ["N:\\Biblio", "D:\\Lib"])
        self.assertEqual(len(migrate_libraries(None)), 3)

    def test_settings_roundtrip(self):
        p = os.path.join(self.root, "settings.json")
        s = Settings(p)
        self.assertEqual([l["name"] for l in s.libraries], ["Modelos", "Materiales", "Texturas"])
        s.libraries[0]["paths"].append(self.root)
        s.libraries.append({"name": "Vegetación", "kind": "models", "paths": []})
        s.imp["proxy_mode"] = "per_object"
        s.save()
        s2 = Settings(p)
        self.assertEqual(s2.libraries[0]["paths"], [self.root])
        self.assertEqual(s2.libraries[3]["name"], "Vegetación")
        self.assertEqual(s2.imp["proxy_mode"], "per_object")
        self.assertIn("relink_dirs", s2.imp)            # defaults nuevos se rellenan

    def test_settings_two_copies_do_not_overwrite(self):
        """Una copia de la app con los ajustes viejos en memoria no pisa lo que guardó otra."""
        p = os.path.join(self.root, "settings.json")
        Settings(p).save()
        old, new = Settings(p), Settings(p)
        new.libraries[0]["paths"].append("B:\\Modelos")
        new.data["theme"] = "light"
        new.save()
        old.data["window_geometry"] = "abcd"            # lo que hace la copia vieja al cerrarse
        old.save()
        s = Settings(p)
        self.assertEqual(s.libraries[0]["paths"], ["B:\\Modelos"])
        self.assertEqual(s.data["theme"], "light")
        self.assertEqual(s.data["window_geometry"], "abcd")
        self.assertEqual(old.libraries[0]["paths"], ["B:\\Modelos"])

    def test_settings_broken_file_uses_backup(self):
        p = os.path.join(self.root, "settings.json")
        s = Settings(p)
        s.libraries[0]["paths"].append("B:\\Modelos")
        s.save()
        s.data["thumb_size"] = 200
        s.save()                                        # deja settings.json.bak con el guardado anterior
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{ roto")
        self.assertEqual(Settings(p).libraries[0]["paths"], ["B:\\Modelos"])

    def test_hidden_folders(self):
        r = "B:\\Lib"
        folders = [r, r + "\\Sillas", r + "\\Sillas\\z-maps", r + "\\Sillas\\z-maps\\4k",
                   r + "\\Mesas", r + "\\Mesas\\Z-Maps", r + "\\Camas", r + "\\Camas\\Dobles"]
        nc = os.path.normcase
        hid = library.hidden_folders(folders, [r], ["z-maps"], [r + "\\Camas"])
        self.assertEqual(hid, {nc(r + "\\Sillas\\z-maps"), nc(r + "\\Sillas\\z-maps\\4k"),
                               nc(r + "\\Mesas\\Z-Maps"), nc(r + "\\Camas"), nc(r + "\\Camas\\Dobles")})
        self.assertEqual(library.hidden_folders(folders, [r], ["z-*", "lib"], []),
                         {nc(r + "\\Sillas\\z-maps"), nc(r + "\\Sillas\\z-maps\\4k"), nc(r + "\\Mesas\\Z-Maps")})
        self.assertEqual(library.hidden_folders(folders, [r]), set())


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_volumes(self):
        v = lambda name, names: archives.volumes(os.path.join("D:\\dl", name), names)
        base = lambda t: (os.path.basename(t[0]), [os.path.basename(p) for p in t[1]], t[2])
        self.assertEqual(base(v("a.zip", ["a.zip", "b.zip"])), ("a.zip", ["a.zip"], []))
        names = ["Sofa.part1.rar", "Sofa.part2.rar", "Sofa.part3.rar", "otro.part1.rar"]
        self.assertEqual(base(v("Sofa.part2.rar", names)), ("Sofa.part1.rar", names[:3], []))
        self.assertEqual(base(v("Sofa.part03.rar", ["Sofa.part01.rar", "Sofa.part03.rar"])),
                         ("Sofa.part01.rar", ["Sofa.part01.rar", "Sofa.part03.rar"], ["Sofa.part02.rar"]))
        self.assertEqual(base(v("Sofa.part2.rar", ["Sofa.part2.rar"]))[2], ["Sofa.part1.rar"])
        self.assertEqual(base(v("m.7z.002", ["m.7z.001", "m.7z.002", "m.7z.003"])),
                         ("m.7z.001", ["m.7z.001", "m.7z.002", "m.7z.003"], []))
        self.assertEqual(base(v("m.r00", ["m.rar", "m.r00", "m.r01"])), ("m.rar", ["m.rar", "m.r00", "m.r01"], []))
        self.assertEqual(base(v("m.z01", ["m.z01", "m.z02", "m.zip"])), ("m.zip", ["m.z01", "m.z02", "m.zip"], []))
        self.assertEqual(base(v("m.z02", ["m.z02", "m.zip"]))[2], ["m.z01"])
        self.assertEqual(archives.display_name("D:\\dl\\Sofa Bolzano.part1.rar"), "Sofa Bolzano")
        self.assertEqual(archives.display_name("D:\\dl\\m.7z.001"), "m")

    def test_zip_without_tools(self):
        import zipfile
        z = os.path.join(self.root, "a.zip")
        with zipfile.ZipFile(z, "w") as fh:
            fh.writestr("Silla/Silla.max", b"x")
            fh.writestr("Silla/maps/wood.jpg", b"y")
        out = os.path.join(self.root, "out")
        archives.extract(z, out, tool=("ninguna", None))
        items = catalog.list_files(out)
        self.assertEqual([(i.name, i.rel) for i in items], [("Silla.max", "Silla"), ("wood.jpg", "Silla\\maps")])
        with open(z, "wb") as fh:
            fh.write(b"esto no es un zip")
        self.assertRaises(archives.ArchiveError, archives.extract, z, out, None, ("ninguna", None))

    def test_guess(self):
        src = os.path.join(self.root, "dl")
        for f in ("Sofa.max", "Sofa.jpg", "maps/wood.jpg", "maps/fabric.png", "leeme.txt", "web.url", "Thumbs.db"):
            touch(os.path.join(src, f))
        kinds = {os.path.relpath(p, src).replace("\\", "/"): k
                 for p, k in catalog.guess(catalog.list_files(src), "Descarga 123").items()}
        self.assertEqual(kinds, {"Sofa.max": "max", "Sofa.jpg": "preview", "maps/wood.jpg": "maps",
                                 "maps/fabric.png": "maps", "leeme.txt": "maps", "web.url": "skip",
                                 "Thumbs.db": "skip"})
        # todo suelto y sin pistas: no se propone preview
        src2 = os.path.join(self.root, "dl2")
        for f in ("a.max", "wood.jpg", "fabric.jpg"):
            touch(os.path.join(src2, f))
        self.assertNotIn("preview", catalog.guess(catalog.list_files(src2)).values())

    def test_names(self):
        self.assertEqual(catalog.clean_name('  Sofa: "Bolzano" / v2. '), "Sofa Bolzano v2")
        self.assertEqual(catalog.max_names("Sofa", [("a.max", "other")]), ["Sofa.max"])
        self.assertEqual(catalog.max_names("Sofa", [("a.max", "corona"), ("b.max", "vray")]),
                         ["Sofa_corona.max", "Sofa_vray.max"])
        self.assertEqual(catalog.max_names("Sofa", [("a_2016.max", "corona"), ("a_2013.max", "corona"),
                                                    ("b.max", None), ("c.max", None)]),
                         ["Sofa_corona.max", "Sofa 2013_corona.max", "Sofa.max", "Sofa 2.max"])
        self.assertEqual(catalog.engine_of("x_vray_2016.max", "other"), "vray")
        self.assertEqual(catalog.engine_of("x_vray.max", "corona"), "corona")
        self.assertIsNone(catalog.engine_of("x.max"))

    def test_disposable(self):
        from openlibrary import pathedit
        d = pathedit.is_disposable
        self.assertTrue(d("Photometric", "C:\\Program Files\\Corona\\lut\\Adanmq_Advantix_100.cube"))
        self.assertTrue(d("Bitmap", "D:\\hdri\\Studio_01.HDR"))
        self.assertTrue(d("Bitmap", "C:\\maps\\uvwunwrap\\UV_Checker.png"))
        self.assertTrue(d("Other", "checker_grid.jpg"))
        self.assertFalse(d("Bitmap", "wood_diffuse.jpg"))
        self.assertFalse(d("Other", "checker.ies"))
        self.assertFalse(d("Bitmap", "sky.exr"))

    def test_plan_and_apply(self):
        src = os.path.join(self.root, "dl")
        dest = os.path.join(self.root, "Lib", "Furniture")
        for f in ("a_corona.max", "a_vray.max", "render.JPG", "maps/wood.jpg", "maps2/wood.jpg", "notas.txt"):
            touch(os.path.join(src, f))
        touch(os.path.join(src, "otra", "wood.jpg"), b"distinta")
        j = lambda *a: os.path.join(src, *a)
        p = catalog.plan(dest, "Sofa", [(j("a_corona.max"), "corona"), (j("a_vray.max"), "vray")], [j("render.JPG")],
                         [j("maps", "wood.jpg"), j("maps2", "wood.jpg"), j("otra", "wood.jpg"), j("notas.txt")])
        self.assertEqual(p.skipped, 1)
        self.assertEqual(p.conflicts(), [])
        self.assertEqual(catalog.apply(p), 6)
        got = sorted(os.path.relpath(os.path.join(d, f), dest).replace("\\", "/")
                     for d, _x, files in os.walk(dest) for f in files)
        self.assertEqual(got, ["Sofa.jpg", "Sofa_corona.max", "Sofa_vray.max", "z-maps/Sofa/notas.txt",
                               "z-maps/Sofa/wood (2).jpg", "z-maps/Sofa/wood.jpg"])
        self.assertTrue(os.path.isfile(j("a_corona.max")))          # copiar no toca el origen
        self.assertEqual(len(p.conflicts()), 6)
        assets = library.scan_folder(dest)
        self.assertEqual([(a.name, sorted(a.versions), os.path.basename(a.preview)) for a in assets],
                         [("Sofa", ["corona", "vray"], "Sofa.jpg")])
        catalog.apply(catalog.plan(dest, "Otro", [(j("a_vray.max"), "vray")], [], []), move=True)
        self.assertFalse(os.path.exists(j("a_vray.max")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "Otro.max")))


class MaxFileTests(unittest.TestCase):
    def test_not_ole(self):
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "x.max")
            touch(f, b"no es un max")
            self.assertEqual(maxfile.detect_engine(f), "other")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_real_files_if_present(self):
        """Usa .max reales si se pasan en OPENLIBRARY_TEST_MAX (separados por ;)."""
        for f in filter(None, os.environ.get("OPENLIBRARY_TEST_MAX", "").split(";")):
            self.assertIn(maxfile.detect_engine(f), maxfile.ENGINES)
            res = maxfile.check_external_files(f)
            self.assertEqual(res["total"], len(set(p.lower() for _, p, _ in maxfile.read_asset_paths(f)
                                                   if os.path.splitext(p)[1])))

    def test_asset_paths_bad_file(self):
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "x.max")
            touch(f, b"nada")
            self.assertEqual(maxfile.read_asset_paths(f), [])
            self.assertEqual(maxfile.check_external_files(f)["total"], 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
