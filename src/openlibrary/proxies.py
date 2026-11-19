"""Dónde viven los proxies de cada asset (lo calcula la app y se lo pasa a Max).

Carpeta por asset, motor, modo y fecha del .max: si el .max no cambia, el proxy
creado en cualquier proyecto se reutiliza tal cual.
"""
import hashlib
import os

from . import config


def local_proxy_root():
    return os.path.join(config.app_data_dir(), "proxies")


def proxy_dir_for(max_path, asset_name, engine, imp, force_local=False):
    try:
        stamp = "%x" % int(os.stat(max_path).st_mtime)
    except OSError:
        stamp = "0"
    sub = "%s_%s_%s_%s" % (asset_name, engine, imp["proxy_mode"], stamp)
    custom = local_proxy_root() if force_local else (
        imp.get("proxy_custom_dir") if imp.get("proxy_location") == "custom" else None)
    if custom:
        h = hashlib.md5(os.path.normcase(max_path).encode("utf-8")).hexdigest()[:8]
        return os.path.join(custom, sub + "_" + h)
    return os.path.join(os.path.dirname(max_path), "_proxies", sub)


def writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        test = os.path.join(folder, ".olb_write_test")
        with open(test, "w") as fh:
            fh.write("ok")
        os.remove(test)
        return True
    except OSError:
        return False


def choose_dir(max_path, asset_name, engine, imp):
    """-> (carpeta, aviso o None). Si no se puede escribir, cae a una carpeta local."""
    pdir = proxy_dir_for(max_path, asset_name, engine, imp)
    if writable(pdir):
        return pdir, None
    local = proxy_dir_for(max_path, asset_name, engine, imp, force_local=True)
    return local, ("No se puede escribir junto al asset; el proxy se guarda en local:\n%s\n"
                   "Ojo si renderizas en granja." % local)


def is_cached(max_path, asset_name, engine, imp):
    if engine not in ("corona", "vray") or not max_path:
        return False
    for d in (proxy_dir_for(max_path, asset_name, engine, imp),
              proxy_dir_for(max_path, asset_name, engine, imp, force_local=True)):
        if os.path.isfile(os.path.join(d, "done.olb")) and os.path.isfile(os.path.join(d, "proxies.max")):
            return True
    return False
