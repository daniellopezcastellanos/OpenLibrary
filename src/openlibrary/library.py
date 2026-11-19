"""Indexado de una biblioteca de modelos.

Convención (sin base de datos, la carpeta es la verdad):

    Sillas/
        Silla_Eames_corona.max     -> versión Corona
        Silla_Eames_vray.max       -> versión V-Ray
        Silla_Eames_fstorm.max     -> versión FStorm
        Silla_Eames.jpg            -> preview (también .png / _preview.jpg)
        maps/ ...                  -> texturas (se usan al re-enlazar)
        _proxies/ ...              -> proxies generados (se ignoran al indexar)

Un .max sin sufijo de motor también es un asset: su motor se detecta leyendo
las clases del archivo (ver maxfile.detect_engine).
"""
import json
import os
import re

MAX_EXT = ".max"
IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
SKIP_DIRS = {"_proxies", ".openlibrary", "$recycle.bin", "@eadir", "#recycle", "autobackup"}

_SUFFIX_RE = re.compile(r"^(?P<base>.+?)[\s_\-\.]+(?P<eng>corona|cr|vray|v-ray|vr|fstorm)$", re.I)
_ENGINE_ALIASES = {"corona": "corona", "cr": "corona", "vray": "vray", "v-ray": "vray", "vr": "vray",
                   "fstorm": "fstorm"}


def split_engine_suffix(stem):
    """'Silla_corona' -> ('Silla', 'corona'); 'Silla' -> ('Silla', None)."""
    m = _SUFFIX_RE.match(stem)
    if m:
        return m.group("base"), _ENGINE_ALIASES[m.group("eng").lower()]
    return stem, None


class Asset(object):
    __slots__ = ("name", "folder", "versions", "auto_files", "preview", "mtime")

    def __init__(self, name, folder):
        self.name = name
        self.folder = folder
        self.versions = {}      # engine -> path (por sufijo)
        self.auto_files = []    # .max sin sufijo (motor por detectar)
        self.preview = None
        self.mtime = 0

    @property
    def key(self):
        return os.path.normcase(os.path.join(self.folder, self.name))

    def all_files(self):
        return list(self.versions.values()) + list(self.auto_files)

    def engines(self, engine_cache=None):
        """Motores disponibles (para los iconos)."""
        found = set(self.versions)
        for f in self.auto_files:
            eng = engine_cache.get(f) if engine_cache else None
            found.add(eng or "pending")
        return found

    def file_for_engine(self, engine, engine_cache=None):
        """Archivo para el motor pedido o None."""
        if engine in self.versions:
            return self.versions[engine]
        for f in self.auto_files:
            eng = engine_cache.detect(f) if engine_cache else "other"
            if eng == engine:
                return f
        return None

    def any_file(self):
        files = self.all_files()
        return files[0] if files else None

    def to_dict(self):
        return {"n": self.name, "v": self.versions, "a": self.auto_files, "p": self.preview, "m": self.mtime}

    @classmethod
    def from_dict(cls, d, folder):
        a = cls(d["n"], folder)
        a.versions = d.get("v", {})
        a.auto_files = d.get("a", [])
        a.preview = d.get("p")
        a.mtime = d.get("m", 0)
        return a

    def default_preview_path(self):
        return os.path.join(self.folder, self.name + ".jpg")

    def matches(self, words):
        hay = (self.name + " " + os.path.basename(self.folder)).lower()
        return all(w in hay for w in words)


def _find_preview(name, stems, images):
    """images: dict stem.lower() -> path."""
    candidates = [name] + list(stems)
    for stem in candidates:
        s = stem.lower()
        for key in (s, s + "_preview", s + "-preview", s + " preview", s + "_thumb"):
            if key in images:
                return images[key]
    return None


def scan_folder(folder, entries=None):
    """Assets de UNA carpeta (no recursivo). entries: os.scandir ya hecho."""
    if entries is None:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return []
    groups = {}
    images = {}
    sub_previews = {}
    for e in entries:
        try:
            is_file = e.is_file()
        except OSError:
            continue
        name = e.name
        low = name.lower()
        if is_file:
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if ext == MAX_EXT:
                base, eng = split_engine_suffix(stem)
                g = groups.setdefault(base.lower(), [base, {}, [], [], 0])
                if eng and eng not in g[1]:
                    g[1][eng] = e.path
                else:
                    g[2].append(e.path)
                g[3].append(stem)
                try:
                    g[4] = max(g[4], e.stat().st_mtime)
                except OSError:
                    pass
            elif ext in IMG_EXTS:
                images[stem.lower()] = e.path
        elif low in ("previews", "preview", "_previews", "thumbs"):
            try:
                for se in os.scandir(e.path):
                    st, ext = os.path.splitext(se.name)
                    if ext.lower() in IMG_EXTS:
                        sub_previews[st.lower()] = se.path
            except OSError:
                pass
    for k, v in sub_previews.items():
        images.setdefault(k, v)

    assets = []
    for base, versions, autos, stems, mtime in groups.values():
        a = Asset(base, folder)
        a.versions = versions
        a.auto_files = autos
        a.preview = _find_preview(base, stems, images)
        if a.preview is None and len(groups) == 1:
            # Carpeta de un solo asset con "preview.jpg" o similar
            for k in ("preview", "thumb", "thumbnail", os.path.basename(folder).lower()):
                if k in images:
                    a.preview = images[k]
                    break
        a.mtime = mtime
        assets.append(a)
    assets.sort(key=lambda x: x.name.lower())
    return assets


class LibraryIndex(object):
    """Índice de una pestaña (varias carpetas raíz), con caché en disco.

    La primera vez se lee todo. Después se carga la caché al instante y se hace
    una pasada incremental: solo se vuelve a listar una carpeta si su fecha de
    modificación ha cambiado (Windows y los NAS la actualizan al crear, borrar o
    renombrar algo dentro). Para las demás basta un stat.
    """
    CACHE_VERSION = 2

    def __init__(self, roots):
        if isinstance(roots, str):
            roots = [roots]
        self.roots = [os.path.normpath(r) for r in roots if r]
        self.records = {}          # normcase(folder) -> {"path", "mtime", "subdirs", "assets"}
        self.folders = []
        self.assets = []
        self.by_folder = {}
        self.cancelled = False
        self.stats = {"listed": 0, "reused": 0}

    @property
    def root(self):
        return self.roots[0] if self.roots else None

    # ------------------------------------------------------------------
    def _rebuild(self):
        self.folders = sorted((r["path"] for r in self.records.values()), key=lambda p: p.lower())
        self.by_folder = {k: r["assets"] for k, r in self.records.items() if r["assets"]}
        self.assets = [a for lst in self.by_folder.values() for a in lst]

    @staticmethod
    def _list_folder(folder):
        entries = list(os.scandir(folder))
        subdirs = []
        for e in entries:
            try:
                if e.is_dir() and e.name.lower() not in SKIP_DIRS and not e.name.startswith("."):
                    subdirs.append(e.path)
            except OSError:
                pass
        return sorted(subdirs, key=lambda p: p.lower()), scan_folder(folder, entries)

    def scan(self, progress=None, incremental=True):
        old = self.records if incremental else {}
        new = {}
        self.stats = {"listed": 0, "reused": 0}
        for root in self.roots:
            stack = [root]
            while stack and not self.cancelled:
                folder = stack.pop()
                key = os.path.normcase(folder)
                try:
                    mtime = os.stat(folder).st_mtime
                except OSError:
                    continue
                rec = old.get(key)
                if rec is None or rec["mtime"] != mtime:
                    try:
                        subdirs, assets = self._list_folder(folder)
                    except OSError:
                        continue
                    rec = {"path": folder, "mtime": mtime, "subdirs": subdirs, "assets": assets}
                    self.stats["listed"] += 1
                else:
                    self.stats["reused"] += 1
                new[key] = rec
                stack.extend(reversed(rec["subdirs"]))
                if progress and len(new) % 25 == 0:
                    progress(len(new), sum(len(r["assets"]) for r in new.values()))
        if not self.cancelled:
            self.records = new
            self._rebuild()
        return self

    def rescan_folder(self, folder):
        key = os.path.normcase(os.path.normpath(folder))
        try:
            subdirs, assets = self._list_folder(folder)
            mtime = os.stat(folder).st_mtime
        except OSError:
            return []
        self.records[key] = {"path": os.path.normpath(folder), "mtime": mtime,
                             "subdirs": subdirs, "assets": assets}
        self._rebuild()
        return assets

    # --- caché en disco -------------------------------------------------
    def save(self, path):
        data = {"version": self.CACHE_VERSION, "roots": self.roots, "records": [
            {"path": r["path"], "mtime": r["mtime"], "subdirs": r["subdirs"],
             "assets": [a.to_dict() for a in r["assets"]]}
            for r in self.records.values()]}
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            pass

    def load(self, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False
        if data.get("version") != self.CACHE_VERSION or \
                [os.path.normcase(r) for r in data.get("roots", [])] != [os.path.normcase(r) for r in self.roots]:
            return False
        recs = {}
        for r in data.get("records", []):
            recs[os.path.normcase(r["path"])] = {
                "path": r["path"], "mtime": r["mtime"], "subdirs": r["subdirs"],
                "assets": [Asset.from_dict(d, r["path"]) for d in r["assets"]]}
        self.records = recs
        self._rebuild()
        return True

    # --- consultas ------------------------------------------------------
    def assets_in(self, folder, recursive=True):
        if folder is None:
            out = list(self.assets)
            out.sort(key=lambda a: a.name.lower())
            return out
        key = os.path.normcase(os.path.normpath(folder))
        if not recursive:
            return list(self.by_folder.get(key, []))
        prefix = key.rstrip("\\/") + os.sep
        out = []
        for k, lst in self.by_folder.items():
            if k == key or k.startswith(prefix):
                out.extend(lst)
        out.sort(key=lambda a: a.name.lower())
        return out

    def search(self, text, folder=None, recursive=True):
        words = [w for w in text.lower().split() if w]
        pool = self.assets_in(folder, recursive)
        if not words:
            return pool
        return [a for a in pool if a.matches(words)]


def hidden_folders(folders, roots, names=(), paths=()):
    """Carpetas (normcase) que no se enseñan: las que se llaman como alguno de `names`
    (admite comodines, p. ej. "z-*"), las de `paths` y todo lo que cuelga de ellas.
    Las carpetas raíz de la biblioteca no se ocultan nunca."""
    import fnmatch
    names = [n.strip().lower() for n in names if n and n.strip()]
    paths = set(os.path.normcase(os.path.normpath(p)) for p in paths if p)
    keep = set(os.path.normcase(os.path.normpath(r)) for r in roots)
    hidden = set()
    if not names and not paths:
        return hidden
    for folder in sorted(folders, key=lambda p: os.path.normcase(p)):       # los padres van antes
        key = os.path.normcase(os.path.normpath(folder))
        if key in keep:
            continue
        base = os.path.basename(key).lower()
        if os.path.dirname(key) in hidden or key in paths or any(fnmatch.fnmatchcase(base, n) for n in names):
            hidden.add(key)
    return hidden


def cache_path_for(cache_dir, roots):
    import hashlib
    key = "|".join(sorted(os.path.normcase(os.path.normpath(r)) for r in roots if r))
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, hashlib.md5(key.encode("utf-8")).hexdigest() + ".json")
