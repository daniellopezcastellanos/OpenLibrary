"""Operaciones dentro de 3ds Max (pymxs + openlibrary_core.ms).

Todo se ejecuta en el hilo principal de Max (lo garantiza server.py). Los
ajustes y las rutas de proxy llegan calculados desde la app; aquí no se lee
ninguna configuración.
"""
import contextlib
import ctypes
import os
import time

import pymxs
from pymxs import runtime as rt

HERE = os.path.dirname(os.path.abspath(__file__))
CORE_MS = os.path.join(HERE, "openlibrary_core.ms")
TEX_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".hdr", ".tga", ".bmp",
            ".psd", ".tx", ".webp", ".ies", ".cgeo", ".cproxy", ".vrmesh", ".abc"}


def load_core():
    rt.fileIn(CORE_MS)


@contextlib.contextmanager
def _undo(label):
    """Bloque de deshacer de Max. pymxs.undo se traga las excepciones de dentro: se guardan y se
    vuelven a lanzar al salir, para que la app reciba el error en vez de un resultado vacío."""
    caught = []
    with pymxs.undo(True, label):
        try:
            yield
        except Exception as e:      # noqa: BLE001
            caught.append(e)
    if caught:
        err = caught.pop()          # sin la lista, el error no queda en un ciclo con este marco
        try:
            raise err
        finally:
            del err


# ---------------------------------------------------------------------------
# Estado de la escena (lo consulta la app cada pocos segundos)
# ---------------------------------------------------------------------------
def max_version():
    try:
        v = rt.maxVersion()
        # 28000 -> 2026
        return 1998 + int(v[0]) // 1000
    except Exception:
        return 0


def watch_state(on):
    """Callbacks de Max que avisan al puente cuando cambia el motor, el archivo o la selección."""
    rt.olb_watchState(bool(on))


def scene_state():
    return {
        "engine": str(rt.olb_sceneEngine()),
        "file": str(rt.maxFileName),
        "folder": str(rt.maxFilePath),
        "selection": int(rt.selection.count),
    }


class _PT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]


def _user32():
    u = ctypes.windll.user32
    u.WindowFromPoint.restype = ctypes.c_void_p
    u.WindowFromPoint.argtypes = [_PT]
    u.GetAncestor.restype = ctypes.c_void_p
    u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    u.IsChild.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PT)]
    u.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
    u.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    return u


def _hwnd(v):
    try:
        return int(v) or None
    except Exception:
        return None


def look_at(sx=None, sy=None):
    """Qué hay de Max en ese punto de la pantalla (por defecto, el ratón):
    ("view", índice, x, y, ancho, alto) un visor con el píxel dentro de su ventana y el tamaño de esta (en
    píxeles de Windows), ("slate",) el editor Slate, o ("other",)."""
    u = _user32()
    pt = _PT()
    if sx is None:
        u.GetCursorPos(ctypes.byref(pt))
    else:
        pt.x, pt.y = int(sx), int(sy)
    hwnd = u.WindowFromPoint(pt)
    if not hwnd:
        return ("other",)
    # ¿un visor? (cada visor de Max tiene su ventana)
    try:
        n = int(rt.viewport.numViews)
    except Exception:
        n = 0
    for i in range(1, n + 1):
        try:
            vh = _hwnd(rt.viewport.getHWnd(index=i))
        except Exception:
            vh = _hwnd(rt.viewport.getHWnd()) if i == int(rt.viewport.activeViewport) else None
        if vh and (vh == hwnd or u.IsChild(vh, hwnd)):
            cp = _PT(pt.x, pt.y)
            u.ScreenToClient(vh, ctypes.byref(cp))
            rc = _RECT()
            u.GetClientRect(vh, ctypes.byref(rc))
            return ("view", i, cp.x, cp.y, rc.r - rc.l, rc.b - rc.t)
    # ¿el editor Slate? por el título de su ventana o porque no es la principal de Max y cae en su marco
    root = u.GetAncestor(hwnd, 2) or hwnd
    buf = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(root, buf, 256)
    if "slate" in buf.value.lower() or "material editor" in buf.value.lower():
        return ("slate",)
    # fuera de los visores y dentro del marco de Slate (también si está acoplado en la ventana de Max)
    try:
        if bool(rt.olb_mouseOverSlate()):
            return ("slate",)
    except Exception:
        pass
    return ("other",)


def _route(target):
    """Al soltar ("cursor"): sobre Slate, solo a Slate; sobre un visor, el objeto que hay en ese píxel
    (si no hay ninguno, la selección)."""
    if target != "cursor":
        return target
    where = look_at()
    if where[0] == "slate":
        return "slate"
    # sobre un visor: el objeto de ese píxel; en otro sitio de Max: ninguno (vale la selección)
    rt.olb_cursorHit = rt.olb_nodeAtView(*where[1:]) if where[0] == "view" else None
    rt.olb_cursorKnown = True
    return target


def focus_max():
    """Trae la ventana de Max al frente (la app nos da permiso antes)."""
    try:
        hwnd = int(rt.windows.getMAXHWND())
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Rutas perdidas
# ---------------------------------------------------------------------------
_map_cache = {}      # carpetas -> (hora, mapa): re-enlazar muchos .max seguidos no repite la búsqueda


def build_file_map(dirs, max_files=200000):
    """nombre.lower() -> ruta, buscando recursivamente en dirs."""
    key = tuple(os.path.normcase(d) for d in dirs if d)
    hit = _map_cache.get(key)
    if hit is not None and time.time() - hit[0] < 120:
        return hit[1]
    found = _walk_files(dirs, max_files)
    if len(_map_cache) > 40:
        _map_cache.clear()
    _map_cache[key] = (time.time(), found)
    return found


def _walk_files(dirs, max_files):
    found = {}
    count = 0
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, subdirs, files in os.walk(d):
            subdirs[:] = [s for s in subdirs if not s.startswith(".") and s.lower() != "$recycle.bin"]
            for f in files:
                if os.path.splitext(f)[1].lower() in TEX_EXTS:
                    found.setdefault(f.lower(), os.path.join(root, f))
                    count += 1
            if count > max_files:
                return found
    return found


def _missing(path, base_dir=None):
    if not path or os.path.isfile(path):
        return False
    if base_dir and not os.path.isabs(path) and os.path.isfile(os.path.join(base_dir, path)):
        return False
    return True


def relink_scene(search_dirs):
    """Re-enlaza los assets perdidos de la escena. -> [arreglados, siguen perdidos]."""
    files = [str(f) for f in rt.olb_sceneFiles()]
    missing = [f for f in files if os.path.splitext(f)[1] and _missing(f)]
    if not missing:
        return [0, 0]
    fmap = build_file_map(search_dirs)
    fixed = 0
    for f in missing:
        hit = fmap.get(os.path.basename(f).lower())
        if hit and rt.olb_setFileDir(f, os.path.dirname(hit)):
            fixed += 1
    return [fixed, len(missing) - fixed]


def relink_max_file(max_path, search_dirs):
    """Re-enlaza rutas DENTRO de un .max de la biblioteca sin abrirlo."""
    meta = rt.getMAXFileAssetMetadata(max_path)
    if meta is None:
        return [0, 0]
    base_dir = os.path.dirname(max_path)
    dirs = [base_dir] + list(search_dirs)
    fmap = None
    fixed = missing = 0
    for a in meta:
        p = str(a.filename)
        if not os.path.splitext(p)[1] or not _missing(p, base_dir):
            continue
        if fmap is None:
            fmap = build_file_map(dirs)
        hit = fmap.get(os.path.basename(p).lower())
        if hit:
            a.filename = hit
            fixed += 1
        else:
            missing += 1
    if fixed:
        rt.setMAXFileAssetMetadata(max_path, meta)
    return [fixed, missing]


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------
def merge(max_path, asset_name, imp, place=True, relink_dirs=None):
    focus_max()
    with _undo("OpenLibrary: Merge " + asset_name):
        nodes = rt.olb_merge(max_path, asset_name, bool(imp["group"]), imp["layer_mode"],
                             imp["object_dups"], imp["material_dups"],
                             bool(imp["import_lights"]), bool(imp["import_cameras"]))
        if relink_dirs and len(nodes):
            relink_scene(relink_dirs)
        if place and len(nodes):
            nodes = rt.olb_place(nodes, bool(imp["place_on_surface"]), bool(imp.get("place_multiple", True)))
    rt.redrawViews()
    return len(nodes)


def merge_as_proxy(max_path, asset_name, engine, imp, proxy_dir, place=True, relink_dirs=None):
    if engine not in ("corona", "vray"):
        raise RuntimeError("Merge as Proxy necesita Corona o V-Ray como motor de la escena.")
    focus_max()
    with _undo("OpenLibrary: Proxy " + asset_name):
        nodes = rt.olb_mergeProxy(max_path, asset_name, proxy_dir, imp["proxy_mode"], engine,
                                  imp["layer_mode"], imp["material_dups"], imp.get("proxy_display", "preview"))
        if relink_dirs and len(nodes):
            relink_scene(relink_dirs)
        if place and len(nodes):
            nodes = rt.olb_place(nodes, bool(imp["place_on_surface"]), bool(imp.get("place_multiple", True)))
    rt.redrawViews()
    return len(nodes)


# ---------------------------------------------------------------------------
# Preview / guardar / abrir
# ---------------------------------------------------------------------------
def make_preview(out_file, prev, from_view=False):
    if not from_view and int(rt.selection.count) == 0:
        raise RuntimeError("Selecciona en 3ds Max los objetos que salen en la preview.")
    return bool(rt.olb_makePreview(out_file, int(prev["size"]), prev["method"],
                                   float(prev["margin"]), float(prev["elevation"]),
                                   float(prev["azimuth"]), bool(from_view)))


# ---------------------------------------------------------------------------
# Materiales y texturas
# ---------------------------------------------------------------------------
def _mxs_array(items):
    arr = rt.Array()
    for it in items:
        rt.append(arr, it)
    return arr


def _engine(engine):
    return str(rt.olb_sceneEngine()) if engine in (None, "", "auto") else engine


def _xyz(size):
    """(ancho, largo[, alto]) en cm -> tres floats; sin alto, el alto es el largo."""
    s = [float(v) for v in (list(size) or [100.0])]
    while len(s) < 3:
        s.append(s[-1])
    return s[:3]


def _put(mats, target, mapping, size):
    """Asigna o lleva a Slate. La caja UVW solo se añade a objetos, nunca en Slate."""
    mode = {"uvw": "box", "realworld": "realworld"}.get(mapping, "") if target != "slate" else ""
    x, y, z = _xyz(size)
    where, n, name = str(rt.olb_putMaterials(_mxs_array(mats), target, mode, x, y, z)).split("|", 2)
    rt.redrawViews()
    return {"where": where, "count": int(n), "name": name}


def _tex_mapping(mapping):
    return mapping if mapping in ("triplanar", "realworld") else "uv"


def check_drop(target="cursor", names=()):
    """Antes de poner un material: adónde va (al soltar, mira ya qué hay bajo el ratón y lo deja apuntado
    para la orden siguiente) y cuáles de esos nombres ya hay en la escena / editor / Slate."""
    route = _route(target)
    return {"route": route, "existing": [n for n in names if rt.olb_findMaterial(n) is not None]}


def _pbr(name, maps, engine, mapping, size, displacement, existing):
    """El material pedido: el que ya hay en la escena con ese nombre (existing="use") o uno nuevo."""
    if existing == "use":
        m = rt.olb_findMaterial(name)
        if m is not None:
            return m
    spec = "|".join("%s=%s" % (k, v) for k, v in maps.items() if v)
    if not spec:
        raise RuntimeError("El material no tiene mapas.")
    x, y, _z = _xyz(size)
    return rt.olb_pbrMaterial(name, _engine(engine), spec, _tex_mapping(mapping), x, y, bool(displacement))


def apply_material(name, maps, engine="auto", mapping="uv", size=(100, 100), displacement=False,
                   target="selection", existing="new", routed=False):
    """Crea el material del motor pedido con sus mapas y lo reparte.
    maps: {canal: ruta}. mapping: "uv", "uvw" (caja de X·Y·Z cm), "realworld" (textura a su medida real
    con caja «Real-World Map Size») o "triplanar". size: (X, Y[, Z]) en cm.
    target: "selection", "cursor" (objeto bajo el ratón) o "slate".
    existing: "new" (otro material, «Nombre_01»…) o "use" (el que ya hay en la escena con ese nombre).
    routed: el destino ya lo miró check_drop (no se vuelve a mirar el ratón)."""
    if not any(maps.values()):
        raise RuntimeError("El material no tiene mapas.")
    if not routed:
        target = _route(target)
    focus_max()
    with _undo("OpenLibrary: material " + name):
        m = _pbr(name, maps, engine, mapping, size, displacement, existing)
        if target == "slate":
            n = int(rt.olb_slateShow(_mxs_array([m])))
            return {"where": "slate", "count": 1, "name": str(m.name), "added": n}
        return _put([m], target, mapping, size)


def apply_materials(items, engine="auto", displacement=False, existing="use"):
    """Varios materiales a Slate, ordenados. items: [{"name", "maps", "mapping", "size"}]. Los que ya están
    en la escena con ese nombre se buscan y se seleccionan (existing="use")."""
    focus_max()
    with _undo("OpenLibrary: %d materiales" % len(items)):
        mats = [_pbr(it["name"], it["maps"], engine, it.get("mapping", "uv"), it.get("size", (100, 100)),
                     displacement, existing) for it in items[:60] if any(it.get("maps", {}).values())]
        if not mats:
            raise RuntimeError("Los materiales no tienen mapas.")
        added = int(rt.olb_slateShow(_mxs_array(mats)))
    return {"where": "slate", "count": len(mats), "name": "%d materiales" % len(mats) if len(mats) > 1
            else str(mats[0].name), "added": added}


def apply_library(mat_file, target="selection"):
    """Materiales de una biblioteca .mat: a Slate van todos; a los objetos, el primero."""
    target = _route(target)
    mats = list(rt.olb_matLibMaterials(mat_file))
    if not mats:
        raise RuntimeError("No pude leer materiales de %s" % os.path.basename(mat_file))
    focus_max()
    with _undo("OpenLibrary: material " + os.path.basename(mat_file)):
        res = _put(mats[:24], target, "uv", (0, 0))
    res["library"] = len(mats)
    return res


def add_textures(files, roles=None, engine="auto", mapping="uv", size=(100, 100), target="slate"):
    """Texturas sueltas: como mapas en Slate, o como material rápido (la primera, de color)."""
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("No hay texturas.")
    roles = roles or ["color"] * len(files)
    eng = _engine(engine)
    target = _route(target)
    focus_max()
    if target != "slate":
        ch = "normal" if roles[0] == "normal" else "color"
        return apply_material(os.path.splitext(os.path.basename(files[0]))[0], {ch: files[0]}, eng,
                              mapping, size, False, target)
    x, y, _z = _xyz(size)
    with _undo("OpenLibrary: texturas"):
        nodes = [rt.olb_texNode(f, eng, "color" if r == "color" else "data", _tex_mapping(mapping), x, y)
                 for f, r in zip(files[:40], roles)]
        n = int(rt.olb_toSlate(_mxs_array(nodes)))
    return {"where": "slate", "count": n, "name": ""}


def apply_interior(name, exr, osl, preview="", size_code="S", width=350.0, height=350.0, engine="auto",
                   depth=-1, target="cursor"):
    """Habitación wParallax: material con el OSL que lee el EXR, puesto al objeto bajo el ratón, a la
    selección, a Slate o a un plano nuevo de la ventana (target "plane", o "cursor" sin objetos)."""
    if not exr or not osl:
        raise RuntimeError("Falta el EXR o el shader OSL de wParallax.")
    target = _route(target)
    focus_max()
    with _undo("OpenLibrary: interior " + name):
        m = rt.olb_interiorMaterial(name, _engine(engine), osl, exr, preview or "", size_code, int(depth))
        where, n, mname = str(rt.olb_putInterior(m, target, float(width), float(height))).split("|", 2)
    rt.redrawViews()
    return {"where": where, "count": int(n), "name": mname}


def open_max_file(max_path):
    focus_max()
    if rt.checkForSave():
        rt.loadMaxFile(max_path, useFileUnits=True, quiet=True)
    return True
