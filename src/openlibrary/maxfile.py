"""Lectura de .max sin abrir 3ds Max.

Un .max es un "Compound File Binary" (OLE). Dentro hay un stream
`ClassDirectory3` con los nombres de todas las clases usadas (VRayMtl,
CoronaPhysicalMtl, ...) y otro `DllDirectory` con los plugins. Leyendo solo
esos streams (pocos KB) sabemos con qué motor se preparó el modelo, incluso
en un NAS y con archivos de cientos de MB.

Python puro, sin dependencias: se puede probar fuera de Max.
"""
import os
import struct
import threading
import json

SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
MAXREGSECT = 0xFFFFFFFA

ENGINES = ("corona", "vray", "fstorm", "other")


class CFBError(Exception):
    pass


class CompoundFile(object):
    """Lector mínimo y perezoso de CFB: solo lee los sectores que necesita."""

    def __init__(self, path):
        self.fh = open(path, "rb")
        try:
            self._read_header()
        except Exception:
            self.fh.close()
            raise

    def close(self):
        self.fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------
    def _read_header(self):
        hdr = self.fh.read(512)
        if len(hdr) < 512 or hdr[:8] != SIGNATURE:
            raise CFBError("No es un archivo compuesto (OLE)")
        self.sector_size = 1 << struct.unpack_from("<H", hdr, 0x1E)[0]
        self.mini_size = 1 << struct.unpack_from("<H", hdr, 0x20)[0]
        (self.n_fat, self.first_dir) = struct.unpack_from("<II", hdr, 0x2C)
        self.mini_cutoff = struct.unpack_from("<I", hdr, 0x38)[0]
        (self.first_minifat, self.n_minifat,
         self.first_difat, self.n_difat) = struct.unpack_from("<IIII", hdr, 0x3C)
        if self.sector_size not in (512, 4096):
            raise CFBError("Tamaño de sector no válido")
        self.per_sector = self.sector_size // 4

        # Lista de sectores FAT (DIFAT): 109 en cabecera + cadena DIFAT.
        fat_sectors = list(struct.unpack_from("<109I", hdr, 0x4C))
        sect = self.first_difat
        guard = 0
        while sect not in (ENDOFCHAIN, FREESECT) and sect <= MAXREGSECT:
            data = self._sector(sect)
            vals = struct.unpack("<%dI" % self.per_sector, data)
            fat_sectors.extend(vals[:-1])
            sect = vals[-1]
            guard += 1
            if guard > 100000:
                raise CFBError("Cadena DIFAT corrupta")
        self.fat_sectors = [s for s in fat_sectors[: self.n_fat] if s <= MAXREGSECT]
        self._fat_cache = {}
        self._minifat = None
        self._entries = None

    def _sector(self, n):
        self.fh.seek((n + 1) * self.sector_size)
        data = self.fh.read(self.sector_size)
        if len(data) < self.sector_size:
            data = data + b"\0" * (self.sector_size - len(data))
        return data

    def _fat(self, n):
        idx, off = divmod(n, self.per_sector)
        table = self._fat_cache.get(idx)
        if table is None:
            if idx >= len(self.fat_sectors):
                raise CFBError("Índice FAT fuera de rango")
            table = struct.unpack("<%dI" % self.per_sector, self._sector(self.fat_sectors[idx]))
            self._fat_cache[idx] = table
        return table[off]

    def _chain(self, start, limit_bytes=None):
        out = []
        sect = start
        total = 0
        guard = 0
        while sect <= MAXREGSECT:
            out.append(self._sector(sect))
            total += self.sector_size
            if limit_bytes is not None and total >= limit_bytes:
                break
            sect = self._fat(sect)
            guard += 1
            if guard > 10000000:
                raise CFBError("Cadena FAT corrupta")
        return b"".join(out)

    # ------------------------------------------------------------------
    def entries(self):
        if self._entries is None:
            raw = self._chain(self.first_dir)
            ents = []
            for i in range(len(raw) // 128):
                e = raw[i * 128:(i + 1) * 128]
                name_len = struct.unpack_from("<H", e, 64)[0]
                etype = e[66]
                if etype == 0 or name_len < 2:
                    ents.append(None)
                    continue
                name = e[: name_len - 2].decode("utf-16-le", "replace")
                start = struct.unpack_from("<I", e, 116)[0]
                size = struct.unpack_from("<Q", e, 120)[0]
                if self.sector_size == 512:
                    size &= 0xFFFFFFFF
                ents.append({"name": name, "type": etype, "start": start, "size": size})
            self._entries = ents
        return self._entries

    def _mini_stream(self, start, size):
        root = self.entries()[0]
        if self._minifat is None:
            raw = self._chain(self.first_minifat) if self.n_minifat else b""
            self._minifat = struct.unpack("<%dI" % (len(raw) // 4), raw)
        out = []
        sect = start
        got = 0
        per_big = self.sector_size // self.mini_size
        root_cache = {}
        while sect <= MAXREGSECT and got < size:
            # Posición del mini-sector dentro del mini stream (cadena del root)
            big_idx, off = divmod(sect, per_big)
            if big_idx not in root_cache:
                # recorre la cadena del root hasta big_idx
                s = root["start"]
                for _ in range(big_idx):
                    s = self._fat(s)
                root_cache[big_idx] = self._sector(s)
            blk = root_cache[big_idx][off * self.mini_size:(off + 1) * self.mini_size]
            out.append(blk)
            got += self.mini_size
            sect = self._minifat[sect] if sect < len(self._minifat) else ENDOFCHAIN
        return b"".join(out)[:size]

    def read_stream(self, name, max_bytes=8 * 1024 * 1024):
        for e in self.entries():
            if e and e["type"] == 2 and e["name"] == name:
                size = min(e["size"], max_bytes)
                if e["size"] < self.mini_cutoff:
                    return self._mini_stream(e["start"], size)
                return self._chain(e["start"], limit_bytes=size)[:size]
        return None


# ----------------------------------------------------------------------
# Detección de motor
# ----------------------------------------------------------------------
_ENGINE_KEYS = (            # en orden de preferencia si empatan
    ("corona", ("corona",)),
    ("vray", ("vray", "v-ray", "v_ray")),
    ("fstorm", ("fstorm",)),
)


def _score(text):
    """Veces que aparece cada motor en el texto: {"corona": n, "vray": n, "fstorm": n}."""
    text = text.lower()
    return {eng: sum(text.count(k) for k in keys) for eng, keys in _ENGINE_KEYS}


def _winner(score):
    best = max(score.values())
    if not best:
        return None
    return next(eng for eng, _keys in _ENGINE_KEYS if score[eng] == best)


def detect_engine(path):
    """Devuelve 'corona', 'vray', 'fstorm' u 'other' leyendo las clases del .max."""
    try:
        with CompoundFile(path) as cf:
            classes = cf.read_stream("ClassDirectory3") or cf.read_stream("ClassDirectory2") or b""
            dlls = cf.read_stream("DllDirectory") or b""
    except (OSError, CFBError, struct.error, IndexError):
        return "other"

    text = classes.decode("utf-16-le", "ignore")
    # Separamos clases de render (motor activo) del resto (materiales, luces,
    # proxies...). Pesa más lo que el modelo *usa* que el render activo.
    usage = dict.fromkeys((eng for eng, _keys in _ENGINE_KEYS), 0)
    for token in _tokens(text):
        tl = token.lower()
        if "render" in tl and "element" not in tl:
            continue
        for eng, n in _score(tl).items():
            usage[eng] += n
    return _winner(usage) or _winner(_score(text + dlls.decode("utf-16-le", "ignore"))) or "other"


def _tokens(text):
    cur = []
    for ch in text:
        if ch.isalnum() or ch in "_-":
            cur.append(ch)
        else:
            if len(cur) > 2:
                yield "".join(cur)
            cur = []
    if len(cur) > 2:
        yield "".join(cur)


class EngineCache(object):
    """Caché local (path, mtime, size) -> motor, para no releer el NAS."""
    VERSION_KEY = "*version"
    VERSION = 2          # 2: se reconoce FStorm

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.dirty = False
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}
        if self.data.get(self.VERSION_KEY) != self.VERSION:
            # la detección sabe más motores: lo que salió "otro motor" se vuelve a mirar una vez
            self.data = {k: v for k, v in self.data.items() if isinstance(v, list) and v[2] != "other"}
            self.data[self.VERSION_KEY] = self.VERSION
            self.dirty = True

    def get(self, file_path, stat=None):
        try:
            st = stat or os.stat(file_path)
        except OSError:
            return None
        key = os.path.normcase(file_path)
        with self.lock:
            rec = self.data.get(key)
        if isinstance(rec, list) and rec[0] == int(st.st_mtime) and rec[1] == st.st_size:
            return rec[2]
        return None

    def detect(self, file_path):
        cached = self.get(file_path)
        if cached:
            return cached
        try:
            st = os.stat(file_path)
        except OSError:
            return "other"
        engine = detect_engine(file_path)
        with self.lock:
            self.data[os.path.normcase(file_path)] = [int(st.st_mtime), st.st_size, engine]
            self.dirty = True
        return engine

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            data = dict(self.data)
            self.dirty = False
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass


# ----------------------------------------------------------------------
# Archivos externos (texturas, IES, proxies...) guardados en el .max
# ----------------------------------------------------------------------
def _read_str(data, i):
    n = struct.unpack_from("<I", data, i)[0]
    i += 4
    if n > 32768 or i + 2 * n > len(data):
        raise CFBError("Cadena no válida")
    return data[i:i + 2 * n].decode("utf-16-le", "replace"), i + 2 * n + 2


def read_asset_paths(path):
    """[(tipo, ruta guardada, ruta resuelta al guardar)] sin abrir Max.

    Stream FileAssetMetaData3: por asset, GUID (16 bytes) + tres cadenas
    UTF-16 con longitud u32 delante y terminador nulo.
    """
    try:
        with CompoundFile(path) as cf:
            data = cf.read_stream("FileAssetMetaData3", max_bytes=16 * 1024 * 1024) or b""
    except (OSError, CFBError, struct.error, IndexError):
        return []
    out = []
    i = 0
    try:
        while i + 20 <= len(data):
            i += 16
            typ, i = _read_str(data, i)
            stored, i = _read_str(data, i)
            resolved, i = _read_str(data, i)
            if stored:
                out.append((typ, stored, resolved))
    except (struct.error, CFBError):
        pass
    return out


def _filenames_under(folder, depth=3, limit=20000):
    names = set()
    stack = [(folder, 0)]
    while stack and len(names) < limit:
        d, lvl = stack.pop()
        try:
            for e in os.scandir(d):
                try:
                    if e.is_dir():
                        if lvl < depth and not e.name.startswith((".", "_proxies")):
                            stack.append((e.path, lvl + 1))
                    else:
                        names.add(e.name.lower())
                except OSError:
                    pass
        except OSError:
            pass
    return names


def external_files(max_path, folder_names=None):
    """Archivos externos de un .max, uno por ruta guardada:
    [{"type", "stored", "resolved", "state"}], state = "ok" | "missing" | "relinkable"
    (relinkable: no está en su ruta pero sí en la carpeta del asset, se re-enlaza solo).
    folder_names: caché opcional {carpeta: set(nombres)} compartida entre assets.
    """
    base = os.path.dirname(max_path)
    out = []
    names = None
    seen = set()
    for typ, stored, resolved in read_asset_paths(max_path):
        if not os.path.splitext(stored)[1]:
            continue
        key = stored.lower()
        if key in seen:
            continue
        seen.add(key)
        row = {"type": typ, "stored": stored, "resolved": resolved, "state": "ok"}
        out.append(row)
        if os.path.isabs(stored) and os.path.isfile(stored):
            continue
        if not os.path.isabs(stored) and os.path.isfile(os.path.join(base, stored)):
            continue
        if resolved and os.path.isfile(resolved):
            continue
        if names is None:
            if folder_names is not None and base in folder_names:
                names = folder_names[base]
            else:
                names = _filenames_under(base)
                if folder_names is not None:
                    folder_names[base] = names
        fname = stored.replace("/", "\\").split("\\")[-1].lower()
        row["state"] = "relinkable" if fname in names else "missing"
    return out


def check_external_files(max_path, folder_names=None):
    """Comprueba los archivos externos de un .max.

    -> {"total", "missing": [rutas no encontradas], "relinkable": [rutas que
        están en la carpeta del asset y se pueden re-enlazar solas]}
    """
    rows = external_files(max_path, folder_names)
    return {"total": len(rows), "missing": [r["stored"] for r in rows if r["state"] == "missing"],
            "relinkable": [r["stored"] for r in rows if r["state"] == "relinkable"]}


class CheckCache(object):
    """Resultado de check_external_files por .max, válido unas horas."""
    MAX_AGE = 12 * 3600

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.dirty = False
        self.folder_names = {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def get(self, file_path):
        import time
        key = os.path.normcase(file_path)
        with self.lock:
            rec = self.data.get(key)
        if not rec:
            return None
        try:
            st = os.stat(file_path)
        except OSError:
            return None
        if rec["m"] != int(st.st_mtime) or rec["s"] != st.st_size or time.time() - rec["t"] > self.MAX_AGE:
            return None
        return rec["r"]

    def peek(self, file_path):
        """Último resultado conocido aunque esté caducado (sin tocar disco)."""
        with self.lock:
            rec = self.data.get(os.path.normcase(file_path))
        return rec["r"] if rec else None

    def check(self, file_path):
        import time
        res = check_external_files(file_path, self.folder_names)
        try:
            st = os.stat(file_path)
        except OSError:
            return res
        with self.lock:
            self.data[os.path.normcase(file_path)] = {"m": int(st.st_mtime), "s": st.st_size,
                                                      "t": time.time(), "r": res}
            self.dirty = True
        return res

    def forget(self, file_path):
        with self.lock:
            self.data.pop(os.path.normcase(file_path), None)
        self.folder_names.pop(os.path.dirname(file_path), None)

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            data = dict(self.data)
            self.dirty = False
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass
