"""Datos de cada .max para la ficha: polígonos, vértices, objetos, desplazamiento y animación.

Se leen con un 3ds Max en segundo plano (3dsmaxbatch con `olb_batchStats`, o de paso al hacer previews en
lote), nunca en el Max abierto. Python puro: prepara el trabajo, lee el resultado y lo guarda en una caché
local (`model_stats.json`) que se invalida si cambia el archivo.
"""
import json
import os

from .batchpreview import _ms
from .bridge_install import bridge_source

FIELDS = ("polys", "verts", "objects", "disp", "anim", "start", "end")


def stamp(path):
    try:
        st = os.stat(path)
        return "%d|%d" % (int(st.st_mtime), st.st_size)
    except OSError:
        return None


def parse_stats(parts):
    """Campos que escribe olb_sceneStats -> dict (o None si no se entiende)."""
    if len(parts) < len(FIELDS):
        return None
    try:
        return {"polys": int(float(parts[0])), "verts": int(float(parts[1])), "objects": int(float(parts[2])),
                "disp": parts[3] == "1", "anim": parts[4] == "1",
                "start": int(float(parts[5])), "end": int(float(parts[6]))}
    except ValueError:
        return None


class StatsCache(object):
    def __init__(self, path):
        self.path = path
        self.data = {}
        self.dirty = False
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                self.data = d
        except (OSError, ValueError):
            pass

    @staticmethod
    def _key(f):
        return os.path.normcase(os.path.normpath(f))

    def get(self, f):
        e = self.data.get(self._key(f))
        if not e or e.get("stamp") != stamp(f):
            return None
        return e

    def put(self, f, stats):
        e = dict(stats)
        e["stamp"] = stamp(f)
        self.data[self._key(f)] = e
        self.dirty = True

    def save(self):
        if not self.dirty:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            pass


def prepare(workdir, files):
    """Script y registro para leer los datos de files con 3dsmaxbatch."""
    os.makedirs(workdir, exist_ok=True)
    jobs_file = os.path.join(workdir, "stats_jobs.txt")
    log_file = os.path.join(workdir, "stats_log.txt")
    script = os.path.join(workdir, "batch_stats.ms")
    with open(jobs_file, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        for f in files:
            fh.write(f + "\n")
    open(log_file, "w").close()
    core = os.path.join(bridge_source(), "openlibrary_core.ms")
    with open(script, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write('fileIn "%s"\n' % _ms(core))
        fh.write('olb_batchStats "%s" "%s"\n' % (_ms(jobs_file), _ms(log_file)))
    return script, log_file


def read_log(log_file, files):
    """{archivo: stats} de los que ya están en el registro ("ok<TAB>n<TAB>campos…", n desde 1)."""
    out = {}
    try:
        with open(log_file, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                parts = line.lstrip("﻿").rstrip("\r\n").split("\t")
                if len(parts) < 2 or parts[0] != "ok":
                    continue
                try:
                    i = int(parts[1]) - 1
                except ValueError:
                    continue
                st = parse_stats(parts[2:])
                if st is not None and 0 <= i < len(files):
                    out[files[i]] = st
    except OSError:
        pass
    return out


def summary(st):
    """Texto corto para la ficha."""
    return "%s caras · %s vértices · %d objeto%s" % (
        _thousands(st["polys"]), _thousands(st["verts"]), st["objects"], "" if st["objects"] == 1 else "s")


def _thousands(n):
    return "{:,}".format(int(n)).replace(",", " ")
