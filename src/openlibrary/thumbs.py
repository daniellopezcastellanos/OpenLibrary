"""Carga asíncrona de miniaturas con caché local.

Las previews viven en la biblioteca (NAS); aquí se guarda una copia reducida en
%LOCALAPPDATA%\\OpenLibrary\\thumbs para que navegar sea instantáneo.
También detecta en segundo plano el motor de los .max sin sufijo.
"""
import hashlib
import os

from .qt import QtCore, QtGui

THUMB_PX = 320


class _Signals(QtCore.QObject):
    loaded = QtCore.Signal(str, QtGui.QImage)    # key, image
    engine = QtCore.Signal(str)                  # path del .max detectado
    checked = QtCore.Signal(str)                 # path del .max con archivos externos revisados


def cache_file_for(cache_dir, src):
    """Copia reducida de src en la caché local (cambia si cambia el archivo). Hace un stat: en el NAS
    puede tardar, por eso se llama desde el hilo de carga y nunca al pintar."""
    try:
        st = os.stat(src)
        stamp = "%s|%d|%d" % (os.path.normcase(src), int(st.st_mtime), st.st_size)
    except OSError:
        stamp = os.path.normcase(src)
    return os.path.join(cache_dir, hashlib.md5(stamp.encode("utf-8")).hexdigest() + ".jpg")


class _ThumbJob(QtCore.QRunnable):
    def __init__(self, key, src, cache_dir, signals, alive):
        super(_ThumbJob, self).__init__()
        self.key, self.src, self.cache_dir, self.signals, self.alive = key, src, cache_dir, signals, alive

    def run(self):
        if not self.alive(self.key):            # ya no hace falta (se ha vaciado la cola)
            return
        self.cache_file = cache_file_for(self.cache_dir, self.src)
        img = QtGui.QImage()
        if os.path.isfile(self.cache_file):
            img.load(self.cache_file)
        if img.isNull():
            reader = QtGui.QImageReader(self.src)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > THUMB_PX:
                size.scale(THUMB_PX, THUMB_PX, QtCore.Qt.KeepAspectRatio)
                reader.setScaledSize(size)
            img = reader.read()
            if not img.isNull() and img.hasAlphaChannel():
                # recortes con fondo transparente (bolas de muestra en PNG): sobre gris, no sobre negro
                flat = QtGui.QImage(img.size(), QtGui.QImage.Format_RGB32)
                flat.fill(QtGui.QColor(58, 61, 68))
                painter = QtGui.QPainter(flat)
                painter.drawImage(0, 0, img)
                painter.end()
                img = flat
            if not img.isNull():
                try:
                    img.save(self.cache_file, "JPG", 90)
                except Exception:
                    pass
        self.signals.loaded.emit(self.key, img)


class _EngineJob(QtCore.QRunnable):
    def __init__(self, path, cache, signals):
        super(_EngineJob, self).__init__()
        self.path, self.cache, self.signals = path, cache, signals

    def run(self):
        self.cache.detect(self.path)
        self.signals.engine.emit(self.path)


class _CheckJob(QtCore.QRunnable):
    def __init__(self, path, cache, signals):
        super(_CheckJob, self).__init__()
        self.path, self.cache, self.signals = path, cache, signals

    def run(self):
        try:
            if self.cache.get(self.path) is None:
                self.cache.check(self.path)
        except Exception:
            pass
        self.signals.checked.emit(self.path)


class ThumbLoader(QtCore.QObject):
    loaded = QtCore.Signal(str)        # key del asset
    engine_detected = QtCore.Signal(str)
    files_checked = QtCore.Signal(str)

    def __init__(self, cache_dir, engine_cache, check_cache=None, parent=None):
        super(ThumbLoader, self).__init__(parent)
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.engine_cache = engine_cache
        self.check_cache = check_cache
        self.check_pending = set()
        self.checked_session = set()   # revisados en esta sesión de Max
        # miniaturas en su propia cola: leer los .max (motor, archivos externos) es lento y no las frena
        self.pool = QtCore.QThreadPool()
        self.pool.setMaxThreadCount(6)
        self.bg_pool = QtCore.QThreadPool()
        self.bg_pool.setMaxThreadCount(2)
        self._order = 0                # la última pedida va primero: lo que se ve ahora, no lo ya pasado
        self.images = {}       # key -> QImage
        self.pending = set()
        self.engine_pending = set()
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.signals.engine.connect(self._on_engine)
        self.signals.checked.connect(self._on_checked)

    def _cache_file(self, src):
        return cache_file_for(self.cache_dir, src)

    def get(self, key, src, prefetch=False):
        """Devuelve la QImage si está lista; si no, la pide y devuelve None (no toca el disco).
        prefetch: lo que aún no se ve (va detrás de todo lo visible)."""
        img = self.images.get(key)
        if img is not None:
            return img
        if src and key not in self.pending:
            self.pending.add(key)
            self._order += 1
            prio = 0 if prefetch else min(self._order, 2 ** 30)
            self.pool.start(_ThumbJob(key, src, self.cache_dir, self.signals, self.pending.__contains__), prio)
        return None

    def prefetch_view(self, view, key_src, pages=2):
        """Pide las miniaturas de las próximas `pages` pantallas de una cuadrícula (QListView en modo icono)."""
        model = view.model()
        grid = view.gridSize()
        n = model.rowCount() if model is not None else 0
        if not n or grid.width() <= 0 or grid.height() <= 0:
            return
        vp = view.viewport()
        cols = max(1, vp.width() // grid.width())
        per_screen = cols * (vp.height() // grid.height() + 1)
        first = (view.verticalScrollBar().value() // grid.height()) * cols
        for row in range(first + per_screen, min(n, first + per_screen * (pages + 1))):
            key, src = key_src(model.index(row, 0))
            if key and src:
                self.get(key, src, prefetch=True)

    def invalidate(self, key):
        self.images.pop(key, None)
        self.pending.discard(key)

    def request_engine(self, path):
        if path in self.engine_pending:
            return
        self.engine_pending.add(path)
        self.bg_pool.start(_EngineJob(path, self.engine_cache, self.signals))

    def request_check(self, path):
        if self.check_cache is None or path in self.check_pending or path in self.checked_session:
            return
        self.check_pending.add(path)
        self.bg_pool.start(_CheckJob(path, self.check_cache, self.signals))

    def clear_queue(self):
        self.pool.clear()
        self.bg_pool.clear()
        self.pending.clear()
        self.engine_pending.clear()
        self.check_pending.clear()

    def _on_checked(self, path):
        self.check_pending.discard(path)
        self.checked_session.add(path)
        self.files_checked.emit(path)

    def recheck(self, path):
        if self.check_cache is not None:
            self.check_cache.forget(path)
        self.checked_session.discard(path)
        self.request_check(path)

    def _on_loaded(self, key, img):
        self.pending.discard(key)
        self.images[key] = img
        self.loaded.emit(key)

    def _on_engine(self, path):
        self.engine_detected.emit(path)
