"""Materiales y texturas: reconocer canales, resoluciones, medidas y grupos de mapas."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from openlibrary import maxlink, surfaces  # noqa: E402


def listing(tree):
    """{carpeta: [nombres]} -> listado como el del índice."""
    return {folder: {"m": 0, "d": [], "f": [(n, 0) for n in names]} for folder, names in tree.items()}


class ParseTests(unittest.TestCase):
    def test_channels(self):
        cases = {
            "WoodFlooring065_COL_4K.jpg": ("color", 4),
            "WoodFlooring065_DISP16_4K.tif": ("disp", 4),
            "Mahogany_Veneer_Wood_basecolor.png": ("color", 0),
            "Brick_Stack_Bond_ambientocclusion.png": ("ao", 0),
            "MOTW_239_Maple_8k_Albedo.tiff": ("color", 8),
            "TextureSupply_Concrete001_Raw_329cm_8K-Normal.jpg": ("normal", 8),
            "txyz_silk_05_dsp_2k.tif": ("disp", 2),
            "3DC_Beech_Wood_NormalMap_OpenGL_Seamless_16K.jpg": ("normal", 16),
            "Poliigon_Facade_10956_heightlacement.tiff": ("disp", 0),
            "Metal_Plate_Base_Color.png": ("color", 0),
            "LARGE_STAINS_08_NORM_8_bits.tiff": ("normal", 0),
        }
        for name, (ch, res) in cases.items():
            p = surfaces.parse_name(name)
            self.assertEqual((p["channel"], p["res"]), (ch, res), name)

    def test_material_word_is_not_a_channel(self):
        # «Metal» en medio del nombre es el material, no el canal metalness
        p = surfaces.parse_name("Brushed_Metal_Plate_roughness.png")
        self.assertEqual(p["channel"], "rough")
        self.assertEqual(p["base"], "Brushed Metal Plate")
        self.assertIsNone(surfaces.parse_name("Oak Classic 123.jpg")["channel"])

    def test_deep_variant_directx(self):
        self.assertTrue(surfaces.parse_name("Wood_NRM16_4K.tif")["deep"])
        self.assertEqual(surfaces.parse_name("Wood_COL_VAR2_4K.jpg")["variant"], 2)
        self.assertTrue(surfaces.parse_name("Wood_Normal_DirectX.png")["dx"])

    def test_real_size(self):
        self.assertEqual(surfaces.real_size("3D Scanned Bunker Concrete - 2.5x2.5 meters"), (250.0, 250.0))
        self.assertEqual(surfaces.real_size("Real World Size=300x188cm.txt"), (300.0, 188.0))
        self.assertEqual(surfaces.real_size("Oak_MultiTexture_40,8x6,8cm"), (40.8, 6.8))
        self.assertEqual(surfaces.real_size("Asphalt_Base5_4x4_4K-4x4m"), (400.0, 400.0))
        self.assertEqual(surfaces.real_size("WF_01_190x24"), (190.0, 24.0))
        self.assertEqual(surfaces.real_size("Concrete001_Raw_329cm_8K"), (329.0, 329.0))
        self.assertIsNone(surfaces.real_size("Render_1920x1080"))
        self.assertIsNone(surfaces.real_size("Oak Classic"))

    def test_role(self):
        self.assertEqual(surfaces.guess_role("x_normal.png"), "normal")
        self.assertEqual(surfaces.guess_role("x_roughness.png"), "data")
        self.assertEqual(surfaces.guess_role("fingerprints_004.jpg"), "color")


class MaterialTests(unittest.TestCase):
    def test_resolutions_merge_and_preview(self):
        mats = surfaces.build_materials(listing({
            r"L:\Wood\Oak 01": ["Oak 01.jpg"],
            r"L:\Wood\Oak 01\2K": ["Oak01_COL_2K.jpg", "Oak01_NRM_2K.jpg", "Oak01_GLOSS_2K.jpg"],
            r"L:\Wood\Oak 01\4K": ["Oak01_COL_4K.jpg", "Oak01_NRM_4K.jpg", "Oak01_NRM16_4K.tif",
                                    "Oak01_DISP_4K.jpg", "Oak01_DISP16_4K.tif"],
            r"L:\Wood": ["Oak 01.jpg"],
        }))
        self.assertEqual(len(mats), 1)
        m = mats[0]
        self.assertEqual(m.folder, r"L:\Wood\Oak 01")
        self.assertEqual(m.resolutions(), [2, 4])
        self.assertEqual(m.channels(), ["color", "gloss", "normal", "disp"])
        top = m.pick()
        self.assertTrue(top["normal"].endswith("Oak01_NRM_4K.jpg"))        # normal: 8 bits
        self.assertTrue(top["disp"].endswith("Oak01_DISP16_4K.tif"))       # desplazamiento: 16 bits
        self.assertTrue(top["gloss"].endswith("Oak01_GLOSS_2K.jpg"))       # lo que falta, de la más cercana
        self.assertTrue(m.pick(lowest=True)["color"].endswith("_2K.jpg"))
        self.assertTrue(m.pick(8)["color"].endswith("_4K.jpg"))
        self.assertEqual(m.preview, r"L:\Wood\Oak 01.jpg")
        self.assertTrue(m.thumb_source().endswith("Oak 01.jpg"))

    def test_plain_image_is_the_color(self):
        mats = surfaces.build_materials(listing({
            r"L:\Dinesen\PBR maps": ["HeartOak-350mm.jpg", "HeartOak-350mm_BUMP.jpg", "HeartOak-350mm_GLOSS.jpg"],
        }))
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0].channels(), ["color", "gloss", "bump"])

    def test_single_map_is_not_a_material(self):
        mats = surfaces.build_materials(listing({r"L:\Dirt": ["Smudge_01_roughness.jpg", "Leak.jpg"]}))
        self.assertEqual(mats, [])
        self.assertEqual(len(surfaces.build_textures(listing({r"L:\Dirt": ["Smudge_01_roughness.jpg", "Leak.jpg",
                                                                            "notes.txt"]}))), 2)

    def test_planks_become_one_material(self):
        names = []
        for i in range(1, 7):
            names += ["Oak_40,8x6,8cm_%d-Albedo.jpg" % i, "Oak_40,8x6,8cm_%d-Normal.jpg" % i]
        mats = surfaces.build_materials(listing({r"L:\Planks": names}))
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0].tiles, 6)
        self.assertEqual(mats[0].size, (40.8, 6.8))
        self.assertTrue(mats[0].pick()["color"].endswith("_1-Albedo.jpg"))

    def test_size_from_txt_and_library(self):
        mats = surfaces.build_materials(listing({
            r"L:\MOTW\Elm\Elm_8k_JPG": ["Elm_Albedo_8k.jpg", "Elm_Roughness_8k.jpg", "Real World Size=300x188cm.txt"],
            r"L:\Libs": ["Asphalt Road.mat", "Asphalt Road.jpg", "Card-3K.mat", "Card_Sphere.jpg"],
        }))
        by = {m.name: m for m in mats}
        self.assertEqual(by["Elm"].size, (300.0, 188.0))
        self.assertEqual(by["Elm"].folder, r"L:\MOTW\Elm")
        self.assertTrue(by["Asphalt Road"].is_library)
        self.assertEqual(by["Asphalt Road"].preview, r"L:\Libs\Asphalt Road.jpg")
        self.assertEqual(by["Card-3K"].preview, r"L:\Libs\Card_Sphere.jpg")

    def test_index_scan_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "lib", "Brick")
            os.makedirs(d)
            for n in ("Brick_basecolor.png", "Brick_normal.png", "loose.jpg"):
                open(os.path.join(d, n), "wb").close()
            idx = surfaces.SurfaceIndex([os.path.join(tmp, "lib")])
            idx.scan()
            self.assertEqual([m.name for m in idx.materials()], ["Brick"])
            self.assertEqual(len(idx.textures()), 3)
            cache = os.path.join(tmp, "cache.json")
            idx.save(cache)
            again = surfaces.SurfaceIndex([os.path.join(tmp, "lib")])
            self.assertTrue(again.load(cache))
            again.scan()
            self.assertEqual(again.stats["listed"], 0)
            self.assertEqual(len(again.materials()), 1)


class ExtraTests(unittest.TestCase):
    def test_preview_beside_with_other_separator(self):
        # Poliigon antiguo: carpeta «Bricks 001» y al lado «Bricks_001.jpg»
        mats = surfaces.build_materials(listing({
            r"L:\Bricks": ["Bricks_001.jpg"],
            r"L:\Bricks\Bricks 001": ["Bricks01_COL_VAR1_6K.jpg", "Bricks01_NRM_6K.jpg"],
        }))
        self.assertEqual(mats[0].preview, r"L:\Bricks\Bricks_001.jpg")
        # Superellipse: la muestra acaba en «Metal», que también es el nombre de un canal
        mats = surfaces.build_materials(listing({
            r"L:\Metal": ["Aged_Cast_Copper_Metal.png"],
            r"L:\Metal\Aged_Cast_Copper_Metal": ["Aged_Cast_Copper_Metal_basecolor.png",
                                                 "Aged_Cast_Copper_Metal_metallic.png"],
        }))
        self.assertEqual(mats[0].preview, r"L:\Metal\Aged_Cast_Copper_Metal.png")

    def test_aspect_and_header(self):
        self.assertEqual(surfaces.aspect_kind(4096, 4096), "square")
        self.assertEqual(surfaces.aspect_kind(4096, 2048), "wide")
        self.assertEqual(surfaces.aspect_kind(300, 600), "tall")
        import struct
        import zlib
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "a.png")
            ihdr = struct.pack(">IIBBBBB", 640, 320, 8, 2, 0, 0, 0)
            with open(p, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr +
                         struct.pack(">I", zlib.crc32(b"IHDR" + ihdr)))
            self.assertEqual(tuple(surfaces.image_size(p)), (640, 320))

    def test_measures_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "Vendor", "Brick A")
            os.makedirs(d)
            for n in ("BrickA_basecolor.png", "BrickA_normal.png"):
                open(os.path.join(d, n), "wb").close()
            with open(os.path.join(tmp, "Vendor", surfaces.MEASURES_FILE), "w", encoding="utf-8") as fh:
                fh.write('{"materiales": {"Brick A": [200, 100]}}')
            idx = surfaces.SurfaceIndex([os.path.join(tmp, "Vendor")])
            idx.scan()
            self.assertEqual(idx.materials()[0].size, (200.0, 100.0))
            # se lleva a la carpeta de medidas del espacio de trabajo y se sigue leyendo desde ahí
            mdir = os.path.join(tmp, "ws", "medidas")
            moved = surfaces.move_measures([os.path.join(tmp, "Vendor")], mdir)
            self.assertEqual(len(moved), 1)
            self.assertFalse(os.path.exists(os.path.join(tmp, "Vendor", surfaces.MEASURES_FILE)))
            self.assertTrue(os.path.isfile(os.path.join(mdir, "Vendor.json")))
            idx2 = surfaces.SurfaceIndex([os.path.join(tmp, "Vendor")])
            idx2.measures_dir = mdir
            idx2.scan()
            self.assertEqual(idx2.materials()[0].size, (200.0, 100.0))


class SlateTests(unittest.TestCase):
    def test_is_slate(self):
        self.assertTrue(maxlink.is_slate(["View1", "Slate Material Editor"]))
        self.assertFalse(maxlink.is_slate(["Perspective", "Untitled - 3ds Max 2026"]))


if __name__ == "__main__":
    unittest.main()
