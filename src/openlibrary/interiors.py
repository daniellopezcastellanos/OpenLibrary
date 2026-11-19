"""Interiores falsos para ventanas (wParallax, ShadersBOX): reconocer habitaciones en las carpetas.

Cada habitación es un EXR con el «atlas» de la sala (paredes, suelo, techo, muebles, cortinas) que en
3ds Max se lee con un mapa OSL (wParallax_SMP.osl / jiWindowBox) puesto en la autoiluminación de un
material sobre un plano. Aquí solo se agrupan los EXR: día/noche, resoluciones, tamaño de ventana
(S/M/L) y su vista previa. Python puro (lo prueban los tests sin Qt ni Max).
"""
import os
import re

EXR_EXTS = (".exr",)
PREVIEW_EXTS = (".jpg", ".jpeg", ".png")
# Tamaño de la ventana: ancho en cm del plano de las escenas de ejemplo (alto siempre 350)
WIDTHS = {"S": 350.0, "M": 700.0, "L": 1050.0}
HEIGHT = 350.0
SIZE_LABEL = {"S": "Ventana pequeña", "M": "Ventana mediana", "L": "Ventana grande"}
_SIZE_WORDS = {"single": "S", "double": "M", "triple": "L"}
# Shaders, del preferido al último recurso (los wParallax_* usan índices en sus desplegables)
OSL_NAMES = ("wparallax_smp.osl", "wparallax_adv.osl", "jiwindowbox_all_v1_10.osl")
_SPLIT = re.compile(r"[_\-\s]+")
_RES = re.compile(r"^(\d{1,2})k$", re.I)


def parse_room(stem, folder=""):
    """Nombre de un EXR o de una vista previa -> {key, name, light, res, size}."""
    light, res, size = None, 0, None
    words = []
    for tok in _SPLIT.split(stem):
        if not tok:
            continue
        low = tok.lower()
        if low in ("day", "night"):
            light = low
        elif _RES.match(tok):
            res = int(_RES.match(tok).group(1))
        elif tok in ("S", "M", "L"):
            size = tok
        elif low in _SIZE_WORDS:
            size = _SIZE_WORDS[low]
        elif low in ("wp", "mp") and not words:
            continue                       # prefijo de la marca
        else:
            words.append(tok)
    f = os.path.basename(folder).lower()
    if not res and "low_res" in f:
        res = 1
    elif not res and "high_res" in f:
        res = 4
    return {"key": " ".join(w.lower() for w in words), "name": " ".join(words), "light": light,
            "res": res, "size": size}


class Room(object):
    """Una habitación: sus EXR por luz (día/noche) y resolución, y su vista previa."""

    def __init__(self, name, folder, key):
        self.name = name
        self.folder = folder               # carpeta del pack
        self.key = key
        self.size = "S"
        self.exrs = {}                      # luz -> {res: ruta}
        self.previews = {}                  # luz -> ruta
        self.osl = None
        self.mtime = 0

    def lights(self):
        return [l for l in ("day", "night") if l in self.exrs]

    def resolutions(self):
        return sorted({r for by in self.exrs.values() for r in by})

    def top_res(self):
        res = self.resolutions()
        return res[-1] if res else 0

    def pick(self, light="day", res=None, lowest=False):
        """Ruta del EXR de esa luz (o la otra si no hay) y de esa resolución (o la más cercana)."""
        by = self.exrs.get(light) or next(iter(self.exrs.values()), {})
        if not by:
            return None
        keys = sorted(by)
        if lowest:
            return by[keys[0]]
        if res is None:
            return by[keys[-1]]
        return by[min(keys, key=lambda r: (abs(r - res), -r))]

    def thumb_source(self, light="day"):
        return self.previews.get(light) or next(iter(self.previews.values()), None)

    def width(self):
        return WIDTHS.get(self.size, WIDTHS["S"])

    def all_files(self):
        return [p for by in self.exrs.values() for p in by.values()]

    def matches(self, words):
        hay = (self.name + " " + self.folder + " " + SIZE_LABEL.get(self.size, "")).lower()
        return all(w in hay for w in words)


def _pack_of(folder, roots_nc):
    """Primera carpeta por debajo de la raíz: el pack (wparallax__bundle_001, shadersbox__rooms…)."""
    k = os.path.normcase(folder)
    for r in roots_nc:
        r = r.rstrip("\\/")
        if k == r:
            return folder
        if k.startswith(r + os.sep):
            first = k[len(r) + 1:].split(os.sep)[0]
            return folder[:len(r) + 1 + len(first)]
    return folder


def build_interiors(listing, roots):
    """listing (el de SurfaceIndex) -> [Room] ordenadas por pack y nombre."""
    roots_nc = [os.path.normcase(r) for r in roots]
    rooms = {}
    previews = {}
    osls = {}
    for folder, rec in listing.items():
        pack = _pack_of(folder, roots_nc)
        for fname, mtime in rec.get("f", []):
            if fname.startswith("._"):
                continue
            stem, ext = os.path.splitext(fname)
            ext = ext.lower()
            path = os.path.join(folder, fname)
            if ext == ".osl":
                osls.setdefault(os.path.normcase(pack), {}).setdefault(fname.lower(), path)
                continue
            if ext not in EXR_EXTS and ext not in PREVIEW_EXTS:
                continue
            p = parse_room(stem, folder)
            if not p["key"]:
                continue
            if ext in PREVIEW_EXTS:
                previews.setdefault((os.path.normcase(pack), p["key"]), {}).setdefault(p["light"] or "day", path)
                continue
            k = (os.path.normcase(pack), p["key"])
            room = rooms.get(k)
            if room is None:
                room = rooms[k] = Room(p["name"], pack, os.path.normcase(pack) + "|" + p["key"])
            if p["size"]:
                room.size = p["size"]
            # ShadersBOX: «…_Day.exr» y sin apellido la de noche
            light = p["light"] or "night"
            room.exrs.setdefault(light, {})[p["res"]] = path
            room.mtime = max(room.mtime, mtime)
    every = {}
    for by in osls.values():
        for low, path in by.items():
            every.setdefault(low, path)
    out = []
    for (pack_nc, key), room in rooms.items():
        room.previews = previews.get((pack_nc, key), {})
        own = osls.get(pack_nc, {})
        # el shader más nuevo que haya en la biblioteca sirve para todos los EXR (mismo atlas)
        room.osl = next((every[n] for n in OSL_NAMES if n in every), None) or \
            next((own[n] for n in OSL_NAMES if n in own), None)
        out.append(room)
    out.sort(key=lambda r: (r.folder.lower(), _natural(r.name)))
    return out


def _natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
