"""Materiales y texturas: qué hay en las carpetas y qué mapas forman cada material.

Python puro (sin Qt ni Max). La carpeta sigue siendo la única fuente de verdad:

- Un MATERIAL es un grupo de imágenes de la misma carpeta que se llaman igual salvo el
  canal (Wood_basecolor.png, Wood_normal.png, Wood_roughness.png…) o una biblioteca .mat.
  Las resoluciones (1K, 4K, 8K) se juntan en el mismo material.
- Una TEXTURA es cualquier imagen suelta.

Los canales se reconocen por la última palabra del nombre; el tamaño real, por el nombre del
material o de su carpeta («2.5x2.5 meters», «300x188cm», «_130cm»…).
"""
import json
import os
import re

IMG_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".tga", ".bmp", ".webp", ".hdr")
MAT_EXT = ".mat"
SKIP_DIRS = {"$recycle.bin", "@eadir", "#recycle", ".openlibrary", "__macosx"}

# canal -> (insignia, color de la insignia, nombre)
CHANNELS = (
    ("color", "BC", "#C4553A", "Color base / difuso"),
    ("rough", "Rg", "#3F8F5F", "Roughness"),
    ("gloss", "Gl", "#3F8F5F", "Glossiness"),
    ("refl", "Rf", "#6C7A89", "Reflexión"),
    ("metal", "Mt", "#B08A2E", "Metalness"),
    ("normal", "Nr", "#8E7CD8", "Normal"),
    ("bump", "Bm", "#6F63A8", "Bump"),
    ("disp", "DS", "#C2218B", "Desplazamiento"),
    ("ao", "AO", "#1E9BD7", "Oclusión ambiental"),
    ("opacity", "Op", "#D9792B", "Opacidad"),
    ("emission", "Em", "#D8C02E", "Emisión"),
    ("transl", "Tr", "#3FA7A0", "Translucidez"),
)
CHANNEL_INFO = {c[0]: c for c in CHANNELS}
CHANNEL_ORDER = [c[0] for c in CHANNELS]
DATA_CHANNELS = ("rough", "gloss", "refl", "metal", "normal", "bump", "disp", "ao", "opacity")

_ALIASES = {
    "color": "col color colour albedo alb basecolor basecolour diffuse diff dif difuse",
    "rough": "roughness rough rgh",
    "gloss": "gloss glossiness glossy",
    "refl": "refl reflection reflect specular spec",
    "metal": "metallic metalness metal mtl",
    "normal": "normal nrm nor norm normalmap nrml",
    "bump": "bump bmp",
    "disp": "disp displacement displace height dsp depth heightlacement",
    "ao": "ao ambientocclusion occlusion occ",
    "opacity": "opacity alpha opc cutout alphamasked",
    "emission": "emissive emission emit selfillum",
    "transl": "translucency translucent sss",
}
_TOKEN_CHANNEL = {}
for _c, _words in _ALIASES.items():
    for _w in _words.split():
        _TOKEN_CHANNEL[_w] = _c

_RES_RE = re.compile(r"^(\d{1,2})k$")
_PX_RE = re.compile(r"^(\d{3,5})px$")
_VAR_RE = re.compile(r"^(?:var|v)(\d{1,2})$")
# palabras del final del nombre que no dicen nada del material
_NOISE = {"seamless", "tile", "tileable", "opengl", "ogl", "gl", "directx", "dx", "hires", "srgb", "raw",
          "linear", "jpg", "jpeg", "png", "tif", "tiff", "exr", "bits", "bit"}
_SPLIT_RE = re.compile(r"[_\-\s]+|\.(?!\d)")
_PREVIEW_WORDS = ("sphere", "preview", "render", "thumb", "ball", "shaderball", "promo", "cube", "flat")


def _res_of(token):
    """'4k' -> 4 ; '6563px' -> 6 ; si no es una resolución, 0."""
    m = _RES_RE.match(token)
    if m:
        return int(m.group(1))
    m = _PX_RE.match(token)
    if m:
        return max(1, int(round(int(m.group(1)) / 1024.0)))
    return 0


def parse_name(filename):
    """Parte el nombre de una imagen. -> dict:
    base (el nombre sin canal ni resolución), channel (o None), res (en K; 0 = no lo dice),
    deep (16/32 bits), variant (número de variante de color, 0 = ninguna), dx (normal DirectX)."""
    stem, ext = os.path.splitext(filename)
    tokens = [t for t in _SPLIT_RE.split(stem) if t]
    low = [t.lower() for t in tokens]
    channel = None
    res = 0
    variant = 0
    deep = ext.lower() in (".exr", ".hdr")
    dx = False
    cut = len(tokens)                # los tokens [cut:] son canal, resolución y ruido
    i = len(tokens) - 1
    while i >= 1:
        t = low[i]
        r = _res_of(t)
        if r:
            res = res or r
        elif t in ("directx", "dx"):
            dx = True
        elif t in _NOISE or (t.isdigit() and i + 1 < len(low) and low[i + 1] in ("bits", "bit")):
            if t in ("16", "32"):
                deep = True
        elif _VAR_RE.match(t) and channel is None:
            variant = int(_VAR_RE.match(t).group(1))
        elif channel is None:
            ch, used, d = _channel_at(low, i)
            if ch is None:
                break
            channel = ch
            deep = deep or d
            i -= used - 1
        else:
            break
        cut = i
        i -= 1
    base = _SPLIT_RE.sub(" ", " ".join(tokens[:cut])).strip()
    if channel is None:
        # sin canal: el nombre entero es la textura (solo se le quita la resolución del final)
        base = " ".join(tokens[:cut] if cut < len(tokens) and res else tokens)
        base = base.strip()
    return {"base": base, "channel": channel, "res": res, "deep": deep, "variant": variant, "dx": dx}


def _channel_at(low, i):
    """Canal que termina en el token i. -> (canal, tokens usados, 16 bits)."""
    t = low[i]
    deep = False
    m = re.match(r"^([a-z]+?)(16|32)$", t)
    if m and m.group(1) in _TOKEN_CHANNEL:
        t, deep = m.group(1), True
    if t in _TOKEN_CHANNEL:
        # «base color», «ambient occlusion», «normal map»
        if t in ("color", "colour") and i >= 1 and low[i - 1] == "base":
            return "color", 2, deep
        if t == "occlusion" and i >= 1 and low[i - 1] == "ambient":
            return "ao", 2, deep
        return _TOKEN_CHANNEL[t], 1, deep
    if t == "map" and i >= 1 and low[i - 1] in _TOKEN_CHANNEL:
        return _TOKEN_CHANNEL[low[i - 1]], 2, deep
    if t.endswith("map") and t[:-3] in _TOKEN_CHANNEL:
        return _TOKEN_CHANNEL[t[:-3]], 1, deep
    return None, 0, False


# ---------------------------------------------------------------------------
# Tamaño real
# ---------------------------------------------------------------------------
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(cm|mm|meters|meter|metros|mts|mt|m)"
_SIZE2_RE = re.compile(_NUM + r"\s*[xX×]\s*" + _NUM + r"\s*" + _UNIT + r"?(?![a-zA-Z0-9])")
_SIZE1_RE = re.compile(r"(?<![a-zA-Z0-9.,])" + _NUM + r"\s*(cm|meters|meter|metros|mts)(?![a-zA-Z])")
_TO_CM = {"cm": 1.0, "mm": 0.1, "m": 100.0, "mt": 100.0, "mts": 100.0, "meter": 100.0, "meters": 100.0,
          "metros": 100.0}


def _f(s):
    return float(s.replace(",", "."))


def real_size(*texts):
    """Tamaño real en cm (ancho, alto) sacado del primer texto que lo diga, o None."""
    for text in texts:
        if not text:
            continue
        for m in _SIZE2_RE.finditer(text):
            a, b, unit = _f(m.group(1)), _f(m.group(2)), (m.group(3) or "").lower()
            if a <= 0 or b <= 0:
                continue
            if not unit:
                # sin unidad: «2x2» son metros; «190x24» son centímetros
                unit = "m" if max(a, b) <= 20 else "cm"
                if max(a, b) > 1000:
                    continue                 # 1920x1080 son píxeles
            k = _TO_CM[unit]
            return (round(a * k, 2), round(b * k, 2))
        m = _SIZE1_RE.search(text)
        if m:
            a = _f(m.group(1)) * _TO_CM[m.group(2).lower()]
            if a > 0:
                return (round(a, 2), round(a, 2))
    return None


# ---------------------------------------------------------------------------
# Material y textura
# ---------------------------------------------------------------------------
class Material(object):
    """Un material: mapas por resolución, o una biblioteca .mat."""
    __slots__ = ("name", "folder", "maps", "preview", "size", "tiles", "mat_file", "mtime", "extra")

    def __init__(self, name, folder):
        self.name = name
        self.folder = folder
        self.maps = {}          # resolución (K, 0 = sin decir) -> {canal: [ruta, ...]} (la 1ª es la preferida)
        self.preview = None     # imagen de muestra del fabricante, si la hay
        self.size = None        # (ancho, alto) en cm
        self.tiles = 0          # nº de lamas/baldosas sueltas (multitextura); 0 = material normal
        self.mat_file = None    # biblioteca .mat de 3ds Max
        self.mtime = 0
        self.extra = 0          # imágenes del grupo que no son un canal conocido

    @property
    def key(self):
        return os.path.normcase(os.path.join(self.folder, self.name)) + ("|mat" if self.mat_file else "|pbr")

    @property
    def is_library(self):
        return self.mat_file is not None

    def resolutions(self):
        return sorted(self.maps)

    def channels(self):
        found = set()
        for chans in self.maps.values():
            found.update(chans)
        return [c for c in CHANNEL_ORDER if c in found]

    def top_res(self):
        r = self.resolutions()
        return r[-1] if r else 0

    def pick(self, res=None, lowest=False):
        """{canal: ruta} para una resolución (None = la más alta; lowest = la más baja).
        Si a esa resolución le falta un canal, se coge de la más cercana."""
        rs = self.resolutions()
        if not rs:
            return {}
        if res is None or res not in self.maps:
            if res is None:
                res = rs[0] if lowest else rs[-1]
            else:
                res = min(rs, key=lambda r: (abs(r - res), -r))
        out = {}
        for r in sorted(rs, key=lambda r: (abs(r - res), -r)):
            for ch, files in self.maps[r].items():
                out.setdefault(ch, files[0])
        return out

    def thumb_source(self):
        """Imagen para la miniatura: la muestra del fabricante o el color más pequeño."""
        if self.preview:
            return self.preview
        m = self.pick(lowest=True)
        return m.get("color") or m.get("rough") or m.get("gloss") or next(iter(m.values()), None)

    def all_files(self):
        out = []
        for chans in self.maps.values():
            for files in chans.values():
                out.extend(files)
        if self.mat_file:
            out.append(self.mat_file)
        return out

    def matches(self, words):
        hay = (self.name + " " + self.folder).lower()
        return all(w in hay for w in words)


class Texture(object):
    __slots__ = ("name", "folder", "path", "mtime", "channel")

    def __init__(self, path, mtime=0):
        self.path = path
        self.folder, fname = os.path.split(path)
        self.name = os.path.splitext(fname)[0]
        self.mtime = mtime
        self.channel = None

    @property
    def key(self):
        return os.path.normcase(self.path)

    def matches(self, words):
        hay = (self.name + " " + self.folder).lower()
        return all(w in hay for w in words)


def _is_res_folder(name):
    """Carpetas que solo separan resoluciones o formatos: «4K», «8k_JPG», «…-1K», «2k»."""
    low = name.lower()
    toks = [t for t in _SPLIT_RE.split(low) if t]
    if not toks:
        return False
    if all(_res_of(t) or t in _NOISE or t.isdigit() for t in toks):
        return True
    return bool(_res_of(toks[-1])) or (len(toks) >= 2 and toks[-1] in _NOISE and bool(_res_of(toks[-2])))


def _prefer(ch, a, b):
    """True si la imagen a es mejor que b para el canal: 16 bits en desplazamiento, 8 en el resto."""
    da, db = a[1], b[1]
    if da != db:
        return da if ch == "disp" else not da
    return a[0].lower() < b[0].lower()


MEASURES_FILE = "openlibrary_medidas.json"


def load_measures(listing):
    """Medidas apuntadas en archivos «openlibrary_medidas.json» de la biblioteca.
    Cada uno: {"materiales": {"subcarpeta\\del\\material": [ancho_cm, alto_cm], ...}} con rutas relativas a
    su carpeta; «carpeta|Nombre» cuando en una carpeta hay varios materiales.
    -> {carpeta normcase o "carpeta normcase|nombre en minúsculas": (ancho, alto)}"""
    out = {}
    for folder, rec in listing.items():
        if not any(n.lower() == MEASURES_FILE for n, _m in rec.get("f", [])):
            continue
        try:
            with open(os.path.join(folder, MEASURES_FILE), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for rel, size in (data.get("materiales") or {}).items():
            try:
                w, h = float(size[0]), float(size[1])
            except (TypeError, ValueError, IndexError):
                continue
            if w > 0 and h > 0:
                rel, _sep, name = rel.partition("|")
                key = os.path.normcase(os.path.normpath(os.path.join(folder, rel)))
                out[key + "|" + name.lower() if name else key] = (w, h)
    return out


def measures_file_for(measures_dir, root):
    """Archivo de medidas de una carpeta raíz dentro de la carpeta de medidas: «02_POLIIGON.json»."""
    name = os.path.basename(os.path.normpath(root)) or "raiz"
    return os.path.join(measures_dir, name + ".json")


def load_measures_dir(measures_dir, roots):
    """Medidas guardadas en la carpeta de medidas (una por raíz, claves relativas a esa raíz)."""
    out = {}
    if not measures_dir:
        return out
    for root in roots:
        try:
            with open(measures_file_for(measures_dir, root), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for rel, size in (data.get("materiales") or {}).items():
            try:
                w, h = float(size[0]), float(size[1])
            except (TypeError, ValueError, IndexError):
                continue
            if w > 0 and h > 0:
                rel, _sep, name = rel.partition("|")
                key = os.path.normcase(os.path.normpath(os.path.join(root, rel)))
                out[key + "|" + name.lower() if name else key] = (w, h)
    return out


def move_measures(roots, measures_dir):
    """Lleva los «openlibrary_medidas.json» que haya en las carpetas raíz a la carpeta de medidas
    (si ya hay uno de esa raíz, se mezclan). Devuelve [(origen, destino)]."""
    moved = []
    for root in roots:
        src = os.path.join(root, MEASURES_FILE)
        if not os.path.isfile(src):
            continue
        dest = measures_file_for(measures_dir, root)
        try:
            with open(src, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if os.path.isfile(dest):
                with open(dest, "r", encoding="utf-8") as fh:
                    old = json.load(fh)
                merged = dict(old.get("materiales") or {})
                merged.update(data.get("materiales") or {})
                data["materiales"] = merged
            os.makedirs(measures_dir, exist_ok=True)
            tmp = dest + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, dest)
            os.remove(src)
            moved.append((src, dest))
        except (OSError, ValueError):
            continue
    return moved


def build_materials(listing):
    """listing: {carpeta: {"f": [(nombre, mtime), ...]}} -> [Material] ordenados por nombre."""
    groups = {}             # (carpeta del grupo normcase, base.lower()) -> datos
    libs = []
    loose = {}              # carpeta -> {stem.lower(): ruta} de imágenes que no son un canal
    plain = {}              # (carpeta del grupo, base.lower()) -> imagen sin apellido: suele ser el color
    for folder, rec in listing.items():
        names = rec.get("f", [])
        if not names:
            continue
        gfolder = os.path.dirname(folder) if _is_res_folder(os.path.basename(folder)) else folder
        for fname, mtime in names:
            ext = os.path.splitext(fname)[1].lower()
            if fname.startswith("._"):
                continue
            if ext == MAT_EXT:
                libs.append((folder, fname, mtime))
                continue
            if ext not in IMG_EXTS:
                continue
            p = parse_name(fname)
            path = os.path.join(folder, fname)
            if p["channel"] is None:
                loose.setdefault(os.path.normcase(folder), {})[os.path.splitext(fname)[0].lower()] = path
                plain.setdefault((os.path.normcase(gfolder), p["base"].lower()), []).append((path, p))
                continue
            key = (os.path.normcase(gfolder), p["base"].lower())
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"name": p["base"], "folder": gfolder, "files": [], "mtime": 0, "src": set()}
            g["files"].append((path, p))
            g["mtime"] = max(g["mtime"], mtime)
            g["src"].add(folder)

    # Lamas sueltas de un mismo suelo («…_1-Albedo», «…_2-Albedo»): un solo material
    merged = {}
    stems = {}
    for key, g in groups.items():
        m = re.match(r"^(.*?)[\s_\-]*(\d{1,3})$", key[1])
        if m and m.group(1):
            stems.setdefault((key[0], m.group(1)), []).append((int(m.group(2)), key))
    for (gf, stem), members in stems.items():
        if len(members) < 4:
            continue
        members.sort()
        first = groups[members[0][1]]
        g = {"name": re.sub(r"[\s_\-]*\d{1,3}$", "", first["name"]) or first["name"], "folder": first["folder"],
             "files": list(first["files"]), "mtime": max(groups[k]["mtime"] for _, k in members),
             "src": set(first["src"]), "tiles": len(members)}
        for _, k in members:
            merged[k] = None
        merged[(gf, stem + "|tiles")] = g
    for k, v in merged.items():
        if v is None:
            groups.pop(k, None)
        else:
            groups[k] = v

    out = []
    for key, g in groups.items():
        chans = set(p["channel"] for _, p in g["files"])
        if "color" not in chans and not g.get("tiles"):
            # «Oak.jpg» junto a «Oak_BUMP.jpg» y «Oak_GLOSS.jpg»: la que no lleva apellido es el color
            for path, p in plain.get(key, []):
                p = dict(p, channel="color")
                g["files"].append((path, p))
                chans.add("color")
        if len(chans) < 2:
            continue                 # una sola imagen con apellido de canal no es un material
        mat = Material(g["name"], g["folder"])
        mat.mtime = g["mtime"]
        mat.tiles = g.get("tiles", 0)
        best = {}
        for path, p in g["files"]:
            if p["variant"] > 1:
                mat.extra += 1
                continue             # variantes de color: se usa la primera
            slot = best.setdefault(p["res"], {}).setdefault(p["channel"], [])
            slot.append((path, p["deep"]))
        for res, by_ch in best.items():
            mat.maps[res] = {}
            for ch, cands in by_ch.items():
                ordered = []
                for c in cands:
                    pos = 0
                    while pos < len(ordered) and not _prefer(ch, c, ordered[pos]):
                        pos += 1
                    ordered.insert(pos, c)
                mat.maps[res][ch] = [c[0] for c in ordered]
        mat.size = real_size(mat.name, os.path.basename(mat.folder),
                             *_txt_names(listing, g["src"] | {mat.folder}))
        mat.preview = _find_preview(mat, loose, listing)
        out.append(mat)

    for folder, fname, mtime in libs:
        stem = os.path.splitext(fname)[0]
        mat = Material(stem, folder)
        mat.mat_file = os.path.join(folder, fname)
        mat.mtime = mtime
        mat.size = real_size(stem)
        mat.preview = _lib_preview(stem, loose.get(os.path.normcase(folder), {}))
        out.append(mat)
    out.sort(key=lambda m: (m.name.lower(), m.folder.lower()))
    return out


def _txt_names(listing, folders):
    out = []
    for f in folders:
        for fname, _m in listing.get(f, {}).get("f", []):
            if fname.lower().endswith(".txt") and not fname.startswith("._"):
                out.append(fname)
    return out


def _find_preview(mat, loose, listing):
    """Muestra del fabricante: en la carpeta del material o, con su mismo nombre, al lado de ella."""
    here = loose.get(os.path.normcase(mat.folder), {})
    low = mat.name.lower().replace(" ", "")
    best = None
    for stem, path in here.items():
        s = stem.replace(" ", "").replace("_", "").replace("-", "")
        if not any(w in stem for w in _PREVIEW_WORDS):
            continue
        rank = next(i for i, w in enumerate(_PREVIEW_WORDS) if w in stem)
        if low.replace("_", "").replace("-", "") not in s and len(here) > 6:
            continue                 # carpeta con muchos materiales: la muestra tiene que nombrarlo
        if best is None or rank < best[0]:
            best = (rank, path)
    if best:
        return best[1]
    parent = os.path.dirname(mat.folder)
    side = loose.get(os.path.normcase(parent), {})
    hit = side.get(os.path.basename(mat.folder).lower())
    if not hit:
        # «Bricks 001» con «Bricks_001.jpg» al lado: se comparan sin espacios, guiones ni mayúsculas
        want = {_squash(os.path.basename(mat.folder)), _squash(mat.name)}
        hit = next((path for stem, path in side.items() if _squash(stem) in want), None)
    if not hit:
        # imagen al lado con el nombre exacto de la carpeta aunque parezca un canal
        # (Superellipse: «Aged_Cast_Copper_Metal.png», que acaba en «Metal»)
        folder_sq = _squash(os.path.basename(mat.folder))
        for fname, _m in listing.get(parent, {}).get("f", []):
            stem, ext = os.path.splitext(fname)
            if ext.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp") and _squash(stem) == folder_sq:
                hit = os.path.join(parent, fname)
                break
    if hit and not hit.lower().endswith((".exr", ".hdr")):
        return hit
    return None


def _squash(s):
    return re.sub(r"[^0-9a-z]", "", s.lower())


def image_size(path):
    """(ancho, alto) en píxeles leyendo solo la cabecera (JPG, PNG, TIFF). None si no se puede."""
    import struct
    try:
        with open(path, "rb") as fh:
            head = fh.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    b = fh.read(1)
                    while b and b != b"\xff":
                        b = fh.read(1)
                    while b == b"\xff":
                        b = fh.read(1)
                    if not b:
                        return None
                    marker = b[0]
                    if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                        continue
                    seg = fh.read(2)
                    if len(seg) < 2:
                        return None
                    length = struct.unpack(">H", seg)[0]
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        data = fh.read(5)
                        h, w = struct.unpack(">HH", data[1:5])
                        return (w, h)
                    fh.seek(length - 2, 1)
            if head[:4] in (b"II*\x00", b"MM\x00*"):
                end = "<" if head[:2] == b"II" else ">"
                fh.seek(struct.unpack(end + "I", head[4:8])[0])
                n = struct.unpack(end + "H", fh.read(2))[0]
                vals = {}
                for _ in range(min(n, 64)):
                    tag, typ, _cnt = struct.unpack(end + "HHI", fh.read(8))
                    raw = fh.read(4)
                    if tag in (256, 257):
                        vals[tag] = struct.unpack(end + ("H" if typ == 3 else "I"), raw[:2] if typ == 3 else raw)[0]
                if 256 in vals and 257 in vals:
                    return (vals[256], vals[257])
    except (OSError, struct.error, IndexError, ValueError):
        return None
    return None


def aspect_kind(w, h):
    """"square", "wide" (más ancho que alto) o "tall"; None si no se sabe."""
    if not w or not h:
        return None
    r = float(w) / float(h)
    if 0.95 <= r <= 1.05:
        return "square"
    return "wide" if r > 1 else "tall"


def _lib_preview(stem, images):
    s = stem.lower()
    for key in (s, s + "_sphere", s + "-01", s + "_01", s + " 01", s + "_preview", s + "_cube", s + "_flat"):
        if key in images:
            return images[key]
    # «Nombre-3K.mat» con «Nombre_Sphere.jpg»
    short = re.sub(r"[\s_\-]*\d{1,2}k$", "", s)
    if short != s:
        for key in (short + "_sphere", short, short + "_cube", short + "_flat"):
            if key in images:
                return images[key]
    return None


def build_textures(listing):
    """Todas las imágenes sueltas. -> [Texture] por carpeta y nombre."""
    out = []
    for folder, rec in listing.items():
        for fname, mtime in rec.get("f", []):
            if fname.startswith("._") or os.path.splitext(fname)[1].lower() not in IMG_EXTS:
                continue
            t = Texture(os.path.join(folder, fname), mtime)
            t.channel = parse_name(fname)["channel"]
            out.append(t)
    out.sort(key=lambda t: (t.folder.lower(), t.name.lower()))
    return out


def guess_role(name):
    """Cómo cargar una textura suelta: "color", "normal" o "data" (lineal)."""
    ch = parse_name(name)["channel"]
    if ch == "normal":
        return "normal"
    if ch in DATA_CHANNELS:
        return "data"
    return "color"


# ---------------------------------------------------------------------------
# Índice de carpetas con caché (solo se vuelven a listar las que cambian)
# ---------------------------------------------------------------------------
class SurfaceIndex(object):
    VERSION = 2              # 2: también se listan los .osl (interiores wParallax)

    def __init__(self, roots):
        self.roots = [r for r in roots if r]
        self.listing = {}        # carpeta -> {"m": mtime, "d": [subcarpetas], "f": [(nombre, mtime)]}
        self.folders = []
        self.cancelled = False
        self.stats = {"listed": 0, "reused": 0}
        self._materials = None
        self._textures = None
        self._interiors = None
        self.dims = {}           # ruta del mapa -> [ancho, alto, mtime] en píxeles (para cuadrada / rectangular)
        self.measures_dir = None  # carpeta de medidas del espacio de trabajo (la pone la interfaz)

    # -- vistas (se calculan una vez por lectura) --
    def interiors(self):
        if self._interiors is None:
            from .interiors import build_interiors
            self._interiors = build_interiors(self.listing, self.roots)
        return self._interiors

    def materials(self):
        if self._materials is None:
            mats = build_materials(self.listing)
            measures = load_measures(self.listing)          # las que aún estén dentro de la biblioteca
            measures.update(load_measures_dir(self.measures_dir, self.roots))
            if measures:
                for m in mats:
                    if not m.size and not m.is_library:
                        k = os.path.normcase(os.path.normpath(m.folder))
                        m.size = measures.get(k + "|" + m.name.lower()) or measures.get(k)
            self._materials = mats
        return self._materials

    def textures(self):
        if self._textures is None:
            self._textures = build_textures(self.listing)
        return self._textures

    def dims_for(self, mat):
        """(ancho, alto) en píxeles del mapa de color del material, si ya se leyó."""
        path = self._dims_path(mat)
        d = self.dims.get(path) if path else None
        return (d[0], d[1]) if d else None

    @staticmethod
    def _dims_path(mat):
        if getattr(mat, "is_library", True):
            return None
        picked = mat.pick()
        return picked.get("color") or next(iter(picked.values()), None)

    def fill_dims(self, progress=None):
        """Lee la cabecera de los mapas de color que aún no se conocen (o que han cambiado)."""
        mtimes = {}
        for folder, rec in self.listing.items():
            for name, mt in rec.get("f", []):
                mtimes[os.path.join(folder, name)] = mt
        done = 0
        for mat in self.materials():
            if self.cancelled:
                return
            path = self._dims_path(mat)
            if not path:
                continue
            mt = mtimes.get(path, 0)
            old = self.dims.get(path)
            if old and old[2] == mt:
                continue
            size = image_size(path)
            self.dims[path] = [size[0], size[1], mt] if size else [0, 0, mt]
            done += 1
            if progress and done % 100 == 0:
                progress(done)

    def _reset(self):
        self._materials = None
        self._textures = None
        self._interiors = None
        self.folders = sorted(self.listing, key=lambda s: s.lower())

    def scan(self, progress=None, incremental=True):
        old = self.listing if incremental else {}
        new = {}
        self.stats = {"listed": 0, "reused": 0}
        stack = [r for r in self.roots if os.path.isdir(r)]
        offline = [r for r in self.roots if not os.path.isdir(r)]
        while stack:
            if self.cancelled:
                return
            folder = stack.pop()
            try:
                mtime = int(os.stat(folder).st_mtime)
            except OSError:
                continue
            rec = old.get(folder)
            if rec is not None and rec.get("m") == mtime:
                self.stats["reused"] += 1
            else:
                rec = self._list(folder, mtime)
                self.stats["listed"] += 1
            new[folder] = rec
            for d in rec["d"]:
                stack.append(os.path.join(folder, d))
            if progress and (len(new) % 50) == 0:
                progress(len(new), sum(len(r["f"]) for r in new.values()) if len(new) % 500 == 0 else -1)
        # una raíz sin conexión conserva lo último que se leyó de ella
        for folder, rec in old.items():
            if any(_under(folder, r) for r in offline):
                new[folder] = rec
        self.listing = new
        self._reset()

    @staticmethod
    def _list(folder, mtime):
        dirs, files = [], []
        try:
            for e in os.scandir(folder):
                name = e.name
                try:
                    if e.is_dir():
                        if not name.startswith(".") and name.lower() not in SKIP_DIRS:
                            dirs.append(name)
                    else:
                        ext = os.path.splitext(name)[1].lower()
                        if ext in IMG_EXTS or ext in (MAT_EXT, ".txt", ".osl") or name.lower() == MEASURES_FILE:
                            files.append((name, int(e.stat().st_mtime)))
                except OSError:
                    continue
        except OSError:
            pass
        return {"m": mtime, "d": dirs, "f": files}

    def save(self, cache_file):
        try:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": self.VERSION, "roots": self.roots, "listing": self.listing,
                           "dims": self.dims}, fh)
            os.replace(tmp, cache_file)
        except OSError:
            pass

    def load(self, cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False
        if data.get("version") != self.VERSION:
            return False
        self.listing = {k: {"m": v.get("m", 0), "d": v.get("d", []), "f": [tuple(x) for x in v.get("f", [])]}
                        for k, v in data.get("listing", {}).items()}
        self.dims = {k: v for k, v in data.get("dims", {}).items() if isinstance(v, list) and len(v) == 3}
        self._reset()
        return True


def _under(folder, root):
    f, r = os.path.normcase(folder), os.path.normcase(root).rstrip("\\/")
    return f == r or f.startswith(r + os.sep)


def cache_path_for(cache_dir, roots):
    import hashlib
    key = "|".join(sorted(os.path.normcase(r) for r in roots))
    return os.path.join(cache_dir, "surf_" + hashlib.md5(key.encode("utf-8")).hexdigest()[:16] + ".json")
