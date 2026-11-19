"""Inspector lateral (preview grande, datos y acciones del asset) y vista rápida a pantalla completa."""
import datetime
import os

from . import icon, theme
from .qt import QtCore, QtGui, QtWidgets

ENGINE_LABEL = {"corona": "Corona", "vray": "V-Ray", "fstorm": "FStorm", "other": "otro motor"}
ENGINE_COLOR = {"corona": "#F4712B", "vray": "#2857AF", "fstorm": "#A7A7A7", "other": "#7A7A7A"}


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _BigSignals(QtCore.QObject):
    loaded = QtCore.Signal(str, QtGui.QImage)


class _BigJob(QtCore.QRunnable):
    """Lee la preview original (no la miniatura) sin bloquear la ventana."""

    def __init__(self, path, max_px, signals):
        super(_BigJob, self).__init__()
        self.path, self.max_px, self.signals = path, max_px, signals

    def run(self):
        reader = QtGui.QImageReader(self.path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > self.max_px:
            size.scale(self.max_px, self.max_px, QtCore.Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        try:
            self.signals.loaded.emit(self.path, reader.read())
        except RuntimeError:
            pass


class BigImageLoader(QtCore.QObject):
    """Carga en segundo plano la imagen grande; solo interesa la última pedida."""
    ready = QtCore.Signal(str, QtGui.QImage)

    def __init__(self, max_px, parent=None):
        super(BigImageLoader, self).__init__(parent)
        self.max_px = max_px
        self.pool = QtCore.QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = _BigSignals()
        self.signals.loaded.connect(self._on_loaded)
        self.cache = {}
        self.wanted = None

    def request(self, path):
        self.wanted = path
        img = self.cache.get(path)
        if img is not None:
            self.ready.emit(path, img)
            return
        self.pool.start(_BigJob(path, self.max_px, self.signals))

    def _on_loaded(self, path, img):
        if len(self.cache) > 24:
            self.cache.clear()
        self.cache[path] = img
        if path == self.wanted:
            self.ready.emit(path, img)

    def forget(self, path):
        self.cache.pop(path, None)


class PreviewLabel(QtWidgets.QWidget):
    """Imagen cuadrada con esquinas redondeadas que llena el ancho del inspector."""
    clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super(PreviewLabel, self).__init__(parent)
        self.image = None
        self.text = ""
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    def sizeHint(self):
        return QtCore.QSize(280, 280)

    def resizeEvent(self, event):
        if self.height() != self.width():
            self.setFixedHeight(self.width())
        super(PreviewLabel, self).resizeEvent(event)

    def set_image(self, image, text=""):
        self.image = image if image is not None and not image.isNull() else None
        self.text = text
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        r = QtCore.QRectF(self.rect())
        path = QtGui.QPainterPath()
        rad = theme.RADIUS + 1 if theme.RADIUS else 0
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        if self.image is None:
            p.fillRect(r, theme.color(theme.SURFACE))
            p.setPen(theme.color(theme.FAINT))
            p.drawText(r, QtCore.Qt.AlignCenter, self.text)
            return
        p.fillRect(r, QtGui.QColor(self.image.pixel(1, 1)))
        s = QtCore.QSizeF(self.image.size())
        s.scale(r.size(), QtCore.Qt.KeepAspectRatio)
        t = QtCore.QRectF(QtCore.QPointF(0, 0), s)
        t.moveCenter(r.center())
        p.drawImage(t, self.image)


class Inspector(QtWidgets.QFrame):
    """Panel derecho: lo que en Connecter o Cosmos es la ficha del asset."""
    open_requested = QtCore.Signal()
    place_requested = QtCore.Signal()
    proxy_requested = QtCore.Signal()
    original_requested = QtCore.Signal()
    reveal_requested = QtCore.Signal()
    zoom_requested = QtCore.Signal()
    missing_requested = QtCore.Signal()
    stats_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super(Inspector, self).__init__(parent)
        self.setObjectName("Inspector")
        self.setMinimumWidth(250)
        self.big = BigImageLoader(700, self)
        self.big.ready.connect(self._on_big)
        self._path = None
        self._connected = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        body = QtWidgets.QWidget()
        body.setAutoFillBackground(False)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        self.preview = PreviewLabel()
        self.preview.setToolTip("Ver en grande (Espacio)")
        self.preview.clicked.connect(self.zoom_requested)
        lay.addWidget(self.preview)

        self.name = QtWidgets.QLabel()
        self.name.setObjectName("InspectorName")
        self.name.setWordWrap(True)
        self.name.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.name)
        self.path_lbl = QtWidgets.QLabel()
        self.path_lbl.setObjectName("Muted")
        self.path_lbl.setWordWrap(True)
        self.path_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.path_lbl)

        self.b_open = QtWidgets.QPushButton("Abrir en 3ds Max")
        self.b_open.setObjectName("Primary")
        self.b_open.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_open.setToolTip("Abre el .max del asset en un 3ds Max nuevo para editarlo; los que tengas "
                               "abiertos no se tocan.\n"
                               "Para meterlo en tu escena: arrastra la miniatura a Max o usa los botones de abajo.")
        self.b_open.clicked.connect(self.open_requested)
        lay.addWidget(self.b_open)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        self.b_place = QtWidgets.QPushButton("Colocar")
        self.b_place.setToolTip("Merge en la escena abierta y colocarlo con el ratón")
        self.b_place.clicked.connect(self.place_requested)
        row.addWidget(self.b_place, 1)
        self.b_proxy = QtWidgets.QPushButton("Proxy")
        self.b_proxy.setToolTip("Merge como proxy (Corona o V-Ray) y colocarlo con el ratón")
        self.b_proxy.clicked.connect(self.proxy_requested)
        row.addWidget(self.b_proxy, 1)
        self.b_orig = QtWidgets.QPushButton("Original")
        self.b_orig.setToolTip("Merge en su posición original, sin colocar con el ratón")
        self.b_orig.clicked.connect(self.original_requested)
        row.addWidget(self.b_orig, 1)
        b_rev = QtWidgets.QToolButton()
        b_rev.setIcon(icon("folder"))
        self.b_rev = b_rev
        b_rev.setToolTip("Mostrar en el explorador")
        b_rev.setCursor(QtCore.Qt.PointingHandCursor)
        b_rev.clicked.connect(self.reveal_requested)
        row.addWidget(b_rev)
        lay.addLayout(row)
        self.hint = QtWidgets.QLabel()
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        self.details = QtWidgets.QLabel()
        self.details.setTextFormat(QtCore.Qt.RichText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.details.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        lay.addWidget(self.details)
        self.b_stats = QtWidgets.QPushButton("Leer caras, vértices y animación")
        self.b_stats.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_stats.setToolTip("Abre el .max con un 3ds Max en segundo plano (sin tocar el tuyo) y apunta sus "
                                "caras, vértices, objetos, si tiene desplazamiento y si tiene animación.\n"
                                "También se apuntan solos al generar previews en lote.")
        self.b_stats.clicked.connect(self.stats_requested)
        self.b_stats.setVisible(False)
        lay.addWidget(self.b_stats)
        self.b_missing = QtWidgets.QPushButton("Ver archivos que faltan…")
        self.b_missing.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_missing.setToolTip("Abre la lista en grande, con la ruta donde debería estar cada uno, para "
                                  "re-enlazarlos a mano o quitarlos del .max")
        self.b_missing.clicked.connect(self.missing_requested)
        self.b_missing.setVisible(False)
        lay.addWidget(self.b_missing)
        self.details2 = QtWidgets.QLabel()
        self.details2.setTextFormat(QtCore.Qt.RichText)
        self.details2.setWordWrap(True)
        self.details2.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        lay.addWidget(self.details2)
        for w in (self.name, self.path_lbl, self.hint, self.details, self.details2):
            w.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            w.setMinimumWidth(1)
        lay.addStretch(1)
        self._actions = (self.b_open, self.b_place, self.b_proxy, self.b_orig, b_rev)
        self.clear()

    def retheme(self):
        self.b_rev.setIcon(icon("folder"))
        self.preview.update()

    # --- Estado -------------------------------------------------------------
    def set_connected(self, engine):
        """engine: motor del Max de destino, o None si no hay Max conectado."""
        self._connected = engine
        on = engine is not None and self._path is not False
        self.b_place.setEnabled(on)
        self.b_orig.setEnabled(on)
        self.b_proxy.setEnabled(on and engine in ("corona", "vray"))
        if engine is None:
            self.hint.setText("Para colocarlo en una escena, abre 3ds Max con el puente instalado. «Abrir en 3ds Max» "
                              "funciona siempre.")
        elif engine not in ("corona", "vray"):
            self.hint.setText("El proxy necesita Corona o V-Ray como motor de la escena.")
        else:
            self.hint.setText("")
        self.hint.setVisible(bool(self.hint.text()) and self._path is not False)

    def clear(self, msg="Selecciona un asset para ver su ficha."):
        self._path = False
        self.big.wanted = None
        self.preview.set_image(None, "")
        self.name.setText("")
        self.path_lbl.setText("")
        self.details.setText("<span style='color:%s'>%s</span>" % (theme.MUTED, _esc(msg)))
        self.details2.setText("")
        self.b_missing.setVisible(False)
        self.b_stats.setVisible(False)
        for w in self._actions + (self.preview, self.name, self.path_lbl, self.hint):
            w.setVisible(False)

    def show_asset(self, a, image, engine_cache, check_cache, scene_engine, proxy_ready, status, stats=None,
                   reading=False):
        """stats(archivo) -> datos de modelstats (o None si no se han leído). reading: se están leyendo."""
        for w in self._actions + (self.preview, self.name, self.path_lbl):
            w.setVisible(True)
        self._path = a.preview
        self.preview.set_image(image, "cargando…" if a.preview else "sin preview")
        if a.preview:
            self.big.request(a.preview)
        self.name.setText(a.name)
        self.path_lbl.setText(a.folder.replace("\\", "\​"))
        self.set_connected(self._connected)

        def cap(t):
            return ("<div style='color:%s; font-size:8pt; font-weight:600; margin-top:12px; "
                    "margin-bottom:2px'>%s</div>" % (theme.FAINT, t))

        rows = [cap("VERSIONES")]
        missing_stats = 0
        files = [(e, p) for e, p in sorted(a.versions.items())] + \
                [(engine_cache.get(p) or "pending", p) for p in a.auto_files]
        for eng, p in files:
            try:
                st = os.stat(p)
                extra = "%.1f MB · %s" % (st.st_size / 1048576.0,
                                         datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y"))
            except OSError:
                extra = "no accesible"
            label = ENGINE_LABEL.get(eng, "detectando…")
            mark = " &nbsp;<span style='color:%s'>✔ motor de la escena</span>" % theme.OK if eng == scene_engine else ""
            rows.append("<span style='color:%s'>●</span> %s%s<br><span style='color:%s'>%s<br>%s</span>%s" % (
                ENGINE_COLOR.get(eng, "#555"), label, mark, theme.MUTED, _esc(os.path.basename(p)), extra,
                self._stats_html(stats(p) if stats else None, reading)))
            if stats and not stats(p):
                missing_stats += 1
        if not files:
            rows.append("<span style='color:%s'>No hay ningún .max</span>" % theme.MUTED)
        self.b_stats.setVisible(bool(files) and stats is not None and not reading)
        self.b_stats.setText("Leer caras, vértices y animación" if missing_stats else "Volver a leer los datos")

        known, total, missing, relinkable = status
        rows.append(cap("ARCHIVOS EXTERNOS"))
        if not known:
            rows.append("<span style='color:%s'>revisando…</span>" % theme.MUTED)
        elif not (missing or relinkable):
            rows.append("%d, todos en su sitio" % total if total else "ninguno")
        else:
            rows.append("<span style='color:%s'>⚠ %d de %d fuera de su ruta</span>" % (
                theme.WARN, len(missing) + len(relinkable), total))
            if relinkable:
                rows.append("%d se re-enlazan solos al importar" % len(relinkable))
            if missing:
                # primero, todos los que faltan por su nombre
                names = sorted(set(os.path.basename(m.replace("/", "\\")) for m in missing), key=lambda s: s.lower())
                rows.append("<span style='color:%s'>Sin encontrar (%d):</span>" % (theme.MUTED, len(names)))
                rows += ["<span style='color:%s'>· %s</span>" % (theme.MUTED, _esc(n)) for n in names[:60]]
                if len(names) > 60:
                    rows.append("<span style='color:%s'>… y %d más (ábrelos en grande)</span>"
                                % (theme.MUTED, len(names) - 60))
        self.b_missing.setVisible(bool(known and (missing or relinkable)))
        self.details.setText("".join(r if r.startswith("<div") else "<div>%s</div>" % r for r in rows))

        rows = [cap("PROXY")]
        rows.append("Ya creado: entra al instante" if proxy_ready else
                    "<span style='color:%s'>Se crea la primera vez que lo uses como proxy</span>" % theme.MUTED)
        if not a.preview:
            rows.append(cap("PREVIEW"))
            rows.append("<span style='color:%s'>No tiene. Selecciona el objeto en Max y pulsa Preview.</span>"
                        % theme.MUTED)
        self.details2.setText("".join(r if r.startswith("<div") else "<div>%s</div>" % r for r in rows))

    def _on_big(self, path, img):
        if path == self._path and not img.isNull():
            self.preview.set_image(img)

    @staticmethod
    def _stats_html(st, reading):
        """Caras, vértices y objetos, y etiquetas de desplazamiento y animación."""
        from . import modelstats
        if st is None:
            text = "leyendo los datos…" if reading else "caras y vértices sin leer"
            return "<br><span style='color:%s'>%s</span>" % (theme.FAINT, text)
        if st.get("error"):
            return "<br><span style='color:%s'>no se pudieron leer los datos de este .max</span>" % theme.WARN
        tags = []
        if st.get("disp"):
            tags.append("desplazamiento")
        if st.get("anim"):
            tags.append("animación %d–%d" % (st.get("start", 0), st.get("end", 0)))
        tag_html = "".join("<span style='color:%s'> &nbsp;▪ %s</span>" % (theme.ACCENT, t) for t in tags) \
            or "<span style='color:%s'> &nbsp;sin desplazamiento ni animación</span>" % theme.MUTED
        return "<br>%s<br>%s" % (modelstats.summary(st), tag_html)


class QuickLook(QtWidgets.QDialog):
    """Vista rápida: la preview en grande sobre la ventana. Espacio/Esc cierra, flechas cambian de asset."""
    step = QtCore.Signal(int)

    def __init__(self, parent):
        super(QuickLook, self).__init__(parent, QtCore.Qt.FramelessWindowHint | QtCore.Qt.Dialog)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.image = None
        self.title = ""
        self.sub = ""
        self.big = BigImageLoader(2000, self)
        self.big.ready.connect(self._on_big)
        self._path = None

    def show_asset(self, a, fallback):
        self.show_image(a.name, a.folder, a.preview, fallback)

    def show_image(self, title, sub, path, fallback):
        """La imagen path en grande (mientras carga, fallback: la miniatura)."""
        self.title = title
        self.sub = sub
        self._path = path
        self.image = fallback if fallback is not None and not fallback.isNull() else None
        if path:
            self.big.request(path)
        top = self.parent().window()
        self.setGeometry(top.geometry())
        self.update()

    def _on_big(self, path, img):
        if path == self._path and not img.isNull():
            self.image = img
            self.update()

    def keyPressEvent(self, event):
        k = event.key()
        if k in (QtCore.Qt.Key_Escape, QtCore.Qt.Key_Space, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.accept()
        elif k in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Down):
            self.step.emit(1)
        elif k in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Up):
            self.step.emit(-1)

    def mousePressEvent(self, event):
        self.accept()

    def wheelEvent(self, event):
        self.step.emit(-1 if event.angleDelta().y() > 0 else 1)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QtGui.QColor(8, 9, 11, 225))
        area = QtCore.QRectF(self.rect()).adjusted(40, 30, -40, -90)
        if self.image is not None:
            s = QtCore.QSizeF(self.image.size())
            s.scale(area.size(), QtCore.Qt.KeepAspectRatio)
            t = QtCore.QRectF(QtCore.QPointF(0, 0), s)
            t.moveCenter(area.center())
            p.drawImage(t, self.image)
        else:
            p.setPen(QtGui.QColor("#8D94A0"))
            p.drawText(area, QtCore.Qt.AlignCenter, "sin preview")
        f = QtGui.QFont(self.font())
        f.setPointSizeF(14)
        f.setWeight(QtGui.QFont.DemiBold)
        p.setFont(f)
        p.setPen(QtGui.QColor("#E8EAEE"))
        cap = QtCore.QRectF(40, self.height() - 80, self.width() - 80, 30)
        p.drawText(cap, QtCore.Qt.AlignCenter, self.title)
        f.setPointSizeF(9)
        f.setWeight(QtGui.QFont.Normal)
        p.setFont(f)
        p.setPen(QtGui.QColor("#8D94A0"))
        p.drawText(cap.translated(0, 28), QtCore.Qt.AlignCenter,
                   "%s   ·   ← →  cambiar   ·   Espacio / Esc  cerrar" % self.sub)
