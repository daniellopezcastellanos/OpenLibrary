"""Cambiar o quitar rutas de archivos externos DENTRO de un .max sin abrirlo.

Lo hace un 3ds Max en segundo plano (3dsmaxbatch) con `olb_editFilePaths`, que usa
getMAXFileAssetMetadata / setMAXFileAssetMetadata: el .max no se carga, solo se reescribe
su tabla de archivos externos. Python puro: aquí se preparan los archivos de trabajo.
"""
import os

from .batchpreview import _ms, find_maxbatch  # noqa: F401  (find_maxbatch se usa desde la interfaz)
from .bridge_install import bridge_source

REMOVE = "<quitar>"         # en vez de ruta nueva: la referencia se deja vacía


def is_disposable(typ, stored):
    """Archivos que casi nunca hacen falta y se pueden quitar de golpe cuando no aparecen:
    LUT de Corona (.cube), HDR de entorno (.hdr) y texturas «checker» de desplegar UV."""
    name = stored.replace("/", "\\").split("\\")[-1].lower()
    ext = os.path.splitext(name)[1]
    if ext in (".cube", ".hdr"):
        return True
    return "checker" in name and ((typ or "").lower().lstrip("#") == "bitmap" or ext in _IMG_EXTS)


_IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".tga", ".webp", ".gif", ".exr", ".psd")


def prepare(workdir, edits):
    """edits: [(archivo .max, ruta guardada, ruta nueva o None para quitarla)]. -> (script, registro)."""
    os.makedirs(workdir, exist_ok=True)
    jobs_file = os.path.join(workdir, "paths.txt")
    log_file = os.path.join(workdir, "paths_log.txt")
    script = os.path.join(workdir, "edit_paths.ms")
    with open(jobs_file, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        for max_path, old, new in edits:
            fh.write("%s\t%s\t%s\n" % (max_path, old, new if new else REMOVE))
    open(log_file, "w").close()
    core = os.path.join(bridge_source(), "openlibrary_core.ms")
    with open(script, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write('fileIn "%s"\n' % _ms(core))
        fh.write('olb_editFilePaths "%s" "%s"\n' % (_ms(jobs_file), _ms(log_file)))
    return script, log_file


def read_log(log_file):
    """{archivo .max (normcase): rutas cambiadas, o -1 si falló}."""
    out = {}
    try:
        with open(log_file, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) == 3 and parts[0] in ("ok", "fail"):
                    try:
                        n = int(parts[1])
                    except ValueError:
                        n = 0
                    out[os.path.normcase(parts[2])] = n if parts[0] == "ok" else -1
    except OSError:
        pass
    return out


def find_by_name(folder, names, limit=300000):
    """Busca en `folder` (con subcarpetas) archivos que se llamen como `names`. -> {nombre.lower(): ruta}."""
    wanted = set(n.lower() for n in names)
    found = {}
    seen = 0
    for d, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x.lower() != "$recycle.bin"]
        for f in files:
            seen += 1
            low = f.lower()
            if low in wanted and low not in found:
                found[low] = os.path.join(d, f)
        if len(found) == len(wanted) or seen > limit:
            break
    return found
