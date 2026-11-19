"""Navegador principal: pestañas + árbol de carpetas + miniaturas + barra de info.

Funciona sin 3ds Max. Las órdenes a Max (merge, proxy, preview, re-enlazar) van
por el puente (maxlink) en segundo plano para que la ventana nunca se congele.
"""
import os
import subprocess

from . import (batchpreview, config, foldericons, icon, icon_path, library, maxfile, maxlink, pathedit, proxies,
               theme, ui_fav)
from .maxfile import CheckCache, EngineCache
from .qt import QtCore, QtGui, QtWidgets
from .thumbs import ThumbLoader
from .ui_catalog import CatalogDialog
from .ui_inspector import Inspector, QuickLook
from .ui_missing import MissingDialog
from .ui_settings import SettingsDialog
from .ui_stats import StatsRunner
from .ui_surfaces import SurfacePanel

MIME = "application/x-openlibrary-asset"
ROLE_ASSET = QtCore.Qt.UserRole + 1
ROLE_PATH = QtCore.Qt.UserRole + 2
ROLE_FAV = QtCore.Qt.UserRole + 3          # el nodo «Favoritos» del árbol

ENGINE_STYLE = {
    "corona":  ("C", QtGui.QColor("#E8731A")),
    "vray":    ("V", QtGui.QColor("#2D7FD3")),
    "fstorm":  ("F", QtGui.QColor("#3A3A3A")),
    "other":   ("?", QtGui.QColor("#7A7A7A")),
    "pending": ("…", QtGui.QColor("#555555")),
}
ENGINE_LABEL = {"corona": "Corona", "vray": "V-Ray", "fstorm": "FStorm", "other": "otro motor"}
ENGINE_ORDER = ("corona", "vray", "fstorm", "other", "pending")
KNOWN_ENGINES = ("corona", "vray", "fstorm")
WARN_COLOR = QtGui.QColor(theme.WARN)


_engine_logos = {}


def engine_logo(engine):
    """Logo del motor (imagen cuadrada) para la etiqueta de la miniatura, o None."""
    if engine not in KNOWN_ENGINES:
        return None
    img = _engine_logos.get(engine)
    if img is None:
        img = QtGui.QImage(icon_path("engine_" + engine)[:-4] + ".png")
        _engine_logos[engine] = img
    return None if img.isNull() else img


def _short(text, n=30):
    return text if len(text) <= n else text[:n - 1] + "…"


def asset_file_status(asset, check_cache):
    """Suma de archivos externos de todas las versiones (resultado en memoria)."""
    total = 0
    missing = []
    relinkable = []
    known = False
    for f in asset.all_files():
        r = check_cache.peek(f) if check_cache else None
        if r is None:
            continue
        known = True
        total += r["total"]
        missing += r["missing"]
        relinkable += r["relinkable"]
    return known, total, missing, relinkable


# ---------------------------------------------------------------------------
# Conexión con 3ds Max
# ---------------------------------------------------------------------------
class _TaskSignals(QtCore.QObject):
    finished = QtCore.Signal(object, object, object)     # callback, result, error


class _MaxTask(QtCore.QRunnable):
    def __init__(self, fn, callback, signals):
        super(_MaxTask, self).__init__()
        self.fn, self.callback, self.signals = fn, callback, signals

    def run(self):
        try:
            res, err = self.fn(), None
        except Exception as exc:
            res, err = None, exc
        self.signals.finished.emit(self.callback, res, err)


class _DiscoverTask(QtCore.QRunnable):
    def __init__(self, signals):
        super(_DiscoverTask, self).__init__()
        self.signals = signals

    def run(self):
        try:
            found = maxlink.discover()
        except Exception:
            found = []
        self.signals.found.emit(found)


class _DiscoverSignals(QtCore.QObject):
    found = QtCore.Signal(object)


# ---------------------------------------------------------------------------
# Escaneo en segundo plano (incremental contra la caché)
# ---------------------------------------------------------------------------
class ScanThread(QtCore.QThread):
    progress = QtCore.Signal(int, int)
    done = QtCore.Signal(object, str)

    def __init__(self, index, cache_file, incremental=True, parent=None):
        super(ScanThread, self).__init__(parent)
        self.index = index
        self.cache_file = cache_file
        self.incremental = incremental

    def run(self):
        self.index.cancelled = False
        self.index.scan(progress=lambda f, a: self.progress.emit(f, a), incremental=self.incremental)
        if not self.index.cancelled:
            self.index.save(self.cache_file)
        self.done.emit(self.index, self.cache_file)

    def cancel(self):
        self.index.cancelled = True


# ---------------------------------------------------------------------------
# Modelo + delegate de miniaturas
# ---------------------------------------------------------------------------
class AssetModel(QtCore.QAbstractListModel):
    def __init__(self, loader, engine_cache, check_cache, parent=None):
        super(AssetModel, self).__init__(parent)
        self.assets = []
        self.rows = {}
        self.loader = loader
        self.engine_cache = engine_cache
        self.check_cache = check_cache
        loader.loaded.connect(self._emit_key)
        loader.engine_detected.connect(self._on_file)
        loader.files_checked.connect(self._on_file)

    def set_assets(self, assets):
        self.beginResetModel()
        self.assets = assets
        self.rows = {a.key: i for i, a in enumerate(assets)}
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.assets)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        a = self.assets[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return a.name
        if role == ROLE_ASSET:
            return a
        if role == QtCore.Qt.ToolTipRole:
            lines = [a.name, a.folder]
            for eng, p in sorted(a.versions.items()):
                lines.append("%s: %s" % (ENGINE_LABEL.get(eng, eng), os.path.basename(p)))
            for p in a.auto_files:
                eng = self.engine_cache.get(p) or "detectando..."
                lines.append("%s: %s" % (ENGINE_LABEL.get(eng, eng), os.path.basename(p)))
            if not a.preview:
                lines.append("(sin preview)")
            known, total, missing, relinkable = asset_file_status(a, self.check_cache)
            if missing or relinkable:
                lines.append("")
                lines.append("⚠ %d archivo(s) externo(s) fuera de su ruta" % (len(missing) + len(relinkable)))
                if relinkable:
                    lines.append("   %d se re-enlazan solos al importar" % len(relinkable))
                for m in (missing + relinkable)[:6]:
                    lines.append("   " + os.path.basename(m.replace("/", "\\")))
            return "\n".join(lines)
        return None

    def flags(self, index):
        f = super(AssetModel, self).flags(index)
        return f | QtCore.Qt.ItemIsDragEnabled if index.isValid() else f

    def _emit_key(self, key):
        row = self.rows.get(key)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx)

    def _on_file(self, path):
        folder = os.path.dirname(path)
        for a in self.assets:
            if a.folder == folder and path in a.all_files():
                self._emit_key(a.key)


class AssetDelegate(QtWidgets.QStyledItemDelegate):
    """Miniaturas. Dos vistas:
    - galería: manda la imagen; el nombre aparece al pasar el ratón o al seleccionar.
    - tarjetas: imagen arriba y nombre + motor debajo.
    """

    def __init__(self, view, loader, engine_cache, check_cache, scene_engine_fn):
        super(AssetDelegate, self).__init__(view)
        self.view = view
        self.loader = loader
        self.engine_cache = engine_cache
        self.check_cache = check_cache
        self.scene_engine_fn = scene_engine_fn
        self.thumb = 160                     # tamaño pedido con el deslizador (mínimo)
        self.fill = 0                        # tamaño real: crece para llenar la fila
        self.cards = False
        self.edge = {}                       # key -> color del borde de la imagen (fondo sin costuras)
        self.refresh_colors()

    def refresh_colors(self):
        self.c_card = theme.color(theme.SURFACE)
        self.c_card_hi = theme.color(theme.SURFACE_HI)
        self.c_border = theme.color(theme.BORDER)
        self.c_border_hi = theme.color(theme.BORDER_HI)
        self.c_accent = theme.color(theme.ACCENT)
        self.c_text = theme.color(theme.TEXT)
        self.c_muted = theme.color(theme.MUTED)
        self.c_faint = theme.color(theme.FAINT)

    @property
    def margin(self):
        return 6 if self.cards else 3

    @property
    def footer(self):
        return 44 if self.cards else 0

    def cell_size(self, minimum=False):
        m = self.margin
        t = self.thumb if minimum else max(self.thumb, self.fill)
        return QtCore.QSize(t + 2 * m, t + self.footer + 2 * m)

    def sizeHint(self, option, index):
        return self.cell_size()

    def heart_rect(self, rect):
        """El corazón de favorito: a la derecha del nombre (tarjetas) o abajo a la derecha de la imagen."""
        m = self.margin
        cell = QtCore.QRectF(QtCore.QPointF(0, 0), QtCore.QSizeF(self.cell_size()))
        cell.moveCenter(QtCore.QRectF(rect).center())
        r = cell.adjusted(m, m, -m, -m)
        if self.cards:
            return QtCore.QRectF(r.right() - 10 - 18, r.bottom() - self.footer + 6, 18, 16)
        return QtCore.QRectF(r.right() - 8 - 22, r.bottom() - 8 - 22, 22, 22)

    def _edge_color(self, key, img):
        c = self.edge.get(key)
        if c is None:
            c = QtGui.QColor(img.pixel(1, 1))
            if len(self.edge) > 5000:
                self.edge.clear()
            self.edge[key] = c
        return c

    def paint(self, p, option, index):
        a = index.data(ROLE_ASSET)
        if a is None:
            return
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        m = self.margin
        cell = QtCore.QRectF(QtCore.QPointF(0, 0), QtCore.QSizeF(self.cell_size()))
        cell.moveCenter(QtCore.QRectF(option.rect).center())
        r = cell.adjusted(m, m, -m, -m)
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        radius = float(theme.RADIUS + 1 if self.cards else theme.RADIUS * 0.8) if theme.RADIUS else 0.0

        card = QtGui.QPainterPath()
        card.addRoundedRect(r, radius, radius)
        img_rect = QtCore.QRectF(r.left(), r.top(), r.width(), r.height() - self.footer)
        img = self.loader.get(a.key, a.preview) if a.preview else None
        has_img = img is not None and not img.isNull()

        p.save()
        p.setClipPath(card)
        p.fillRect(r, self.c_card_hi if (hover or selected) else self.c_card)
        if has_img:
            p.fillRect(img_rect, self._edge_color(a.key, img))
            s = QtCore.QSizeF(img.size())
            s.scale(img_rect.size(), QtCore.Qt.KeepAspectRatio)
            target = QtCore.QRectF(QtCore.QPointF(0, 0), s)
            target.moveCenter(img_rect.center())
            p.drawImage(target, img)
        else:
            f = QtGui.QFont(option.font)
            p.setFont(f)
            if self.cards:
                f.setPointSizeF(8.5)
                p.setFont(f)
                p.setPen(self.c_faint)
                p.drawText(img_rect, QtCore.Qt.AlignCenter, "cargando…" if a.preview else "sin preview")
            else:
                # En galería no hay pie: el nombre va dentro para saber qué es
                f.setWeight(QtGui.QFont.DemiBold)
                p.setFont(f)
                p.setPen(self.c_muted)
                box = img_rect.adjusted(10, 26, -10, -22)
                p.drawText(box, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, a.name)
                f.setWeight(QtGui.QFont.Normal)
                f.setPointSizeF(8)
                p.setFont(f)
                p.setPen(self.c_faint)
                p.drawText(QtCore.QRectF(img_rect.left(), img_rect.bottom() - 22, img_rect.width(), 16),
                           QtCore.Qt.AlignCenter, "cargando…" if a.preview else "sin preview")

        # Galería: el nombre aparece sobre un degradado al pasar el ratón o seleccionar
        if not self.cards and has_img and (hover or selected):
            h = min(img_rect.height() * 0.42, 64.0)
            band = QtCore.QRectF(img_rect.left(), img_rect.bottom() - h, img_rect.width(), h + 1)
            grad = QtGui.QLinearGradient(band.topLeft(), band.bottomLeft())
            grad.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QtGui.QColor(0, 0, 0, 205))
            p.fillRect(band, grad)
            f1 = QtGui.QFont(option.font)
            f1.setWeight(QtGui.QFont.DemiBold)
            f1.setPointSizeF(max(8.0, option.font.pointSizeF() - 0.5))
            p.setFont(f1)
            p.setPen(QtGui.QColor("white"))
            tr = band.adjusted(9, 0, -36, -7)
            name = QtGui.QFontMetrics(f1).elidedText(a.name, QtCore.Qt.ElideRight, int(tr.width()))
            p.drawText(tr, QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom, name)
        p.restore()

        # Trabajo en segundo plano solo para lo que se ve
        for f in a.all_files():
            if f in a.auto_files and self.engine_cache.get(f) is None:
                self.loader.request_engine(f)
            self.loader.request_check(f)

        # Motor: etiqueta blanca con el logo, arriba a la izquierda (como las de herramienta de Behance)
        d = float(max(20, min(28, self.thumb // 7)))
        engines = sorted(a.engines(self.engine_cache), key=lambda e: ENGINE_ORDER.index(e) if e in ENGINE_ORDER else 9)
        scene = self.scene_engine_fn()
        x = img_rect.left() + 7
        y = img_rect.top() + 7
        for eng in engines:
            tag = QtCore.QRectF(x, y, d, d)
            dim = scene in KNOWN_ENGINES and eng in KNOWN_ENGINES and eng != scene
            shape = QtGui.QPainterPath()
            shape.addRoundedRect(tag, d * 0.24, d * 0.24)
            logo = engine_logo(eng)
            if logo is not None:
                # la etiqueta es el propio logo; la versión que no es del motor de la escena, apagada
                p.save()
                p.setClipPath(shape, QtCore.Qt.IntersectClip)
                p.fillRect(tag, QtGui.QColor("white"))
                p.setOpacity(0.38 if dim else 1.0)
                p.drawImage(tag, logo)
                p.restore()
                p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 150), 1))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawPath(shape)
            else:
                p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 45), 1))
                p.setBrush(QtGui.QColor("white"))
                p.drawPath(shape)
                font = QtGui.QFont(option.font)
                font.setBold(True)
                font.setPixelSize(int(d * 0.58))
                p.setFont(font)
                p.setPen(QtGui.QColor("#7A7A7A"))
                p.drawText(tag, QtCore.Qt.AlignCenter, ENGINE_STYLE.get(eng, ENGINE_STYLE["other"])[0])
            p.setOpacity(1.0)
            x += d + 4
        d = d * 0.82

        # Aviso amarillo arriba a la derecha: archivos externos fuera de su ruta
        known, total, missing, relinkable = asset_file_status(a, self.check_cache)
        if missing or relinkable:
            self._warning(p, QtCore.QRectF(img_rect.right() - d - 6, img_rect.top() + 6, d, d))

        fav = self.view.panel.is_fav(a)
        if fav or hover or selected:
            hr = self.heart_rect(option.rect)
            if self.cards:
                ui_fav.paint_heart(p, hr.adjusted(2, 1.5, -2, -1.5), fav, self.c_faint)
            else:
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QColor(20, 24, 34, 200))
                p.drawEllipse(hr)
                ui_fav.paint_heart(p, hr.adjusted(5, 5.5, -5, -4.5), fav, QtGui.QColor(255, 255, 255, 200))

        if self.cards:
            foot = QtCore.QRectF(r.left() + 10, img_rect.bottom() + 5, r.width() - 20, self.footer - 10)
            f1 = QtGui.QFont(option.font)
            f1.setWeight(QtGui.QFont.DemiBold)
            p.setFont(f1)
            p.setPen(self.c_accent if selected else self.c_text)
            name = QtGui.QFontMetrics(f1).elidedText(a.name, QtCore.Qt.ElideRight, int(foot.width() - 22))
            p.drawText(QtCore.QRectF(foot.left(), foot.top(), foot.width(), foot.height() / 2 + 2),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, name)
            f2 = QtGui.QFont(option.font)
            f2.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
            p.setFont(f2)
            p.setPen(self.c_muted)
            labels = [ENGINE_LABEL.get(e, "detectando…" if e == "pending" else e) for e in engines]
            sub = " · ".join(labels) if labels else "sin .max"
            sub = QtGui.QFontMetrics(f2).elidedText(sub, QtCore.Qt.ElideRight, int(foot.width()))
            p.drawText(QtCore.QRectF(foot.left(), foot.top() + foot.height() / 2, foot.width(), foot.height() / 2),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub)

        # Borde
        p.setBrush(QtCore.Qt.NoBrush)
        if selected:
            p.setPen(QtGui.QPen(self.c_accent, 2.5))
            p.drawRoundedRect(r.adjusted(1.2, 1.2, -1.2, -1.2), max(0.0, radius - 1), max(0.0, radius - 1))
        elif hover:
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 90), 1.2))
            p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), radius, radius)
        elif self.cards or not has_img:
            p.setPen(QtGui.QPen(self.c_border, 1))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.restore()

    @staticmethod
    def _warning(p, rect):
        tri = QtGui.QPolygonF([QtCore.QPointF(rect.center().x(), rect.top()),
                               QtCore.QPointF(rect.right(), rect.bottom()),
                               QtCore.QPointF(rect.left(), rect.bottom())])
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 150), 1.5))
        p.setBrush(WARN_COLOR)
        p.drawPolygon(tri)
        f = QtGui.QFont(p.font())
        f.setBold(True)
        f.setPixelSize(int(rect.height() * 0.6))
        p.setFont(f)
        p.setPen(QtGui.QColor("#222"))
        p.drawText(rect.adjusted(0, rect.height() * 0.22, 0, 0), QtCore.Qt.AlignCenter, "!")


class AssetView(QtWidgets.QListView):
    dropped_outside = QtCore.Signal(object, int)    # [Asset], PID de la ventana donde se soltó

    def __init__(self, panel, parent=None):
        super(AssetView, self).__init__(parent)
        self.panel = panel
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setMovement(QtWidgets.QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        # al moverse, se piden ya las miniaturas de las pantallas siguientes
        self._pre = QtCore.QTimer(self)
        self._pre.setSingleShot(True)
        self._pre.setInterval(120)
        self._pre.timeout.connect(self._prefetch)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._pre.start())

    def _prefetch(self):
        def key_src(idx):
            a = idx.data(ROLE_ASSET)
            return (a.key, a.preview) if a is not None else (None, None)
        self.panel.loader.prefetch_view(self, key_src)

    def resizeEvent(self, event):
        super(AssetView, self).resizeEvent(event)
        self.panel._fit_grid()
        QtCore.QTimer.singleShot(0, self.panel._fit_grid)

    def _heart_at(self, pos):
        idx = self.indexAt(pos)
        if idx.isValid() and self.panel.delegate.heart_rect(self.visualRect(idx)).adjusted(-3, -3, 3, 3) \
                .contains(QtCore.QPointF(pos)):
            return idx.data(ROLE_ASSET)
        return None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            a = self._heart_at(event.pos())
            if a is not None:
                self.panel.toggle_fav([a])
                event.accept()
                return
        super(AssetView, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super(AssetView, self).mouseMoveEvent(event)
        if not event.buttons():
            on = self._heart_at(event.pos()) is not None
            self.viewport().setCursor(QtCore.Qt.PointingHandCursor if on else QtCore.Qt.ArrowCursor)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Space:
            self.panel._quick_look()
            return
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            sel = self.panel._selected_assets()
            if sel:
                self.panel._drop_menu(sel)
            return
        super(AssetView, self).keyPressEvent(event)

    def startDrag(self, actions):
        idx = self.currentIndex()
        a = idx.data(ROLE_ASSET) if idx.isValid() else None
        if a is None:
            return
        assets = self.panel._selected_assets()
        if a not in assets:
            assets = [a]
        mime = QtCore.QMimeData()
        mime.setData(MIME, QtCore.QByteArray(a.key.encode("utf-8")))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        img = self.panel.loader.images.get(a.key)
        if img is not None and not img.isNull():
            drag.setPixmap(QtGui.QPixmap.fromImage(img).scaled(
                96, 96, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        drag.exec(QtCore.Qt.CopyAction)
        # Nadie acepta nuestro tipo MIME: miramos qué ventana hay debajo del ratón.
        pos = QtGui.QCursor.pos()
        w = QtWidgets.QApplication.widgetAt(pos)
        if w is not None and (w is self.panel or self.panel.isAncestorOf(w)):
            return
        self.dropped_outside.emit(assets, maxlink.pid_under_cursor(pos.x(), pos.y()))


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _chip(text, tip, checked=False):
    b = QtWidgets.QToolButton()
    b.setObjectName("Chip")
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    return b


def _tool(icon_name, text, tip, name=None):
    b = QtWidgets.QToolButton()
    if name:
        b.setObjectName(name)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setIcon(icon(icon_name))
    b.setProperty("icon_name", icon_name)
    b.setIconSize(QtCore.QSize(18, 18))
    b.setText(text)
    b.setToolTip(tip)
    b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon if text else QtCore.Qt.ToolButtonIconOnly)
    b.setAutoRaise(True)
    return b


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------
class BrowserPanel(QtWidgets.QWidget):
    pin_toggled = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super(BrowserPanel, self).__init__(parent)
        self.setObjectName("OpenLibraryPanel")
        self.settings = config.Settings()
        app = config.app_data_dir()
        self.cache_dir = os.path.join(app, "index")
        self.engine_cache = EngineCache(os.path.join(app, "engines.json"))
        self.check_cache = CheckCache(os.path.join(app, "external_files.json"))
        from . import modelstats
        self.stats = modelstats.StatsCache(os.path.join(app, "model_stats.json"))
        self.stats_runner = StatsRunner(self.stats, self)
        self.stats_runner.progress.connect(self._stats_progress)
        self.stats_runner.updated.connect(lambda _f: self._update_info())
        self.stats_runner.finished.connect(self._stats_done)
        self.loader = ThumbLoader(os.path.join(app, "thumbs"), self.engine_cache, self.check_cache, self)
        self.indexes = {}            # cache_file -> LibraryIndex (en memoria toda la sesión)
        self.scanned = set()         # cache_files ya revisados en esta sesión
        self.index = None
        self.cache_file = None
        self.hidden = set()          # carpetas ocultas (normcase) de la pestaña actual
        self.fav_item = None         # nodo «Favoritos» del árbol (si la pestaña lo enseña)
        self.scans = {}              # cache_file -> ScanThread (cada pestaña acaba la suya aunque cambies)
        self.maxes = []              # MaxInstance con el puente activo
        self.target_pid = 0          # el Max que manda (maxlink.front_pid)
        self._fav_keys = {}          # (raíces, ruta) -> clave de favorito (se calcula una vez)
        self._models_text = None     # búsqueda con la que se montó la galería de modelos
        self._tab_save = QtCore.QTimer(self)
        self._tab_save.setSingleShot(True)
        self._tab_save.setInterval(2000)
        self._tab_save.timeout.connect(self.settings.save)
        self.front_timer = QtCore.QTimer(self)
        self.front_timer.timeout.connect(self._follow_front_max)
        self.front_timer.start(700)
        self.max_pool = QtCore.QThreadPool(self)
        self.max_pool.setMaxThreadCount(4)
        self.task_signals = _TaskSignals()
        self.task_signals.finished.connect(lambda cb, res, err: cb(res, err))
        self.discover_signals = _DiscoverSignals()
        self.discover_signals.found.connect(self._on_maxes)
        self._discovering = False
        self._busy = 0               # órdenes a Max en marcha
        self.batch = None            # lote de previews en segundo plano
        self.batch_timer = QtCore.QTimer(self)
        self.batch_timer.timeout.connect(self._batch_tick)
        self._build_ui()
        self._refresh_max_combo()
        self._reload_tabs()

        self.engine_timer = QtCore.QTimer(self)
        self.engine_timer.timeout.connect(self._discover)
        self.engine_timer.start(2000)
        self._discover()
        QtCore.QTimer.singleShot(1500, self._ws_notice)
        # lo que cambian los compañeros llega solo (cada 10 s se mira si ha cambiado el archivo común)
        self.ws_timer = QtCore.QTimer(self)
        self.ws_timer.setInterval(10000)
        self.ws_timer.timeout.connect(self._ws_poll)
        self.ws_timer.start()
        self.save_timer = QtCore.QTimer(self)
        self.save_timer.timeout.connect(self._save_caches)
        self.save_timer.start(15000)
        self.loader.files_checked.connect(self._on_file_checked)

    # --- UI -------------------------------------------------------------
    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Cabecera: pestañas, buscador, acciones
        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        # tres columnas iguales: pestañas a la izquierda, buscador en el centro del ancho, botones a la derecha
        top = QtWidgets.QGridLayout(header)
        top.setContentsMargins(16, 10, 12, 10)
        top.setHorizontalSpacing(12)
        self.tabbar = QtWidgets.QTabBar()
        self.tabbar.setObjectName("LibTabs")
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.setCursor(QtCore.Qt.PointingHandCursor)
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        top.addWidget(self.tabbar, 0, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Buscar en la biblioteca…")
        self.search.setClearButtonEnabled(True)
        self.search_action = self.search.addAction(icon("search"), QtWidgets.QLineEdit.LeadingPosition)
        self.search.setMinimumWidth(300)
        self.search.setMaximumWidth(520)
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self._on_search)
        self.search.textChanged.connect(lambda _: self.search_timer.start())
        top.addWidget(self.search, 0, 1, QtCore.Qt.AlignCenter)
        right = QtWidgets.QHBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        self.b_ref = _tool("refresh", "", "Buscar cambios en las carpetas")
        self.b_ref.setPopupMode(QtWidgets.QToolButton.DelayedPopup)
        mref = QtWidgets.QMenu(self.b_ref)
        mref.addAction("Buscar cambios (rápido)", lambda: self._scan_current(incremental=True))
        mref.addAction("Leer todo de nuevo", lambda: self._scan_current(incremental=False))
        self.b_ref.setMenu(mref)
        self.b_ref.clicked.connect(lambda: self._scan_current(incremental=True))
        self.b_ref.setToolTip("Buscar cambios en las carpetas (mantén pulsado para leer todo de nuevo)")
        right.addWidget(self.b_ref)
        self.b_theme = _tool("moon" if theme.is_light() else "sun", "",
                             "Cambiar a modo oscuro" if theme.is_light() else "Cambiar a modo claro")
        self.b_theme.clicked.connect(self._toggle_theme)
        right.addWidget(self.b_theme)
        b_set = _tool("settings", "", "Ajustes")
        b_set.clicked.connect(lambda: self._open_settings(0))
        right.addWidget(b_set)
        top.addLayout(right, 0, 2)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)
        top.setColumnStretch(2, 1)
        lay.addWidget(header)

        # Cuerpo: barra lateral de carpetas + zona central
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setHandleWidth(1)
        side = QtWidgets.QFrame()
        side.setObjectName("Sidebar")
        side_lay = QtWidgets.QVBoxLayout(side)
        side.setMinimumWidth(190)
        side_lay.setContentsMargins(10, 14, 6, 10)
        side_lay.setSpacing(6)
        cap = QtWidgets.QLabel("CARPETAS")
        cap.setObjectName("Caption")
        cap.setContentsMargins(6, 0, 0, 0)
        side_lay.addWidget(cap)
        self.tree_model = QtGui.QStandardItemModel(self)
        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.tree_model)
        self.tree.setHeaderHidden(True)
        self.tree.setObjectName("Folders")
        self.tree.setIndentation(16)
        self.tree.clicked.connect(self._on_tree_clicked)
        self.tree.setIconSize(QtCore.QSize(16, 16))
        self.tree.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tree.selectionModel().currentChanged.connect(lambda *_: self._update_assets())
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        ui_fav.shift_collapse(self.tree)
        side_lay.addWidget(self.tree, 1)
        self.sub_cb = QtWidgets.QCheckBox("Incluir subcarpetas")
        self.sub_cb.setChecked(self.settings.data.get("include_subfolders", True))
        self.sub_cb.toggled.connect(self._on_sub_toggled)
        self.sub_cb.setContentsMargins(6, 0, 0, 0)
        side_lay.addWidget(self.sub_cb)
        split.addWidget(side)

        main = QtWidgets.QFrame()
        main.setObjectName("Main")
        main_lay = QtWidgets.QVBoxLayout(main)
        main_lay.setContentsMargins(18, 14, 12, 12)
        main_lay.setSpacing(10)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.folder_title = QtWidgets.QLabel("")
        self.folder_title.setObjectName("FolderTitle")
        bar.addWidget(self.folder_title)
        self.count_lbl = QtWidgets.QLabel("")
        self.count_lbl.setObjectName("Muted")
        self.count_lbl.setContentsMargins(4, 4, 0, 0)
        bar.addWidget(self.count_lbl)
        bar.addStretch(1)

        self.b_cat = _tool("catalog", "Catalogar", "Abrir una descarga (zip, rar, 7z… o una carpeta), repartir "
                                                   "sus archivos y guardarla en la biblioteca con su nombre",
                           "Accent")
        self.b_cat.setProperty("icon_name", None)
        self.b_cat.setIcon(icon("catalog", theme.ACCENT_TEXT))
        self.b_cat.clicked.connect(self._open_catalog)
        bar.addWidget(self.b_cat)

        b_prev = _tool("preview", "Preview", "Generar previews: del asset seleccionado con lo que tengas en Max, "
                                             "o de muchos a la vez en segundo plano", "Action")
        b_prev.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        m = QtWidgets.QMenu(b_prev)
        m.addAction("…")
        m.aboutToShow.connect(lambda m=m: self._fill_preview_menu(m))
        b_prev.setMenu(m)
        bar.addWidget(b_prev)

        b_rel = _tool("relink", "Re-enlazar", "Buscar y re-enlazar texturas y archivos perdidos: en la escena de "
                                              "Max, en los .max seleccionados o en todos los de la vista", "Action")
        b_rel.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        m2 = QtWidgets.QMenu(b_rel)
        m2.addAction("…")
        m2.aboutToShow.connect(lambda m2=m2: self._fill_relink_menu(m2))
        b_rel.setMenu(m2)
        bar.addWidget(b_rel)
        main_lay.addLayout(bar)

        # Filtros rápidos, orden y tipo de vista
        frow = QtWidgets.QHBoxLayout()
        frow.setSpacing(6)
        self.engine_group = QtWidgets.QButtonGroup(self)
        self.engine_group.setExclusive(True)
        cur_eng = self.settings.data.get("filter_engine", "all")
        for key, text, tip in (("all", "Todos", "Todos los motores"),
                               ("corona", "Corona", "Solo assets con versión Corona"),
                               ("vray", "V-Ray", "Solo assets con versión V-Ray"),
                               ("fstorm", "FStorm", "Solo assets con versión FStorm"),
                               ("scene", "Motor de la escena", "Solo los que tienen versión para el motor del "
                                                               "3ds Max conectado")):
            c = _chip(text, tip, key == cur_eng)
            c.setProperty("filter", key)
            self.engine_group.addButton(c)
            frow.addWidget(c)
        if self.engine_group.checkedButton() is None:
            self.engine_group.buttons()[0].setChecked(True)
        self.engine_group.buttonClicked.connect(self._on_filter_changed)
        sep1 = QtWidgets.QFrame()
        sep1.setFixedSize(1, 18)
        sep1.setObjectName("Sep")
        frow.addSpacing(4)
        frow.addWidget(sep1)
        frow.addSpacing(4)
        self.chip_warn = _chip("⚠ Con avisos", "Solo assets con texturas o archivos externos fuera de su ruta")
        self.chip_warn.toggled.connect(self._on_filter_changed)
        frow.addWidget(self.chip_warn)
        self.chip_noprev = _chip("Sin preview", "Solo assets que todavía no tienen imagen de preview")
        self.chip_noprev.toggled.connect(self._on_filter_changed)
        frow.addWidget(self.chip_noprev)
        frow.addStretch(1)
        self.sort_combo = QtWidgets.QComboBox()
        self.sort_combo.setObjectName("MaxChip")
        self.sort_combo.addItem("Nombre A–Z", "name")
        self.sort_combo.addItem("Más recientes", "recent")
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(self.settings.data.get("sort", "name"))))
        self.sort_combo.setToolTip("Orden de los assets")
        self.sort_combo.activated.connect(self._on_filter_changed)
        frow.addWidget(self.sort_combo)
        self.chip_names = _chip("Nombres", "Mostrar el nombre y el motor debajo de cada miniatura",
                                self.settings.data.get("view_mode", "gallery") == "cards")
        self.chip_names.toggled.connect(self._on_view_mode)
        frow.addWidget(self.chip_names)
        main_lay.addLayout(frow)

        self.model = AssetModel(self.loader, self.engine_cache, self.check_cache, self)
        self.view = AssetView(self)
        self.view.setModel(self.model)
        self.delegate = AssetDelegate(self.view, self.loader, self.engine_cache, self.check_cache,
                                      lambda: self._scene_engine)
        self.delegate.cards = self.chip_names.isChecked()
        self.view.setItemDelegate(self.delegate)
        self.view.dropped_outside.connect(self._on_dropped)
        self.view.doubleClicked.connect(lambda idx: self._quick_look())
        self.view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._asset_menu)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._update_info())
        self.empty = QtWidgets.QLabel("")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(QtCore.Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.empty)
        main_lay.addWidget(self.stack, 1)

        split.addWidget(main)
        self.info = Inspector()
        self.info.setVisible(bool(self.settings.data.get("show_info_bar", True)))
        self.info.open_requested.connect(self._open_selected)
        self.info.place_requested.connect(lambda: self._merge_selected(False, True))
        self.info.proxy_requested.connect(lambda: self._merge_selected(True, True))
        self.info.original_requested.connect(lambda: self._merge_selected(False, False))
        self.info.reveal_requested.connect(self._reveal_selected)
        self.info.zoom_requested.connect(self._quick_look)
        self.info.missing_requested.connect(self._open_missing)
        self.info.stats_requested.connect(lambda: self._read_stats(self._selected_assets()))
        split.addWidget(self.info)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([220, 760, 300])
        split.setCollapsible(1, False)
        self.quick = None
        # Materiales y texturas tienen su propio cuerpo; la cabecera y la barra de estado son comunes
        self.models_body = split
        self.surf = SurfacePanel(self)
        self.body = QtWidgets.QStackedWidget()
        self.body.addWidget(split)
        self.body.addWidget(self.surf)
        lay.addWidget(self.body, 1)

        # Barra de estado: mensaje, tamaño, conexión con Max
        sb = QtWidgets.QFrame()
        sb.setObjectName("StatusBar")
        bottom = QtWidgets.QHBoxLayout(sb)
        bottom.setContentsMargins(14, 4, 10, 4)
        bottom.setSpacing(6)
        ver = QtWidgets.QLabel("v" + config.VERSION)
        ver.setObjectName("AppVersion")
        ver.setToolTip("OpenLibrary " + config.VERSION)
        bottom.addWidget(ver)
        bottom.addSpacing(8)
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("Status")
        bottom.addWidget(self.status, 1)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(120)
        self.progress.setVisible(False)
        bottom.addWidget(self.progress)
        self.b_cancel = QtWidgets.QToolButton()
        self.b_cancel.setText("Cancelar")
        self.b_cancel.setToolTip("Parar el lote de previews")
        self.b_cancel.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_cancel.clicked.connect(self._batch_cancel)
        self.b_cancel.setVisible(False)
        bottom.addWidget(self.b_cancel)
        bottom.addSpacing(8)
        self.size_ic = QtWidgets.QLabel()
        self.size_ic.setPixmap(icon("preview").pixmap(14, 14))
        self.size_ic.setToolTip("Tamaño de miniatura")
        bottom.addWidget(self.size_ic)
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size_slider.setRange(96, 400)
        self.size_slider.setFixedWidth(110)
        self.size_slider.setToolTip("Tamaño de miniatura")
        self.size_slider.setValue(int(self.settings.data.get("thumb_size", 160)))
        self.size_slider.valueChanged.connect(self._on_thumb_size)
        bottom.addWidget(self.size_slider)
        bottom.addSpacing(10)
        sep = QtWidgets.QFrame()
        sep.setFixedSize(1, 18)
        sep.setObjectName("Sep")
        bottom.addWidget(sep)
        bottom.addSpacing(6)
        self.max_dot = QtWidgets.QLabel()
        self.max_dot.setFixedWidth(12)
        bottom.addWidget(self.max_dot)
        self.max_chip = QtWidgets.QLabel()          # el Max que manda (se elige solo, sin lista)
        self.max_chip.setObjectName("MaxChip")
        self.max_chip.setMinimumWidth(0)
        self.max_chip.setMaximumWidth(340)
        self.max_chip.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        bottom.addWidget(self.max_chip)
        self.b_pin = _tool("pin", "", "Mantener OpenLibrary siempre encima (cómodo para arrastrar a Max)")
        self.b_pin.setCheckable(True)
        self.b_pin.setChecked(bool(self.settings.data.get("always_on_top", False)))
        self.b_pin.toggled.connect(self._toggle_pin)
        self.b_pin.setIconSize(QtCore.QSize(16, 16))
        bottom.addWidget(self.b_pin)
        self.b_info = _tool("info", "", "Mostrar u ocultar la ficha del asset (panel derecho)")
        self.b_info.setCheckable(True)
        self.b_info.setChecked(self.info.isVisible())
        self.b_info.toggled.connect(self._toggle_info)
        self.b_info.setIconSize(QtCore.QSize(16, 16))
        bottom.addWidget(self.b_info)
        lay.addWidget(sb)
        self._on_thumb_size(self.size_slider.value(), save=False)

    # --- Pestañas -------------------------------------------------------
    def refresh_shared(self):
        """Trae los cambios del espacio de trabajo compartido (si los hay) y repinta lo que toque."""
        try:
            changed = self.settings.refresh_shared()
        except Exception:                       # el NAS puede fallar a medias: no molestamos
            return
        if not changed:
            self._ws_notice()
            return
        if set(changed) & {"libraries", "hidden_folders", "preview"}:
            self._reload_tabs()                 # cambian las pestañas o lo que se ve: se rehacen
        else:
            # medidas, mapeado o iconos de carpeta: se repinta sin perder la carpeta ni la selección
            if "folder_marks" in changed and self.index is not None and not self._in_surfaces():
                self._build_tree(self._current_folder())
            self.view.viewport().update()
            self.surf.view.viewport().update()
        self.status.setText("Actualizado con los cambios del espacio de trabajo compartido.")

    def _ws_poll(self):
        if self.settings.ws_state == "ok" and self.isVisible():   # sin conexión se reintenta al volver a la app
            self.refresh_shared()

    def _ws_notice(self):
        if self.settings.ws_state == "offline":
            self.status.setText("Sin conexión con el espacio de trabajo compartido (%s): se usa la última "
                                "copia de este equipo." % self.settings.workspace)

    def _reload_tabs(self):
        self.tabbar.blockSignals(True)
        while self.tabbar.count():
            self.tabbar.removeTab(0)
        for lib in self.settings.libraries:
            self.tabbar.addTab(lib["name"])
        idx = self.settings.data.get("current_library", 0)
        if self.settings.libraries:
            self.tabbar.setCurrentIndex(max(0, min(idx, len(self.settings.libraries) - 1)))
        self.tabbar.blockSignals(False)
        self._show_tab(self.tabbar.currentIndex(), force=True)

    def _on_tab_changed(self, i):
        self.settings.data["current_library"] = i
        self._tab_save.start()           # se guarda un poco después, no en cada cambio de pestaña
        self._show_tab(i)

    def _current_lib(self):
        i = self.tabbar.currentIndex()
        libs = self.settings.libraries
        return libs[i] if 0 <= i < len(libs) else None

    def _clear_browser(self, msg):
        self.index = None
        self.cache_file = None
        self.tree_model.clear()
        self.model.set_assets([])
        self.status.setText("")
        lib = self._current_lib()
        self.folder_title.setText(lib["name"] if lib else "")
        self.count_lbl.setText("")
        self._show_empty(msg)
        self.info.clear()

    def _show_empty(self, msg):
        if msg:
            self.empty.setText("<div style='font-size:12pt'>%s</div>" % _esc(msg))
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.view)

    def _show_tab(self, i, force=False):
        """force: volver a montar el árbol y la galería aunque la pestaña sea la misma de antes (al cambiar
        los ajustes). Al ir y volver entre pestañas, lo que ya estaba montado se queda tal cual."""
        lib = self._current_lib()
        if lib is None:
            self._clear_browser("No hay pestañas. Créalas en Ajustes > Libraries.")
            return
        if lib.get("kind", "models") != "models":
            # el árbol y la galería de modelos se quedan montados (ocultos) para cuando se vuelva
            self.status.setText("")
            self.info.clear()
            self.body.setCurrentWidget(self.surf)
            self.search.setPlaceholderText("Buscar %s…" % lib["name"].lower())
            self.surf.show_library(lib, self.search.text().strip())
            self.surf.set_thumb(self.size_slider.value())
            return
        self.body.setCurrentWidget(self.models_body)
        self.search.setPlaceholderText("Buscar en la biblioteca…")
        paths = [p for p in lib.get("paths", []) if p]
        if not paths:
            self._clear_browser("«%s» no tiene carpetas. Añádelas en Ajustes > Libraries." % lib["name"])
            return
        cache_file = library.cache_path_for(self.cache_dir, paths)
        idx = self.indexes.get(cache_file)
        if idx is None:
            idx = library.LibraryIndex(paths)
            idx.load(cache_file)           # instantáneo si ya se leyó otra vez
            self.indexes[cache_file] = idx
        same = (not force and idx is self.index and cache_file == self.cache_file
                and self._models_text == self.search.text().strip() and self.tree_model.rowCount() > 0)
        self.index = idx
        self.cache_file = cache_file
        if same:                            # se vuelve a la misma pestaña: ya está montada
            self._show_empty("")
            self._update_info()
        else:
            self._build_tree(fav=ui_fav.open_on_fav(lib))
            self._update_assets()
        offline = [p for p in paths if not os.path.isdir(p)]
        if offline:
            self.status.setText("Sin acceso a: %s (se muestra lo último leído)" % ", ".join(offline))
        if cache_file not in self.scanned:
            self._scan_current(incremental=True)

    @property
    def scan_thread(self):
        """La lectura en marcha de la pestaña que se ve (las de las otras siguen solas en segundo plano)."""
        return self.scans.get(self.cache_file)

    @scan_thread.setter
    def scan_thread(self, th):
        if th is not None:
            self.scans[self.cache_file] = th

    def _in_surfaces(self):
        return self.body.currentWidget() is self.surf

    def _on_search(self):
        if self._in_surfaces():
            self.surf.set_search(self.search.text().strip())
        else:
            self._update_assets()

    def _scan_current(self, incremental=True):
        if self._in_surfaces():
            self.surf.rescan(incremental)
            return
        if self.index is None:
            self._show_tab(self.tabbar.currentIndex())
            return
        if self.scan_thread is not None and self.scan_thread.isRunning():
            return                       # ya se está leyendo esta pestaña
        first = not self.index.records
        self.status.setText("Leyendo la biblioteca por primera vez..." if first else "Buscando cambios...")
        self.scan_thread = ScanThread(self.index, self.cache_file, incremental, self)
        th = self.scan_thread
        self.scan_thread.progress.connect(        # en otra pestaña no se dice: no es lo que se está viendo
            lambda f, a: None if self._in_surfaces() or self.scan_thread is not th else
            self.status.setText("Buscando cambios en modelos... %d carpetas, %d assets" % (f, a)))
        self.scan_thread.done.connect(self._on_scanned)
        self.scan_thread.start()
        if first:
            self._show_empty("Leyendo la biblioteca por primera vez…\nLas próximas veces solo se buscan cambios.")

    def _on_scanned(self, index, cache_file):
        if index.cancelled:
            return
        self.scanned.add(cache_file)
        if index is not self.index:
            return
        listed, reused = index.stats["listed"], index.stats["reused"]
        self._build_tree(self._current_folder())
        self._update_assets()
        if not self._in_surfaces():
            self.status.setText("%d assets · %d carpetas revisadas, %d con cambios" % (
            len(index.assets), listed + reused, listed))

    def _expanded_folders(self):
        out = set()

        def walk(parent):
            for r in range(self.tree_model.rowCount(parent)):
                i = self.tree_model.index(r, 0, parent)
                if self.tree.isExpanded(i):
                    path = i.data(ROLE_PATH)
                    if path:
                        out.add(os.path.normcase(path))
                    walk(i)
        walk(QtCore.QModelIndex())
        return out

    def _folder_icon(self, folder, default):
        mark = self.settings.data.get("folder_marks", {}).get(foldericons.mark_key(folder), {})
        if default == "drive" and not mark:
            return icon("drive")
        name = mark.get("icon") or ("folder" if default == "drive" else default)
        return foldericons.make_icon(name, mark.get("color"))

    def _build_tree(self, select_path=None, fav=None):
        """fav: abrir «Favoritos» (None = seguir en él si era lo abierto)."""
        if fav is None:
            fav = self._current_is_fav() and not select_path
        self.fav_item = None
        had_tree = self.tree_model.rowCount() > 0
        opened = self._expanded_folders()
        self.tree_model.clear()
        idx = self.index
        if idx is None:
            return
        h = self.settings.hidden
        self.hidden = library.hidden_folders(idx.folders, idx.roots, h["names"], h["paths"])
        counts = {k: len(v) for k, v in idx.by_folder.items() if k not in self.hidden}
        totals = {}
        roots_nc = [os.path.normcase(r) for r in idx.roots]
        for key, n in counts.items():
            k = key
            while True:
                totals[k] = totals.get(k, 0) + n
                if k in roots_nc:
                    break
                parent = os.path.dirname(k)
                if parent == k:
                    break
                k = parent
        items = {}
        show_fav, show_all = ui_fav.tree_nodes(self._current_lib())
        if show_fav:
            self.fav_item = QtGui.QStandardItem("")
            self.fav_item.setData(None, ROLE_PATH)
            self.fav_item.setData(True, ROLE_FAV)
            self.fav_item.setIcon(ui_fav.heart_icon())
            self.fav_item.setToolTip("Los marcados con el corazón (cada persona tiene los suyos)")
            self.tree_model.appendRow(self.fav_item)
            self._fav_label()
        all_it = None
        if show_all:
            all_it = QtGui.QStandardItem("Todos  (%d)" % sum(counts.values()))
            all_it.setData(None, ROLE_PATH)
            all_it.setIcon(icon())
            self.tree_model.appendRow(all_it)
        for root in idx.roots:
            key = os.path.normcase(root)
            label = os.path.basename(root.rstrip("\\/")) or root
            it = QtGui.QStandardItem("%s  (%d)" % (label, totals.get(key, 0)))
            it.setData(root, ROLE_PATH)
            it.setToolTip(root)
            it.setIcon(self._folder_icon(root, "drive"))
            self.tree_model.appendRow(it)
            items[key] = it
        for folder in idx.folders:
            key = os.path.normcase(folder)
            if key in items or key in self.hidden:
                continue
            parent = items.get(os.path.normcase(os.path.dirname(folder)))
            if parent is None:
                continue
            n = totals.get(key, 0)
            it = QtGui.QStandardItem(os.path.basename(folder) + ("  (%d)" % n if n else ""))
            it.setData(folder, ROLE_PATH)
            it.setIcon(self._folder_icon(folder, foldericons.guess(os.path.basename(folder))))
            if not n:
                it.setForeground(QtGui.QBrush(theme.color(theme.FAINT)))
            parent.appendRow(it)
            items[key] = it
        for root in idx.roots:
            it = items.get(os.path.normcase(root))
            if it is not None and (not had_tree or os.path.normcase(root) in opened):
                self.tree.expand(it.index())
        for key in opened:
            it = items.get(key)
            if it is not None:
                self.tree.expand(it.index())
        sel = items.get(os.path.normcase(select_path)) if select_path else None
        if fav and self.fav_item is not None:
            sel = self.fav_item
        sel = sel or all_it or (items.get(roots_nc[0]) if roots_nc else None) or self.fav_item
        self.tree.blockSignals(True)
        if sel is not None:
            self.tree.setCurrentIndex(sel.index())
        self.tree.blockSignals(False)

    def _on_tree_clicked(self, idx):
        """Un clic en una carpeta enseña sus subcarpetas (se pliega con la flecha)."""
        if idx.isValid() and self.tree_model.rowCount(idx) and not self.tree.isExpanded(idx):
            self.tree.expand(idx)

    def _current_folder(self):
        idx = self.tree.currentIndex()
        return idx.data(ROLE_PATH) if idx.isValid() else None

    def _current_is_fav(self):
        idx = self.tree.currentIndex()
        return bool(idx.isValid() and idx.data(ROLE_FAV))

    # --- favoritos (de cada persona) -----------------------------------------
    def fav_key(self, a):
        roots = tuple(self.index.roots) if self.index else ()
        k = (roots, a.key)
        hit = self._fav_keys.get(k)
        if hit is None:
            hit = self._fav_keys[k] = ui_fav.rel_key(roots, a.key, "|model")
        return hit

    def is_fav(self, a):
        favs = self.settings.data.get("favorites")
        if not favs:
            return False
        return bool(favs.get(self.fav_key(a)))

    def toggle_fav(self, assets):
        assets = [a for a in assets if a is not None]
        if not assets:
            return
        on = not all(self.is_fav(a) for a in assets)
        d = dict(self.settings.data.get("favorites", {}))
        for a in assets:
            if on:
                d[self.fav_key(a)] = 1
            else:
                d.pop(self.fav_key(a), None)
        self.settings.data["favorites"] = d
        self.settings.save()
        self._fav_label()
        self.view.viewport().update()
        self.status.setText(("Añadido a favoritos: %s" if on else "Quitado de favoritos: %s")
                            % ", ".join(a.name for a in assets[:3]) + ("…" if len(assets) > 3 else ""))

    def _fav_label(self):
        it = getattr(self, "fav_item", None)
        if it is None or self.index is None:
            return
        gone = set(id(a) for k in self.hidden for a in self.index.by_folder.get(k, ()))
        n = sum(1 for a in self.index.search("", None, True) if id(a) not in gone and self.is_fav(a))
        it.setText("Favoritos  (%d)" % n)

    def _update_assets(self):
        if self.index is None:
            return
        folder = self._current_folder()        # None = todas las carpetas de la pestaña
        favs = self._current_is_fav()
        text = self.search.text().strip()
        recursive = self.sub_cb.isChecked() or bool(text) or folder is None
        self._models_text = text
        found = self.index.search(text, folder, recursive)
        if favs:
            found = [a for a in found if self.is_fav(a)]
        if not found and not recursive:
            # carpeta que solo tiene subcarpetas: se ve lo que hay dentro en vez de un hueco
            found = self.index.search(text, folder, True)
        if self.hidden:
            gone = set(id(a) for k in self.hidden for a in self.index.by_folder.get(k, ()))
            found = [a for a in found if id(a) not in gone]
        assets = self._apply_filters(found)
        if not favs and ui_fav.show_mode(self._current_lib()) == "both":
            assets = sorted(assets, key=lambda a: not self.is_fav(a))   # estable: los favoritos primero
        self.model.set_assets(assets)
        self.view._pre.start()
        scanning = bool(self.scan_thread and self.scan_thread.isRunning())
        if not scanning and not self._in_surfaces():
            self.status.setText("")
        lib = self._current_lib()
        if text:
            title = "Resultados de «%s»" % text
        elif favs:
            title = "Favoritos"
        elif folder:
            title = os.path.basename(folder.rstrip("\\/")) or folder
        else:
            title = lib["name"] if lib else ""
        self.folder_title.setText(title)
        self.count_lbl.setText("%d asset%s" % (len(assets), "" if len(assets) == 1 else "s"))
        if assets:
            self._show_empty("")
        elif scanning and not self.index.records:
            self._show_empty("Leyendo la biblioteca por primera vez…")
        elif text:
            self._show_empty("Nada coincide con «%s»." % text)
        elif favs:
            self._show_empty("Aún no hay favoritos.\nPulsa el corazón de un modelo para marcarlo; aparecerá aquí.")
        elif self._filters_active():
            self._show_empty("Ningún asset de esta carpeta pasa los filtros.")
        else:
            self._show_empty("No hay assets en esta carpeta.")
        self._update_info()

    def _filters_active(self):
        b = self.engine_group.checkedButton()
        return (b is not None and b.property("filter") != "all") or self.chip_warn.isChecked() \
            or self.chip_noprev.isChecked()

    def _apply_filters(self, assets):
        b = self.engine_group.checkedButton()
        eng = b.property("filter") if b is not None else "all"
        if eng == "scene":
            eng = self._scene_engine if self._scene_engine in KNOWN_ENGINES else "all"
        if eng != "all":
            assets = [a for a in assets if eng in a.engines(self.engine_cache)]
        if self.chip_noprev.isChecked():
            assets = [a for a in assets if not a.preview]
        if self.chip_warn.isChecked():
            out = []
            for a in assets:
                known, total, missing, relinkable = asset_file_status(a, self.check_cache)
                if missing or relinkable:
                    out.append(a)
            assets = out
        if self.sort_combo.currentData() == "recent":
            assets = sorted(assets, key=lambda a: -a.mtime)
        return assets

    def _on_filter_changed(self, *_):
        b = self.engine_group.checkedButton()
        self.settings.data["filter_engine"] = b.property("filter") if b is not None else "all"
        self.settings.data["sort"] = self.sort_combo.currentData()
        self.settings.save()
        self._update_assets()

    def _on_view_mode(self, cards):
        self.delegate.cards = bool(cards)
        self.settings.data["view_mode"] = "cards" if cards else "gallery"
        self.settings.save()
        self._fit_grid(force=True)
        self.view.viewport().update()

    # --- Acciones del inspector y vista rápida ----------------------------------------
    def _merge_selected(self, proxy, place):
        sel = self._selected_assets()
        if sel:
            self._merge_many(sel, proxy, place)

    def _open_selected(self):
        """Abre en 3ds Max el .max del asset seleccionado, para editarlo."""
        sel = self._selected_assets()
        if len(sel) != 1:
            return
        a = sel[0]
        files = a.all_files()
        if not files:
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No hay archivo .max para este asset.")
            return
        path = files[0]
        if len(files) > 1:
            path = a.file_for_engine(self._scene_engine, self.engine_cache) if self.target else None
            if not path:
                labels = [os.path.basename(f) for f in files]
                item, ok = QtWidgets.QInputDialog.getItem(self, "OpenLibrary", "¿Qué versión quieres abrir?",
                                                          labels, 0, False)
                if not ok:
                    return
                path = files[labels.index(item)]
        self._open_file(path)

    # --- Modo claro / oscuro -------------------------------------------------------
    def _toggle_theme(self):
        mode = "dark" if theme.is_light() else "light"
        self.settings.data["theme"] = mode
        self.settings.save()
        theme.set_mode(mode)
        theme.apply(QtWidgets.QApplication.instance())
        self._retheme()

    def _retheme(self):
        light = theme.is_light()
        self.b_theme.setProperty("icon_name", "moon" if light else "sun")
        self.b_theme.setToolTip("Cambiar a modo oscuro" if light else "Cambiar a modo claro")
        for b in self.findChildren(QtWidgets.QToolButton):
            name = b.property("icon_name")
            if name:
                b.setIcon(icon(name))
        self.search_action.setIcon(icon("search"))
        self.b_cat.setIcon(icon("catalog", theme.ACCENT_TEXT))
        self.size_ic.setPixmap(icon("preview").pixmap(14, 14))
        self.delegate.refresh_colors()
        self.surf.refresh_colors()
        if self._in_surfaces():
            self.surf.build_tree(self.surf.current_folder())
        if self.index is not None:
            self._build_tree(self._current_folder())
        self._refresh_max_combo()
        self.info.retheme()
        self._update_info()
        self.view.viewport().update()
        for w in QtWidgets.QApplication.topLevelWidgets():
            if w.isWindow() and w.isVisible():
                theme.title_bar(w)

    # --- Menús de Preview y Re-enlazar ----------------------------------------------
    def _fill_preview_menu(self, m):
        m.clear()
        sel = self._selected_assets()
        one = len(sel) == 1
        who = "«%s»" % _short(sel[0].name).replace("&", "&&") if one else "un asset (selecciona uno)"
        a1 = m.addAction(icon("preview"), "De %s, con lo seleccionado en 3ds Max" % who,
                         lambda: self._make_preview(False))
        a2 = m.addAction(icon("preview"), "De %s, desde mi vista de 3ds Max" % who,
                         lambda: self._make_preview(True))
        a1.setEnabled(one)
        a2.setEnabled(one)
        m.addSeparator()
        with_file = [a for a in sel if a.all_files()]
        a3 = m.addAction("De los seleccionados (%d), en segundo plano…" % len(with_file),
                         lambda: self._batch_previews(with_file))
        a3.setEnabled(bool(with_file))
        missing = [a for a in self.model.assets if not a.preview and a.all_files()]
        a4 = m.addAction("De todos los que no tienen preview aquí (%d), en segundo plano…" % len(missing),
                         lambda: self._batch_previews(missing))
        a4.setEnabled(bool(missing))

    def _fill_relink_menu(self, m):
        m.clear()
        sel = self._selected_assets()
        m.addAction(icon("relink"), "La escena abierta en 3ds Max", lambda: self._relink_scene())
        m.addSeparator()
        n = sum(len(a.all_files()) for a in sel)
        a1 = m.addAction("Dentro del .max seleccionado" if n == 1 else
                         "Dentro de los .max seleccionados (%d)" % n, lambda: self._relink_assets(sel))
        a1.setEnabled(n > 0)
        every = list(self.model.assets)
        total = sum(len(a.all_files()) for a in every)
        a2 = m.addAction("Dentro de todos los .max de esta vista (%d)…" % total,
                         lambda: self._relink_assets(every))
        a2.setEnabled(total > 0)

    # --- Previews en lote (3ds Max en segundo plano) --------------------------------
    def _batch_previews(self, assets):
        if self.batch is not None:
            QtWidgets.QMessageBox.information(self, "OpenLibrary", "Ya hay un lote de previews en marcha.")
            return
        exe = batchpreview.find_maxbatch()
        if not exe:
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No encuentro 3dsmaxbatch.exe (viene con 3ds Max).")
            return
        jobs = []
        replaced = 0
        for a in assets:
            f = a.versions.get("corona") or a.versions.get("vray") or a.versions.get("fstorm") or a.any_file()
            if not f:
                continue
            if a.preview and a.preview.lower().endswith((".jpg", ".jpeg", ".png")):
                out = a.preview
                replaced += 1
            else:
                out = a.default_preview_path()
            jobs.append((a.key, f, out))
        if not jobs:
            return
        text = ("Se van a generar %d preview(s) con un 3ds Max en segundo plano: no toca la escena que tengas "
                "abierta y puedes seguir trabajando.\n\nCada imagen se guarda junto a su asset, en la biblioteca."
                % len(jobs))
        if replaced:
            text += "\n\nOJO: %d de ellos ya tienen preview y se sustituirá por la nueva." % replaced
        if QtWidgets.QMessageBox.question(self, "OpenLibrary", text + "\n\n¿Empezar?") != QtWidgets.QMessageBox.Yes:
            return
        try:
            script, log = batchpreview.prepare(os.path.join(config.app_data_dir(), "batch"),
                                               [(f, out) for _, f, out in jobs], dict(self.settings.preview))
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "OpenLibrary", str(exc))
            return
        proc = QtCore.QProcess(self)
        proc.setProgram(exe)
        proc.setArguments([script])
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyRead.connect(proc.readAll)            # se descarta: solo interesa el registro
        proc.finished.connect(lambda *_: self._batch_finished())
        proc.errorOccurred.connect(self._batch_error)
        self.batch = {"proc": proc, "log": log, "jobs": jobs, "index": self.index, "cache_file": self.cache_file,
                      "cancelled": False}
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.b_cancel.setVisible(True)
        self.status.setText("Previews en segundo plano: arrancando 3ds Max…")
        self.batch_timer.start(1000)
        proc.start()

    def _batch_tick(self):
        if self.batch is None:
            return
        ok, fail = batchpreview.read_log(self.batch["log"])
        total = len(self.batch["jobs"])
        self.progress.setValue(ok + fail)
        if ok + fail:
            self.status.setText("Previews en segundo plano: %d de %d…" % (ok + fail, total))

    def _batch_cancel(self):
        if self.batch is not None:
            self.batch["cancelled"] = True
            batchpreview.kill_tree(self.batch["proc"])

    def _batch_error(self, err):
        if err == QtCore.QProcess.FailedToStart:
            self._batch_finished("No se pudo arrancar 3dsmaxbatch.exe.")

    def _batch_finished(self, error=None):
        b = self.batch
        if b is None:
            return
        self.batch = None
        self.batch_timer.stop()
        self.b_cancel.setVisible(False)
        self.progress.setVisible(self._busy > 0)
        self.progress.setRange(0, 0)
        ok, fail = batchpreview.read_log(b["log"])
        from . import modelstats
        files = [f for _k, f, _o in b["jobs"]]
        for f, st in modelstats.read_log(b["log"], files).items():
            self.stats.put(f, st)
        self.stats.save()
        folders = set()
        for key, _f, out in b["jobs"]:
            if os.path.isfile(out):
                self.loader.invalidate(key)
                self.info.big.forget(out)
                folders.add(os.path.dirname(out))
        idx = b["index"]
        if idx is not None and folders:
            for d in folders:
                idx.rescan_folder(d)
            idx.save(b["cache_file"])
            if idx is self.index:
                self._update_assets()
        left = len(b["jobs"]) - ok - fail
        msg = "Previews: %d hechas" % ok
        if fail:
            msg += ", %d no se pudieron generar" % fail
        if b["cancelled"]:
            msg += " (cancelado, quedaban %d)" % left
        elif error:
            msg += ". " + error
        elif left:
            msg += ". 3ds Max se cerró antes de acabar: quedaron %d sin hacer" % left
        self.status.setText(msg)
        b["proc"].deleteLater()

    def _reveal_selected(self):
        sel = self._selected_assets()
        if sel:
            files = sel[0].all_files()
            self._reveal(files[0] if files else sel[0].folder)

    def _quick_look(self):
        idx = self.view.currentIndex()
        a = idx.data(ROLE_ASSET) if idx.isValid() else None
        if a is None:
            return
        if self.quick is None:
            self.quick = QuickLook(self)
            self.quick.step.connect(self._quick_step)
        self.quick.show_asset(a, self.loader.images.get(a.key))
        self.quick.exec()

    def _quick_step(self, delta):
        row = self.view.currentIndex().row() + delta
        if 0 <= row < self.model.rowCount():
            idx = self.model.index(row)
            self.view.setCurrentIndex(idx)
            self.view.scrollTo(idx)
            a = idx.data(ROLE_ASSET)
            self.quick.show_asset(a, self.loader.images.get(a.key))

    def _on_sub_toggled(self, v):
        self.settings.data["include_subfolders"] = bool(v)
        self.settings.save()
        self._update_assets()

    def _on_thumb_size(self, v, save=True):
        self.delegate.thumb = v
        self._fit_grid()
        if hasattr(self, "surf"):
            self.surf.set_thumb(v)
        if save:
            self.settings.data["thumb_size"] = v
            self.settings.save()

    def _fit_grid(self, force=False):
        """Reparte el ancho sobrante entre las columnas para que la cuadrícula llene la zona."""
        if not hasattr(self, "delegate"):
            return
        cell = self.delegate.cell_size(minimum=True)
        # Mismo ancho útil que usa QListView al repartir: el máximo menos la barra de desplazamiento nominal
        sb = self.view.verticalScrollBar()
        extent = self.view.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent, None, sb)
        w = self.view.maximumViewportSize().width() - max(extent, sb.sizeHint().width()) - 1
        cols = max(1, w // cell.width())
        # Las miniaturas crecen hasta llenar la fila (el deslizador marca el mínimo)
        self.delegate.fill = max(self.delegate.thumb, w // cols - 2 * self.delegate.margin)
        grid = self.delegate.cell_size()
        if force or grid != self.view.gridSize():
            self.view.setGridSize(grid)
            self.view.doItemsLayout()

    def _toggle_info(self, on):
        self.info.setVisible(on)
        self.surf.detail.setVisible(on)
        self.surf._on_selection()
        self.settings.data["show_info_bar"] = bool(on)
        self.settings.save()
        self._update_info()

    def _update_info(self):
        if not self.info.isVisible():
            return
        sel = self._selected_assets()
        if len(sel) != 1:
            self.info.clear("%d assets seleccionados." % len(sel) if sel else
                            "Selecciona un asset para ver su información.")
            return
        a = sel[0]
        f = a.file_for_engine(self._scene_engine, self.engine_cache) or a.any_file()
        eng = self._scene_engine
        ready = bool(f) and proxies.is_cached(f, a.name, eng, self.settings.imp)
        self.info.show_asset(a, self.loader.images.get(a.key), self.engine_cache, self.check_cache,
                             self._scene_engine, ready, asset_file_status(a, self.check_cache),
                             stats=self.stats.get,
                             reading=self.stats_runner.running() and any(
                                 self.stats.get(f) is None for f in a.all_files()))

    def _on_file_checked(self, path):
        sel = self._selected_assets()
        if len(sel) == 1 and path in sel[0].all_files():
            self._update_info()

    # --- 3ds Max -------------------------------------------------------
    @property
    def target(self):
        for m in self.maxes:
            if m.pid == self.target_pid:
                return m
        return self.maxes[0] if self.maxes else None

    @property
    def _scene_engine(self):
        t = self.target
        return t.engine if t else "other"

    def _discover(self):
        if self._discovering:
            return
        self._discovering = True
        self.max_pool.start(_DiscoverTask(self.discover_signals))

    def _on_maxes(self, found):
        self._discovering = False
        old_engine = self._scene_engine
        old = [(m.pid, m.label, m.engine) for m in self.maxes]
        self.maxes = sorted(found, key=lambda m: m.port)
        if len(self.maxes) > 1:
            self.target_pid = maxlink.front_pid([m.pid for m in self.maxes]) or self.target_pid
        changed = False
        if self.target and self.target.pid != self.target_pid:
            self.target_pid = self.target.pid
            changed = True                              # para refrescar el indicador
        if changed or [(m.pid, m.label, m.engine) for m in self.maxes] != old:
            self._refresh_max_combo()
            old_pids = {pid for pid, _l, _e in old}
            stale = [m for m in self.maxes if m.protocol < maxlink.PROTOCOL and m.pid not in old_pids]
            if stale:
                self.status.setText("%s tiene un puente anterior a esta versión de la app: actualízalo en "
                                    "Ajustes > Instalación y reinicia 3ds Max." % stale[0].label)
        t = self.target
        self.info.set_connected(t.engine if t else None)
        if self._scene_engine != old_engine:
            b = self.engine_group.checkedButton()
            if b is not None and b.property("filter") == "scene":
                self._update_assets()
            self.view.viewport().update()
            self._update_info()

    def _refresh_max_combo(self):
        """Indicador del 3ds Max al que van los assets (sin lista: manda el de encima o el del ratón)."""
        if not self.maxes:
            text, tip = "3ds Max sin conectar", "Sin conexión. Instala el puente en Ajustes > Instalación."
            self.max_dot.setText("<span style='color:%s'>●</span>" % theme.FAINT)
            self.max_dot.setToolTip(tip)
        else:
            t = self.target
            text = "%s · %s" % (t.label, ENGINE_LABEL.get(t.engine, t.engine))
            tip = ("Los assets van al 3ds Max que está por encima (o al que tiene el ratón).\n"
                   "Al arrastrar, al Max sobre el que sueltas.")
            if len(self.maxes) > 1:
                tip += "\n\nAbiertos:\n" + "\n".join("· " + m.label for m in self.maxes)
            self.max_dot.setText("<span style='color:%s'>●</span>" % theme.OK)
            self.max_dot.setToolTip("Conectado")
        fm = self.max_chip.fontMetrics()
        self.max_chip.setText(fm.elidedText(text, QtCore.Qt.ElideMiddle, self.max_chip.maximumWidth() - 12))
        self.max_chip.setToolTip(text + "\n\n" + tip)

    def _follow_front_max(self):
        """Cada poco: si hay varios Max, manda el que está por encima o el que tiene el ratón."""
        if len(self.maxes) < 2:
            return
        pid = maxlink.front_pid([m.pid for m in self.maxes])
        if pid and pid != self.target_pid:
            old_engine = self._scene_engine
            self.target_pid = pid
            self._refresh_max_combo()
            t = self.target
            self.info.set_connected(t.engine if t else None)
            if self._scene_engine != old_engine:
                b = self.engine_group.checkedButton()
                if b is not None and b.property("filter") == "scene":
                    self._update_assets()
                self.view.viewport().update()
                self._update_info()

    def _toggle_pin(self, on):
        self.settings.data["always_on_top"] = bool(on)
        self.settings.save()
        self.pin_toggled.emit(bool(on))

    def _need_max(self, inst=None):
        inst = inst or self.target
        if inst is None:
            QtWidgets.QMessageBox.information(
                self, "OpenLibrary",
                "No hay ningún 3ds Max conectado.\n\nAbre 3ds Max con el puente instalado "
                "(Ajustes > Instalación) y vuelve a intentarlo.")
        return inst

    def _run_in_max(self, inst, label, fn, done=None):
        """Ejecuta fn() (que llama al puente) en segundo plano; done(result, error) al acabar."""
        maxlink.allow_focus(inst.pid)
        self.status.setText("%s en %s..." % (label, inst.label))
        self._busy += 1
        if self.batch is None:
            self.progress.setRange(0, 0)
        self.progress.setVisible(True)

        def _finish(res, err):
            self._busy = max(0, self._busy - 1)
            if self.batch is None:
                self.progress.setVisible(self._busy > 0)
            if err is not None:
                self.status.setText("%s: error" % label)
                QtWidgets.QMessageBox.warning(self, "OpenLibrary", "%s:\n%s" % (label, err))
            elif done is None:
                self.status.setText("%s: hecho" % label)
            if done is not None:
                done(res, err)
            self._discover()
        self.max_pool.start(_MaxTask(fn, _finish, self.task_signals))

    def _open_settings(self, tab=0):
        dlg = SettingsDialog(self.settings, self, tab)
        if dlg.exec():
            self._reload_tabs()

    def _save_caches(self):
        self.engine_cache.save()
        self.check_cache.save()
        self.stats.save()

    # --- Caras, vértices, desplazamiento y animación (3dsmaxbatch en segundo plano) ----------------
    def _read_stats(self, assets):
        files = [f for a in assets for f in a.all_files()]
        if not files:
            return
        try:
            self.stats_runner.start(files)
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", str(exc))
            return
        self.status.setText("Leyendo caras, vértices y animación con un 3ds Max en segundo plano "
                            "(arrancarlo tarda un poco)…")
        self._update_info()

    def _stats_progress(self, done, total):
        self.status.setText("Leyendo datos de los modelos: %d de %d…" % (done, total))

    def _stats_done(self, ok, fail):
        msg = "Datos de los modelos: %d leídos" % ok
        if fail:
            msg += ", %d no se pudieron leer (archivos que 3ds Max no abre sin interfaz)" % fail
        self.status.setText(msg + ".")
        self._update_info()

    # --- Selección --------------------------------------------------------
    def _selected_assets(self):
        return [i.data(ROLE_ASSET) for i in self.view.selectionModel().selectedIndexes()]

    def _choose_file(self, asset):
        """Devuelve (ruta, motor) según el motor de la escena, o (None, None)."""
        eng = self._scene_engine
        f = asset.file_for_engine(eng, self.engine_cache)
        if f:
            return f, eng
        options = [(e, p) for e, p in asset.versions.items()]
        options += [(self.engine_cache.detect(p), p) for p in asset.auto_files]
        if not options:
            return None, None
        if self.settings.imp["missing_engine"] == "fallback":
            return options[0][1], options[0][0]
        labels = ["%s  -  %s" % (ENGINE_LABEL.get(e, e), os.path.basename(p)) for e, p in options]
        item, ok = QtWidgets.QInputDialog.getItem(
            self, "OpenLibrary",
            "La escena usa %s y \"%s\" no tiene esa versión.\n¿Cuál quieres usar?"
            % (ENGINE_LABEL.get(eng, eng), asset.name), labels, 0, False)
        if not ok:
            return None, None
        e, p = options[labels.index(item)]
        return p, e

    def _relink_dirs(self, asset):
        dirs = [asset.folder]
        roots = self.index.roots if self.index else []
        for root in roots:
            for sub in ("maps", "Maps", "textures", "Textures", "tex"):
                cand = os.path.join(root, sub)
                if os.path.isdir(cand):
                    dirs.append(cand)
        dirs.extend(self.settings.imp.get("relink_dirs", []))
        return dirs

    # --- Merge ----------------------------------------------------------
    def _on_dropped(self, assets, pid):
        inst = next((m for m in self.maxes if m.pid == pid), None)
        if inst is None:
            if not self.maxes:
                self.status.setText("Suelta el asset sobre un 3ds Max abierto con el puente instalado.")
            else:
                self.status.setText("Suelta el asset sobre la ventana de 3ds Max.")
            return
        self._drop_menu(assets, inst)

    def _drop_menu(self, assets, inst=None):
        """Merge and Place / Proxy / posición original, para uno o varios modelos."""
        if not isinstance(assets, (list, tuple)):
            assets = [assets]
        assets = [a for a in assets if a is not None]
        if not assets:
            return
        inst = inst or self._need_max()
        if inst is None:
            return
        menu = QtWidgets.QMenu(self)
        menu.addSection(assets[0].name if len(assets) == 1 else "%d modelos" % len(assets))
        a_place = menu.addAction("Merge and Place")
        a_proxy = menu.addAction("Merge as Proxy")
        menu.addSeparator()
        a_origin = menu.addAction("Merge en su posición original")
        if inst.engine not in ("corona", "vray"):
            a_proxy.setEnabled(False)
            a_proxy.setText("Merge as Proxy (necesita Corona o V-Ray)")
        chosen = menu.exec(QtGui.QCursor.pos())
        if chosen is a_place:
            self._merge_many(assets, proxy=False, place=True, inst=inst)
        elif chosen is a_proxy:
            self._merge_many(assets, proxy=True, place=True, inst=inst)
        elif chosen is a_origin:
            self._merge_many(assets, proxy=False, place=False, inst=inst)

    def _merge_many(self, assets, proxy, place, inst=None):
        """Uno detrás de otro (con «Place», se coloca cada uno con su clic en Max)."""
        queue = list(assets)
        total = len(queue)

        def nxt(_n=None, err=None):
            if err is not None or not queue:
                return
            a = queue.pop(0)
            k = total - len(queue)
            self._do_merge(a, proxy, place, inst, then=nxt, step="%d/%d" % (k, total) if total > 1 else "")
        nxt()

    def _do_merge(self, asset, proxy, place, inst=None, then=None, step=""):
        inst = self._need_max(inst)
        if inst is None:
            return
        if inst.busy:
            self.status.setText("3ds Max está ocupado con la orden anterior.")
            return
        prev_pid = self.target_pid
        self.target_pid = inst.pid
        path, eng = self._choose_file(asset)
        self.target_pid = prev_pid
        if not path:
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No hay archivo .max para este asset.")
            return
        imp = dict(self.settings.imp)
        relink = self._relink_dirs(asset) if imp.get("relink_on_import", True) else None
        if proxy:
            pdir, warn = proxies.choose_dir(path, asset.name, inst.engine, imp)
            if warn:
                QtWidgets.QMessageBox.information(self, "OpenLibrary", warn)
            fn = lambda: inst.call("merge_proxy", max_path=path, asset_name=asset.name, engine=inst.engine,
                                   imp=imp, proxy_dir=pdir, place=place, relink_dirs=relink)
        else:
            fn = lambda: inst.call("merge", max_path=path, asset_name=asset.name, imp=imp,
                                   place=place, relink_dirs=relink)
        pre = ("[%s] " % step) if step else ""
        if place:
            self.status.setText(pre + "%s · en 3ds Max: clic para colocar · rueda gira 90º · botón derecho o Esc termina"
                                % asset.name)

        def done(n, err):
            if err is None:
                self.status.setText(pre + "%s: %d objetos en %s (%s)" % (asset.name, n or 0, inst.label,
                                                                        ENGINE_LABEL.get(eng, eng)))
                self._update_info()
            if then is not None:
                then(n, err)
        self._run_in_max(inst, pre + "Importar %s" % asset.name, fn, done)

    # --- Menús contextuales ---------------------------------------------
    def _asset_menu(self, pos):
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        a = idx.data(ROLE_ASSET)
        menu = QtWidgets.QMenu(self)
        sel = [i.data(ROLE_ASSET) for i in self.view.selectionModel().selectedIndexes()] or [a]
        if a not in sel:
            sel = [a]
        all_fav = all(self.is_fav(s) for s in sel)
        fav_act = QtWidgets.QAction(ui_fav.heart_icon(), "Quitar de favoritos" if all_fav else "Añadir a favoritos", menu)
        fav_act.triggered.connect(lambda: self.toggle_fav(sel))
        menu.addAction(fav_act)
        menu.addSeparator()
        many = " (%d)" % len(sel) if len(sel) > 1 else ""
        menu.addAction("Merge and Place" + many, lambda: self._merge_many(sel, False, True))
        p = menu.addAction("Merge as Proxy" + many, lambda: self._merge_many(sel, True, True))
        p.setEnabled(self._scene_engine in ("corona", "vray"))
        for act in menu.actions():
            act.setEnabled(act.isEnabled() and self.target is not None)
        menu.addAction("Merge en su posición original" + many, lambda: self._merge_many(sel, False, False))
        menu.addSeparator()
        files = a.all_files()
        for text, rep in (("Abrir en un 3ds Max nuevo", False),
                          ("Abrir en el 3ds Max conectado (en lugar de su escena)", True)):
            if rep and self.target is None:
                continue
            if len(files) == 1:
                menu.addAction(text, lambda rep=rep: self._open_file(files[0], rep))
            else:
                sub = menu.addMenu(text)
                for f in files:
                    sub.addAction(os.path.basename(f), lambda f=f, rep=rep: self._open_file(f, rep))
        menu.addAction("Mostrar en el explorador", lambda: self._reveal(files[0] if files else a.folder))
        menu.addAction("Copiar ruta", lambda: QtWidgets.QApplication.clipboard().setText(files[0] if files else a.folder))
        menu.addSeparator()
        menu.addAction(icon("preview"), "Generar preview (encuadre automático)", lambda: self._make_preview(False, a))
        menu.addAction(icon("preview"), "Generar preview desde mi vista", lambda: self._make_preview(True, a))
        menu.addAction(icon("relink"), "Re-enlazar texturas dentro del .max", self._relink_assets)
        menu.addAction("Archivos que faltan…", lambda: self._open_missing(a))
        menu.addAction("Leer caras, vértices y animación" + many, lambda: self._read_stats(sel))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _tree_menu(self, pos):
        idx = self.tree.indexAt(pos)
        folder = idx.data(ROLE_PATH) if idx.isValid() else None
        menu = QtWidgets.QMenu(self)
        if folder:
            mark = self.settings.data.get("folder_marks", {}).get(foldericons.mark_key(folder), {})
            mc = menu.addMenu("Color")
            for label, col in foldericons.COLORS:
                act = mc.addAction(foldericons.swatch(col), label, lambda c=col: self._set_mark(folder, "color", c))
                act.setCheckable(True)
                act.setChecked(mark.get("color") == col)
            mc.addSeparator()
            mc.addAction("Sin color", lambda: self._set_mark(folder, "color", None))
            mi = menu.addMenu("Icono")
            auto = foldericons.guess(os.path.basename(folder.rstrip("\\/")))
            mi.addAction(foldericons.make_icon(auto, mark.get("color")),
                         "Automático (por el nombre)", lambda: self._set_mark(folder, "icon", None))
            mi.addSeparator()
            for name, (label, _body) in foldericons.ICONS.items():
                act = mi.addAction(foldericons.make_icon(name, mark.get("color")), label,
                                   lambda n=name: self._set_mark(folder, "icon", n))
                act.setCheckable(True)
                act.setChecked(mark.get("icon") == name)
            menu.addSeparator()
            menu.addAction("Mostrar en el explorador", lambda: self._reveal(folder))
            menu.addAction("Nueva carpeta...", lambda: self._new_folder(folder))
            if self.index is not None and os.path.normcase(os.path.normpath(folder)) not in \
                    [os.path.normcase(r) for r in self.index.roots]:
                base = os.path.basename(folder.rstrip("\\/"))
                menu.addSeparator()
                menu.addAction(icon("hide"), "Ocultar esta carpeta", lambda: self._hide_folder("paths", folder))
                menu.addAction(icon("hide"), "Ocultar todas las que se llamen «%s»" % base.replace("&", "&&"),
                               lambda: self._hide_folder("names", base))
        if idx.isValid() and self.tree_model.rowCount(idx):
            menu.addAction("Desplegar todo lo de dentro", lambda: self.tree.expandRecursively(idx))
        h = self.settings.hidden
        if h["names"] or h["paths"]:
            mh = menu.addMenu("Carpetas ocultas (%d)" % (len(h["names"]) + len(h["paths"])))
            mh.setToolTipsVisible(True)
            for name in h["names"]:
                mh.addAction("Volver a mostrar: todas las «%s»" % name.replace("&", "&&"),
                             lambda n=name: self._unhide_folder("names", n))
            for path in h["paths"]:
                act = mh.addAction("Volver a mostrar: %s" % os.path.basename(path.rstrip("\\/")).replace("&", "&&"),
                                   lambda p=path: self._unhide_folder("paths", p))
                act.setToolTip(path)
            mh.addSeparator()
            mh.addAction("Mostrar todas", lambda: self._unhide_folder(None, None))
        menu.addAction("Ocultar carpetas por nombre...", self._hide_by_name)
        menu.addSeparator()
        menu.addAction("Buscar cambios", lambda: self._scan_current(True))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _hide_folder(self, kind, value):
        lst = self.settings.hidden[kind]
        if value.lower() not in [v.lower() for v in lst]:
            lst.append(value)
        self.settings.save()
        cur = self._current_folder()
        self._build_tree(cur)                 # si la carpeta abierta era la oculta, se vuelve a «Todos»
        self._update_assets()

    def _unhide_folder(self, kind, value):
        h = self.settings.hidden
        if kind is None:
            h["names"], h["paths"] = [], []
        elif value in h[kind]:
            h[kind].remove(value)
        self.settings.save()
        self._build_tree(self._current_folder())
        self._update_assets()

    def _hide_by_name(self):
        h = self.settings.hidden
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Ocultar carpetas por nombre",
            "Nombres de carpeta que no se enseñan en el árbol, separados por comas.\n"
            "Vale en cualquier nivel y admite comodines: z-maps, maps, z-*",
            text=", ".join(h["names"]))
        if not ok:
            return
        names = []
        for n in text.split(","):
            n = n.strip()
            if n and n.lower() not in [x.lower() for x in names]:
                names.append(n)
        h["names"] = names
        self.settings.save()
        self._build_tree(self._current_folder())
        self._update_assets()

    def _set_mark(self, folder, what, value):
        marks = self.settings.data.setdefault("folder_marks", {})
        key = foldericons.mark_key(folder)
        mark = dict(marks.get(key, {}))
        if value:
            mark[what] = value
        else:
            mark.pop(what, None)
        if mark:
            marks[key] = mark
        else:
            marks.pop(key, None)
        self.settings.save()
        self._build_tree(self._current_folder())

    def _reveal(self, path):
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(path)

    def _open_file(self, path, replace=False):
        """Abre el .max en un 3ds Max NUEVO, sin tocar los que ya hay abiertos.
        replace=True: lo abre en el Max conectado, en lugar de su escena."""
        inst = self.target
        if not replace or inst is None:
            exe = batchpreview.find_max(inst.version if inst is not None else None)
            try:
                if exe:
                    subprocess.Popen([exe, path], cwd=os.path.dirname(exe))
                else:
                    os.startfile(path)      # lo que Windows tenga asociado a los .max
                self.status.setText("Abriendo %s en un 3ds Max nuevo (tarda lo que tarde Max en arrancar)…"
                                    % os.path.basename(path))
            except OSError as exc:
                QtWidgets.QMessageBox.critical(self, "OpenLibrary", str(exc))
            return
        if inst.busy:
            self.status.setText("3ds Max está ocupado con la orden anterior (¿colocando un asset? Esc lo termina).")
            return
        self.status.setText("Abriendo en 3ds Max (si hay cambios sin guardar, Max pregunta antes)…")
        self._run_in_max(inst, "Abrir %s" % os.path.basename(path), lambda: inst.call("open_file", max_path=path))

    def _new_folder(self, parent):
        name, ok = QtWidgets.QInputDialog.getText(self, "Nueva carpeta", "Nombre:")
        if ok and name.strip():
            try:
                os.makedirs(os.path.join(parent, name.strip()), exist_ok=True)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(self, "OpenLibrary", str(exc))
                return
            self._scan_current(True)

    # --- Preview --------------------------------------------------------
    def _make_preview(self, from_view, asset=None):
        inst = self._need_max()
        if inst is None:
            return
        assets = [asset] if asset else self._selected_assets()
        if len(assets) > 1:
            QtWidgets.QMessageBox.information(self, "OpenLibrary",
                                              "Selecciona un solo asset para generar su preview.")
            return
        if inst.busy:
            QtWidgets.QMessageBox.information(
                self, "OpenLibrary", "3ds Max está ocupado con la orden anterior (si estás colocando un asset, "
                                     "termina con Esc).")
            return
        if not from_view and inst.selection == 0:
            QtWidgets.QMessageBox.information(
                self, "OpenLibrary",
                "Selecciona en 3ds Max los objetos que deben salir en la preview y vuelve a pulsar.\n\n"
                "Si el asset no está en tu escena, usa «en segundo plano»: abre el .max por su cuenta.")
            return
        a = None
        if assets:
            a = assets[0]
            out = a.preview if a.preview and a.preview.lower().endswith((".jpg", ".jpeg", ".png")) \
                else a.default_preview_path()
        else:
            # Sin asset seleccionado: el archivo que tenga abierto ese Max
            if not inst.file:
                QtWidgets.QMessageBox.information(
                    self, "OpenLibrary",
                    "Selecciona un asset en OpenLibrary, o abre y guarda en 3ds Max el .max del asset.")
                return
            base, _ = library.split_engine_suffix(os.path.splitext(inst.file)[0])
            out = os.path.join(inst.folder, base + ".jpg")
        prev = dict(self.settings.preview)

        def done(ok, err):
            if err is not None:
                return
            if not ok:
                self.status.setText("No se pudo generar la preview (mira el MAXScript Listener).")
                return
            self.status.setText("Preview guardada: %s" % out)
            if a is not None:
                self.loader.invalidate(a.key)
            self._rescan_folder(os.path.dirname(out))
        self.status.setText("Generando la preview en 3ds Max (el render puede tardar)…")
        self._run_in_max(inst, "Generar preview",
                         lambda: inst.call("make_preview", out_file=out, prev=prev, from_view=from_view), done)

    def _rescan_folder(self, folder):
        if self.index:
            self.index.rescan_folder(folder)
            self.index.save(self.cache_file)
            self._update_assets()

    # --- Archivos que faltan ----------------------------------------------
    def _open_missing(self, asset=None):
        if asset is None:
            sel = self._selected_assets()
            if len(sel) != 1:
                return
            asset = sel[0]
        dlg = MissingDialog(asset.name, asset.all_files(), self.settings, self)

        def saved(files):
            for f in files:
                self.loader.recheck(f)
            self.view.viewport().update()
        dlg.saved.connect(saved)
        dlg.exec()
        self._update_info()

    # --- Catalogar una descarga -------------------------------------------
    def _open_catalog(self):
        if self.index is None:
            QtWidgets.QMessageBox.information(self, "OpenLibrary", "Añade antes una carpeta de biblioteca a esta "
                                                                   "pestaña en Ajustes › Libraries.")
            return
        dlg = CatalogDialog(self.settings, self.index, self.hidden, self._current_folder(), self)
        dlg.catalogued.connect(self._on_catalogued)
        dlg.exec()

    def _on_catalogued(self, folder, hid):
        """Algo nuevo en `folder`: se relee esa carpeta (y las que se hayan creado por encima) y se enseña."""
        if self.index is None:
            return
        chain = [os.path.normpath(folder)]
        roots = [os.path.normcase(r) for r in self.index.roots]
        while os.path.normcase(chain[-1]) not in self.index.records and os.path.normcase(chain[-1]) not in roots:
            parent = os.path.dirname(chain[-1])
            if parent == chain[-1]:
                break
            chain.append(parent)
        for f in reversed(chain):
            self.index.rescan_folder(f)
        self.index.save(self.cache_file)
        self._build_tree(folder)
        self._update_assets()
        self.status.setText("Catalogado en %s%s" % (folder, " · la carpeta de texturas queda oculta en el árbol"
                                                    if hid else ""))

    # --- Re-enlazar -----------------------------------------------------
    def _relink_scene(self):
        inst = self._need_max()
        if inst is None:
            return
        if inst.busy:
            QtWidgets.QMessageBox.information(
                self, "OpenLibrary", "3ds Max está ocupado con la orden anterior (si estás colocando un asset, "
                                     "termina con Esc).")
            return
        dirs = []
        for a in self._selected_assets():
            dirs.extend(self._relink_dirs(a))
        if not dirs:
            folder = self._current_folder()
            dirs = [folder] if folder else (list(self.index.roots) if self.index else [])
        dirs = list(dict.fromkeys(dirs + list(self.settings.imp.get("relink_dirs", []))))
        if not dirs:
            QtWidgets.QMessageBox.information(self, "OpenLibrary", "No hay carpetas donde buscar.")
            return

        def done(res, err):
            if err is None:
                fixed, missing = res
                if not fixed and not missing:
                    text = "La escena no tiene rutas perdidas."
                else:
                    text = "Escena: %d rutas re-enlazadas, %d siguen perdidas." % (fixed, missing)
                self.status.setText(text)
                QtWidgets.QMessageBox.information(self, "OpenLibrary",
                                                  "%s\n\nBuscado en:\n%s" % (text, "\n".join(dirs)))
        self.status.setText("Re-enlazando la escena (buscar en carpetas grandes puede tardar)…")
        self._run_in_max(inst, "Re-enlazar escena", lambda: inst.call("relink_scene", search_dirs=dirs), done)

    def _relink_assets(self, assets=None):
        inst = self._need_max()
        if not isinstance(assets, list):
            assets = self._selected_assets()
        if inst is None:
            return
        if not assets:
            QtWidgets.QMessageBox.information(self, "OpenLibrary", "Selecciona antes uno o varios assets.")
            return
        jobs = [(f, self._relink_dirs(a)) for a in assets for f in a.all_files()]
        if QtWidgets.QMessageBox.question(
                self, "OpenLibrary",
                "Se van a reescribir las rutas dentro de %d archivo(s) .max de la biblioteca.\n¿Seguir?"
                % len(jobs)) != QtWidgets.QMessageBox.Yes:
            return
        prog = [0]
        timer = QtCore.QTimer(self)
        timer.timeout.connect(lambda: self.status.setText("Re-enlazando %d de %d…" % (prog[0], len(jobs))))
        timer.start(400)

        def work():
            report = []
            for f, dirs in jobs:
                prog[0] += 1
                try:
                    fixed, missing = inst.call("relink_file", max_path=f, search_dirs=dirs)
                    report.append((os.path.basename(f), fixed, missing, None))
                except maxlink.MaxLinkError as exc:
                    report.append((os.path.basename(f), 0, 0, str(exc)))
            return report

        def done(report, err):
            timer.stop()
            timer.deleteLater()
            for f, _ in jobs:
                self.loader.recheck(f)
            if err is not None:
                return
            fixed = sum(r[1] for r in report)
            missing = sum(r[2] for r in report)
            errors = [r for r in report if r[3]]
            head = "%d archivo(s) revisados: %d rutas arregladas, %d siguen perdidas." % (
                len(report), fixed, missing)
            self.status.setText(head)
            lines = ["%s: %d arregladas, %d perdidas" % (n, fx, ms) for n, fx, ms, e in report if (fx or ms) and not e]
            lines += ["%s: error %s" % (n, e) for n, _fx, _ms, e in errors]
            if len(lines) > 18:
                lines = lines[:18] + ["… y %d más" % (len(lines) - 18)]
            text = head + ("\n\n" + "\n".join(lines) if lines else "")
            edits = self._disposable_edits([f for (f, _d), r in zip(jobs, report) if r[2] and not r[3]]) \
                if missing else []
            if not edits:
                QtWidgets.QMessageBox.information(self, "OpenLibrary", text)
                return
            nfiles = len(set(e[0] for e in edits))
            names = sorted(set(os.path.basename(e[1].replace("/", "\\")) for e in edits), key=lambda s: s.lower())
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("OpenLibrary")
            box.setIcon(QtWidgets.QMessageBox.Question)
            box.setText(text)
            box.setInformativeText(
                "De las que siguen perdidas, %d %s (.cube, .hdr o «checker»):\n%s%s\n\n"
                "¿Quitarlas de %s? El .max deja de pedirlas; no se puede deshacer desde aquí." % (
                    len(edits), "es de las que suelen sobrar" if len(edits) == 1 else "son de las que suelen sobrar",
                    ", ".join(names[:8]), "…" if len(names) > 8 else "",
                    "el archivo" if nfiles == 1 else "los %d archivos" % nfiles))
            yes = box.addButton("Quitar %d de golpe" % len(edits), QtWidgets.QMessageBox.AcceptRole)
            box.addButton("Dejarlas", QtWidgets.QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is yes:
                self._run_path_edits(edits)
        self._run_in_max(inst, "Re-enlazar .max", work, done)

    def _disposable_edits(self, files):
        """[(archivo .max, ruta guardada, None)] de lo perdido que se puede quitar de golpe."""
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            return [(f, r["stored"], None) for f in files for r in maxfile.external_files(f)
                    if r["state"] == "missing" and pathedit.is_disposable(r["type"], r["stored"])]
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _run_path_edits(self, edits):
        """Escribe los cambios de rutas en los .max con un 3ds Max en segundo plano."""
        self.surf.shutdown()
        if getattr(self, "path_proc", None) is not None:
            return
        exe = pathedit.find_maxbatch()
        if not exe:
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No encuentro 3dsmaxbatch.exe (viene con 3ds Max).")
            return
        workdir = os.path.join(config.app_data_dir(), "pathedit_tmp", "lote")
        script, log_file = pathedit.prepare(workdir, edits)
        files = sorted(set(e[0] for e in edits))
        proc = QtCore.QProcess(self)
        proc.setProgram(exe)
        proc.setArguments([script])
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.path_proc = proc
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.status.setText("Quitando %d referencias de %d archivo(s) con un 3ds Max en segundo plano…"
                            % (len(edits), len(files)))

        def finished(*_a):
            if self.path_proc is None:
                return
            self.path_proc = None
            proc.deleteLater()
            self.progress.setVisible(self._busy > 0 or self.batch is not None)
            log = pathedit.read_log(log_file)
            done = sum(n for n in log.values() if n > 0)
            bad = [f for f in files if log.get(os.path.normcase(f), -1) < 0]
            for f in files:
                self.loader.recheck(f)
            self.view.viewport().update()
            self._update_info()
            self.status.setText("Quitadas %d referencias de %d archivo(s)%s." % (
                done, len(files) - len(bad), "; no se pudo escribir en %d" % len(bad) if bad else ""))
        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda e: finished() if e == QtCore.QProcess.FailedToStart else None)
        proc.start()

    def shutdown(self):
        self.settings.save()
        self.engine_timer.stop()
        self.batch_timer.stop()
        if self.batch is not None:
            batchpreview.kill_tree(self.batch["proc"])
            self.batch["proc"].waitForFinished(2000)
            self.batch = None
        if self.stats_runner.running():
            proc = self.stats_runner.proc
            self.stats_runner.cancel()
            proc.waitForFinished(2000)
        self.max_pool.waitForDone(500)
        self.save_timer.stop()
        for th in list(self.scans.values()):
            if th.isRunning():
                th.cancel()
                th.wait(3000)
        if getattr(self, "path_proc", None) is not None:
            self.path_proc.waitForFinished(60000)      # a medias dejaría un .max sin terminar de escribir
        self.loader.clear_queue()
        self.loader.pool.waitForDone(2000)
        self.loader.bg_pool.waitForDone(2000)
        self._save_caches()
