"""Pestañas Materiales, Texturas e Interiores: árbol de carpetas + miniaturas + opciones de envío a Max.

Materiales: cada grupo de mapas PBR (o biblioteca .mat) es una bola; se arrastra a un objeto de
Max, a la selección o al editor Slate. Texturas: cada imagen suelta; se arrastra a Slate como mapa.
Interiores: cada habitación wParallax (EXR + shader OSL); se arrastra a una ventana o al visor.
La lectura de carpetas y el reconocimiento están en surfaces.py e interiors.py (Python puro).
"""
import os
import subprocess

from . import icon, interiors, library, maxlink, surfaces, theme, ui_fav
from .qt import QtCore, QtGui, QtWidgets

ROLE_ITEM = QtCore.Qt.UserRole + 1
ROLE_PATH = QtCore.Qt.UserRole + 2
ROLE_FAV = QtCore.Qt.UserRole + 3          # el nodo «Favoritos» del árbol
FAV = object()                             # build_tree(select=FAV): abrir los favoritos
# segundos que se espera a 3ds Max al crear un material (si tiene una ventana abierta, no contesta)
MAX_WAIT = 120

ENGINES = (("auto", "Motor de la escena"), ("corona", "Corona"), ("vray", "V-Ray"), ("max", "Physical (Max)"))
MAPPINGS = (("uv", "UV del objeto"), ("realworld", "Real World"), ("uvw", "UVW Map"), ("triplanar", "Triplanar"))
# ejes que usa cada mapeado (los demás se ven, pero apagados)
AXES = {"uv": 0, "realworld": 2, "uvw": 3, "triplanar": 1}
RESOLUTIONS = (("max", "Res. más alta"), ("min", "Res. más baja"), (8, "8K"), (4, "4K"), (2, "2K"), (1, "1K"))
ROLES = (("auto", "Según el nombre"), ("color", "Color (sRGB)"), ("data", "Datos (lineal)"))
LIGHTS = (("day", "Día"), ("night", "Noche"))
DEPTHS = ((-1, "Fondo automático"), (1, "Fondo ×1"), (3, "Fondo ×1,5"), (4, "Fondo ×2"), (5, "Fondo ×3"),
          (6, "Fondo ×4"), (7, "Fondo ×5"))
DEFAULTS = {"engine": "auto", "res": "max", "mapping": "uv", "displacement": False, "balls": True, "role": "auto",
            "light": "day", "depth": -1}
NOUNS = {"materials": ("material", "materiales"), "textures": ("textura", "texturas"),
         "interiors": ("habitación", "habitaciones")}


def _combo(options, current, tip):
    c = QtWidgets.QComboBox()
    c.setObjectName("MaxChip")
    for key, text in options:
        c.addItem(text, key)
    c.setCurrentIndex(max(0, c.findData(current)))
    c.setToolTip(tip)
    c.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
    return c


def _chip(text, tip, checked=False):
    b = QtWidgets.QToolButton()
    b.setObjectName("Chip")
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    return b


def _button(text, tip, name="Action", icon_name=None):
    b = QtWidgets.QToolButton()
    b.setObjectName(name)
    b.setText(text)
    b.setToolTip(tip)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setAutoRaise(True)
    if icon_name:
        b.setIcon(icon(icon_name, theme.ACCENT_TEXT if name == "Accent" else None))
        b.setIconSize(QtCore.QSize(18, 18))
        b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    return b


def _fmt_cm(v):
    return ("%.1f" % v).rstrip("0").rstrip(".")


def size_text(size):
    if not size:
        return ""
    w, h = size[0], size[1]
    if w >= 100 and h >= 100:
        return "%s×%s m" % (_fmt_cm(w / 100.0), _fmt_cm(h / 100.0))
    return "%s×%s cm" % (_fmt_cm(w), _fmt_cm(h))


class _ScanThread(QtCore.QThread):
    progress = QtCore.Signal(int)
    done = QtCore.Signal(object, str)
    measured = QtCore.Signal(object, int)

    def __init__(self, index, cache_file, incremental, dims=False, parent=None):
        super(_ScanThread, self).__init__(parent)
        self.index, self.cache_file, self.incremental, self.dims = index, cache_file, incremental, dims

    def run(self):
        self.index.cancelled = False
        self.index.scan(progress=lambda folders, _files: self.progress.emit(folders), incremental=self.incremental)
        if not self.index.cancelled:
            self.index.save(self.cache_file)
        self.done.emit(self.index, self.cache_file)
        if self.dims and not self.index.cancelled:
            # cuadrada o rectangular: se lee la cabecera de cada mapa de color (solo los nuevos)
            self.index.fill_dims(progress=lambda n: self.measured.emit(self.index, n))
            if not self.index.cancelled:
                self.index.save(self.cache_file)
            self.measured.emit(self.index, -1)

    def cancel(self):
        self.index.cancelled = True


class _Model(QtCore.QAbstractListModel):
    def __init__(self, loader, parent=None):
        super(_Model, self).__init__(parent)
        self.items = []
        self.rows = {}
        self.loader = loader
        loader.loaded.connect(self._on_loaded)

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.rows = {it.key: i for i, it in enumerate(items)}
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        it = self.items[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return it.name
        if role == ROLE_ITEM:
            return it
        if role == QtCore.Qt.ToolTipRole:
            return tooltip(it)
        return None

    def flags(self, index):
        f = super(_Model, self).flags(index)
        return f | QtCore.Qt.ItemIsDragEnabled if index.isValid() else f

    def _on_loaded(self, key):
        row = self.rows.get(key)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx)


def room_text(room):
    return "%s · %s m" % (interiors.SIZE_LABEL.get(room.size, ""), _fmt_cm(room.width() / 100.0) + "×" +
                          _fmt_cm(interiors.HEIGHT / 100.0))


def tooltip(it):
    if isinstance(it, surfaces.Texture):
        return "%s\n%s" % (os.path.basename(it.path), it.folder)
    if isinstance(it, interiors.Room):
        lines = [it.name, it.folder, room_text(it),
                 "Luz: " + " y ".join(dict(LIGHTS)[l].lower() for l in it.lights())]
        res = [("%dK" % r) for r in it.resolutions() if r]
        if res:
            lines.append("Resoluciones: " + ", ".join(res))
        return "\n".join(lines)
    lines = [it.name, it.folder]
    if it.is_library:
        lines.append("Biblioteca de materiales de 3ds Max (.mat)")
        return "\n".join(lines)
    if it.size:
        lines.append("Tamaño real: " + size_text(it.size))
    res = [("%dK" % r) for r in it.resolutions() if r]
    if res:
        lines.append("Resoluciones: " + ", ".join(res))
    if it.tiles:
        lines.append("%d lamas sueltas (se usa la primera)" % it.tiles)
    lines.append("")
    for ch, path in sorted(it.pick().items(), key=lambda kv: surfaces.CHANNEL_ORDER.index(kv[0])):
        lines.append("%s: %s" % (surfaces.CHANNEL_INFO[ch][3], os.path.basename(path)))
    return "\n".join(lines)


class _Delegate(QtWidgets.QStyledItemDelegate):
    FOOT = 40

    def __init__(self, view, loader):
        super(_Delegate, self).__init__(view)
        self.view = view
        self.loader = loader
        self.thumb = 160
        self.fill = 0
        self.balls = True
        self.light = "day"
        self.refresh_colors()

    def refresh_colors(self):
        self.c_card = theme.color(theme.SURFACE)
        self.c_card_hi = theme.color(theme.SURFACE_HI)
        self.c_border = theme.color(theme.BORDER)
        self.c_accent = theme.color(theme.ACCENT)
        self.c_text = theme.color(theme.TEXT)
        self.c_muted = theme.color(theme.MUTED)
        self.c_faint = theme.color(theme.FAINT)

    def cell_size(self, minimum=False):
        t = self.thumb if minimum else max(self.thumb, self.fill)
        return QtCore.QSize(t + 12, t + self.FOOT + 12)

    def sizeHint(self, option, index):
        return self.cell_size()

    def heart_rect(self, rect):
        """Dónde va el corazón de favorito dentro de la celda rect (a la derecha del nombre)."""
        cell = QtCore.QRectF(QtCore.QPointF(0, 0), QtCore.QSizeF(self.cell_size()))
        cell.moveCenter(QtCore.QRectF(rect).center())
        r = cell.adjusted(6, 6, -6, -6)
        foot_top = r.bottom() - self.FOOT + 4
        return QtCore.QRectF(r.right() - 9 - 18, foot_top + 1, 18, 16)

    def paint(self, p, option, index):
        it = index.data(ROLE_ITEM)
        if it is None:
            return
        is_mat = isinstance(it, surfaces.Material)
        is_room = isinstance(it, interiors.Room)
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        cell = QtCore.QRectF(QtCore.QPointF(0, 0), QtCore.QSizeF(self.cell_size()))
        cell.moveCenter(QtCore.QRectF(option.rect).center())
        r = cell.adjusted(6, 6, -6, -6)
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        card = QtGui.QPainterPath()
        rad = float(theme.RADIUS)
        card.addRoundedRect(r, rad, rad)
        img_rect = QtCore.QRectF(r.left(), r.top(), r.width(), r.height() - self.FOOT)
        if is_room:
            src = it.thumb_source(self.light)
            img = self.loader.get(it.key + "|" + self.light, src) if src else None
        else:
            src = it.thumb_source() if is_mat else it.path
            img = self.loader.get(it.key, src) if src else None
        has_img = img is not None and not img.isNull()

        p.save()
        p.setClipPath(card)
        p.fillRect(r, self.c_card_hi if (hover or selected) else self.c_card)
        if has_img:
            as_ball = is_mat and self.balls and not it.preview
            if as_ball:
                self._ball(p, img_rect, img)
            else:
                s = QtCore.QSizeF(img.size())
                s.scale(img_rect.size(), QtCore.Qt.KeepAspectRatioByExpanding if (is_mat or is_room)
                        else QtCore.Qt.KeepAspectRatio)
                target = QtCore.QRectF(QtCore.QPointF(0, 0), s)
                target.moveCenter(img_rect.center())
                p.save()
                p.setClipRect(img_rect, QtCore.Qt.IntersectClip)
                p.drawImage(target, img)
                p.restore()
        else:
            f = QtGui.QFont(option.font)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(self.c_faint)
            if img is None and src:
                text = "cargando…"
            elif is_mat and it.is_library:
                text = ".mat"
            elif is_room:
                text = "EXR\n(sin vista previa)"
            elif src:
                text = os.path.splitext(src)[1].lstrip(".").upper() + "\n(sin vista previa)"
            else:
                text = "sin imagen"
            p.drawText(img_rect, QtCore.Qt.AlignCenter, text)
        p.restore()

        if is_mat:
            self._badges(p, option, img_rect, it)
            self._shape(p, option, img_rect, self.view.panel.ratio_for(it))
        elif is_room:
            self._room_badges(p, option, img_rect, it)

        foot = QtCore.QRectF(r.left() + 9, img_rect.bottom() + 4, r.width() - 18, self.FOOT - 8)
        fav = self.view.panel.is_fav(it)
        if fav or hover or selected:
            ui_fav.paint_heart(p, self.heart_rect(option.rect).adjusted(2, 1.5, -2, -1.5), fav, self.c_faint)
        name_w = foot.width() - 22
        f1 = QtGui.QFont(option.font)
        f1.setWeight(QtGui.QFont.DemiBold)
        p.setFont(f1)
        p.setPen(self.c_accent if selected else self.c_text)
        p.drawText(QtCore.QRectF(foot.left(), foot.top(), foot.width(), foot.height() / 2 + 1),
                   QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                   QtGui.QFontMetrics(f1).elidedText(it.name, QtCore.Qt.ElideMiddle, int(name_w)))
        f2 = QtGui.QFont(option.font)
        f2.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
        p.setFont(f2)
        p.setPen(self.c_muted)
        if is_mat:
            known = None if it.is_library else self.view.panel.size_for(it, known_only=True)
            bits = [size_text(known)] if known else []
            bits.append("biblioteca .mat" if it.is_library else os.path.basename(it.folder))
            sub = " · ".join(b for b in bits if b)
        elif is_room:
            sub = room_text(it)
        else:
            sub = os.path.basename(it.folder)
        p.drawText(QtCore.QRectF(foot.left(), foot.top() + foot.height() / 2, foot.width(), foot.height() / 2),
                   QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                   QtGui.QFontMetrics(f2).elidedText(sub, QtCore.Qt.ElideRight, int(foot.width())))

        p.setBrush(QtCore.Qt.NoBrush)
        if selected:
            p.setPen(QtGui.QPen(self.c_accent, 2.5))
            p.drawRoundedRect(r.adjusted(1.2, 1.2, -1.2, -1.2), max(0.0, rad - 1), max(0.0, rad - 1))
        else:
            p.setPen(QtGui.QPen(self.c_border, 1))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        p.restore()

    @staticmethod
    def _ball(p, rect, img):
        """Bola aproximada: la textura recortada en círculo con luz y sombra pintadas encima."""
        d = min(rect.width(), rect.height()) * 0.84
        ball = QtCore.QRectF(0, 0, d, d)
        ball.moveCenter(QtCore.QPointF(rect.center().x(), rect.center().y() - d * 0.02))
        p.save()
        p.setPen(QtCore.Qt.NoPen)
        shadow = QtGui.QRadialGradient(QtCore.QPointF(ball.center().x(), ball.bottom() - d * 0.02), d * 0.5)
        shadow.setColorAt(0.0, QtGui.QColor(0, 0, 0, 110))
        shadow.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
        p.setBrush(shadow)
        p.drawEllipse(QtCore.QRectF(ball.left(), ball.bottom() - d * 0.12, d, d * 0.2))
        path = QtGui.QPainterPath()
        path.addEllipse(ball)
        p.setClipPath(path, QtCore.Qt.IntersectClip)
        s = QtCore.QSizeF(img.size())
        s.scale(ball.size(), QtCore.Qt.KeepAspectRatioByExpanding)
        target = QtCore.QRectF(QtCore.QPointF(0, 0), s)
        target.moveCenter(ball.center())
        p.drawImage(target, img)
        shade = QtGui.QRadialGradient(ball.center(), d * 0.5,
                                      QtCore.QPointF(ball.left() + d * 0.34, ball.top() + d * 0.28))
        shade.setColorAt(0.0, QtGui.QColor(255, 255, 255, 75))
        shade.setColorAt(0.22, QtGui.QColor(255, 255, 255, 12))
        shade.setColorAt(0.55, QtGui.QColor(0, 0, 0, 25))
        shade.setColorAt(0.85, QtGui.QColor(0, 0, 0, 120))
        shade.setColorAt(1.0, QtGui.QColor(0, 0, 0, 205))
        p.setBrush(shade)
        p.drawEllipse(ball)
        p.restore()

    def _shape(self, p, option, rect, ratio):
        """Arriba a la derecha: la forma de la textura rellena (blanca si es cuadrada, ámbar si es
        rectangular) y su proporción, «1:1», «2:1»…"""
        if not ratio:
            return
        kind, text = ratio
        d = float(max(18, min(26, self.thumb // 7)))
        font = QtGui.QFont(option.font)
        font.setBold(True)
        font.setPixelSize(int(d * 0.46))
        tw = QtGui.QFontMetrics(font).horizontalAdvance(text)
        u = d * 0.5
        w, h = {"square": (u, u), "wide": (u * 1.6, u * 0.8), "tall": (u * 0.6, u * 1.0)}[kind]
        pill = QtCore.QRectF(0, 0, d * 0.45 + w + 5 + tw + d * 0.4, d)
        pill.moveTopRight(QtCore.QPointF(rect.right() - 7, rect.top() + 7))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(20, 24, 34, 215))
        p.drawRoundedRect(pill, d / 2, d / 2)
        box = QtCore.QRectF(pill.left() + d * 0.45, pill.center().y() - h / 2, w, h)
        p.setBrush(QtGui.QColor("white") if kind == "square" else theme.color(theme.ACCENT))
        p.drawRoundedRect(box, 1.5, 1.5)
        p.setFont(font)
        p.setPen(QtGui.QColor("white"))
        p.drawText(QtCore.QRectF(box.right() + 5, pill.top(), tw + 2, d), QtCore.Qt.AlignVCenter, text)

    def _room_badges(self, p, option, rect, room):
        d = float(max(18, min(26, self.thumb // 7)))
        font = QtGui.QFont(option.font)
        font.setBold(True)
        font.setPixelSize(int(d * 0.46))
        p.setFont(font)
        tags = []
        if room.top_res():
            tags.append(("%dK" % room.top_res(), QtGui.QColor(20, 24, 34, 215), QtGui.QColor("white")))
        tags.append((room.size, theme.color(theme.ACCENT), theme.color(theme.ACCENT_TEXT)))
        x = rect.left() + 7
        for text, color, fg in tags:
            tag = QtCore.QRectF(x, rect.top() + 7, d * 1.25, d)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(tag, d / 2, d / 2)
            p.setPen(fg)
            p.drawText(tag, QtCore.Qt.AlignCenter, text)
            x += d * 1.25 + 4
        x = rect.left() + 7
        for light in room.lights():
            tag = QtCore.QRectF(x, rect.bottom() - d - 6, d * 2.4, d)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 1))
            p.setBrush(QtGui.QColor("#E0B53A") if light == "day" else QtGui.QColor("#3B5BA8"))
            p.drawRoundedRect(tag, d / 2, d / 2)
            p.setPen(QtGui.QColor("white") if light == "night" else QtGui.QColor(30, 30, 30))
            p.drawText(tag, QtCore.Qt.AlignCenter, dict(LIGHTS)[light])
            x += d * 2.4 + 4

    def _badges(self, p, option, rect, mat):
        d = float(max(18, min(26, self.thumb // 7)))
        font = QtGui.QFont(option.font)
        font.setBold(True)
        font.setPixelSize(int(d * 0.46))
        p.setFont(font)
        p.setPen(QtCore.Qt.NoPen)
        top = mat.top_res()
        if top:
            tag = QtCore.QRectF(rect.left() + 7, rect.top() + 7, d * 1.25, d)
            p.setBrush(QtGui.QColor(20, 24, 34, 215))
            p.drawRoundedRect(tag, d / 2, d / 2)
            p.setPen(QtGui.QColor("white"))
            p.drawText(tag, QtCore.Qt.AlignCenter, "%dK" % top)
        if mat.is_library:
            return
        x = rect.left() + 7
        y = rect.bottom() - d - 6
        for ch in mat.channels():
            letters, color = surfaces.CHANNEL_INFO[ch][1], surfaces.CHANNEL_INFO[ch][2]
            if not letters or ch == "refl":
                continue
            if x + d > rect.right() - 4:
                break
            tag = QtCore.QRectF(x, y, d, d)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 1))
            p.setBrush(QtGui.QColor(color))
            p.drawEllipse(tag)
            p.setPen(QtGui.QColor("white"))
            p.drawText(tag, QtCore.Qt.AlignCenter, letters)
            x += d + 3


class _View(QtWidgets.QListView):
    dropped_outside = QtCore.Signal(object, int, object)     # items, PID, títulos de la ventana

    def __init__(self, panel, parent=None):
        super(_View, self).__init__(parent)
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
        self._pre = QtCore.QTimer(self)
        self._pre.setSingleShot(True)
        self._pre.setInterval(120)
        self._pre.timeout.connect(self._prefetch)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._pre.start())

    def _prefetch(self):
        light = self.panel.delegate.light

        def key_src(idx):
            it = idx.data(ROLE_ITEM)
            if it is None:
                return None, None
            if isinstance(it, interiors.Room):
                return it.key + "|" + light, it.thumb_source(light)
            if isinstance(it, surfaces.Material):
                return it.key, it.thumb_source()
            return it.key, it.path
        self.panel.loader.prefetch_view(self, key_src)

    def resizeEvent(self, event):
        super(_View, self).resizeEvent(event)
        self.panel.fit_grid()
        QtCore.QTimer.singleShot(0, self.panel.fit_grid)

    def _heart_at(self, pos):
        idx = self.indexAt(pos)
        if idx.isValid() and self.panel.delegate.heart_rect(self.visualRect(idx)).adjusted(-3, -3, 3, 3) \
                .contains(QtCore.QPointF(pos)):
            return idx.data(ROLE_ITEM)
        return None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            it = self._heart_at(event.pos())
            if it is not None:
                self.panel.toggle_fav([it])
                event.accept()
                return
        super(_View, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super(_View, self).mouseMoveEvent(event)
        if not event.buttons():
            on = self._heart_at(event.pos()) is not None
            self.viewport().setCursor(QtCore.Qt.PointingHandCursor if on else QtCore.Qt.ArrowCursor)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.panel.send("selection")
            return
        if event.key() == QtCore.Qt.Key_Space:
            self.panel.quick_look()
            return
        super(_View, self).keyPressEvent(event)

    def startDrag(self, actions):
        items = self.panel.selected()
        if not items:
            return
        mime = QtCore.QMimeData()
        mime.setData("application/x-openlibrary-surface", QtCore.QByteArray(items[0].key.encode("utf-8")))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        key = items[0].key
        if isinstance(items[0], interiors.Room):
            key += "|" + self.panel.delegate.light
        img = self.panel.loader.images.get(key)
        if img is not None and not img.isNull():
            drag.setPixmap(QtGui.QPixmap.fromImage(img).scaled(
                88, 88, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        drag.exec(QtCore.Qt.CopyAction)
        pos = QtGui.QCursor.pos()
        w = QtWidgets.QApplication.widgetAt(pos)
        host = self.panel.host
        if w is not None and (w is host or host.isAncestorOf(w)):
            return
        pid, titles = maxlink.window_under_cursor(pos.x(), pos.y())
        self.dropped_outside.emit(items, pid, titles)


class SurfacePanel(QtWidgets.QSplitter):
    """Cuerpo de las pestañas Materiales y Texturas (la cabecera y la barra de estado son las de la app)."""

    def __init__(self, host):
        super(SurfacePanel, self).__init__(QtCore.Qt.Horizontal, host)
        self.host = host
        self.settings = host.settings
        self.loader = host.loader
        self.kind = "materials"
        self.lib = None
        self.index = None
        self.cache_file = None
        self.indexes = {}
        self.scanned = set()
        self.scans = {}              # cache_file -> _ScanThread (cada pestaña acaba la suya aunque cambies)
        self.hidden = set()
        self.fav_node = None
        self.text = ""
        self._loading = False
        self.setHandleWidth(1)
        self._build()

    # --- opciones guardadas -------------------------------------------------
    def opt(self, key):
        return self.settings.data.get("surfaces", {}).get(key, DEFAULTS[key])

    def set_opt(self, key, value):
        opts = dict(self.settings.data.get("surfaces", {}))
        opts[key] = value
        self.settings.data["surfaces"] = opts
        self.settings.save()

    # --- interfaz -----------------------------------------------------------
    def _build(self):
        side = QtWidgets.QFrame()
        side.setObjectName("Sidebar")
        side.setMinimumWidth(190)
        sl = QtWidgets.QVBoxLayout(side)
        sl.setContentsMargins(10, 14, 6, 10)
        sl.setSpacing(6)
        cap = QtWidgets.QLabel("CARPETAS")
        cap.setObjectName("Caption")
        cap.setContentsMargins(6, 0, 0, 0)
        sl.addWidget(cap)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName("Folders")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tree.setIconSize(QtCore.QSize(16, 16))
        self.tree.currentItemChanged.connect(lambda *_: self.update_items())
        self.tree.itemClicked.connect(lambda it, _c: it.setExpanded(True))
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        ui_fav.shift_collapse(self.tree)
        sl.addWidget(self.tree, 1)
        self.addWidget(side)

        main = QtWidgets.QFrame()
        main.setObjectName("Main")
        ml = QtWidgets.QVBoxLayout(main)
        ml.setContentsMargins(18, 14, 12, 12)
        ml.setSpacing(10)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.title = QtWidgets.QLabel("")
        self.title.setObjectName("FolderTitle")
        bar.addWidget(self.title)
        self.count = QtWidgets.QLabel("")
        self.count.setObjectName("Muted")
        self.count.setContentsMargins(4, 4, 0, 0)
        bar.addWidget(self.count)
        bar.addStretch(1)
        # filtros de la vista (arriba, para dejar la fila de opciones a lo que va a Max)
        self.chip_lib = _chip(".mat", "Solo bibliotecas de materiales de 3ds Max (.mat)")
        self.chip_lib.toggled.connect(lambda _on: self.update_items())
        bar.addWidget(self.chip_lib)
        self.chip_size = _chip("Con medidas", "Solo materiales de los que se sabe el tamaño real")
        self.chip_size.toggled.connect(lambda _on: self.update_items())
        bar.addWidget(self.chip_size)
        self.c_sort = _combo((("name", "Nombre A–Z"), ("recent", "Más recientes")), "name", "Orden")
        self.c_sort.activated.connect(lambda _i: self.update_items())
        bar.addWidget(self.c_sort)
        self.chip_balls = _chip("Bolas", "Enseñar los materiales como bolas (la bola es un dibujo aproximado hecho "
                                         "con el mapa de color, no un render)", self.opt("balls"))
        self.chip_balls.toggled.connect(self._on_balls)
        bar.addWidget(self.chip_balls)
        bar.addSpacing(6)
        self.b_slate = _button("Al Slate", "Poner lo seleccionado en la vista activa del editor de materiales Slate")
        self.b_slate.clicked.connect(lambda: self.send("slate"))
        bar.addWidget(self.b_slate)
        self.b_plane = _button("Crear ventana", "Crear en 3ds Max un plano del tamaño de la ventana (S, M o L) "
                                                "con esta habitación", "Accent")
        self.b_plane.clicked.connect(lambda: self.send("plane"))
        bar.addWidget(self.b_plane)
        self.b_apply = _button("Aplicar", "", "Primary", "check")
        self.b_apply.clicked.connect(lambda: self.send("selection"))
        bar.addWidget(self.b_apply)
        ml.addLayout(bar)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        self.c_engine = _combo(ENGINES, self.opt("engine"),
                               "Con qué motor se crea el material o el mapa en 3ds Max")
        self.c_engine.activated.connect(lambda _i: self.set_opt("engine", self.c_engine.currentData()))
        row.addWidget(self.c_engine)
        self.c_res = _combo(RESOLUTIONS, self.opt("res"),
                            "Qué resolución se carga cuando el material trae varias (si no hay esa, la más cercana)")
        self.c_res.activated.connect(lambda _i: self.set_opt("res", self.c_res.currentData()))
        row.addWidget(self.c_res)
        self.c_role = _combo(ROLES, self.opt("role"),
                             "Cómo se carga la textura: color (sRGB) o datos sin gamma (normales, roughness, máscaras).\n"
                             "«Según el nombre» lo decide por el apellido del archivo (_normal, _roughness…).")
        self.c_role.activated.connect(lambda _i: self.set_opt("role", self.c_role.currentData()))
        row.addWidget(self.c_role)
        self.c_light = _combo(LIGHTS, self.opt("light"), "Qué versión de la habitación se carga: de día o de noche "
                                                          "(también cambia la miniatura)")
        self.c_light.activated.connect(self._on_light)
        row.addWidget(self.c_light)
        self.c_depth = _combo(DEPTHS, self.opt("depth"),
                              "Profundidad de la habitación respecto al ancho de la ventana.\n"
                              "Automático: la de las escenas de ejemplo (×1,5 en ventanas S, ×3 en M y L).")
        self.c_depth.activated.connect(lambda _i: self.set_opt("depth", self.c_depth.currentData()))
        row.addWidget(self.c_depth)
        self.c_map = _combo(MAPPINGS, self.opt("mapping"),
                            "UV del objeto: no toca el mapeado.\n"
                            "Tamaño real: la textura mide X × Y y el objeto recibe un UVW Map de caja con "
                            "«Real-World Map Size».\n"
                            "Caja UVW a medida: UVW Map de caja de X × Y × Z.\n"
                            "Triplanar: proyecta la textura por las tres caras con baldosas de X, sin UV.\n"
                            "En Slate nunca se añade el UVW Map. Al soltar sobre un objeto se pregunta.")
        self.c_map.activated.connect(lambda _i: self._on_mapping(True))
        row.addWidget(self.c_map)
        self.size_lbls = []
        self.spins = []
        for axis, tip in (("X", "Ancho real de la textura (X), en cm"),
                          ("Y", "Largo real de la textura (Y), en cm"),
                          ("Z", "Alto de la caja UVW (Z), en cm")):
            lbl = QtWidgets.QLabel(axis)
            lbl.setObjectName("Muted")
            spin = self._spin(tip)
            self.size_lbls.append(lbl)
            self.spins.append(spin)
            row.addWidget(lbl)
            row.addWidget(spin)
        self.s_w, self.s_h, self.s_z = self.spins
        self.cm_lbl = QtWidgets.QLabel("cm")
        self.cm_lbl.setObjectName("Muted")
        row.addWidget(self.cm_lbl)
        self.b_size_reset = QtWidgets.QToolButton()
        self.b_size_reset.setObjectName("Action")
        self.b_size_reset.setAutoRaise(True)
        self.b_size_reset.setText("↺")
        self.b_size_reset.setToolTip("Este material tiene medidas propias guardadas. Clic: volver a las del nombre.")
        self.b_size_reset.clicked.connect(self._reset_size)
        row.addWidget(self.b_size_reset)
        self.size_timer = QtCore.QTimer(self)
        self.size_timer.setSingleShot(True)
        self.size_timer.setInterval(500)
        self.size_timer.timeout.connect(self._on_size_edited)
        self.chip_disp = _chip("Desplazamiento", "Dejar encendido el mapa de desplazamiento del material "
                                                 "(si no, se conecta pero apagado)", self.opt("displacement"))
        self.chip_disp.toggled.connect(lambda on: self.set_opt("displacement", bool(on)))
        row.addWidget(self.chip_disp)
        row.addStretch(1)
        ml.addLayout(row)

        self.model = _Model(self.loader, self)
        self.view = _View(self)
        self.view.setModel(self.model)
        self.delegate = _Delegate(self.view, self.loader)
        self.delegate.balls = bool(self.opt("balls"))
        self.view.setItemDelegate(self.delegate)
        self.view.dropped_outside.connect(self._on_dropped)
        self.view.doubleClicked.connect(lambda _idx: self.quick_look())     # la preview en grande
        self.quick = None
        self.view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._item_menu)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._on_selection())
        self.empty = QtWidgets.QLabel("")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(QtCore.Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.empty)
        ml.addWidget(self.stack, 1)
        self.addWidget(main)

        self.detail = QtWidgets.QScrollArea()
        self.detail.setObjectName("Inspector")
        self.detail.setWidgetResizable(True)
        self.detail.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.detail.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.detail.setMinimumWidth(240)
        self.detail_lbl = QtWidgets.QLabel()
        self.detail_lbl.setTextFormat(QtCore.Qt.RichText)
        self.detail_lbl.setWordWrap(True)
        self.detail_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.detail_lbl.setContentsMargins(16, 16, 14, 14)
        self.detail_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.detail.setWidget(self.detail_lbl)
        self.detail.setVisible(bool(self.settings.data.get("show_info_bar", True)))
        self.addWidget(self.detail)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)
        self.setStretchFactor(2, 0)
        self.setSizes([220, 760, 300])
        self.setCollapsible(1, False)
        self._on_mapping()

    def _spin(self, tip):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(0.1, 100000.0)
        s.setDecimals(1)
        s.setValue(100.0)
        s.setFixedWidth(92)
        s.setToolTip(tip)
        s.valueChanged.connect(self._on_size_changed)
        return s

    # --- pestaña ------------------------------------------------------------
    def show_library(self, lib, text=""):
        self.lib = lib
        self.kind = lib.get("kind", "materials")
        self.text = text
        mats = self.kind == "materials"
        rooms = self.kind == "interiors"
        for w in (self.chip_disp, self.chip_lib, self.chip_size, self.chip_balls):
            w.setVisible(mats)
        self.c_res.setVisible(mats or rooms)
        self.c_role.setVisible(self.kind == "textures")
        for w in (self.c_light, self.c_depth, self.b_plane):
            w.setVisible(rooms)
        self.c_map.setVisible(not rooms)
        self.delegate.light = self.c_light.currentData()
        self._on_mapping()
        if rooms:
            self.b_apply.setText("Aplicar a la selección")
            self.b_apply.setToolTip("Poner la habitación a los objetos seleccionados en 3ds Max (planos o cajas "
                                    "de ventana)")
        else:
            self.b_apply.setText("Aplicar a la selección" if mats else "Material rápido")
            self.b_apply.setToolTip("Crear el material y ponérselo a los objetos seleccionados en 3ds Max" if mats
                                    else "Crear un material con esta textura y ponérselo a los objetos seleccionados")
        self.title.setText(lib["name"])
        paths = [p for p in lib.get("paths", []) if p]
        if not paths:
            self.index = None
            self.tree.clear()
            self.model.set_items([])
            self.count.setText("")
            self._empty("«%s» no tiene carpetas. Añádelas en Ajustes > Libraries." % lib["name"])
            return
        cache_file = surfaces.cache_path_for(self.host.cache_dir, paths)
        idx = self.indexes.get(cache_file)
        if idx is None:
            idx = surfaces.SurfaceIndex(paths)
            idx.load(cache_file)
            self.indexes[cache_file] = idx
        mdir = self.settings.measures_dir()
        if idx.measures_dir != mdir:            # p. ej. se ha cambiado de espacio de trabajo
            idx.measures_dir = mdir
            idx._materials = None
        self.index = idx
        self.cache_file = cache_file
        self.build_tree(FAV if ui_fav.open_on_fav(lib) else None)
        self.update_items()
        if cache_file not in self.scanned:
            self.rescan(True)

    @property
    def scan_thread(self):
        """La lectura en marcha de la pestaña que se ve (las de las otras siguen solas en segundo plano)."""
        return self.scans.get(self.cache_file)

    @scan_thread.setter
    def scan_thread(self, th):
        if th is not None:
            self.scans[self.cache_file] = th

    def rescan(self, incremental=True):
        if self.index is None:
            return
        if self.scan_thread is not None and self.scan_thread.isRunning():
            return                       # ya se está leyendo esta pestaña
        first = not self.index.listing
        self.host.status.setText("Leyendo las carpetas por primera vez…" if first else "Buscando cambios…")
        if first:
            self._empty("Leyendo las carpetas por primera vez…\nLas próximas veces solo se buscan cambios.")
        self.scan_thread = _ScanThread(self.index, self.cache_file, incremental, self.kind == "materials", self)
        th = self.scan_thread
        self.scan_thread.progress.connect(
            lambda n: self.host.status.setText("Leyendo… %d carpetas" % n)
            if self.isVisible() and self.scan_thread is th else None)
        self.scan_thread.done.connect(self._on_scanned)
        self.scan_thread.measured.connect(self._on_measured)
        self.scan_thread.start()

    def _on_measured(self, index, n):
        if index is not self.index or not self.isVisible():
            return
        if n >= 0:
            self.host.status.setText("Midiendo texturas (cuadradas o rectangulares)… %d" % n)
        else:
            # sin tocar X·Y·Z (se podría estar escribiendo en ellas): solo forma y triplanar
            self.view.viewport().update()
            sel = self.selected()
            if len(sel) == 1 and self.kind == "materials" and not sel[0].is_library:
                self._set_triplanar_allowed(self.aspect_for(sel[0]) in (None, "square"))
            self._show_detail(sel)

    def _on_scanned(self, index, cache_file):
        if index.cancelled:
            return
        self.scanned.add(cache_file)
        if index is not self.index or not self.isVisible():
            return
        self.build_tree(FAV if self.current_is_fav() else self.current_folder())
        self.update_items()
        if self.kind == "interiors":
            what = "%d habitaciones" % len(index.interiors())
        else:
            what = "%d materiales · %d texturas" % (len(index.materials()), len(index.textures()))
        self.host.status.setText("%s · %d carpetas revisadas, %d con cambios" % (
            what, index.stats["listed"] + index.stats["reused"], index.stats["listed"]))

    def all_items(self):
        if self.index is None:
            return []
        if self.kind == "interiors":
            return self.index.interiors()
        return self.index.materials() if self.kind == "materials" else self.index.textures()

    # --- árbol --------------------------------------------------------------
    def current_folder(self):
        it = self.tree.currentItem()
        return it.data(0, ROLE_PATH) if it is not None else None

    def current_is_fav(self):
        it = self.tree.currentItem()
        return bool(it is not None and it.data(0, ROLE_FAV))

    # --- favoritos (de cada persona, no del espacio compartido) -----------------
    def show_mode(self):
        """Qué se abre en la pestaña: «both» (todos, los favoritos primero), «favorites» o «all»."""
        return ui_fav.show_mode(self.lib)

    def is_fav(self, it):
        return bool(self.saved("favorites", it))

    def toggle_fav(self, items):
        items = [it for it in items if it is not None]
        if not items:
            return
        on = not all(self.is_fav(it) for it in items)
        self.remember("favorites", [(it, 1 if on else None) for it in items])
        self._fav_label()
        self.view.viewport().update()
        self.host.status.setText(("Añadido a favoritos: %s" if on else "Quitado de favoritos: %s")
                                 % ", ".join(it.name for it in items[:3]) + ("…" if len(items) > 3 else ""))

    def _fav_label(self):
        if self.fav_node is None:
            return
        n = sum(1 for it in self.all_items()
                if os.path.normcase(it.folder) not in self.hidden and self.is_fav(it))
        self.fav_node.setText(0, "Favoritos  (%d)" % n)

    def build_tree(self, select=None):
        opened = set()
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            if it.value().isExpanded() and it.value().data(0, ROLE_PATH):
                opened.add(os.path.normcase(it.value().data(0, ROLE_PATH)))
            it += 1
        had = self.tree.topLevelItemCount() > 0
        self.tree.blockSignals(True)
        self.tree.clear()
        self.fav_node = None
        idx = self.index
        if idx is None:
            self.tree.blockSignals(False)
            return
        h = self.settings.hidden
        self.hidden = library.hidden_folders(idx.folders, idx.roots, h["names"], h["paths"])
        roots_nc = [os.path.normcase(r) for r in idx.roots]
        totals = {}
        n_all = 0
        for item in self.all_items():
            k = os.path.normcase(item.folder)
            if k in self.hidden:
                continue
            n_all += 1
            while True:
                totals[k] = totals.get(k, 0) + 1
                if k in roots_nc:
                    break
                parent = os.path.dirname(k)
                if parent == k:
                    break
                k = parent
        show_fav, show_all = ui_fav.tree_nodes(self.lib)
        if show_fav:
            n_fav = sum(1 for item in self.all_items()
                        if os.path.normcase(item.folder) not in self.hidden and self.is_fav(item))
            self.fav_node = QtWidgets.QTreeWidgetItem(["Favoritos  (%d)" % n_fav])
            self.fav_node.setData(0, ROLE_FAV, True)
            self.fav_node.setIcon(0, ui_fav.heart_icon())
            self.fav_node.setToolTip(0, "Los marcados con el corazón (cada persona tiene los suyos)")
            self.tree.addTopLevelItem(self.fav_node)
        top = None
        if show_all:
            top = QtWidgets.QTreeWidgetItem(["Todos  (%d)" % n_all])
            top.setIcon(0, icon())
            self.tree.addTopLevelItem(top)
        nodes = {}
        for root in idx.roots:
            key = os.path.normcase(root)
            node = QtWidgets.QTreeWidgetItem(["%s  (%d)" % (os.path.basename(root.rstrip("\\/")) or root,
                                                            totals.get(key, 0))])
            node.setData(0, ROLE_PATH, root)
            node.setToolTip(0, root)
            node.setIcon(0, icon("drive"))
            self.tree.addTopLevelItem(node)
            nodes[key] = node
        # una carpeta por material no ayuda a navegar: solo se enseñan las que juntan dos o más
        least = 2 if self.kind == "materials" else 1
        for folder in idx.folders:
            key = os.path.normcase(folder)
            n = totals.get(key, 0)
            if key in nodes or key in self.hidden or n < least:
                continue
            parent = nodes.get(os.path.normcase(os.path.dirname(folder)))
            if parent is None:
                continue
            node = QtWidgets.QTreeWidgetItem(["%s  (%d)" % (os.path.basename(folder), n)])
            node.setData(0, ROLE_PATH, folder)
            node.setIcon(0, icon("folder"))
            parent.addChild(node)
            nodes[key] = node
        for key, node in nodes.items():
            if key in opened or (not had and key in roots_nc):
                node.setExpanded(True)
        if select is FAV:
            target = self.fav_node
        else:
            target = nodes.get(os.path.normcase(select)) if select else None
        target = target or top or (nodes.get(roots_nc[0]) if roots_nc else None) or self.fav_node
        if target is not None:
            self.tree.setCurrentItem(target)
        self.tree.blockSignals(False)

    def _tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        folder = it.data(0, ROLE_PATH) if it is not None else None
        if not folder:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction(icon("open"), "Abrir en el Explorador", lambda: os.startfile(folder))
        name = os.path.basename(folder.rstrip("\\/"))
        if os.path.normcase(folder) not in [os.path.normcase(r) for r in self.index.roots]:
            menu.addSeparator()
            menu.addAction(icon("hide"), "Ocultar esta carpeta", lambda: self._hide("paths", folder))
            menu.addAction("Ocultar todas las que se llamen «%s»" % name, lambda: self._hide("names", name))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _hide(self, kind, value):
        lst = self.settings.hidden[kind]
        if value not in lst:
            lst.append(value)
            self.settings.save()
        self.build_tree()
        self.update_items()

    # --- cuadrícula ---------------------------------------------------------
    def set_search(self, text):
        self.text = text
        self.update_items()

    def update_items(self):
        if self.index is None:
            return
        folder = self.current_folder()
        favs = self.current_is_fav()
        words = self.text.lower().split()
        base = os.path.normcase(folder).rstrip("\\/") if folder else None
        mats = self.kind == "materials"
        only_lib = mats and self.chip_lib.isChecked()
        only_size = mats and self.chip_size.isChecked()
        out = []
        for it in self.all_items():
            k = os.path.normcase(it.folder)
            if base and not (k == base or k.startswith(base + os.sep)):
                continue
            if k in self.hidden:
                continue
            if words and not it.matches(words):
                continue
            if only_lib and not it.is_library:
                continue
            if only_size and not self.size_for(it, known_only=True):
                continue
            if favs and not self.is_fav(it):
                continue
            out.append(it)
        if self.c_sort.currentData() == "recent":
            out.sort(key=lambda it: -it.mtime)
        if not favs and self.show_mode() == "both":
            out.sort(key=lambda it: not self.is_fav(it))       # estable: el orden de antes dentro de cada grupo
        self.model.set_items(out)
        self.view._pre.start()
        if self.text:
            self.title.setText("Resultados de «%s»" % self.text)
        elif favs:
            self.title.setText("Favoritos")
        elif folder:
            self.title.setText(os.path.basename(folder.rstrip("\\/")) or folder)
        else:
            self.title.setText(self.lib["name"] if self.lib else "")
        one, many = NOUNS.get(self.kind, NOUNS["materials"])
        self.count.setText("%d %s" % (len(out), one if len(out) == 1 else many))
        scanning = bool(self.scan_thread and self.scan_thread.isRunning())
        if out:
            self._empty("")
        elif scanning and not self.index.listing:
            self._empty("Leyendo las carpetas por primera vez…")
        elif self.text:
            self._empty("Nada coincide con «%s»." % self.text)
        elif favs:
            self._empty("Aún no hay favoritos.\nPulsa el corazón de una tarjeta (abajo a la derecha) para "
                        "marcarla; aparecerán aquí.")
        elif mats:
            self._empty("Aquí no hay materiales.\nUn material es un grupo de mapas con el mismo nombre "
                        "(…_basecolor, …_normal, …_roughness) o una biblioteca .mat.")
        elif self.kind == "interiors":
            self._empty("Aquí no hay habitaciones.\nSe reconocen los EXR de wParallax y ShadersBOX "
                        "(…_S_day_2K.exr, …_Single_Day.exr).")
        else:
            self._empty("No hay imágenes en esta carpeta.")
        self._on_selection()

    def _empty(self, msg):
        if msg:
            self.empty.setText("<div style='font-size:12pt'>%s</div>" % msg.replace("\n", "<br>"))
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.view)

    def set_thumb(self, v):
        self.delegate.thumb = v
        self.fit_grid()

    def fit_grid(self, force=False):
        cell = self.delegate.cell_size(minimum=True)
        sb = self.view.verticalScrollBar()
        extent = self.view.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent, None, sb)
        w = self.view.maximumViewportSize().width() - max(extent, sb.sizeHint().width()) - 1
        cols = max(1, w // cell.width())
        self.delegate.fill = max(self.delegate.thumb, w // cols - 12)
        grid = self.delegate.cell_size()
        if force or grid != self.view.gridSize():
            self.view.setGridSize(grid)
            self.view.doItemsLayout()

    def refresh_colors(self):
        self.delegate.refresh_colors()
        self.view.viewport().update()
        self._on_selection()

    def _on_balls(self, on):
        self.delegate.balls = bool(on)
        self.set_opt("balls", bool(on))
        self.view.viewport().update()

    def selected(self):
        rows = sorted(i.row() for i in self.view.selectionModel().selectedIndexes())
        return [self.model.items[r] for r in rows if r < len(self.model.items)]

    # --- medidas ------------------------------------------------------------
    @staticmethod
    def _xyz(size):
        """(ancho, largo[, alto]) -> tres valores; sin alto, el alto es el largo."""
        s = [float(v) for v in size]
        while len(s) < 3:
            s.append(s[-1])
        return tuple(s[:3])

    # --- lo guardado por material (medidas y mapeado) -------------------------
    # Se guarda con una clave relativa a la carpeta raíz de la pestaña («02_POLIIGON/bricks/...»), no con
    # la ruta entera: así vale igual abriendo la biblioteca como B:\ o como \\SERVIDOR\... Las claves
    # antiguas (ruta completa) se siguen leyendo y se cambian a la nueva al guardar.
    def pkey(self, it):
        key = getattr(it, "key", None)
        if not key or self.index is None:
            return key
        full = os.path.normcase(os.path.join(it.folder, it.name))
        suffix = key[len(full):] if key.startswith(full) else ""
        for r in self.index.roots:
            rn = os.path.normcase(r).rstrip("\\/")
            if full == rn or full.startswith(rn + os.sep):
                rel = os.path.relpath(full, rn).replace(os.sep, "/")
                return os.path.basename(rn) + "/" + rel + suffix
        return key

    def saved(self, store, it):
        d = self.settings.data.get(store, {})
        v = d.get(self.pkey(it))
        return v if v is not None else d.get(getattr(it, "key", None))

    def remember(self, store, items_values):
        """items_values: [(item, valor o None para quitarlo)]. Guarda con la clave nueva."""
        d = dict(self.settings.data.get(store, {}))
        for it, value in items_values:
            d.pop(getattr(it, "key", None), None)
            if value is None:
                d.pop(self.pkey(it), None)
            else:
                d[self.pkey(it)] = value
        self.settings.data[store] = d
        self.settings.save()

    def saved_size(self, it):
        saved = self.saved("surface_sizes", it)
        return self._xyz(saved) if saved else None

    def size_for(self, it, known_only=False):
        """Medidas X, Y, Z en cm: las guardadas para ese material, las del nombre o 100."""
        saved = self.saved_size(it)
        if saved:
            return saved
        size = getattr(it, "size", None)
        if isinstance(size, (tuple, list)) and size:
            return self._xyz(size)
        if known_only:
            return None
        return (100.0, 100.0, 100.0)

    def _on_mapping(self, save=False):
        """save: lo eligió la persona en el desplegable (se recuerda para el material seleccionado)."""
        mode = self.c_map.currentData()
        if save:
            self.set_opt("mapping", mode)
            sel = self.selected()
            if self.kind == "materials" and len(sel) == 1 and not sel[0].is_library:
                self.remember("surface_mapping", [(sel[0], mode)])
                self._show_detail(sel)
        show = self.kind != "interiors"
        used = AXES.get(mode, 3)
        for i, (lbl, spin) in enumerate(zip(self.size_lbls, self.spins)):
            lbl.setVisible(show)
            spin.setVisible(show)
            lbl.setEnabled(i < used)
            spin.setEnabled(i < used)
        self.cm_lbl.setVisible(show)
        self._update_reset()

    def mapping_for(self, it):
        """El mapeado guardado para ese material o, si no tiene, «UV del objeto». Triplanar solo si es cuadrada."""
        mode = self.saved("surface_mapping", it) or "uv"
        if mode == "triplanar" and self.aspect_for(it) not in (None, "square"):
            mode = "realworld"
        return mode if mode in AXES else "uv"

    def aspect_for(self, it):
        """"square", "wide", "tall" o None: por las medidas reales si se saben; si no, por los píxeles."""
        if not isinstance(it, surfaces.Material) or it.is_library:
            return None
        size = self.size_for(it, known_only=True)
        if size:
            return surfaces.aspect_kind(size[0], size[1])
        dims = self.index.dims_for(it) if self.index is not None else None
        return surfaces.aspect_kind(*dims) if dims else None

    def ratio_for(self, it):
        """(tipo, "2:1") para la marca de la tarjeta, o None."""
        kind = self.aspect_for(it)
        if not kind:
            return None
        if kind == "square":
            return kind, "1:1"
        size = self.size_for(it, known_only=True)
        if size:
            w, h = size[0], size[1]
        else:
            w, h = self.index.dims_for(it)
        r = max(w, h) / float(min(w, h))
        txt = ("%d" % round(r)) if abs(r - round(r)) < 0.08 else ("%.1f" % r).replace(".", ",")
        return kind, (txt + ":1" if kind == "wide" else "1:" + txt)

    def _set_triplanar_allowed(self, allowed):
        item = self.c_map.model().item(self.c_map.findData("triplanar"))
        if item is not None:
            item.setEnabled(allowed)
            item.setToolTip("" if allowed else "Solo para texturas cuadradas")

    def _update_reset(self):
        sel = self.selected()
        self.b_size_reset.setVisible(self.kind == "materials" and len(sel) == 1
                                     and self.saved_size(sel[0]) is not None)

    def _on_size_changed(self, _v):
        if not self._loading:
            self.size_timer.start()

    def _on_size_edited(self):
        """Lo que se escribe en X·Y·Z se queda guardado para el material seleccionado."""
        if self._loading or self.kind != "materials":
            return
        sel = self.selected()
        if len(sel) != 1 or getattr(sel[0], "is_library", False):
            return
        value = [round(s.value(), 2) for s in self.spins]
        self.store_size(sel[0], value)

    def store_size(self, it, value):
        known = it.size and self._xyz(it.size)
        same = known and all(abs(a - b) < 0.01 for a, b in zip(known, value))
        self.remember("surface_sizes", [(it, None if same else list(value))])
        self._show_detail(self.selected())
        self._update_reset()
        self.view.viewport().update()

    def _reset_size(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        self.remember("surface_sizes", [(sel[0], None)])
        self._on_selection()
        self.view.viewport().update()

    def _size_to_folder(self, it):
        """Copia las medidas de este material a todos los de su carpeta que no traen las suyas."""
        value = list(self.size_for(it))
        folder = os.path.normcase(it.folder)
        todo = []
        for other in self.all_items():
            if other is it or getattr(other, "is_library", False) or os.path.normcase(other.folder) != folder:
                continue
            if other.size or self.saved_size(other):
                continue
            todo.append((other, value))
        self.remember("surface_sizes", todo)
        n = len(todo)
        self.view.viewport().update()
        self.host.status.setText("Medidas %s puestas a %d materiales de «%s»." % (
            size_text(value), n, os.path.basename(it.folder)))

    def _on_light(self, _i):
        self.set_opt("light", self.c_light.currentData())
        self.delegate.light = self.c_light.currentData()
        self.view.viewport().update()

    def _on_selection(self):
        sel = self.selected()
        if len(sel) == 1 and self.kind == "materials" and not sel[0].is_library:
            self._loading = True
            for spin, v in zip(self.spins, self.size_for(sel[0])):
                spin.setValue(v)
            self._set_triplanar_allowed(self.aspect_for(sel[0]) in (None, "square"))
            self.c_map.setCurrentIndex(max(0, self.c_map.findData(self.mapping_for(sel[0]))))
            self._on_mapping()
            self._loading = False
        else:
            self._set_triplanar_allowed(True)
        self._update_reset()
        self._show_detail(sel)

    def _show_detail(self, sel):
        if not self.detail.isVisible():
            return
        muted, faint = theme.MUTED, theme.FAINT

        def cap(t):
            return ("<div style='color:%s; font-size:8pt; font-weight:600; letter-spacing:1px; "
                    "margin-top:14px'>%s</div>" % (faint, t))
        if len(sel) != 1:
            hint = {"materials": "Arrastra un material sobre un objeto de 3ds Max para ponérselo (con el mapeado y "
                                 "las medidas que tenga guardados; si el editor Slate está abierto, sale también "
                                 "ahí), o sobre el editor Slate para dejarlo solo ahí. Doble clic lo aplica a la "
                                 "selección.",
                    "textures": "Arrastra una o varias texturas sobre el editor Slate para tenerlas como mapas, o "
                                "sobre un objeto para crearle un material rápido.",
                    "interiors": "Arrastra una habitación sobre una ventana (plano o caja) de 3ds Max para "
                                 "ponérsela; si sueltas en el vacío, se crea el plano de la ventana con su tamaño. "
                                 "También puedes llevarla a Slate."}.get(self.kind, "")
            head = "%d seleccionados" % len(sel) if sel else ""
            self.detail_lbl.setText("<div style='font-size:11pt; font-weight:600'>%s</div>"
                                    "<div style='color:%s; margin-top:8px'>%s</div>" % (head, muted, hint))
            return
        it = sel[0]
        rows = ["<div style='font-size:12pt; font-weight:600'>%s</div>" % _esc(it.name),
                "<div style='color:%s'>%s</div>" % (muted, _esc(it.folder))]
        if isinstance(it, interiors.Room):
            rows.append(cap("VENTANA"))
            rows.append("<div>%s</div>" % room_text(it))
            rows.append("<div style='color:%s'>Al crear la ventana se hace un plano de ese tamaño; en tus planos "
                        "o cajas el OSL se adapta solo (multi planar).</div>" % muted)
            res = [r for r in it.resolutions() if r]
            if res:
                rows.append(cap("RESOLUCIONES"))
                rows.append("<div>%s</div>" % " · ".join("%dK" % r for r in res))
            rows.append(cap("SE CARGARÍA"))
            exr = self.room_exr(it)
            rows.append("<div>%s</div>" % _esc(os.path.basename(exr or "—")))
            rows.append(cap("SHADER OSL"))
            if it.osl:
                rows.append("<div>%s</div>" % _esc(os.path.basename(it.osl)))
            else:
                rows.append("<div style='color:%s'>No encuentro wParallax_SMP.osl (ni jiWindowBox) en estas "
                            "carpetas: sin él no se puede montar.</div>" % muted)
        elif isinstance(it, surfaces.Texture):
            role = {"color": "color (sRGB)", "data": "datos (lineal)", "normal": "normal (lineal)"}[
                surfaces.guess_role(os.path.basename(it.path))]
            rows.append(cap("TEXTURA"))
            rows.append("<div>%s</div>" % _esc(os.path.basename(it.path)))
            rows.append("<div style='color:%s'>Por el nombre se cargaría como %s.</div>" % (muted, role))
        elif it.is_library:
            rows.append(cap("BIBLIOTECA .MAT"))
            rows.append("<div>%s</div>" % _esc(os.path.basename(it.mat_file)))
            rows.append("<div style='color:%s'>A Slate van todos sus materiales; a los objetos, el primero. "
                        "Se cargan tal cual están guardados (motor, resolución y mapeado no se cambian).</div>"
                        % muted)
        else:
            rows.append(cap("TAMAÑO REAL"))
            saved = self.saved_size(it)
            size = self.size_for(it, known_only=True)
            if size:
                x, y, z = size
                text = "X %s · Y %s · Z %s cm" % (_fmt_cm(x), _fmt_cm(y), _fmt_cm(z))
                note = " (guardado para este material)" if saved else " (sacado del nombre)"
                rows.append("<div>%s<span style='color:%s'>%s</span></div>" % (text, muted, note))
            else:
                rows.append("<div style='color:%s'>No se sabe. Escríbelo arriba en X·Y·Z y se queda guardado "
                            "para este material.</div>" % muted)
            kind = self.aspect_for(it)
            if kind:
                rows.append("<div style='color:%s'>Textura %s</div>" % (muted, {
                    "square": "cuadrada: vale el triplanar", "wide": "rectangular (más ancha que alta)",
                    "tall": "rectangular (más alta que ancha)"}[kind]))
            rows.append("<div style='color:%s'>Mapeado: %s</div>" % (muted, dict(MAPPINGS)[self.mapping_for(it)]))
            res = [r for r in it.resolutions() if r]
            if res:
                rows.append(cap("RESOLUCIONES"))
                rows.append("<div>%s</div>" % " · ".join("%dK" % r for r in res))
            rows.append(cap("MAPAS QUE SE CARGARÍAN"))
            picked = self.maps_for(it)
            for ch in surfaces.CHANNEL_ORDER:
                if ch not in picked:
                    continue
                info = surfaces.CHANNEL_INFO[ch]
                note = ""
                if ch in ("ao",):
                    note = " <span style='color:%s'>(no se conecta)</span>" % faint
                rows.append("<div style='margin-top:3px'><span style='color:%s'>●</span> <b>%s</b>%s<br>"
                            "<span style='color:%s'>%s</span></div>"
                            % (info[2], info[3], note, muted, _esc(os.path.basename(picked[ch]))))
            if it.tiles:
                rows.append("<div style='color:%s; margin-top:8px'>%d lamas sueltas: de momento se usa la "
                            "primera.</div>" % (muted, it.tiles))
        self.detail_lbl.setText("".join(rows))

    # --- envío a 3ds Max ----------------------------------------------------
    def maps_for(self, mat):
        res = self.c_res.currentData()
        if res == "max":
            return mat.pick()
        if res == "min":
            return mat.pick(lowest=True)
        return mat.pick(res)

    def room_exr(self, room):
        res = self.c_res.currentData()
        light = self.c_light.currentData()
        if res == "max":
            return room.pick(light)
        if res == "min":
            return room.pick(light, lowest=True)
        return room.pick(light, res)

    def _on_dropped(self, items, pid, titles):
        inst = next((m for m in self.host.maxes if m.pid == pid), None)
        if inst is None and pid:
            # un Max recién abierto que la app aún no ha visto: se busca ahora mismo
            inst = next((m for m in maxlink.discover(timeout=0.4) if m.pid == pid), None)
            if inst is not None:
                self.host._discover()
        if inst is None:
            self.host.status.setText("Suelta sobre un 3ds Max abierto con el puente instalado.")
            return
        # Max comprueba además si el ratón está sobre su editor Slate (acoplado o no)
        self.send("slate" if maxlink.is_slate(titles) else "cursor", items, inst)

    def send(self, target, items=None, inst=None, mapping=None):
        items = items or self.selected()
        if not items:
            return
        inst = self.host._need_max(inst)
        if inst is None:
            return
        need = 5          # 4 acierta el objeto bajo el ratón; 5 sabe qué materiales ya están en la escena
        if inst.protocol < need:
            QtWidgets.QMessageBox.information(
                self, "OpenLibrary",
                "El puente instalado en este 3ds Max es anterior a esta función.\n\n"
                "Actualízalo en Ajustes > Instalación y reinicia 3ds Max.")
            return
        if inst.busy:
            self.host.status.setText("3ds Max está ocupado con la orden anterior.")
            return
        engine = self.c_engine.currentData()
        mapping = mapping or self.c_map.currentData()
        sizes = [s.value() for s in self.spins]
        if self.kind == "interiors":
            room = items[0]
            exr = self.room_exr(room)
            if not room.osl:
                QtWidgets.QMessageBox.information(
                    self, "OpenLibrary", "No encuentro el shader de wParallax (wParallax_SMP.osl) en las carpetas "
                    "de esta pestaña. Añade la carpeta que lo trae (OSL_Shaders) a la pestaña.")
                return
            preview = room.thumb_source(self.c_light.currentData()) or ""
            self.host._run_in_max(inst, room.name, lambda: inst.call(
                "apply_interior", timeout=MAX_WAIT, name=room.name, exr=exr, osl=room.osl, preview=preview,
                size_code=room.size,
                width=room.width(), height=interiors.HEIGHT, engine=engine, depth=self.c_depth.currentData(),
                target=target), lambda res, err: self._done(res, err, target))
            return
        if self.kind == "textures":
            files = [it.path for it in items]
            mode = self.c_role.currentData()
            roles = [surfaces.guess_role(os.path.basename(f)) if mode == "auto" else mode for f in files]
            label = "Texturas" if len(files) > 1 else items[0].name
            self.host._run_in_max(inst, label, lambda: inst.call(
                "add_textures", timeout=MAX_WAIT, files=files, roles=roles, engine=engine, mapping=mapping,
                size=sizes, target=target), lambda res, err: self._done(res, err, target))
            return
        mat = items[0]
        if mat.is_library:
            self.host._run_in_max(inst, mat.name, lambda: inst.call(
                "apply_library", timeout=MAX_WAIT, mat_file=mat.mat_file, target=target),
                lambda res, err: self._done(res, err, target))
            return
        disp = self.chip_disp.isChecked()
        if target == "slate":
            # todos los seleccionados, cada uno con sus medidas y su mapeado; los que ya están, se buscan
            mats = [m for m in items if not m.is_library]
            payload = [self._payload(m) for m in mats]
            label = mats[0].name if len(mats) == 1 else "%d materiales" % len(mats)
            self.host._run_in_max(inst, label, lambda: inst.call(
                "apply_materials", timeout=MAX_WAIT, items=payload, engine=engine, displacement=disp,
                existing="use"), lambda res, err: self._done(res, err, target))
            return
        p = self._payload(mat)

        def checked(res, err):
            if err is not None or not isinstance(res, dict):
                return
            route = res.get("route", target)
            existing = "use" if route == "slate" else "new"
            if route != "slate" and res.get("existing"):
                existing = self._ask_existing(mat.name)
                if existing is None:
                    self.host.status.setText("«%s»: cancelado." % mat.name)
                    return
            self.host._run_in_max(inst, mat.name, lambda: inst.call(
                "apply_material", timeout=MAX_WAIT, engine=engine, displacement=disp, target=route,
                existing=existing, routed=True, **p), lambda r, e: self._done(r, e, route))
        # primero: adónde va (lo de debajo del ratón, ahora que aún está ahí) y si ya está en la escena
        self.host._run_in_max(inst, mat.name, lambda: inst.call(
            "check_drop", timeout=MAX_WAIT, target=target, names=[mat.name]), checked)

    def _payload(self, mat):
        """Nombre, mapas, mapeado y medidas de un material para el puente."""
        maps = dict(self.maps_for(mat))
        normal = maps.get("normal")
        if normal and surfaces.parse_name(os.path.basename(normal))["dx"]:
            maps["normaldx"] = maps.pop("normal")
        mapping = self.mapping_for(mat)
        if mapping not in ("uv", "realworld", "uvw", "triplanar"):
            mapping = "uv"
        return {"name": mat.name, "maps": maps, "mapping": mapping, "size": list(self.size_for(mat))}

    def _ask_existing(self, name):
        """«name» ya está en la escena: "use" (ponerle el de la escena), "new" (uno nuevo, «name_01») o None."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("OpenLibrary")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("«%s» ya está en la escena." % name)
        box.setInformativeText("¿Le pongo el que ya hay o meto uno nuevo (se llamará «%s_01»)?" % name)
        use = box.addButton("Usar el de la escena", QtWidgets.QMessageBox.AcceptRole)
        new = box.addButton("Meter uno nuevo", QtWidgets.QMessageBox.ActionRole)
        box.addButton("Cancelar", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(use)
        self.window().raise_()
        self.window().activateWindow()
        box.exec()
        return {use: "use", new: "new"}.get(box.clickedButton())

    def _done(self, res, err, target):
        if err is not None or not isinstance(res, dict):
            return
        name = res.get("name") or "Las texturas"
        n = res.get("count", 0)
        if res.get("where", "").startswith("objects"):
            msg = "«%s» puesto a %d objeto%s." % (name, n, "" if n == 1 else "s")
            if res["where"].endswith("slate"):
                msg += " También está en la vista activa de Slate."
            if res.get("library", 1) > 1:
                msg += " La biblioteca trae %d materiales: los demás, con «Al Slate»." % res["library"]
        elif res.get("where") == "plane":
            msg = "«%s»: ventana creada en 3ds Max (seleccionada para moverla a su sitio)." % name
        elif res.get("where") == "slate":
            added = res.get("added", n)
            if not n:
                msg = "No pude abrir el editor Slate en 3ds Max."
            elif added < n:
                msg = "%s: en Slate (%d ya estaba%s en la escena: seleccionado%s)." % (
                    name, n - added, "n" if n - added > 1 else "", "s" if n - added > 1 else "")
            else:
                msg = "%s: %d nodo%s en la vista activa de Slate." % (name, n, "" if n == 1 else "s")
        else:
            msg = "No hay objetos seleccionados en 3ds Max: selecciónalos o usa «Al Slate»."
            if self.kind == "interiors":
                msg = "No hay objetos seleccionados en 3ds Max: selecciona la ventana o usa «Crear ventana»."
        self.host.status.setText(msg)

    def _item_menu(self, pos):
        sel = self.selected()
        if not sel:
            return
        it = sel[0]
        menu = QtWidgets.QMenu(self)
        mats = self.kind == "materials"
        all_fav = all(self.is_fav(s) for s in sel)
        fav_act = QtWidgets.QAction(ui_fav.heart_icon(), "Quitar de favoritos" if all_fav else "Añadir a favoritos", menu)
        fav_act.triggered.connect(lambda: self.toggle_fav(sel))
        menu.addAction(fav_act)
        menu.addSeparator()
        if self.kind == "interiors":
            menu.addAction(icon("check"), "Aplicar a la selección de 3ds Max", lambda: self.send("selection"))
            menu.addAction("Crear la ventana en 3ds Max", lambda: self.send("plane"))
            menu.addAction("Poner en el editor Slate", lambda: self.send("slate"))
            menu.addSeparator()
            menu.addAction(icon("open"), "Mostrar en el Explorador", lambda: self._reveal(it))
            menu.addAction("Copiar la ruta del EXR", lambda: QtWidgets.QApplication.clipboard().setText(
                self.room_exr(it) or ""))
            menu.exec(self.view.viewport().mapToGlobal(pos))
            return
        menu.addAction(icon("check"), "Aplicar a la selección de 3ds Max" if mats else
                       "Material rápido en la selección", lambda: self.send("selection"))
        menu.addAction("Poner en el editor Slate", lambda: self.send("slate"))
        if mats and not it.is_library:
            menu.addSeparator()
            if self.saved_size(it):
                menu.addAction("Volver a las medidas del nombre", self._reset_size)
            menu.addAction("Usar estas medidas en toda la carpeta (los que no tienen)",
                           lambda: self._size_to_folder(it))
        menu.addSeparator()
        menu.addAction(icon("open"), "Mostrar en el Explorador", lambda: self._reveal(it))
        if mats and not it.is_library:
            menu.addAction("Copiar la lista de mapas", lambda: QtWidgets.QApplication.clipboard().setText(
                "\n".join(self.maps_for(it).values())))
        else:
            menu.addAction("Copiar la ruta", lambda: QtWidgets.QApplication.clipboard().setText(
                it.mat_file if mats else it.path))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    # --- vista rápida (doble clic o Espacio) -----------------------------------
    def _big_source(self, it):
        """(clave de la miniatura, imagen grande) de un material, textura o habitación."""
        if isinstance(it, interiors.Room):
            light = self.delegate.light
            return it.key + "|" + light, it.thumb_source(light)
        if isinstance(it, surfaces.Material):
            if it.preview:
                return it.key, it.preview
            m = it.pick()                       # el mapa de color a la resolución más alta
            return it.key, m.get("color") or it.thumb_source()
        return it.key, it.path

    def quick_look(self):
        idx = self.view.currentIndex()
        it = idx.data(ROLE_ITEM) if idx.isValid() else None
        if it is None:
            return
        if self.quick is None:
            from .ui_inspector import QuickLook
            self.quick = QuickLook(self)
            self.quick.step.connect(self._quick_step)
        self._quick_show(it)
        self.quick.exec()

    def _quick_show(self, it):
        key, path = self._big_source(it)
        self.quick.show_image(it.name, it.folder, path, self.loader.images.get(key))

    def _quick_step(self, delta):
        row = self.view.currentIndex().row() + delta
        if 0 <= row < self.model.rowCount():
            idx = self.model.index(row)
            self.view.setCurrentIndex(idx)
            self.view.scrollTo(idx)
            self._quick_show(idx.data(ROLE_ITEM))

    @staticmethod
    def _reveal(it):
        target = getattr(it, "path", None) or getattr(it, "mat_file", None)
        if not target:
            files = it.all_files()
            target = files[0] if files else it.folder
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
        except OSError:
            pass

    def shutdown(self):
        for th in list(self.scans.values()):
            if th.isRunning():
                th.cancel()
                th.wait(3000)


ZWSP = chr(0x200B)


def _esc(s):
    # con un corte invisible tras «_» y «\» para que los nombres largos no se salgan del panel
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace("_", "_" + ZWSP).replace(chr(92), chr(92) + ZWSP)
