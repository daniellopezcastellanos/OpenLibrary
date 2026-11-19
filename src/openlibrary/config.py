"""Ajustes de usuario de OpenLibrary.

Se guardan por usuario en %LOCALAPPDATA%\\OpenLibrary\\settings.json.

Espacio de trabajo: si se elige una carpeta (p. ej. en el NAS del estudio), lo que es de todos
(SHARED_KEYS: pestañas y carpetas, carpetas ocultas, iconos de carpeta, medidas y mapeado de cada
material, ajustes de preview) se guarda también en <carpeta>\\workspace.json y lo comparten todas las
personas que apunten a ella. Lo personal (ventana, tema, miniaturas, con qué Max se conecta...) sigue
solo en el settings.json local. Al guardar se mezcla con lo que haya en el archivo compartido: en
ENTRY_KEYS cada entrada por separado, así dos personas que ponen medidas a la vez no se pisan.
Sin conexión con la carpeta se trabaja con la última copia (va también en el settings.json local).
"""
import copy
import json
import os
import shutil

APP_NAME = "OpenLibrary"
VERSION = "0.2.1"


def app_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def settings_path():
    return os.path.join(app_data_dir(), "settings.json")


WORKSPACE_FILE = "workspace.json"
WORKSPACE_DIRNAME = "_OpenLibrary"        # la carpeta común que se crea dentro de la que elige el equipo
WORKSPACE_README = """Espacio de trabajo compartido de OpenLibrary.

Lo usan todas las personas que eligen esta carpeta en OpenLibrary (Ajustes > Espacio de trabajo):
  workspace.json  pestañas y sus carpetas, carpetas ocultas, iconos de carpeta, medidas y mapeado de
                  cada material y ajustes de preview. La app lo va juntando con lo de cada persona.
  medidas/        medidas de fabricante (Poliigon, Superellipse...), un archivo por carpeta de biblioteca.

No hace falta tocar nada a mano. Si se borra, cada persona sigue con la última copia de su equipo.
"""


def workspace_dir(chosen):
    """La carpeta del espacio de trabajo para la que ha elegido la persona: esa misma si ya lo es (o se llama
    _OpenLibrary), o la _OpenLibrary de dentro (que se creará si no existe)."""
    chosen = os.path.normpath(chosen)
    if os.path.basename(chosen).lower() == WORKSPACE_DIRNAME.lower() or \
            os.path.isfile(os.path.join(chosen, WORKSPACE_FILE)):
        return chosen
    return os.path.join(chosen, WORKSPACE_DIRNAME)


def prepare_workspace(folder):
    """Crea la carpeta común con lo que necesita (medidas, LEEME). Devuelve True si ya era un espacio."""
    existed = os.path.isfile(os.path.join(folder, WORKSPACE_FILE))
    os.makedirs(os.path.join(folder, "medidas"), exist_ok=True)
    readme = os.path.join(folder, "LEEME.txt")
    if not os.path.isfile(readme):
        try:
            with open(readme, "w", encoding="utf-8") as fh:
                fh.write(WORKSPACE_README)
        except OSError:
            pass
    return existed
SHARED_KEYS = ("libraries", "hidden_folders", "folder_marks", "surface_sizes", "surface_mapping", "preview")
ENTRY_KEYS = ("folder_marks", "surface_sizes", "surface_mapping")


DEFAULTS = {
    # Pestañas del navegador. Cada una agrupa varias carpetas.
    # kind: "models" | "materials" | "textures" | "interiors" (los tres últimos: ui_surfaces.py)
    "libraries": [
        {"name": "Modelos", "kind": "models", "paths": []},
        {"name": "Materiales", "kind": "materials", "paths": []},
        {"name": "Texturas", "kind": "textures", "paths": []},
    ],
    "current_library": 0,
    "show_info_bar": True,
    "always_on_top": False,
    "thumb_size": 160,
    "include_subfolders": True,
    "import": {
        # Merge
        "group": True,
        "layer_mode": "asset",          # "asset" | "file" | "current"
        "object_dups": "autorename",    # "autorename" | "merge" | "skip" | "replace" | "ask"
        "material_dups": "scene",       # "scene" | "file" | "rename" | "ask"
        "import_lights": False,
        "import_cameras": False,
        "place_on_surface": True,
        "place_multiple": True,         # seguir colocando instancias con cada clic
        # Proxy
        "proxy_mode": "single",         # "single" (todo en uno) | "per_object"
        "proxy_location": "asset",      # "asset" (junto al .max) | "custom"
        "proxy_custom_dir": "",
        "proxy_display": "preview",     # "bbox" | "preview" | "full"
        "missing_engine": "ask",        # "ask" | "fallback"
        "relink_on_import": True,
        "relink_dirs": [],              # carpetas extra de texturas
    },
    "catalog": {
        "maps_folder": "z-maps",        # carpeta de texturas dentro de la carpeta elegida
        "last_dir": "",
    },
    "preview": {
        "size": 512,
        "method": "render",             # "render" | "viewport"
        "margin": 1.15,
        "elevation": 20.0,
        "azimuth": 35.0,
    },
}


def _merge(base, data):
    out = copy.deepcopy(base)
    for key, value in (data or {}).items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


KINDS = ("models", "materials", "textures", "interiors")
SHOW_MODES = ("both", "favorites", "all")
_MISSING = object()


def migrate_libraries(libs):
    """Admite el formato antiguo [{"name", "path"}] y lo pasa a pestañas con carpetas."""
    if not isinstance(libs, list):
        return copy.deepcopy(DEFAULTS["libraries"])
    out = []
    loose = []
    for lib in libs:
        if not isinstance(lib, dict):
            continue
        if "paths" in lib:
            entry = {"name": lib.get("name") or "Biblioteca",
                     "kind": lib.get("kind") if lib.get("kind") in KINDS else "models",
                     "paths": [p for p in lib["paths"] if p]}
            if lib.get("show") in SHOW_MODES:
                entry["show"] = lib["show"]       # qué se ve al abrir la pestaña (favoritos primero...)
            for k in ("tree_fav", "tree_all"):    # «Favoritos» / «Todos» en el árbol
                if isinstance(lib.get(k), bool):
                    entry[k] = lib[k]
            out.append(entry)
        elif lib.get("path"):
            loose.append(lib["path"])
    if loose:
        models = next((l for l in out if l["kind"] == "models"), None)
        if models is None:
            out = copy.deepcopy(DEFAULTS["libraries"]) if not out else out
            models = next((l for l in out if l["kind"] == "models"), None)
            if models is None:
                models = {"name": "Modelos", "kind": "models", "paths": []}
                out.insert(0, models)
        for p in loose:
            if p not in models["paths"]:
                models["paths"].append(p)
    return out


def _snap(v):
    # copia para comparar luego; la marca de «no existe» se deja tal cual (deepcopy crearía otra)
    return v if v is _MISSING else copy.deepcopy(v)


class Settings(object):
    def __init__(self, path=None):
        self.path = path or settings_path()
        self.data = copy.deepcopy(DEFAULTS)
        self.ws_state = "local"     # "local" | "ok" | "new" (aún sin archivo) | "offline"
        self._ws_synced = {}
        self._ws_stamp = None
        self.load()
        self._load_shared()

    @staticmethod
    def _read(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("ajustes sin formato")
        data = _merge(DEFAULTS, data)
        data["libraries"] = migrate_libraries(data.get("libraries"))
        return data

    def _stamp(self):
        try:
            st = os.stat(self.path)
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def load(self):
        data = None
        # si el archivo está pero no se puede leer, se prueba con la copia del guardado anterior
        for path in (self.path, self.path + ".bak") if os.path.exists(self.path) else (self.path,):
            try:
                data = self._read(path)
                break
            except (OSError, ValueError):
                continue
        if data is None:
            data = copy.deepcopy(DEFAULTS)
            data["libraries"] = migrate_libraries(data.get("libraries"))
        self.data = data
        self._synced = copy.deepcopy(data)      # lo que había en disco la última vez que se leyó o guardó
        self._disk = self._stamp()

    def save(self):
        """Guarda sin pisar lo de otra copia de la app.

        Si el archivo ha cambiado desde la última vez (otra OpenLibrary abierta ha guardado), se
        parte de lo que hay en disco y encima solo va lo que se ha tocado aquí. Así una copia con
        los ajustes viejos en memoria no devuelve las bibliotecas a como estaban.
        """
        disk = None
        try:
            disk = self._read(self.path)
        except (OSError, ValueError):
            pass
        if disk is not None and self._stamp() != self._disk:
            for key in set(self.data) | set(self._synced):
                mine = self.data.get(key, _MISSING)
                if mine != self._synced.get(key, _MISSING):
                    if mine is _MISSING:
                        disk.pop(key, None)
                    else:
                        disk[key] = mine
            self.data.clear()
            self.data.update(disk)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
        if disk is not None:
            try:
                shutil.copyfile(self.path, self.path + ".bak")
            except OSError:
                pass
        os.replace(tmp, self.path)
        self._synced = copy.deepcopy(self.data)
        self._disk = self._stamp()
        if self.ws_state in ("ok", "new"):
            self._save_shared()

    # --- espacio de trabajo compartido --------------------------------------
    @property
    def workspace(self):
        return (self.data.get("workspace") or "").strip()

    def workspace_file(self):
        return os.path.join(self.workspace, WORKSPACE_FILE) if self.workspace else None

    def measures_dir(self):
        """Carpeta de los archivos de medidas de fabricante (uno por carpeta raíz de biblioteca)."""
        return os.path.join(self.workspace or app_data_dir(), "medidas")

    @staticmethod
    def _ws_read(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("espacio de trabajo sin formato")
        if "libraries" in data:
            data["libraries"] = migrate_libraries(data["libraries"])
        return data

    def _ws_file_stamp(self):
        try:
            st = os.stat(self.workspace_file())
            return st.st_mtime_ns, st.st_size
        except (OSError, TypeError):
            return None

    def _load_shared(self):
        """Toma de la carpeta compartida lo que es de todos (si se puede leer)."""
        self._ws_synced = {}
        if not self.workspace:
            self.ws_state = "local"
            return
        path = self.workspace_file()
        if not os.path.isdir(self.workspace):
            self.ws_state = "offline"
            return
        if not os.path.isfile(path):
            self.ws_state = "new"
            return
        try:
            shared = self._ws_read(path)
        except (OSError, ValueError):
            self.ws_state = "offline"
            return
        for k in SHARED_KEYS:
            if k in shared:
                self.data[k] = shared[k]
            self._ws_synced[k] = _snap(self.data.get(k, _MISSING))
        self._ws_stamp = self._ws_file_stamp()
        self.ws_state = "ok"

    def _save_shared(self):
        path = self.workspace_file()
        if self.ws_state == "ok" and all(self.data.get(k, _MISSING) == self._ws_synced.get(k, _MISSING)
                                         for k in SHARED_KEYS):
            return                         # nada común ha cambiado: no se toca el archivo del NAS
        disk = {}
        if self.ws_state == "ok":
            try:
                disk = self._ws_read(path)
            except (OSError, ValueError):
                disk = {}
        out = dict(disk)
        for k in SHARED_KEYS:
            mine = self.data.get(k, _MISSING)
            base = self._ws_synced.get(k, _MISSING)
            theirs = disk.get(k, _MISSING)
            if self.ws_state == "new" or theirs is _MISSING:
                if mine is not _MISSING:
                    out[k] = mine
            elif mine != base:
                if k in ENTRY_KEYS and isinstance(mine, dict):
                    merged = dict(theirs) if isinstance(theirs, dict) else {}
                    b = base if isinstance(base, dict) else {}
                    for ek in set(mine) | set(b):
                        mv, bv = mine.get(ek, _MISSING), b.get(ek, _MISSING)
                        if mv != bv:
                            if mv is _MISSING:
                                merged.pop(ek, None)
                            else:
                                merged[ek] = mv
                    out[k] = merged
                elif mine is _MISSING:
                    out.pop(k, None)
                else:
                    out[k] = mine
            # lo que no se ha tocado aquí: se queda lo de la carpeta (puede venir de otra persona)
        try:
            os.makedirs(self.workspace, exist_ok=True)
            tmp = path + ".%d.tmp" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            self.ws_state = "offline"
            return
        for k in SHARED_KEYS:
            if k in out:
                self.data[k] = copy.deepcopy(out[k])
            self._ws_synced[k] = _snap(self.data.get(k, _MISSING))
        self._ws_stamp = self._ws_file_stamp()
        self.ws_state = "ok"

    def refresh_shared(self):
        """Si otra persona ha cambiado la carpeta compartida, trae sus cambios (sin perder los nuestros
        sin guardar). Devuelve las claves que han cambiado."""
        if self.ws_state not in ("ok", "offline") or not self.workspace:
            return []
        if self.ws_state == "ok" and self._ws_file_stamp() == self._ws_stamp:
            return []
        before = {k: copy.deepcopy(self.data.get(k)) for k in SHARED_KEYS}
        pending = {k for k in SHARED_KEYS if self.data.get(k, _MISSING) != self._ws_synced.get(k, _MISSING)}
        if self.ws_state == "offline" or pending:
            self.ws_state = "ok" if os.path.isfile(self.workspace_file() or "") else self.ws_state
            if self.ws_state == "ok":
                self._save_shared()         # mezcla lo nuestro pendiente con lo de la carpeta
        else:
            mine = {k: self.data.get(k) for k in SHARED_KEYS}
            self._load_shared()
            if self.ws_state != "ok":
                self.data.update({k: v for k, v in mine.items() if v is not None})
        return [k for k in SHARED_KEYS if self.data.get(k) != before[k]]

    def set_workspace(self, folder, take_theirs):
        """Cambia de espacio de trabajo. take_theirs: usar lo que ya hay en esa carpeta (si no, se crea
        con lo de esta persona). folder vacío = volver a trabajar solo en local."""
        self.data["workspace"] = folder or ""
        if not folder:
            self.ws_state = "local"
            self._ws_synced = {}
            self.save()
            return
        if take_theirs:
            self._load_shared()
        else:
            self.ws_state = "new"
        self.save()

    # --- atajos -----------------------------------------------------------
    @property
    def libraries(self):
        return self.data["libraries"]

    @property
    def imp(self):
        return self.data["import"]

    @property
    def preview(self):
        return self.data["preview"]

    @property
    def hidden(self):
        """Carpetas ocultas del árbol: {"names": [nombres o patrones], "paths": [rutas]}."""
        h = self.data.get("hidden_folders")
        if not isinstance(h, dict):
            h = self.data["hidden_folders"] = {}
        h.setdefault("names", [])
        h.setdefault("paths", [])
        return h

    def current_library(self):
        libs = self.libraries
        if not libs:
            return None
        idx = max(0, min(self.data.get("current_library", 0), len(libs) - 1))
        return libs[idx]
