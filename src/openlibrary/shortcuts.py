"""Accesos directos de Windows (menú Inicio y escritorio) con el icono de OpenLibrary.

Windows no deja que un programa se ancle solo a la barra de tareas: eso lo hace
la persona (clic derecho en el icono de la barra > Anclar a la barra de tareas).
"""
import glob
import hashlib
import os
import shutil
import subprocess
import sys

from . import app_icon_file
from .bridge_install import app_command

LNK_NAME = "OpenLibrary.lnk"

_PS = r"""
$ErrorActionPreference = 'Stop'
$folder = $env:OL_DIR
if (-not $folder) { $folder = [Environment]::GetFolderPath($env:OL_FOLDER) }
$path = Join-Path $folder $env:OL_NAME
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$s.TargetPath = $env:OL_TARGET
$s.Arguments = $env:OL_ARGS
$s.WorkingDirectory = $env:OL_WORKDIR
$s.IconLocation = $env:OL_ICON
$s.Description = 'OpenLibrary - biblioteca de modelos 3D para 3ds Max'
$s.Save()
Write-Output $path
"""

FOLDERS = {"start": "Programs", "desktop": "Desktop"}


def _quote(arg):
    return '"%s"' % arg if " " in arg else arg


def stamped_icon():
    """Copia del .ico con su huella en el nombre (en %LOCALAPPDATA%\\OpenLibrary\\icons).

    Windows guarda en caché el icono de cada acceso directo por la ruta del archivo: si el icono cambia
    pero la ruta no (el mismo .exe), la barra de tareas sigue enseñando el viejo. Con un nombre nuevo
    cada vez que cambia el icono, Windows tiene que leerlo de nuevo."""
    from .config import app_data_dir
    src = app_icon_file()
    try:
        with open(src, "rb") as fh:
            tag = hashlib.sha1(fh.read()).hexdigest()[:10]
    except OSError:
        return None
    folder = os.path.join(app_data_dir(), "icons")
    dst = os.path.join(folder, "openlibrary-%s.ico" % tag)
    try:
        if not os.path.isfile(dst):
            os.makedirs(folder, exist_ok=True)
            shutil.copyfile(src, dst)
            for old in glob.glob(os.path.join(folder, "openlibrary-*.ico")):
                if os.path.normcase(old) != os.path.normcase(dst):
                    try:
                        os.remove(old)
                    except OSError:
                        pass
    except OSError:
        return None
    return dst


def _icon_location(cmd):
    ico = stamped_icon()
    if ico:
        return "%s,0" % ico
    if getattr(sys, "frozen", False):
        return "%s,0" % cmd[0]          # el .exe lleva el icono dentro
    return "%s,0" % app_icon_file()


def pinned_folder():
    """Donde guarda Windows los accesos anclados a la barra de tareas."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned", "TaskBar")


def folder_path(where):
    """Ruta de la carpeta (menú Inicio / escritorio) sin llamar a PowerShell."""
    if where == "start":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)   # CSIDL_DESKTOPDIRECTORY
        if buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def exists(where):
    return os.path.isfile(os.path.join(folder_path(where), LNK_NAME))


def create(where, folder=None):
    """Crea (o actualiza) el acceso directo. Devuelve la ruta del .lnk.

    folder: carpeta concreta en vez de la del menú Inicio / escritorio (pruebas)."""
    cmd = app_command()
    env = dict(os.environ)
    env.update({
        "OL_DIR": folder or "",
        "OL_FOLDER": FOLDERS[where],
        "OL_NAME": LNK_NAME,
        "OL_TARGET": cmd[0],
        "OL_ARGS": " ".join(_quote(a) for a in cmd[1:]),
        "OL_WORKDIR": os.path.dirname(cmd[-1]),
        "OL_ICON": _icon_location(cmd),
    })
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS],
        env=env, capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout or "PowerShell falló").strip())
    return out.stdout.strip()


def remove(where):
    p = os.path.join(folder_path(where), LNK_NAME)
    if os.path.isfile(p):
        os.remove(p)


def refresh_icons(settings):
    """Si el icono de la app ha cambiado desde la última vez: rehace los accesos directos que haya (también
    el anclado a la barra de tareas) apuntando a la copia nueva del icono y le pide a Windows que vuelva a
    leer los iconos."""
    ico = stamped_icon()
    if not ico:
        return False
    stamp = "v2|" + os.path.basename(ico)
    pinned = os.path.join(pinned_folder(), LNK_NAME)
    if settings.data.get("icon_stamp") == stamp:
        return False
    for where in FOLDERS:
        if exists(where):
            try:
                create(where)
            except Exception:
                pass
    if os.path.isfile(pinned):
        try:
            create("start", folder=pinned_folder())
        except Exception:
            pass
    notify_icons_changed()
    settings.data["icon_stamp"] = stamp
    settings.save()
    return True


def notify_icons_changed():
    """Que el Explorador y la barra de tareas vuelvan a leer los iconos."""
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)     # SHCNE_ASSOCCHANGED
    except Exception:
        pass
    try:
        subprocess.Popen(["ie4uinit.exe", "-show"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass
