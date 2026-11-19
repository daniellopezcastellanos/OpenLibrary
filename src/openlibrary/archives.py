"""Abrir comprimidos (zip, rar, 7z...) con lo que haya instalado en el equipo.

Python puro, sin Qt. Se usa, por este orden: 7-Zip o NanaZip (`7z`), WinRAR (`UnRAR`), el
`zipfile` de Python para los .zip sencillos y el `tar` de Windows 10/11 (lee rar y 7z sin
contraseña). No se incluye ningún descompresor con la app.
"""
import os
import re
import shutil
import subprocess
import zipfile

EXTS = (".zip", ".rar", ".7z", ".001", ".tar", ".gz", ".tgz", ".bz2", ".xz")
FILTER = "Comprimidos (*.zip *.rar *.7z *.001 *.r00 *.z01 *.tar *.gz *.tgz *.bz2 *.xz);;Todos los archivos (*)"
_NO_PASSWORD = "-sin-clave-"        # 7z pregunta por teclado si no se le pasa ninguna


class ArchiveError(Exception):
    """No se pudo abrir el comprimido; el texto es para enseñarlo tal cual."""


class NeedPassword(ArchiveError):
    """Tiene contraseña. `wrong` = se probó una y no era."""
    def __init__(self, wrong=False):
        ArchiveError.__init__(self, "Contraseña incorrecta." if wrong else "El archivo tiene contraseña.")
        self.wrong = wrong


class NoTool(ArchiveError):
    """Hace falta 7-Zip (o WinRAR) para este archivo."""


# --- partes -----------------------------------------------------------------------------
_PART_RAR = re.compile(r"^(?P<base>.+)\.part(?P<n>\d+)\.rar$", re.I)
_NUMBERED = re.compile(r"^(?P<base>.+\.(?:7z|zip|rar|tar))\.(?P<n>\d{3,})$", re.I)
_OLD_RAR = re.compile(r"^(?P<base>.+)\.(?:rar|r(?P<n>\d\d))$", re.I)
_OLD_ZIP = re.compile(r"^(?P<base>.+)\.(?:zip|z(?P<n>\d\d))$", re.I)


def volumes(path, names=None):
    """Para un comprimido partido en trozos: (el que hay que abrir, todas las partes, las que faltan).

    Da igual qué parte se elija. `names`: lo que hay en la carpeta (para las pruebas).
    Un archivo de una sola pieza devuelve (path, [path], []).
    """
    folder, name = os.path.split(path)
    if names is None:
        try:
            names = os.listdir(folder or ".")
        except OSError:
            names = [name]
    by_low = {n.lower(): n for n in names}
    full = lambda n: os.path.join(folder, n)

    def numbered(regex, base, first_n, make):
        found = {}
        for n in names:
            m = regex.match(n)
            if m and m.group("base").lower() == base.lower() and m.group("n") is not None:
                found[int(m.group("n"))] = n
        last = max(found) if found else first_n - 1
        missing = [make(i) for i in range(first_n, last + 1) if i not in found]
        return [found[i] for i in sorted(found)], missing

    m = _PART_RAR.match(name)
    if m:
        width = len(m.group("n"))
        parts, missing = numbered(_PART_RAR, m.group("base"), 1,
                                  lambda i: "%s.part%s.rar" % (m.group("base"), str(i).zfill(width)))
        first = parts[0] if not missing or missing[0] != "%s.part%s.rar" % (m.group("base"), "1".zfill(width)) \
            else missing[0]
        return full(first), [full(p) for p in parts], missing
    m = _NUMBERED.match(name)
    if m:
        width = len(m.group("n"))
        parts, missing = numbered(_NUMBERED, m.group("base"), 1,
                                  lambda i: "%s.%s" % (m.group("base"), str(i).zfill(width)))
        first = "%s.%s" % (m.group("base"), "1".zfill(width))
        return full(by_low.get(first.lower(), first)), [full(p) for p in parts], missing
    for regex, main_ext, first_n in ((_OLD_RAR, ".rar", 0), (_OLD_ZIP, ".zip", 1)):
        m = regex.match(name)
        if not m:
            continue
        base = m.group("base")
        letter = main_ext[1]
        parts, missing = numbered(regex, base, first_n, lambda i: "%s.%s%02d" % (base, letter, i))
        if not parts:
            continue                    # un .rar o .zip normal
        main = by_low.get((base + main_ext).lower())
        if main is None:
            missing.insert(0, base + main_ext)
        # rar antiguo: se abre el .rar y siguen .r00, .r01...; zip partido: .z01, .z02... y se abre el .zip
        ordered = ([main] if main else []) + parts if main_ext == ".rar" else parts + ([main] if main else [])
        return full(main or base + main_ext), [full(p) for p in ordered], missing
    return path, [path], []


def display_name(path):
    """Nombre del comprimido sin extensión ni «.part1» (sirve de nombre propuesto)."""
    name = os.path.basename(path)
    for regex in (_PART_RAR, _NUMBERED):
        m = regex.match(name)
        if m:
            name = m.group("base") + (".rar" if regex is _PART_RAR else "")
            break
    stem, ext = os.path.splitext(name)
    if stem.lower().endswith(".tar"):
        stem = stem[:-4]
    return stem if ext else name


# --- herramientas -----------------------------------------------------------------------
def _program_dirs():
    out = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        d = os.environ.get(var)
        if d and d not in out:
            out.append(d)
    return out


def find_tool():
    """("7z" | "unrar" | "tar", ruta) de lo mejor que haya, o None."""
    for exe in ("7z", "7zz", "7za", "NanaZipC"):
        p = shutil.which(exe)
        if p:
            return "7z", p
    for d in _program_dirs():
        for rel in (r"7-Zip\7z.exe", r"7-Zip-Zstandard\7z.exe", r"NanaZip\NanaZipC.exe", r"PeaZip\res\bin\7z\7z.exe"):
            p = os.path.join(d, rel)
            if os.path.isfile(p):
                return "7z", p
    p = shutil.which("unrar")
    if p:
        return "unrar", p
    for d in _program_dirs():
        p = os.path.join(d, r"WinRAR\UnRAR.exe")
        if os.path.isfile(p):
            return "unrar", p
    p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
    if os.path.isfile(p):
        return "tar", p
    return None


def _run(args, holder):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=flags)
    if holder is not None:
        holder.append(proc)
    out = proc.communicate()[0] or b""
    for enc in ("utf-8", "mbcs", "latin-1"):
        try:
            return proc.returncode, out.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return proc.returncode, ""


def _last_lines(text, n=4):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    errs = [l for l in lines if "error" in l.lower() or "cannot" in l.lower() or "can not" in l.lower()]
    return "\n".join((errs or lines)[-n:])


def _is_password_error(text):
    low = text.lower()
    return "wrong password" in low or "encrypted" in low or "password is incorrect" in low or "passphrase" in low


def _extract_zip(path, dest, password):
    try:
        with zipfile.ZipFile(path) as z:
            if any(i.flag_bits & 1 for i in z.infolist()) and not password:
                raise NeedPassword()
            try:
                z.extractall(dest, pwd=password.encode("utf-8") if password else None)
            except RuntimeError as exc:
                if "password" in str(exc).lower():
                    raise NeedPassword(wrong=True)
                raise ArchiveError(str(exc))
            except NotImplementedError:
                raise NoTool("Este .zip usa un cifrado o una compresión que solo abre 7-Zip. Instálalo "
                             "(7-zip.org) y vuelve a probar.")
    except zipfile.BadZipFile as exc:
        raise ArchiveError("El .zip está dañado o incompleto (%s)." % exc)
    except OSError as exc:
        raise ArchiveError(str(exc))


def extract(path, dest, password=None, tool=None, holder=None):
    """Saca todo el comprimido en `dest` (carpeta nueva o vacía).

    Lanza NeedPassword, NoTool o ArchiveError. `holder`: lista donde se deja el proceso en
    marcha, por si hay que matarlo para cancelar.
    """
    os.makedirs(dest, exist_ok=True)
    tool = tool or find_tool()
    kind, exe = tool if tool else (None, None)
    low = path.lower()
    if kind == "7z":
        code, out = _run([exe, "x", "-y", "-bd", "-sccUTF-8", "-o" + dest, "-p" + (password or _NO_PASSWORD), path],
                         holder)
        if code in (0, 1):
            return
        if _is_password_error(out):
            raise NeedPassword(wrong=bool(password))
        if "missing volume" in out.lower() or "unexpected end" in out.lower():
            raise ArchiveError("El archivo está incompleto: falta alguna parte o la descarga se cortó.")
        raise ArchiveError(_last_lines(out) or "7-Zip no pudo abrir el archivo.")
    if low.endswith(".zip"):
        return _extract_zip(path, dest, password)
    if kind == "unrar" and (low.endswith(".rar") or re.search(r"\.r\d\d$", low)):
        code, out = _run([exe, "x", "-y", "-o+", "-p" + (password or "-"), path, dest + os.sep], holder)
        if code == 0:
            return
        if code == 11 or _is_password_error(out) or "password" in out.lower():
            raise NeedPassword(wrong=bool(password))
        raise ArchiveError(_last_lines(out) or "UnRAR no pudo abrir el archivo.")
    if kind in ("tar", "unrar"):
        tar = exe if kind == "tar" else os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        if os.path.isfile(tar):
            code, out = _run([tar, "-xf", path, "-C", dest], holder)
            if code == 0:
                return
            if _is_password_error(out):
                raise NoTool("El archivo tiene contraseña y Windows solo no sabe abrirlo. Instala 7-Zip "
                             "(7-zip.org) y vuelve a probar.")
            raise NoTool("Windows no pudo abrir este archivo (%s).\nInstala 7-Zip (7-zip.org) y vuelve a probar."
                         % (_last_lines(out, 2) or "formato no admitido"))
    raise NoTool("Para abrir este tipo de archivo hace falta 7-Zip (7-zip.org) o WinRAR instalados.")
