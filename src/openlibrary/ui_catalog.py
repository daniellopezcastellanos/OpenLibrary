"""Ventana «Catalogar»: abrir una descarga (zip, rar, 7z... o una carpeta), repartir sus
archivos en .max / preview / texturas, ponerle nombre y dejarla en una carpeta de la biblioteca."""
import os
import shutil
import uuid

from . import app_icon, archives, catalog, config, icon, library, maxfile, theme
from .qt import QtCore, QtGui, QtWidgets

ROLE_ITEM = QtCore.Qt.UserRole + 1
ROLE_PATH = QtCore.Qt.UserRole + 2
ENGINE_LABEL = {"corona": "Corona", "vray": "V-Ray", "fstorm": "FStorm"}
THUMB = 44
_THUMB_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


class _Worker(QtCore.QThread):
    """Ejecuta fn() fuera del hilo de la interfaz."""
    finished_ok = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    progress = QtCore.Signal(int, int)

    def __init__(self, fn, parent=None):
        super(_Worker, self).__init__(parent)
        self.fn = fn

    def run(self):
        try:
            res = self.fn()
        except Exception as exc:        # se enseña en la ventana
            self.failed.emit(exc)
        else:
            self.finished_ok.emit(res)


class _Bucket(QtWidgets.QListWidget):
    """Lista de archivos; se arrastran de una lista a otra."""
    changed = QtCore.Signal()

    def __init__(self, kind, parent=None):
        super(_Bucket, self).__init__(parent)
        self.kind = kind
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
        self.setIconSize(QtCore.QSize(THUMB, THUMB))
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def _ok(self, event):
        return isinstance(event.source(), _Bucket) and event.source() is not self

    def dragEnterEvent(self, event):
        if self._ok(event):
            event.setDropAction(QtCore.Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event):
        if not self._ok(event):
            event.ignore()
            return
        self.take_from(event.source())
        event.setDropAction(QtCore.Qt.CopyAction)      # ya se han movido a mano: que Qt no borre nada
        event.accept()

    def take_from(self, other, items=None):
        items = items if items is not None else other.selectedItems()
        rows = sorted((other.row(it) for it in items), reverse=True)
        moved = [other.takeItem(r) for r in rows]
        self.clearSelection()
        for it in reversed(moved):
            self.addItem(it)
            it.setSelected(True)
        if moved:
            other.changed.emit()
            self.changed.emit()

    def entries(self):
        return [self.item(i).data(ROLE_ITEM) for i in range(self.count())]


class CatalogDialog(QtWidgets.QDialog):
    catalogued = QtCore.Signal(str, bool)       # carpeta de destino, ¿se ocultó la carpeta de texturas?

    def __init__(self, settings, index, hidden, current_folder=None, parent=None):
        super(CatalogDialog, self).__init__(parent)
        self.settings = settings
        self.index = index
        self.hidden = hidden or set()
        self.cfg = settings.data.setdefault("catalog", {})
        self.tmp_root = os.path.join(config.app_data_dir(), "catalog_tmp")
        shutil.rmtree(self.tmp_root, ignore_errors=True)       # restos de otra vez
        self.work_dir = None         # carpeta temporal con lo extraído (None si se abrió una carpeta)
        self.source = None
        self.engines = {}            # ruta del .max -> motor
        self.worker = None
        self.proc = []               # proceso del descompresor, para poder cancelarlo
        self.thumb_queue = []
        self.cancelled = False
        self.thumb_timer = QtCore.QTimer(self)
        self.thumb_timer.setInterval(0)
        self.thumb_timer.timeout.connect(self._next_thumb)
        self.setWindowTitle("OpenLibrary - Catalogar")
        self.setWindowIcon(app_icon())
        self.resize(1240, 780)
        self.setAcceptDrops(True)
        self._build()
        self._fill_tree(current_folder)
        self._refresh()

    # --- interfaz ---------------------------------------------------------------------
    def _caption(self, text, hint=""):
        lab = QtWidgets.QLabel(text + ("  <span style='font-weight:400;letter-spacing:0'>%s</span>" % hint
                                       if hint else ""))
        lab.setObjectName("Caption")
        return lab

    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        top = QtWidgets.QHBoxLayout()
        self.b_open = QtWidgets.QPushButton(icon("catalog"), " Abrir comprimido…")
        self.b_open.setToolTip("Elegir el .zip, .rar, .7z… que te has descargado. Si viene en partes, vale cualquiera.")
        self.b_open.clicked.connect(self._choose_archive)
        top.addWidget(self.b_open)
        self.b_folder = QtWidgets.QPushButton(icon("folder"), " Abrir carpeta…")
        self.b_folder.setToolTip("Si ya lo tienes descomprimido: se copian los archivos, la carpeta no se toca.")
        self.b_folder.clicked.connect(self._choose_folder)
        top.addWidget(self.b_folder)
        self.src_lbl = QtWidgets.QLabel("Elige una descarga o arrástrala a esta ventana.")
        self.src_lbl.setObjectName("Muted")
        self.src_lbl.setContentsMargins(8, 0, 0, 0)
        top.addWidget(self.src_lbl, 1)
        lay.addLayout(top)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setHandleWidth(10)
        split.setChildrenCollapsible(False)

        self.buckets = {}
        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        ll.addWidget(self._caption("NO SE COPIA", "lo que dejes aquí se queda fuera"))
        self.buckets["skip"] = _Bucket("skip")
        ll.addWidget(self.buckets["skip"], 1)
        split.addWidget(left)

        mid = QtWidgets.QWidget()
        ml = QtWidgets.QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(6)
        self.captions = {}
        for kind, text, stretch in (("max", "1 · ARCHIVOS .MAX", 2), ("preview", "2 · PREVIEW", 2),
                                    ("maps", "3 · TEXTURAS Y OTROS", 5)):
            self.captions[kind] = self._caption(text)
            self.captions[kind].setProperty("base", text)
            ml.addWidget(self.captions[kind])
            self.buckets[kind] = _Bucket(kind)
            ml.addWidget(self.buckets[kind], stretch)
        split.addWidget(mid)
        for kind, b in self.buckets.items():
            b.changed.connect(self._refresh)
            b.customContextMenuRequested.connect(lambda pos, b=b: self._bucket_menu(b, pos))
            b.itemDoubleClicked.connect(lambda it: os.startfile(it.data(ROLE_ITEM).path))

        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        rl.addWidget(self._caption("NOMBRE", "del .max, del preview y de su carpeta de texturas"))
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("Nombre del modelo")
        self.name.textChanged.connect(self._refresh)
        rl.addWidget(self.name)
        rl.addSpacing(6)
        rl.addWidget(self._caption("CARPETA DE LA BIBLIOTECA", "donde se guarda"))
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Buscar carpeta…")
        self.filter.setClearButtonEnabled(True)
        self.filter_timer = QtCore.QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(220)
        self.filter_timer.timeout.connect(self._apply_filter)
        self.filter.textChanged.connect(lambda _: self.filter_timer.start())
        rl.addWidget(self.filter)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName("Folders")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(lambda *_: self._refresh())
        rl.addWidget(self.tree, 1)
        row = QtWidgets.QHBoxLayout()
        self.b_new = QtWidgets.QPushButton(icon("add"), " Nueva carpeta…")
        self.b_new.setToolTip("Crear una carpeta dentro de la que está seleccionada")
        self.b_new.clicked.connect(self._new_folder)
        row.addWidget(self.b_new)
        row.addStretch(1)
        row.addWidget(QtWidgets.QLabel("Texturas en"))
        self.maps = QtWidgets.QLineEdit(self.cfg.get("maps_folder") or catalog.MAPS_FOLDER)
        self.maps.setFixedWidth(110)
        self.maps.setToolTip("Nombre de la carpeta donde van las texturas, dentro de la carpeta elegida.\n"
                             "Dentro se crea otra con el nombre del modelo.")
        self.maps.textChanged.connect(self._refresh)
        row.addWidget(self.maps)
        rl.addLayout(row)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(QtCore.Qt.RichText)
        self.summary.setObjectName("Muted")
        self.summary.setMinimumHeight(96)
        self.summary.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        rl.addWidget(self.summary)
        split.addWidget(right)
        split.setSizes([300, 480, 400])
        lay.addWidget(split, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("Status")
        bottom.addWidget(self.status, 1)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(160)
        self.progress.setVisible(False)
        bottom.addWidget(self.progress)
        self.b_cancel = QtWidgets.QPushButton("Cancelar")
        self.b_cancel.setVisible(False)
        self.b_cancel.clicked.connect(self._cancel)
        bottom.addWidget(self.b_cancel)
        self.b_go = QtWidgets.QPushButton("Catalogar")
        self.b_go.setObjectName("Primary")
        self.b_go.setMinimumWidth(130)
        self.b_go.clicked.connect(self._go)
        bottom.addWidget(self.b_go)
        b_close = QtWidgets.QPushButton("Cerrar")
        b_close.clicked.connect(self.reject)
        bottom.addWidget(b_close)
        for b in (self.b_open, self.b_folder, self.b_new, self.b_cancel, self.b_go, b_close):
            b.setAutoDefault(False)
        lay.addLayout(bottom)

    def showEvent(self, event):
        super(CatalogDialog, self).showEvent(event)
        theme.title_bar(self)

    # --- árbol de destino ---------------------------------------------------------------
    def _fill_tree(self, select=None):
        self.tree.clear()
        self.tree_items = {}
        if self.index is None:
            return
        folder_ic = icon("folder")
        for root in self.index.roots:
            it = QtWidgets.QTreeWidgetItem([os.path.basename(root.rstrip("\\/")) or root])
            it.setData(0, ROLE_PATH, root)
            it.setIcon(0, icon("drive"))
            it.setToolTip(0, root)
            self.tree.addTopLevelItem(it)
            self.tree_items[os.path.normcase(root)] = it
        for folder in self.index.folders:
            key = os.path.normcase(folder)
            if key in self.tree_items or key in self.hidden:
                continue
            parent = self.tree_items.get(os.path.normcase(os.path.dirname(folder)))
            if parent is None:
                continue
            it = QtWidgets.QTreeWidgetItem(parent, [os.path.basename(folder)])
            it.setData(0, ROLE_PATH, folder)
            it.setIcon(0, folder_ic)
            self.tree_items[key] = it
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(True)
        sel = self.tree_items.get(os.path.normcase(select)) if select else None
        if sel is not None:
            self.tree.setCurrentItem(sel)
            self.tree.scrollToItem(sel, QtWidgets.QAbstractItemView.PositionAtCenter)

    def _apply_filter(self):
        words = self.filter.text().lower().split()
        cur = self.tree.currentItem()

        def walk(it):
            hit = all(w in it.text(0).lower() for w in words)
            inside = False
            for i in range(it.childCount()):
                inside = walk(it.child(i)) or inside
            it.setHidden(bool(words) and not (hit or inside))
            if words:
                it.setExpanded(inside)
            return hit or inside

        self.tree.setUpdatesEnabled(False)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            walk(top)
            top.setHidden(False)
            if not words:
                top.setExpanded(True)
        self.tree.setUpdatesEnabled(True)
        if cur is not None and not words:
            self.tree.scrollToItem(cur, QtWidgets.QAbstractItemView.PositionAtCenter)

    def _dest(self):
        it = self.tree.currentItem()
        return it.data(0, ROLE_PATH) if it is not None else None

    def _new_folder(self):
        parent_it = self.tree.currentItem()
        if parent_it is None:
            QtWidgets.QMessageBox.information(self, "OpenLibrary", "Elige antes la carpeta dentro de la que crearla.")
            return
        parent = parent_it.data(0, ROLE_PATH)
        text, ok = QtWidgets.QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta nueva, dentro de\n%s:"
                                                  % parent)
        name = catalog.clean_name(text)
        if not ok or not name:
            return
        path = os.path.join(parent, name)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "OpenLibrary", "No se pudo crear la carpeta:\n%s" % exc)
            return
        key = os.path.normcase(path)
        it = self.tree_items.get(key)
        if it is None:
            it = QtWidgets.QTreeWidgetItem(parent_it, [name])
            it.setData(0, ROLE_PATH, path)
            it.setIcon(0, icon("folder"))
            self.tree_items[key] = it
            parent_it.sortChildren(0, QtCore.Qt.AscendingOrder)
        self.filter.clear()
        self._apply_filter()
        parent_it.setExpanded(True)
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it)

    # --- cargar la descarga -------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self.worker is None:
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            event.acceptProposedAction()
            path = urls[0]
            QtCore.QTimer.singleShot(0, lambda: self._load_folder(path) if os.path.isdir(path)
                                     else self._load_archive(path))

    def _choose_archive(self):
        start = self.cfg.get("last_dir") or os.path.join(os.path.expanduser("~"), "Downloads")
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Abrir comprimido", start, archives.FILTER)
        if path:
            self._load_archive(os.path.normpath(path))

    def _choose_folder(self):
        start = self.cfg.get("last_dir") or os.path.join(os.path.expanduser("~"), "Downloads")
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Carpeta ya descomprimida", start)
        if path:
            self._load_folder(os.path.normpath(path))

    def _busy(self, text, cancellable=True, determinate=False):
        self.status.setText(text)
        self.progress.setRange(0, 100 if determinate else 0)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.b_cancel.setVisible(cancellable)
        for w in (self.b_open, self.b_folder, self.b_go, self.b_new):
            w.setEnabled(False)

    def _idle(self, text=""):
        self.worker = None
        self.proc = []
        self.status.setText(text)
        self.progress.setVisible(False)
        self.b_cancel.setVisible(False)
        for w in (self.b_open, self.b_folder, self.b_new):
            w.setEnabled(True)
        self._refresh()

    def _cancel(self):
        self.cancelled = True
        for p in self.proc:
            try:
                p.kill()
            except OSError:
                pass

    def _clear(self):
        self.thumb_timer.stop()
        self.thumb_queue = []
        for b in self.buckets.values():
            b.clear()
        self.engines = {}
        self.source = None
        if self.work_dir:
            shutil.rmtree(self.work_dir, ignore_errors=True)
        self.work_dir = None

    def _load_archive(self, path, password=None):
        if self.worker is not None:
            return
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No encuentro el archivo:\n%s" % path)
            return
        first, parts, missing = archives.volumes(path)
        if missing:
            QtWidgets.QMessageBox.warning(
                self, "OpenLibrary",
                "Este archivo viene en partes y faltan %d:\n\n%s\n\nPonlas en la misma carpeta que las demás (%s) "
                "y vuelve a abrirlo." % (len(missing), "\n".join(missing[:12]), os.path.dirname(path)))
            return
        self._clear()
        self.cfg["last_dir"] = os.path.dirname(path)
        work = os.path.join(self.tmp_root, uuid.uuid4().hex[:10])
        self.cancelled = False
        self.proc = []
        proc = self.proc
        note = " (%d partes)" % len(parts) if len(parts) > 1 else ""
        self._busy("Abriendo %s%s…" % (os.path.basename(first), note))

        def work_fn():
            archives.extract(first, work, password, holder=proc)
            items = catalog.list_files(work)
            return items, {i.path: catalog.engine_of(i.path, maxfile.detect_engine(i.path))
                           for i in items if i.ext == library.MAX_EXT}

        def ok(res):
            items, engines = res
            self.work_dir = work
            self._idle()
            self._show_items(first, items, engines, len(parts))

        def failed(exc):
            shutil.rmtree(work, ignore_errors=True)
            self._idle()
            if self.cancelled:
                self.status.setText("Cancelado.")
            elif isinstance(exc, archives.NeedPassword):
                text, got = QtWidgets.QInputDialog.getText(
                    self, "Contraseña",
                    ("Esa contraseña no es. Prueba otra vez:" if exc.wrong else
                     "«%s» tiene contraseña.\nEscríbela (suele venir en la web de descarga o en un .txt):"
                     % os.path.basename(first)))
                if got and text:
                    self._load_archive(path, text)
            else:
                QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No se pudo abrir %s:\n\n%s"
                                              % (os.path.basename(first), exc))

        self.worker = _Worker(work_fn, self)
        self.worker.finished_ok.connect(ok)
        self.worker.failed.connect(failed)
        self.worker.start()

    def _load_folder(self, path):
        if self.worker is not None or not os.path.isdir(path):
            return
        self._clear()
        self.cfg["last_dir"] = os.path.dirname(path)
        items = catalog.list_files(path)
        if len(items) > 5000:
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", "Esa carpeta tiene %d archivos: parece más una "
                                          "biblioteca entera que una descarga. Elige la carpeta de un modelo."
                                          % len(items))
            return
        engines = {i.path: catalog.engine_of(i.path, maxfile.detect_engine(i.path))
                           for i in items if i.ext == library.MAX_EXT}
        self._show_items(path, items, engines, 1)

    def _show_items(self, source, items, engines, nparts):
        self.source = source
        self.engines = engines
        name = archives.display_name(source) if os.path.isfile(source) else os.path.basename(source.rstrip("\\/"))
        kinds = catalog.guess(items, name)
        for it in items:
            li = QtWidgets.QListWidgetItem(self._label(it))
            li.setData(ROLE_ITEM, it)
            li.setToolTip(os.path.join(it.rel, it.name) if it.rel else it.name)
            li.setIcon(icon("max" if it.ext == library.MAX_EXT else ("image" if it.is_image else "file")))
            li.setSizeHint(QtCore.QSize(10, THUMB + 10))
            self.buckets[kinds[it.path]].addItem(li)
            if it.ext in _THUMB_EXTS and (it.ext in (".jpg", ".jpeg") or it.size < 12 * 1024 * 1024):
                self.thumb_queue.append(li)
        # primero las miniaturas de lo que puede ser el preview
        self.thumb_queue.sort(key=lambda li: kinds[li.data(ROLE_ITEM).path] != "preview")
        self.thumb_timer.start()
        self.name.setText(catalog.clean_name(name))
        self.name.selectAll()
        self.name.setFocus()
        total = sum(i.size for i in items)
        self.src_lbl.setText("%s  ·  %d archivos, %s%s%s" % (
            os.path.basename(source), len(items), catalog.human_size(total),
            "  ·  %d partes" % nparts if nparts > 1 else "",
            "" if self.work_dir else "  ·  carpeta: se copia, no se mueve"))
        if not any(i.ext == library.MAX_EXT for i in items):
            self.status.setText("Aquí dentro no hay ningún .max.")
        self._refresh()

    def _label(self, it):
        extra = ""
        if it.ext == library.MAX_EXT:
            eng = self.engines.get(it.path)
            extra = "  ·  " + ENGINE_LABEL.get(eng, "motor sin identificar")
        return "%s\n%s%s" % (it.name, catalog.human_size(it.size), extra)

    def _next_thumb(self):
        if not self.thumb_queue:
            self.thumb_timer.stop()
            return
        li = self.thumb_queue.pop(0)
        try:
            it = li.data(ROLE_ITEM)
            reader = QtGui.QImageReader(it.path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and size.width() > 0:
                reader.setScaledSize(size.scaled(THUMB * 2, THUMB * 2, QtCore.Qt.KeepAspectRatio))
            img = reader.read()
            if not img.isNull():
                li.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(img)))
        except RuntimeError:            # el elemento ya no existe (se abrió otra descarga)
            pass

    def _bucket_menu(self, bucket, pos):
        items = bucket.selectedItems()
        if not items:
            return
        menu = QtWidgets.QMenu(self)
        for kind, text in (("max", "Mover a «Archivos .max»"), ("preview", "Mover a «Preview»"),
                           ("maps", "Mover a «Texturas y otros»"), ("skip", "No copiar")):
            if kind != bucket.kind:
                menu.addAction(text, lambda k=kind: self.buckets[k].take_from(bucket, items))
        if bucket.kind == "preview" and len(items) == 1 and bucket.row(items[0]) > 0:
            menu.addSeparator()
            menu.addAction("Usar esta de miniatura (ponerla la primera)", lambda: self._first_preview(items[0]))
        menu.addSeparator()
        menu.addAction("Abrir", lambda: os.startfile(items[0].data(ROLE_ITEM).path))
        menu.exec(bucket.viewport().mapToGlobal(pos))

    def _first_preview(self, li):
        b = self.buckets["preview"]
        b.insertItem(0, b.takeItem(b.row(li)))
        self._refresh()

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            return                                  # Intro en el nombre no cataloga ni cierra
        if event.key() == QtCore.Qt.Key_Delete:
            w = self.focusWidget()
            if isinstance(w, _Bucket) and w.kind != "skip":
                self.buckets["skip"].take_from(w)
                return
        super(CatalogDialog, self).keyPressEvent(event)

    # --- resumen y catalogar ---------------------------------------------------------------
    def _plan(self):
        name = catalog.clean_name(self.name.text())
        dest = self._dest()
        if not name or not dest:
            return None
        maxes = [(i.path, self.engines.get(i.path)) for i in self.buckets["max"].entries()]
        return catalog.plan(dest, name, maxes, [i.path for i in self.buckets["preview"].entries()],
                            [i.path for i in self.buckets["maps"].entries()], self.maps.text())

    def _refresh(self):
        for kind, cap in self.captions.items():
            n = self.buckets[kind].count()
            cap.setText(cap.property("base") + ("  (%d)" % n if n else ""))
        name = catalog.clean_name(self.name.text())
        dest = self._dest()
        n_all = sum(self.buckets[k].count() for k in ("max", "preview", "maps"))
        lines = []
        p = self._plan() if n_all else None
        if p is not None:
            esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
            base = os.path.basename(dest.rstrip("\\/")) or dest
            top = [os.path.basename(d) for _s, d in p.ops if os.path.dirname(d) == dest]
            for f in top[:6]:
                lines.append("%s\\<b>%s</b>" % (esc(base), esc(f)))
            if len(top) > 6:
                lines.append("… y %d más" % (len(top) - 6))
            if p.maps_dir:
                n = len(p.ops) - len(top)
                lines.append("%s\\%s\\<b>%s</b>\\  ·  %d archivo%s%s" % (
                    esc(base), esc(os.path.basename(os.path.dirname(p.maps_dir))), esc(name), n,
                    "" if n == 1 else "s", " (%d repetidos fuera)" % p.skipped if p.skipped else ""))
            exist = p.conflicts()
            if exist:
                lines.append("<span style='color:%s'>⚠ Ya existe%s: %s</span>" % (
                    theme.WARN, "" if len(exist) == 1 else "n %d" % len(exist),
                    esc(", ".join(os.path.basename(e) for e in exist[:3])) + ("…" if len(exist) > 3 else "")))
            if not self.buckets["preview"].count():
                lines.append("Sin preview: luego puedes generarlo con el botón Preview.")
        elif self.source and not name:
            lines.append("Escribe el nombre del modelo.")
        elif self.source and not dest:
            lines.append("Elige en el árbol la carpeta donde guardarlo.")
        elif self.source:
            lines.append("Arrastra a las listas 1, 2 y 3 lo que quieras guardar.")
        elif self.index is None:
            lines.append("Esta pestaña no tiene carpetas de biblioteca: añádelas en Ajustes › Libraries.")
        self.summary.setText("<br>".join(lines))
        self.b_go.setEnabled(p is not None and self.worker is None)

    def _go(self):
        p = self._plan()
        if p is None or self.worker is not None:
            return
        dest = self._dest()
        name = catalog.clean_name(self.name.text())
        if not self.buckets["max"].count() and QtWidgets.QMessageBox.question(
                self, "OpenLibrary", "No hay ningún .max en la lista 1, así que no saldrá como modelo en la "
                                     "biblioteca. ¿Guardar igualmente?") != QtWidgets.QMessageBox.Yes:
            return
        exist = p.conflicts()
        if exist and QtWidgets.QMessageBox.question(
                self, "OpenLibrary", "Ya existen %d archivo%s en el destino:\n\n%s%s\n\n¿Sobrescribirlos?" % (
                    len(exist), "" if len(exist) == 1 else "s", "\n".join(exist[:10]),
                    "\n…" if len(exist) > 10 else "")) != QtWidgets.QMessageBox.Yes:
            return
        maps_name = catalog.clean_name(self.maps.text()) or catalog.MAPS_FOLDER
        self.cfg["maps_folder"] = maps_name
        move = bool(self.work_dir)
        self.cancelled = False
        self._busy("Guardando «%s»…" % name, determinate=True)
        worker = _Worker(lambda: catalog.apply(p, move, lambda a, b: worker.progress.emit(a, b),
                                               lambda: self.cancelled), self)
        worker.progress.connect(lambda a, b: self.progress.setValue(int(a * 100 / max(1, b))))

        def ok(done):
            hid = False
            if p.maps_dir and not self.cancelled:
                names = self.settings.hidden["names"]
                if maps_name.lower() not in [n.lower() for n in names]:
                    names.append(maps_name)         # la carpeta de texturas no se enseña en el árbol
                    hid = True
            self.settings.save()
            cancelled = self.cancelled
            self._clear()
            self.name.clear()
            self.src_lbl.setText("Elige otra descarga o arrástrala a esta ventana.")
            self._idle("Cancelado: se guardaron %d de %d archivos de «%s»." % (done, len(p.ops), name)
                       if cancelled else "Guardado «%s» en %s (%d archivos)." % (name, dest, done))
            self.catalogued.emit(dest, hid)

        def failed(exc):
            self._idle("No se pudo guardar todo.")
            QtWidgets.QMessageBox.critical(self, "OpenLibrary", "No se pudo guardar:\n\n%s\n\nLo que no se haya "
                                           "copiado sigue en las listas." % exc)
            self.catalogued.emit(dest, False)

        worker.finished_ok.connect(ok)
        worker.failed.connect(failed)
        self.worker = worker
        worker.start()

    def done(self, result):
        if self.worker is not None:
            self._cancel()
            self.worker.wait(5000)
        self.thumb_timer.stop()
        self.settings.save()
        if self.work_dir:
            shutil.rmtree(self.work_dir, ignore_errors=True)
        shutil.rmtree(self.tmp_root, ignore_errors=True)
        super(CatalogDialog, self).done(result)
