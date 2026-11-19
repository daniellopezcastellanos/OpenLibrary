"""Previews en lote con un 3ds Max en segundo plano (3dsmaxbatch), sin tocar el Max abierto.

Python puro: prepara los archivos de trabajo y la línea de comandos. La app lanza el
proceso y va leyendo el registro para enseñar el progreso.
"""
import glob
import os
import re

from .bridge_install import bridge_source


def _installs():
    """[(año, carpeta de 3ds Max)] de lo instalado, del más nuevo al más viejo."""
    found = set()
    for key, value in os.environ.items():
        m = re.match(r"ADSK_3DSMAX_x64_(\d{4})$", key, re.I)
        if m:
            found.add((int(m.group(1)), os.path.normpath(value)))
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        if base:
            for exe in glob.glob(os.path.join(base, "Autodesk", "3ds Max *", "3dsmax.exe")):
                m = re.search(r"3ds Max (\d{4})", exe)
                found.add((int(m.group(1)) if m else 0, os.path.dirname(exe)))
    return sorted(found, reverse=True)


def find_maxbatch():
    """Ruta de 3dsmaxbatch.exe del 3ds Max más nuevo instalado, o None."""
    for _year, folder in _installs():
        exe = os.path.join(folder, "3dsmaxbatch.exe")
        if os.path.isfile(exe):
            return exe
    return None


def find_max(year=None):
    """Ruta de 3dsmax.exe: el de ese año si está instalado; si no, el más nuevo. O None."""
    installs = [(y, os.path.join(folder, "3dsmax.exe")) for y, folder in _installs()]
    installs = [(y, exe) for y, exe in installs if os.path.isfile(exe)]
    for y, exe in installs:
        if year and y == year:
            return exe
    return installs[0][1] if installs else None


def kill_tree(proc):
    """Cierra un 3dsmaxbatch y el 3ds Max que lanza (matar solo el primero deja el Max vivo de fondo)."""
    try:
        pid = int(proc.processId())
    except Exception:
        pid = 0
    if pid:
        import subprocess
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    proc.kill()


def _ms(path):
    return path.replace("\\", "/").replace('"', "")


def prepare(workdir, jobs, prev):
    """jobs: [(archivo .max, preview de salida)]. Devuelve (script, registro)."""
    os.makedirs(workdir, exist_ok=True)
    jobs_file = os.path.join(workdir, "jobs.txt")
    log_file = os.path.join(workdir, "log.txt")
    script = os.path.join(workdir, "batch_preview.ms")
    with open(jobs_file, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        for max_path, out in jobs:
            fh.write("%s\t%s\n" % (max_path, out))
    open(log_file, "w").close()
    core = os.path.join(bridge_source(), "openlibrary_core.ms")
    with open(script, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write('fileIn "%s"\n' % _ms(core))
        fh.write('olb_batchPreviews "%s" "%s" %d %s %s %s\n' % (
            _ms(jobs_file), _ms(log_file), int(prev["size"]), float(prev["margin"]),
            float(prev["elevation"]), float(prev["azimuth"])))
    return script, log_file


def read_log(log_file):
    """(hechos, fallidos) según el registro."""
    ok = fail = 0
    try:
        with open(log_file, "r", errors="replace") as fh:
            for line in fh:
                if line.startswith("ok"):
                    ok += 1
                elif line.startswith("fail"):
                    fail += 1
    except OSError:
        pass
    return ok, fail
