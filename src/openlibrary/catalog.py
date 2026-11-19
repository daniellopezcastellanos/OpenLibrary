"""Catalogar una descarga: repartir sus archivos y dejarlos en la biblioteca con su nombre.

Estructura que se crea (p. ej. destino = ...\\Dimensiva\\Furniture, nombre = «Sofa Bolzano»):

    Furniture\\Sofa Bolzano.max            el modelo (con _corona / _vray si hay varias versiones)
    Furniture\\Sofa Bolzano.jpg            el preview, con el mismo nombre -> sale de miniatura
    Furniture\\z-maps\\Sofa Bolzano\\...     texturas y todo lo demás, con sus nombres originales

Python puro, sin Qt.
"""
import os
import re
import shutil

from .library import IMG_EXTS, MAX_EXT

MAPS_FOLDER = "z-maps"
KINDS = ("skip", "max", "preview", "maps")
_JUNK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
_JUNK_EXTS = {".url", ".lnk", ".webloc"}
_MAPS_DIRS = re.compile(r"(^|[\\/ _.-])(maps?|textures?|texturas?|tex|bitmaps?|images?|materials?)($|[\\/ _.-])", re.I)
_PREVIEW_WORDS = ("preview", "prev", "render", "thumb", "cover", "beauty")
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_YEAR = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
ENGINES = ("corona", "vray", "fstorm")


class Item(object):
    """Un archivo de la descarga. `rel` = subcarpeta donde venía (solo informativo)."""
    def __init__(self, path, rel=""):
        self.path = path
        self.name = os.path.basename(path)
        self.rel = rel
        self.ext = os.path.splitext(self.name)[1].lower()
        try:
            self.size = os.path.getsize(path)
        except OSError:
            self.size = 0

    @property
    def is_image(self):
        return self.ext in IMG_EXTS


def list_files(folder):
    """Todos los archivos de la carpeta, sin estructura (las subcarpetas se aplanan)."""
    out = []
    for d, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if x.lower() != "__macosx"]
        rel = os.path.relpath(d, folder)
        rel = "" if rel == "." else rel
        for f in files:
            out.append(Item(os.path.join(d, f), rel))
    out.sort(key=lambda i: (i.ext != MAX_EXT, i.name.lower()))
    return out


def guess(items, source_name=""):
    """Reparto propuesto: {path: "max" | "preview" | "maps" | "skip"}.

    Los .max van a su sitio; lo demás, a texturas. De preview solo se propone una imagen si
    está clara (se llama como el .max o como la descarga, lleva «preview» en el nombre, o es
    la única imagen que no viene en una carpeta de mapas).
    """
    out = {}
    stems = set()
    for it in items:
        low = it.name.lower()
        if it.ext == MAX_EXT:
            out[it.path] = "max"
            stems.add(os.path.splitext(low)[0])
        elif low in _JUNK_NAMES or it.ext in _JUNK_EXTS or low.startswith("._"):
            out[it.path] = "skip"
        else:
            out[it.path] = "maps"
    if source_name:
        stems.add(source_name.lower())
    images = [it for it in items if it.is_image and out[it.path] == "maps"]
    best, best_score = None, 0
    loose = [it for it in images if not _MAPS_DIRS.search(it.rel)]
    for it in images:
        stem = os.path.splitext(it.name)[0].lower()
        in_maps = bool(_MAPS_DIRS.search(it.rel))
        score = 0
        if any(w in stem for w in _PREVIEW_WORDS):
            score = 5
        elif stem in stems and not in_maps:
            score = 4
        elif len(loose) == 1 and it is loose[0] and len(images) > 1:
            score = 3
        elif len(images) == 1 and not in_maps:
            score = 2
        if score > best_score:
            best, best_score = it, score
    if best is not None:
        out[best.path] = "preview"
    return out


def engine_of(path, detected=None):
    """Motor de un .max: el leído del archivo y, si no se pudo, el que diga su nombre."""
    if detected in ENGINES:
        return detected
    low = os.path.basename(path).lower()
    for eng, keys in (("corona", ("corona", "_cr.", "_cr_")), ("vray", ("vray", "v-ray", "v_ray", "_vr.", "_vr_")),
                      ("fstorm", ("fstorm",))):
        if any(k in low for k in keys):
            return eng
    return None


def clean_name(text):
    """Nombre válido para archivo y carpeta en Windows."""
    text = _BAD_CHARS.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.upper() in ("CON", "PRN", "AUX", "NUL") or re.match(r"^(COM|LPT)\d$", text, re.I):
        text += "_"
    return text


def max_names(name, maxes):
    """Nombre final de cada .max. maxes: [(ruta, motor)] -> [nombre de archivo], en el mismo orden.

    Uno solo: «Nombre.max». Varios: «Nombre_corona.max», «Nombre_vray.max»... y si se repite el
    motor, se distingue con el año que lleve el archivo original («Nombre 2016_corona.max») o un número.
    """
    if len(maxes) == 1:
        return [name + MAX_EXT]
    used = set()
    out = []
    for path, engine in maxes:
        suffix = "_" + engine if engine in ENGINES else ""
        cand = name + suffix
        if cand.lower() in used:
            year = _YEAR.search(os.path.splitext(os.path.basename(path))[0])
            cand = "%s %s%s" % (name, year.group(1), suffix) if year else cand
            n = 2
            while cand.lower() in used:
                cand = "%s %d%s" % (name, n, suffix)
                n += 1
        used.add(cand.lower())
        out.append(cand + MAX_EXT)
    return out


class Plan(object):
    def __init__(self):
        self.ops = []            # (origen, destino)
        self.maps_dir = None     # carpeta de texturas (None si no hay nada que dejar en ella)
        self.skipped = 0         # texturas repetidas (mismo nombre y tamaño) que no hace falta copiar dos veces

    def conflicts(self):
        return [dst for _src, dst in self.ops if os.path.exists(dst)]


def plan(dest, name, maxes, previews, others, maps_folder=MAPS_FOLDER):
    """Qué archivo va a dónde. maxes: [(ruta, motor)]; previews y others: [ruta]."""
    p = Plan()
    for (src, _eng), fname in zip(maxes, max_names(name, maxes)):
        p.ops.append((src, os.path.join(dest, fname)))
    for i, src in enumerate(previews):
        ext = os.path.splitext(src)[1].lower()
        p.ops.append((src, os.path.join(dest, name + ("" if i == 0 else "_%d" % (i + 1)) + ext)))
    if others:
        p.maps_dir = os.path.join(dest, clean_name(maps_folder) or MAPS_FOLDER, name)
        seen = {}
        for src in others:
            fname = os.path.basename(src)
            try:
                size = os.path.getsize(src)
            except OSError:
                size = -1
            key = fname.lower()
            if key in seen:
                if size in seen[key]:
                    p.skipped += 1          # la misma textura venía en dos carpetas
                    continue
                stem, ext = os.path.splitext(fname)
                n = 2
                while ("%s (%d)%s" % (stem, n, ext)).lower() in seen:
                    n += 1
                fname = "%s (%d)%s" % (stem, n, ext)
                key = fname.lower()
            seen.setdefault(key, set()).add(size)
            p.ops.append((src, os.path.join(p.maps_dir, fname)))
    return p


def apply(p, move=False, progress=None, cancelled=None):
    """Copia (o mueve) los archivos del plan. Devuelve cuántos ha dejado."""
    done = 0
    for src, dst in p.ops:
        if cancelled and cancelled():
            break
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
        if move:
            shutil.move(src, dst)
        else:
            shutil.copy2(src, dst)
        done += 1
        if progress:
            progress(done, len(p.ops))
    return done


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0
