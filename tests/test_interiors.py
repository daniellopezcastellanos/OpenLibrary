"""Interiores wParallax / ShadersBOX: agrupar EXR por habitación, luz, resolución y tamaño de ventana."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from openlibrary import interiors  # noqa: E402


def listing(tree):
    return {folder: {"m": 0, "d": [], "f": [(n, 0) for n in names]} for folder, names in tree.items()}


ROOT = r"L:\WP"


class ParseTests(unittest.TestCase):
    def test_names(self):
        p = interiors.parse_room("wP_Lobby_v1_LB07_M_day_2K")
        self.assertEqual((p["key"], p["light"], p["res"], p["size"]), ("lobby v1 lb07", "day", 2, "M"))
        p = interiors.parse_room("mP_Rooms_v1_R01_L_night_1k")
        self.assertEqual((p["key"], p["light"], p["res"], p["size"]), ("rooms v1 r01", "night", 1, "L"))
        p = interiors.parse_room("Commerce_V10_Triple_Day", r"X\maps_high_res")
        self.assertEqual((p["key"], p["light"], p["res"], p["size"]), ("commerce v10", "day", 4, "L"))
        # la vista previa de bundle_002 no lleva tamaño: tiene que dar la misma clave
        self.assertEqual(interiors.parse_room("wp_Bedroom_01_day")["key"],
                         interiors.parse_room("wP_Bedroom_01_S_night_3K")["key"])


class BuildTests(unittest.TestCase):
    def test_rooms(self):
        rooms = interiors.build_interiors(listing({
            ROOT + r"\lobby\OSL_Shaders": ["jiWindowBox_All_v1_10.osl", "wParallax_SMP.osl"],
            ROOT + r"\lobby\wP_Lobby_01\EXR\2K": ["wP_Lobby_v1_LB07_M_day_2K.exr", "wP_Lobby_v1_LB07_M_night_2K.exr"],
            ROOT + r"\lobby\wP_Lobby_01\EXR\4K": ["wP_Lobby_v1_LB07_M_day_4K.exr"],
            ROOT + r"\lobby\wP_Lobby_01\Preview": ["wP_Lobby_v1_LB07_M_day_4K.jpg", "wP_Lobby_v1_LB07_M_night_4K.JPG"],
            ROOT + r"\sbox\maps_low_res": ["Rooms-Bedroom_V1_Single.exr", "Rooms-Bedroom_V1_Single_Day.exr"],
            ROOT + r"\sbox\maps_high_res": ["Rooms-Bedroom_V1_Single.exr"],
            ROOT + r"\bundle\osl_shaders": ["jiWindowBox_All_v1_10.osl"],
        }), [ROOT])
        self.assertEqual(len(rooms), 2)
        by = {r.name: r for r in rooms}
        lobby = by["Lobby v1 LB07"]
        self.assertEqual(lobby.folder, ROOT + r"\lobby")
        self.assertEqual(lobby.size, "M")
        self.assertEqual(lobby.width(), 700.0)
        self.assertEqual(lobby.lights(), ["day", "night"])
        self.assertEqual(lobby.resolutions(), [2, 4])
        self.assertTrue(lobby.pick("day").endswith("_day_4K.exr"))
        self.assertTrue(lobby.pick("night", 4).endswith("_night_2K.exr"))   # no hay 4K de noche
        self.assertTrue(lobby.pick("day", lowest=True).endswith("_day_2K.exr"))
        self.assertTrue(lobby.thumb_source("night").endswith("night_4K.JPG"))
        self.assertTrue(lobby.osl.endswith("wParallax_SMP.osl"))
        sbox = by["Rooms Bedroom V1"]
        self.assertEqual(sbox.size, "S")
        self.assertEqual(sbox.resolutions(), [1, 4])
        self.assertTrue(sbox.pick("day").endswith("Single_Day.exr"))
        self.assertTrue(sbox.osl.endswith("wParallax_SMP.osl"))           # el más nuevo de la biblioteca
        self.assertIsNone(sbox.thumb_source())


if __name__ == "__main__":
    unittest.main()
