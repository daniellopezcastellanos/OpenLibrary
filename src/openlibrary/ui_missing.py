"""Ventana «Archivos que faltan»: las texturas y demás archivos externos que un .max no
encuentra, con su ruta guardada; se re-enlazan a mano o se quitan y se guarda en el .max
sin abrirlo (lo hace un 3ds Max en segundo plano)."""
import os
import shutil
import uuid

from . import app_icon, config, icon, maxfile, pathedit, theme
from .qt import QtCore, QtGui, QtWidgets

COL_NAME, COL_DIR, COL_TYPE, COL_STATE, COL_FILE = range(5)
ROLE_ROW = QtCore.Qt.UserRole + 1
TYPE_LABEL = {"bitmap": "Textura", "photometric": "Fotométrico / LUT", "xref": "XRef", "animation": "Animación",
              "sound": "Sonido", "other": "Otro", "externallink": "Enlace externo", "containerdefinition": "Container",
              "renderoutput": "Salida de render", "preRenderScript": "Script"}


def _base(path):
    return path.replace("/", "\\").split("\\")[-1]


def _dir(path):
    p = path.replace("/", "\\")
    return p.rsplit("\\", 1)[0] if "\\" in p else "(sin ruta: solo el nombre)"


class _Finder(QtCore.QThread):
    found = QtCore.Signal(object)

    def __init__(self, folder, names, parent=None):
        super(_Finder, self).__init__(parent)
        self.folder, self.names = folder, names

    def run(self):
        self.found.emit(pathedit.find_by_name(self.folder, self.names))


class MissingDialog(QtWidgets.QDialog):
    saved = QtCore.Signal(list)         # archivos .max cambiados

    def __init__(self, name, max_files, settings, parent=None):
        super(MissingDialog, self).__init__(parent)
        self.max_files = list(max_files)
        self.settings = settings
        self.rows = []               # {"file", "type", "stored", "state", "new"}   new: None | ruta | pathedit.REMOVE
        self.proc = None
        self.finder = None
        self.workdir = None
        self.setWindowTitle("OpenLibrary - Archivos que faltan · %s" % name)
        self.setWindowIcon(app_icon())
        self.resize(1180, 640)
        self._build()
        self._load()

    # --- interfaz ---------------------------------------------------------------------
    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)

        self.table = QtWidgets.QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setHeaderLabels(["Archivo que falta", "Dónde debería estar (ruta guardada en el .max)", "Tipo",
                                    "Qué se va a hacer", "En el .max"])
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, QtCore.Qt.AscendingOrder)
        self.table.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda *_: self._relink())
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        h = self.table.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(COL_DIR, QtWidgets.QHeaderView.Stretch)
        for col, w in ((COL_NAME, 270), (COL_TYPE, 110), (COL_STATE, 290), (COL_FILE, 170)):
            self.table.setColumnWidth(col, w)
        lay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.b_relink = QtWidgets.QPushButton(icon("relink"), " Re-enlazar a mano…")
        self.b_relink.setToolTip("Una fila: eliges el archivo que la sustituye (puede llamarse distinto).\n"
                                 "Varias filas: eliges la carpeta donde están, con sus mismos nombres.")
        self.b_relink.clicked.connect(self._relink)
        row.addWidget(self.b_relink)
        self.b_search = QtWidgets.QPushButton(icon("search"), " Buscar en una carpeta…")
        self.b_search.setToolTip("Busca por nombre, con subcarpetas, las seleccionadas (o todas si no hay selección)")
        self.b_search.clicked.connect(self._search)
        row.addWidget(self.b_search)
        self.b_remove = QtWidgets.QPushButton(icon("hide"), " Quitar del .max")
        self.b_remove.setToolTip("Borra la referencia: el .max deja de pedir ese archivo.\n"
                                 "El material sigue ahí, pero ese mapa se queda sin imagen.")
        self.b_remove.clicked.connect(self._remove)
        row.addWidget(self.b_remove)
        self.b_junk = QtWidgets.QPushButton("Quitar .cube, .hdr y checker")
        self.b_junk.setToolTip("Marca para quitar, de golpe, lo que casi nunca hace falta y no aparece:\n"
                               "LUT de Corona (.cube), HDR (.hdr) y texturas «checker» de desplegar UV")
        self.b_junk.clicked.connect(self._junk)
        row.addWidget(self.b_junk)
        self.b_undo = QtWidgets.QPushButton("Deshacer")
        self.b_undo.setToolTip("Dejar las seleccionadas como estaban (antes de guardar)")
        self.b_undo.clicked.connect(self._undo)
        row.addWidget(self.b_undo)
        row.addStretch(1)
        self.b_copy = QtWidgets.QPushButton("Copiar lista")
        self.b_copy.setToolTip("Copia al portapapeles el nombre y la ruta de lo que falta")
        self.b_copy.clicked.connect(self._copy)
        row.addWidget(self.b_copy)
        lay.addLayout(row)

        bottom = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(150)
        self.progress.setVisible(False)
        bottom.addWidget(self.progress)
        self.b_save = QtWidgets.QPushButton("Guardar en el .max")
        self.b_save.setObjectName("Primary")
        self.b_save.setMinimumWidth(170)
        self.b_save.clicked.connect(self._save)
        bottom.addWidget(self.b_save)
        self.b_close = QtWidgets.QPushButton("Cerrar")
        self.b_close.clicked.connect(self.reject)
        bottom.addWidget(self.b_close)
        lay.addLayout(bottom)
        for b in self.findChildren(QtWidgets.QPushButton):
            b.setAutoDefault(False)

    def showEvent(self, event):
        super(MissingDialog, self).showEvent(event)
        theme.title_bar(self)

    # --- datos ------------------------------------------------------------------------
    def _load(self):
        self.rows = []
        for f in self.max_files:
            for r in maxfile.external_files(f):
                if r["state"] != "ok":
                    self.rows.append({"file": f, "type": r["type"], "stored": r["stored"], "state": r["state"],
                                      "new": None})
        self.table.setSortingEnabled(False)
        self.table.clear()
        for n, r in enumerate(self.rows):
            it = QtWidgets.QTreeWidgetItem()
            it.setData(0, ROLE_ROW, n)           # el índice: Qt copiaría el diccionario
            it.setIcon(COL_NAME, icon("image" if r["type"].lower().lstrip("#") == "bitmap" else "file"))
            self.table.addTopLevelItem(it)
            self._paint(it)
        self.table.setSortingEnabled(True)
        self.table.setColumnHidden(COL_FILE, len(self.max_files) < 2)
        self._update_buttons()

    def _row(self, it):
        return self.rows[it.data(0, ROLE_ROW)]

    def _paint(self, it):
        r = self._row(it)
        typ = r["type"].lstrip("#")
        it.setText(COL_NAME, _base(r["stored"]))
        it.setText(COL_DIR, _dir(r["stored"]))
        it.setToolTip(COL_DIR, r["stored"])
        it.setText(COL_TYPE, TYPE_LABEL.get(typ.lower(), typ))
        it.setText(COL_FILE, os.path.basename(r["file"]))
        it.setToolTip(COL_FILE, r["file"])
        if r["new"] == pathedit.REMOVE:
            text, col = "Se quita del .max", theme.WARN
        elif r["new"]:
            text, col = "→ " + r["new"], theme.OK
        elif r["state"] == "relinkable":
            text, col = "Falta, pero está en la carpeta del modelo", theme.MUTED
        else:
            text, col = "Falta", theme.MUTED
        it.setText(COL_STATE, text)
        it.setToolTip(COL_STATE, r["new"] if r["new"] and r["new"] != pathedit.REMOVE else text)
        it.setForeground(COL_STATE, QtGui.QBrush(theme.color(col)))
        f = it.font(COL_NAME)
        f.setStrikeOut(r["new"] == pathedit.REMOVE)
        it.setFont(COL_NAME, f)

    def _items(self, selected=True):
        if selected:
            return self.table.selectedItems()
        return [self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())]

    def _pending(self):
        return [r for r in self.rows if r["new"]]

    def _update_buttons(self):
        busy = self.proc is not None or self.finder is not None
        sel = self._items()
        pend = self._pending()
        self.b_relink.setEnabled(bool(sel) and not busy)
        self.b_remove.setEnabled(bool(sel) and not busy)
        self.b_undo.setEnabled(any(self._row(i)["new"] for i in sel) and not busy)
        self.b_search.setEnabled(bool(self.rows) and not busy)
        self.b_copy.setEnabled(bool(self.rows))
        junk = sum(1 for r in self.rows if self._is_junk(r) and r["new"] != pathedit.REMOVE)
        self.b_junk.setEnabled(bool(junk) and not busy)
        self.b_junk.setText("Quitar .cube, .hdr y checker (%d)" % junk if junk else "Quitar .cube, .hdr y checker")
        self.b_save.setEnabled(bool(pend) and not busy)
        self.b_save.setText("Guardar en el .max (%d)" % len(pend) if pend else "Guardar en el .max")
        n = len(self.rows)
        if not n:
            self.head.setText("<b>No falta nada.</b> Todos los archivos externos de este modelo están en su sitio.")
        else:
            here = sum(1 for r in self.rows if r["state"] == "relinkable")
            self.head.setText(
                "<b>%d archivo%s sin encontrar</b>%s. Selecciona una o varias filas para re-enlazarlas a mano o "
                "quitarlas del .max; no cambia nada hasta que pulses «Guardar en el .max»." % (
                    n, "" if n == 1 else "s",
                    " (%d están en la carpeta del modelo y se re-enlazan solos al importar)" % here if here else ""))

    def _menu(self, pos):
        if not self._items():
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction(icon("relink"), "Re-enlazar a mano…", self._relink)
        menu.addAction(icon("hide"), "Quitar del .max", self._remove)
        menu.addAction("Deshacer", self._undo)
        menu.addSeparator()
        menu.addAction("Copiar ruta", lambda: QtWidgets.QApplication.clipboard().setText(
            "\n".join(self._row(i)["stored"] for i in self._items())))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # --- acciones ---------------------------------------------------------------------
    def _start_dir(self):
        last = self.settings.data.get("relink_last_dir")
        return last if last and os.path.isdir(last) else os.path.dirname(self.max_files[0])

    def _set(self, items, fn):
        for it in items:
            r = self._row(it)
            r["new"] = fn(r)
            self._paint(it)
        self._update_buttons()

    def _relink(self):
        items = self._items()
        if not items or self.proc is not None:
            return
        if len(items) == 1:
            r = self._row(items[0])
            path, _f = QtWidgets.QFileDialog.getOpenFileName(
                self, "Archivo para «%s»" % _base(r["stored"]), os.path.join(self._start_dir(), _base(r["stored"])))
            if not path:
                return
            path = os.path.normpath(path)
            self.settings.data["relink_last_dir"] = os.path.dirname(path)
            self._set(items, lambda _r: path)
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Carpeta donde están los %d archivos seleccionados" % len(items), self._start_dir())
        if not folder:
            return
        folder = os.path.normpath(folder)
        self.settings.data["relink_last_dir"] = folder
        hit = [0]

        def pick(r):
            p = os.path.join(folder, _base(r["stored"]))
            if os.path.isfile(p):
                hit[0] += 1
                return p
            return r["new"]
        self._set(items, pick)
        self.status.setText("%d de %d están en esa carpeta%s." % (
            hit[0], len(items), "" if hit[0] == len(items) else "; las demás se quedan como estaban "
                                                                "(prueba «Buscar en una carpeta…», que mira subcarpetas)"))

    def _search(self):
        items = self._items() or self._items(False)
        if not items or self.finder is not None:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Carpeta donde buscar (con subcarpetas)", self._start_dir())
        if not folder:
            return
        folder = os.path.normpath(folder)
        self.settings.data["relink_last_dir"] = folder
        names = [_base(self._row(i)["stored"]) for i in items]
        self.status.setText("Buscando %d archivo%s en %s…" % (len(names), "" if len(names) == 1 else "s", folder))
        self.progress.setVisible(True)
        self.finder = _Finder(folder, names, self)

        def done(found):
            self.finder = None
            self.progress.setVisible(False)
            self._set(items, lambda r: found.get(_base(r["stored"]).lower(), r["new"]))
            self.status.setText("Encontrados %d de %d en %s." % (len(found), len(set(n.lower() for n in names)),
                                                                 folder))
        self.finder.found.connect(done)
        self.finder.start()
        self._update_buttons()

    def _remove(self):
        self._set(self._items(), lambda _r: pathedit.REMOVE)

    @staticmethod
    def _is_junk(r):
        return r["state"] == "missing" and pathedit.is_disposable(r["type"], r["stored"])

    def _junk(self):
        items = [i for i in self._items(False) if self._is_junk(self._row(i))]
        self._set(items, lambda _r: pathedit.REMOVE)
        self.status.setText("%d marcadas para quitar. Pulsa «Guardar en el .max»." % len(items))

    def _undo(self):
        self._set(self._items(), lambda _r: None)

    def _copy(self):
        lines = ["%s\t%s" % (_base(r["stored"]), r["stored"]) for r in self.rows]
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))
        self.status.setText("Lista copiada (%d)." % len(lines))

    # --- guardar ----------------------------------------------------------------------
    def _save(self):
        pend = self._pending()
        if not pend or self.proc is not None:
            return
        exe = pathedit.find_maxbatch()
        if not exe:
            QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No encuentro 3dsmaxbatch.exe (viene con 3ds Max "
                                                               "2019 o posterior). Sin él no se puede escribir "
                                                               "dentro del .max.")
            return
        rem = sum(1 for r in pend if r["new"] == pathedit.REMOVE)
        files = sorted(set(r["file"] for r in pend))
        msg = "Se va a reescribir %s:\n\n%s\n\n· %d ruta%s re-enlazada%s\n· %d referencia%s quitada%s" % (
            "el archivo" if len(files) == 1 else "%d archivos" % len(files),
            "\n".join(os.path.basename(f) for f in files),
            len(pend) - rem, "" if len(pend) - rem == 1 else "s", "" if len(pend) - rem == 1 else "s",
            rem, "" if rem == 1 else "s", "" if rem == 1 else "s")
        if rem:
            msg += "\n\nLo que se quita no se puede recuperar desde aquí: el mapa se queda sin imagen en el material."
        msg += "\n\nLo hace un 3ds Max en segundo plano; tarda medio minuto. ¿Seguir?"
        if QtWidgets.QMessageBox.question(self, "OpenLibrary", msg) != QtWidgets.QMessageBox.Yes:
            return
        self.workdir = os.path.join(config.app_data_dir(), "pathedit_tmp", uuid.uuid4().hex[:10])
        edits = [(r["file"], r["stored"], None if r["new"] == pathedit.REMOVE else r["new"]) for r in pend]
        script, self.log_file = pathedit.prepare(self.workdir, edits)
        self.saving = files
        proc = QtCore.QProcess(self)
        proc.setProgram(exe)
        proc.setArguments([script])
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.finished.connect(lambda *_: self._save_done())
        proc.errorOccurred.connect(lambda _e: self._save_done("No se pudo arrancar 3dsmaxbatch."))
        self.proc = proc
        self.progress.setVisible(True)
        self.status.setText("Guardando en el .max con un 3ds Max en segundo plano (medio minuto)…")
        self._update_buttons()
        proc.start()

    def _save_done(self, error=None):
        if self.proc is None:
            return
        self.proc.deleteLater()
        self.proc = None
        self.progress.setVisible(False)
        log = pathedit.read_log(self.log_file)
        shutil.rmtree(self.workdir, ignore_errors=True)
        ok = [f for f in self.saving if log.get(os.path.normcase(f), -1) >= 0]
        bad = [f for f in self.saving if f not in ok]
        changed = sum(log[os.path.normcase(f)] for f in ok)
        self._load()
        self.saved.emit(self.saving)
        if error or bad:
            self.status.setText(error or "No se pudo escribir en: %s (¿abierto en 3ds Max o de solo lectura?)"
                                % ", ".join(os.path.basename(f) for f in bad))
        else:
            self.status.setText("Guardado: %d ruta%s cambiada%s. %s" % (
                changed, "" if changed == 1 else "s", "" if changed == 1 else "s",
                "Ya no falta nada." if not self.rows else "Siguen faltando %d." % len(self.rows)))

    def done(self, result):
        if self.proc is not None:
            if QtWidgets.QMessageBox.question(self, "OpenLibrary", "Se está guardando en el .max. ¿Esperar a que "
                                              "termine?") == QtWidgets.QMessageBox.Yes:
                return
            self.proc.kill()
            self.proc.waitForFinished(3000)
        elif self._pending() and result != QtWidgets.QDialog.Accepted and QtWidgets.QMessageBox.question(
                self, "OpenLibrary", "Hay %d cambio(s) sin guardar en el .max. ¿Cerrar sin guardarlos?"
                % len(self._pending())) != QtWidgets.QMessageBox.Yes:
            return
        self.settings.save()
        super(MissingDialog, self).done(result)
