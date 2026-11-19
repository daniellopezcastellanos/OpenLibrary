"""Ventana de Ajustes: Libraries (pestañas y carpetas), Importación y Preview."""
import os

from .qt import QtCore, QtGui, QtWidgets


KIND_LABELS = [("models", "Modelos 3D"), ("materials", "Materiales"), ("textures", "Texturas"),
               ("interiors", "Interiores (wParallax)")]
SHOW_LABELS = [("both", "Todos, con los favoritos primero"), ("favorites", "Solo los favoritos"),
               ("all", "Todos (sin poner los favoritos primero)")]
# filas fijas arriba de la lista de carpetas: (clave del ajuste, texto); se marcan para verlas en el árbol
FIXED_ROWS = (("tree_fav", "Favoritos"), ("tree_all", "Todos"))


class _LibrariesTab(QtWidgets.QWidget):
    """Pestañas del navegador (Modelos, Materiales, Texturas...) y sus carpetas."""

    def __init__(self, libraries, parent=None):
        super(_LibrariesTab, self).__init__(parent)
        # (dict(l): se conservan los demás ajustes de la pestaña, p. ej. «show»)
        self.libs = [dict(l, kind=l.get("kind", "models"), paths=list(l.get("paths", []))) for l in libraries]
        lay = QtWidgets.QHBoxLayout(self)

        # --- Pestañas
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Pestañas del navegador:"))
        self.tabs = QtWidgets.QListWidget()
        self.tabs.currentRowChanged.connect(self._on_tab)
        left.addWidget(self.tabs, 1)
        row = QtWidgets.QHBoxLayout()
        for text, tip, slot in (("+", "Nueva pestaña", self._add_tab), ("✎", "Renombrar", self._rename_tab),
                                ("−", "Quitar", self._remove_tab), ("▲", "Subir", lambda: self._move(-1)),
                                ("▼", "Bajar", lambda: self._move(1))):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        left.addLayout(row)
        self.kind = _combo(KIND_LABELS, "models")
        self.kind.currentIndexChanged.connect(self._on_kind)
        self.show = _combo(SHOW_LABELS, "both")
        self.show.setToolTip("Qué se ve al entrar en la pestaña. Los favoritos se marcan con el corazón de cada "
                             "tarjeta y están en «Favoritos», arriba del árbol de carpetas.")
        self.show.currentIndexChanged.connect(self._on_show)
        kf = QtWidgets.QFormLayout()
        kf.addRow("Contenido:", self.kind)
        kf.addRow("Al abrir, mostrar:", self.show)
        left.addLayout(kf)
        lay.addLayout(left, 2)

        # --- Carpetas de la pestaña
        right = QtWidgets.QVBoxLayout()
        self.paths_lbl = QtWidgets.QLabel()
        right.addWidget(self.paths_lbl)
        self.paths = QtWidgets.QListWidget()
        self.paths.setIconSize(QtCore.QSize(14, 14))      # Favoritos / Todos, a la altura del texto
        self.paths.itemChanged.connect(self._on_fixed)
        right.addWidget(self.paths, 1)
        prow = QtWidgets.QHBoxLayout()
        for text, slot in (("Añadir carpeta...", self._add_path), ("Cambiar...", self._change_path),
                           ("Quitar", self._remove_path)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            prow.addWidget(b)
        prow.addStretch(1)
        right.addLayout(prow)
        note = QtWidgets.QLabel("Quitar una pestaña o una carpeta no borra nada del disco.")
        note.setEnabled(False)
        right.addWidget(note)
        lay.addLayout(right, 3)
        self._refresh_tabs(0)

    # --- pestañas
    def _row(self):
        return self.tabs.currentRow()

    def _refresh_tabs(self, select=None):
        self.tabs.blockSignals(True)
        self.tabs.clear()
        for lib in self.libs:
            self.tabs.addItem("%s   (%d)" % (lib["name"], len(lib["paths"])))
        self.tabs.blockSignals(False)
        if self.libs:
            self.tabs.setCurrentRow(max(0, min(select if select is not None else 0, len(self.libs) - 1)))
        self._on_tab(self._row())

    def _on_tab(self, r):
        valid = 0 <= r < len(self.libs)
        self.kind.setEnabled(valid)
        self.show.setEnabled(valid)
        self.paths.clear()
        if not valid:
            self.paths_lbl.setText("Crea una pestaña para añadirle carpetas.")
            return
        lib = self.libs[r]
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(max(0, self.kind.findData(lib["kind"])))
        self.kind.blockSignals(False)
        self.show.blockSignals(True)
        self.show.setCurrentIndex(max(0, self.show.findData(lib.get("show", "both"))))
        self.show.blockSignals(False)
        self.paths_lbl.setText("Carpetas de «%s» (las marcadas se ven en el árbol):"
                               % lib["name"])
        self.paths.blockSignals(True)
        for key, text in FIXED_ROWS:
            it = QtWidgets.QListWidgetItem(text)
            it.setData(QtCore.Qt.UserRole, key)
            it.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if lib.get(key, True) else QtCore.Qt.Unchecked)
            it.setToolTip("Enseñar «%s» arriba del árbol de carpetas de esta pestaña" % text)
            if key == "tree_fav":
                from . import ui_fav
                it.setIcon(ui_fav.heart_icon())
            else:
                from . import icon
                it.setIcon(icon())
            self.paths.addItem(it)
        self.paths.blockSignals(False)
        for p in lib["paths"]:
            it = QtWidgets.QListWidgetItem(p)
            if not os.path.isdir(p):
                it.setForeground(QtGui.QBrush(QtGui.QColor("#d9534f")))
                it.setToolTip("La carpeta no existe o no está accesible ahora mismo")
            self.paths.addItem(it)

    def _on_kind(self, _):
        r = self._row()
        if 0 <= r < len(self.libs):
            self.libs[r]["kind"] = self.kind.currentData()

    def _on_fixed(self, item):
        r, key = self._row(), item.data(QtCore.Qt.UserRole)
        if key and 0 <= r < len(self.libs):
            self.libs[r][key] = item.checkState() == QtCore.Qt.Checked

    def _path_row(self):
        """Índice de la carpeta elegida en lib["paths"] (las filas fijas no cuentan), o -1."""
        i = self.paths.currentRow() - len(FIXED_ROWS)
        return i if i >= 0 else -1

    def _on_show(self, _):
        r = self._row()
        if 0 <= r < len(self.libs):
            self.libs[r]["show"] = self.show.currentData()

    def _add_tab(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Nueva pestaña", "Nombre:")
        if ok and name.strip():
            self.libs.append({"name": name.strip(), "kind": "models", "paths": []})
            self._refresh_tabs(len(self.libs) - 1)

    def _rename_tab(self):
        r = self._row()
        if r < 0:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Renombrar", "Nombre:", text=self.libs[r]["name"])
        if ok and name.strip():
            self.libs[r]["name"] = name.strip()
            self._refresh_tabs(r)

    def _remove_tab(self):
        r = self._row()
        if r < 0:
            return
        if QtWidgets.QMessageBox.question(self, "OpenLibrary", "¿Quitar la pestaña «%s»?" % self.libs[r]["name"]) \
                != QtWidgets.QMessageBox.Yes:
            return
        del self.libs[r]
        self._refresh_tabs(r)

    def _move(self, d):
        r = self._row()
        n = r + d
        if r < 0 or not (0 <= n < len(self.libs)):
            return
        self.libs[r], self.libs[n] = self.libs[n], self.libs[r]
        self._refresh_tabs(n)

    # --- carpetas
    def _add_path(self):
        r = self._row()
        if r < 0:
            return
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Carpeta para «%s»" % self.libs[r]["name"])
        if path:
            path = os.path.normpath(path)
            if path not in self.libs[r]["paths"]:
                self.libs[r]["paths"].append(path)
            self._refresh_tabs(r)

    def _change_path(self):
        r, i = self._row(), self._path_row()
        if r < 0 or i < 0:
            return
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Carpeta", self.libs[r]["paths"][i])
        if path:
            self.libs[r]["paths"][i] = os.path.normpath(path)
            self._refresh_tabs(r)

    def _remove_path(self):
        r, i = self._row(), self._path_row()
        if r < 0 or i < 0:
            return
        del self.libs[r]["paths"][i]
        self._refresh_tabs(r)


def _combo(options, current):
    cb = QtWidgets.QComboBox()
    for value, label in options:
        cb.addItem(label, value)
    idx = cb.findData(current)
    cb.setCurrentIndex(max(0, idx))
    return cb


class _ImportTab(QtWidgets.QWidget):
    def __init__(self, imp, parent=None):
        super(_ImportTab, self).__init__(parent)
        self.imp = dict(imp)
        outer = QtWidgets.QVBoxLayout(self)

        g1 = QtWidgets.QGroupBox("Merge")
        f1 = QtWidgets.QFormLayout(g1)
        self.group = QtWidgets.QCheckBox("Agrupar el asset al importar")
        self.group.setChecked(imp["group"])
        f1.addRow(self.group)
        self.layer = _combo([("asset", "Capa con el nombre del asset"),
                             ("current", "Capa actual"),
                             ("file", "Mantener capas del archivo")], imp["layer_mode"])
        f1.addRow("Capa:", self.layer)
        self.odups = _combo([("autorename", "Renombrar automáticamente"),
                             ("merge", "Mantener ambos (mismo nombre)"),
                             ("skip", "Saltar los repetidos"),
                             ("replace", "Reemplazar los de la escena"),
                             ("ask", "Preguntar cada vez")], imp["object_dups"])
        f1.addRow("Objetos duplicados:", self.odups)
        self.mdups = _combo([("scene", "Usar los de la escena"),
                             ("file", "Usar los del archivo"),
                             ("rename", "Renombrar"),
                             ("ask", "Preguntar cada vez")], imp["material_dups"])
        f1.addRow("Materiales duplicados:", self.mdups)
        self.lights = QtWidgets.QCheckBox("Importar luces")
        self.lights.setChecked(imp["import_lights"])
        self.cams = QtWidgets.QCheckBox("Importar cámaras")
        self.cams.setChecked(imp["import_cameras"])
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.lights)
        row.addWidget(self.cams)
        row.addStretch(1)
        f1.addRow(row)
        self.surface = QtWidgets.QCheckBox("Merge and Place: apoyar sobre superficies (Ctrl = solo grid)")
        self.surface.setChecked(imp["place_on_surface"])
        f1.addRow(self.surface)
        self.multi = QtWidgets.QCheckBox("Seguir colocando instancias con cada clic (Esc para terminar)")
        self.multi.setChecked(imp.get("place_multiple", True))
        f1.addRow(self.multi)
        self.missing = _combo([("ask", "Preguntar qué versión usar"),
                               ("fallback", "Usar la que haya sin preguntar")], imp["missing_engine"])
        f1.addRow("Si no hay versión del motor:", self.missing)
        outer.addWidget(g1)

        g2 = QtWidgets.QGroupBox("Merge as Proxy")
        f2 = QtWidgets.QFormLayout(g2)
        self.pmode = _combo([("single", "Todo en uno (un proxy por asset)"),
                             ("per_object", "Uno por objeto")], imp["proxy_mode"])
        f2.addRow("Modo:", self.pmode)
        self.pdisplay = _combo([("bbox", "Caja (lo más ligero)"),
                                ("preview", "Vista previa (nube de puntos / preview)"),
                                ("full", "Malla completa")], imp.get("proxy_display", "preview"))
        f2.addRow("Ver en viewport:", self.pdisplay)
        self.ploc = _combo([("asset", "Junto al asset (carpeta _proxies)"),
                            ("custom", "Carpeta personalizada")], imp["proxy_location"])
        f2.addRow("Guardar proxies:", self.ploc)
        drow = QtWidgets.QHBoxLayout()
        self.pdir = QtWidgets.QLineEdit(imp.get("proxy_custom_dir", ""))
        b = QtWidgets.QPushButton("...")
        b.setFixedWidth(28)
        b.clicked.connect(self._pick_pdir)
        drow.addWidget(self.pdir)
        drow.addWidget(b)
        f2.addRow("Carpeta:", drow)
        outer.addWidget(g2)

        g3 = QtWidgets.QGroupBox("Texturas")
        v3 = QtWidgets.QVBoxLayout(g3)
        self.relink = QtWidgets.QCheckBox("Re-enlazar texturas perdidas al importar")
        self.relink.setChecked(imp.get("relink_on_import", True))
        v3.addWidget(self.relink)
        v3.addWidget(QtWidgets.QLabel("Carpetas extra donde buscar (además de la del asset):"))
        self.rdirs = QtWidgets.QListWidget()
        self.rdirs.addItems(imp.get("relink_dirs", []))
        self.rdirs.setMaximumHeight(80)
        v3.addWidget(self.rdirs)
        brow = QtWidgets.QHBoxLayout()
        ba = QtWidgets.QPushButton("Añadir carpeta...")
        ba.clicked.connect(self._add_rdir)
        br = QtWidgets.QPushButton("Quitar")
        br.clicked.connect(lambda: [self.rdirs.takeItem(self.rdirs.row(i)) for i in self.rdirs.selectedItems()])
        brow.addWidget(ba)
        brow.addWidget(br)
        brow.addStretch(1)
        v3.addLayout(brow)
        outer.addWidget(g3)
        outer.addStretch(1)

    def _pick_pdir(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Carpeta de proxies", self.pdir.text())
        if p:
            self.pdir.setText(os.path.normpath(p))
            self.ploc.setCurrentIndex(self.ploc.findData("custom"))

    def _add_rdir(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Carpeta de texturas")
        if p:
            self.rdirs.addItem(os.path.normpath(p))

    def values(self):
        return {
            "group": self.group.isChecked(),
            "layer_mode": self.layer.currentData(),
            "object_dups": self.odups.currentData(),
            "material_dups": self.mdups.currentData(),
            "import_lights": self.lights.isChecked(),
            "import_cameras": self.cams.isChecked(),
            "place_on_surface": self.surface.isChecked(),
            "place_multiple": self.multi.isChecked(),
            "proxy_display": self.pdisplay.currentData(),
            "missing_engine": self.missing.currentData(),
            "proxy_mode": self.pmode.currentData(),
            "proxy_location": self.ploc.currentData(),
            "proxy_custom_dir": self.pdir.text().strip(),
            "relink_on_import": self.relink.isChecked(),
            "relink_dirs": [self.rdirs.item(i).text() for i in range(self.rdirs.count())],
        }


class _PreviewTab(QtWidgets.QWidget):
    def __init__(self, prev, parent=None):
        super(_PreviewTab, self).__init__(parent)
        f = QtWidgets.QFormLayout(self)
        self.size = QtWidgets.QSpinBox()
        self.size.setRange(128, 2048)
        self.size.setSingleStep(64)
        self.size.setValue(int(prev["size"]))
        f.addRow("Tamaño (px):", self.size)
        self.method = _combo([("render", "Render con el motor de la escena"),
                              ("viewport", "Captura del viewport (rápido)")], prev["method"])
        f.addRow("Método:", self.method)
        self.margin = QtWidgets.QDoubleSpinBox()
        self.margin.setRange(1.0, 2.0)
        self.margin.setSingleStep(0.05)
        self.margin.setValue(float(prev["margin"]))
        f.addRow("Margen de encuadre:", self.margin)
        self.elev = QtWidgets.QDoubleSpinBox()
        self.elev.setRange(-80, 80)
        self.elev.setValue(float(prev["elevation"]))
        f.addRow("Altura de cámara (°):", self.elev)
        self.azim = QtWidgets.QDoubleSpinBox()
        self.azim.setRange(-180, 180)
        self.azim.setValue(float(prev["azimuth"]))
        f.addRow("Giro de cámara (°):", self.azim)
        note = QtWidgets.QLabel("El encuadre automático se calcula con la caja del objeto,\n"
                                "así sirve igual para una silla que para un edificio.\n"
                                "\"Desde mi vista\" usa la vista activa tal cual.")
        note.setEnabled(False)
        f.addRow(note)

    def values(self):
        return {"size": self.size.value(), "method": self.method.currentData(),
                "margin": self.margin.value(), "elevation": self.elev.value(),
                "azimuth": self.azim.value()}


class _InstallTab(QtWidgets.QWidget):
    """Accesos directos de Windows y puente (con su barra opcional) en cada 3ds Max."""

    def __init__(self, parent=None):
        super(_InstallTab, self).__init__(parent)
        from . import bridge_install, shortcuts, ui_setup
        self.bi, self.sc, self.setup = bridge_install, shortcuts, ui_setup
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(10)

        g_win = QtWidgets.QGroupBox("Windows")
        wl = QtWidgets.QVBoxLayout(g_win)
        self.win_state = QtWidgets.QLabel()
        self.win_state.setObjectName("Muted")
        wl.addWidget(self.win_state)
        row = QtWidgets.QHBoxLayout()
        b_sc = QtWidgets.QPushButton("Crear accesos directos")
        b_sc.setToolTip("Menú Inicio y escritorio, con el icono de OpenLibrary")
        b_sc.clicked.connect(self._shortcuts)
        row.addWidget(b_sc)
        row.addStretch(1)
        wl.addLayout(row)
        hint = QtWidgets.QLabel(ui_setup.PIN_HINT)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setTextFormat(QtCore.Qt.RichText)
        wl.addWidget(hint)
        lay.addWidget(g_win)

        g_max = QtWidgets.QGroupBox("3ds Max")
        ml = QtWidgets.QVBoxLayout(g_max)
        intro = QtWidgets.QLabel(
            "Para arrastrar assets a la escena, generar previews o re-enlazar, cada 3ds Max necesita un "
            "puente pequeño (sin ventanas ni menús) que arranca con Max y escucha solo en este equipo.")
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        ml.addWidget(intro)
        self.list = QtWidgets.QTreeWidget()
        self.list.setHeaderLabels(["Versión", "Puente", "Botón en Max"])
        self.list.setRootIsDecorated(False)
        self.list.setColumnWidth(0, 150)
        self.list.setColumnWidth(1, 150)
        self.list.setMinimumHeight(110)
        ml.addWidget(self.list, 1)
        self.cb_toolbar = QtWidgets.QCheckBox("Añadir el botón de OpenLibrary a una barra de herramientas de Max")
        self.cb_toolbar.setChecked(True)
        ml.addWidget(self.cb_toolbar)
        row2 = QtWidgets.QHBoxLayout()
        b_in = QtWidgets.QPushButton("Instalar / actualizar")
        b_in.setObjectName("Primary")
        b_in.clicked.connect(self._install)
        b_out = QtWidgets.QPushButton("Quitar")
        b_out.clicked.connect(self._uninstall)
        row2.addWidget(b_in)
        row2.addWidget(b_out)
        row2.addStretch(1)
        ml.addLayout(row2)
        note = QtWidgets.QLabel("Después de instalar, reinicia 3ds Max.")
        note.setObjectName("Muted")
        ml.addWidget(note)
        lay.addWidget(g_max, 1)
        self.list.currentItemChanged.connect(self._sync_toolbar_cb)
        self._refresh()

    def _refresh(self):
        have = [w for w in ("start", "desktop") if self.sc.exists(w)]
        names = {"start": "menú Inicio", "desktop": "escritorio"}
        self.win_state.setText("Accesos directos: " + (", ".join(names[w] for w in have) if have else "ninguno"))
        self.list.clear()
        self.targets = self.bi.find_targets()
        if not self.targets:
            self.list.addTopLevelItem(QtWidgets.QTreeWidgetItem(["No encuentro 3ds Max", "", ""]))
            return
        for t in self.targets:
            v = t.installed_version()
            if not t.supported:
                state = "no compatible (Max %d+)" % self.bi.MIN_VERSION
            elif v and t.outdated():
                state = "desactualizado (%s): pulsa Instalar y reinicia Max" % v
            elif v:
                state = "instalado (%s)" % v
            else:
                state = "no instalado"
            tb = ("sí" if t.toolbar_enabled() else "no") if v else ""
            it = QtWidgets.QTreeWidgetItem([t.label, state, tb])
            it.setDisabled(not t.supported)
            self.list.addTopLevelItem(it)
        for i, t in enumerate(self.targets):
            if t.supported:
                self.list.setCurrentItem(self.list.topLevelItem(i))
                break

    def _current(self):
        it = self.list.currentItem()
        if it is None or not self.targets:
            return None
        t = self.targets[self.list.indexOfTopLevelItem(it)]
        return t if t.supported else None

    def _sync_toolbar_cb(self, *_):
        t = self._current()
        if t is not None and t.installed_version():
            self.cb_toolbar.setChecked(t.toolbar_enabled())

    def _shortcuts(self):
        done, errors = self.setup.install(True, True, [], False)
        self.setup.report(self, done, errors, False)
        self._refresh()

    def _install(self):
        t = self._current()
        if t is None:
            return
        done, errors = self.setup.install(False, False, [t], self.cb_toolbar.isChecked())
        self._refresh()
        self.setup.report(self, done, errors, True)

    def _uninstall(self):
        t = self._current()
        if t is None or not t.installed_version():
            return
        if QtWidgets.QMessageBox.question(self, "OpenLibrary", "¿Quitar el puente de %s?" % t.label) \
                != QtWidgets.QMessageBox.Yes:
            return
        try:
            t.uninstall()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "OpenLibrary", "No se pudo quitar:\n%s" % exc)
        self._refresh()


class _WorkspaceTab(QtWidgets.QWidget):
    """Dónde se guarda lo que comparte el equipo: solo en este equipo o en una carpeta común (NAS)."""

    def __init__(self, settings, parent=None):
        super(_WorkspaceTab, self).__init__(parent)
        from . import config
        self.settings = settings
        self.config = config
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(10)
        intro = QtWidgets.QLabel(
            "Si trabajáis varios con la misma biblioteca, elegid todos la misma carpeta del NAS: "
            "las pestañas y sus carpetas, las carpetas ocultas, los iconos de carpeta, las medidas y el "
            "mapeado de cada material, los ajustes de preview y los archivos de medidas de fabricante se "
            "guardan ahí y los ve todo el equipo. Lo personal (ventana, tema, tamaño de miniatura, con qué "
            "3ds Max conectas…) sigue en tu equipo.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.r_local = QtWidgets.QRadioButton("Solo en este equipo")
        self.r_shared = QtWidgets.QRadioButton("En una carpeta compartida (NAS):")
        lay.addWidget(self.r_local)
        lay.addWidget(self.r_shared)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(22, 0, 0, 0)
        self.path = QtWidgets.QLineEdit(settings.workspace)
        self.path.setPlaceholderText(r"\\SERVIDOR\BIBLIO\_OpenLibrary")
        row.addWidget(self.path, 1)
        b = QtWidgets.QPushButton("Elegir…")
        b.clicked.connect(self._choose)
        row.addWidget(b)
        lay.addLayout(row)
        (self.r_shared if settings.workspace else self.r_local).setChecked(True)
        self.r_local.toggled.connect(self._sync)
        self.path.textChanged.connect(self._sync)
        self.state = QtWidgets.QLabel()
        self.state.setWordWrap(True)
        self.state.setObjectName("Muted")
        lay.addWidget(self.state)
        tip = QtWidgets.QLabel(
            "Consejo: que todos escribáis las carpetas de las pestañas igual (mejor la ruta de red "
            "\\\\SERVIDOR\\… que una letra de unidad). Las medidas y el mapeado de los materiales valen "
            "igual con cualquiera de las dos.")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        lay.addWidget(tip)
        cap = QtWidgets.QLabel("MEDIDAS DE FABRICANTE")
        cap.setObjectName("Caption")
        lay.addSpacing(8)
        lay.addWidget(cap)
        self.m_lbl = QtWidgets.QLabel()
        self.m_lbl.setWordWrap(True)
        lay.addWidget(self.m_lbl)
        self.b_move = QtWidgets.QPushButton("Traer aquí las medidas que hay dentro de las carpetas de la biblioteca")
        self.b_move.clicked.connect(self._move)
        lay.addWidget(self.b_move, 0, QtCore.Qt.AlignLeft)
        lay.addStretch(1)
        self._sync()

    def folder(self):
        f = self.path.text().strip()
        return os.path.normpath(f) if f and self.r_shared.isChecked() else ""

    def measures_dir(self):
        return os.path.join(self.folder() or self.config.app_data_dir(), "medidas")

    def _choose(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Carpeta del NAS para el espacio de trabajo",
                                                       self.path.text())
        if d:
            self.path.setText(self.config.workspace_dir(d))      # …\_OpenLibrary
            self.r_shared.setChecked(True)

    def _sync(self, *_):
        self.path.setEnabled(self.r_shared.isChecked())
        f = self.folder()
        if not f:
            self.state.setText("Todo se guarda solo en este equipo (%s)." % self.config.app_data_dir())
        elif f == self.settings.workspace and self.settings.ws_state == "offline":
            self.state.setText("Sin conexión con la carpeta: se está usando la última copia que hay en este "
                               "equipo. Los cambios se juntan con los del equipo al volver a conectar.")
        elif os.path.isfile(os.path.join(f, self.config.WORKSPACE_FILE)):
            self.state.setText("Esa carpeta ya es un espacio de trabajo: al aceptar usarás sus pestañas y "
                               "medidas (las tuyas se sustituyen por las del equipo).")
        elif os.path.isdir(f) or os.path.isdir(os.path.dirname(f)):
            self.state.setText("Carpeta nueva: al aceptar se crea «%s» con tus pestañas y medidas, y tus "
                               "compañeros podrán unirse eligiendo esta misma carpeta." % f)
        else:
            self.state.setText("No encuentro esa carpeta.")
        self.m_lbl.setText("Se guardan en %s (un archivo por carpeta de biblioteca, p. ej. «02_POLIIGON.json»)."
                           % self.measures_dir())

    def _roots(self):
        out = []
        for lib in self.settings.libraries:
            if lib.get("kind") == "materials":
                out += [p for p in lib.get("paths", []) if p]
        return out

    def _move(self):
        from . import surfaces
        moved = surfaces.move_measures(self._roots(), self.measures_dir())
        if moved:
            QtWidgets.QMessageBox.information(
                self, "OpenLibrary", "Movidos %d archivos de medidas a %s:\n\n%s" % (
                    len(moved), self.measures_dir(), "\n".join(os.path.basename(d) for _s, d in moved)))
        else:
            QtWidgets.QMessageBox.information(self, "OpenLibrary", "No hay archivos de medidas dentro de las "
                                                                   "carpetas de las pestañas de materiales.")


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None, tab=0):
        super(SettingsDialog, self).__init__(parent)
        self.settings = settings
        self.setWindowTitle("OpenLibrary - Ajustes")
        from . import app_icon
        self.setWindowIcon(app_icon())
        self.resize(660, 640)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.tabs = QtWidgets.QTabWidget()
        self.t_libs = _LibrariesTab(settings.libraries)
        self.t_imp = _ImportTab(settings.imp)
        self.t_prev = _PreviewTab(settings.preview)
        self.tabs.addTab(self.t_libs, "Libraries")
        self.tabs.addTab(self.t_imp, "Importación")
        self.tabs.addTab(self.t_prev, "Preview")
        self.t_max = _InstallTab()
        self.tabs.addTab(self.t_max, "Instalación")
        self.t_ws = _WorkspaceTab(settings)
        self.tabs.addTab(self.t_ws, "Espacio de trabajo")
        self.tabs.setCurrentIndex(tab)
        lay.addWidget(self.tabs)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def showEvent(self, event):
        super(SettingsDialog, self).showEvent(event)
        from . import theme
        theme.dark_title_bar(self)

    def accept(self):
        d = self.settings.data
        d["libraries"] = self.t_libs.libs
        d["import"].update(self.t_imp.values())
        d["preview"].update(self.t_prev.values())
        d["current_library"] = max(0, min(d.get("current_library", 0), len(d["libraries"]) - 1))
        new = self.t_ws.folder()
        if new != self.settings.workspace:
            from .config import WORKSPACE_FILE, prepare_workspace
            if new and not os.path.isdir(new) and not os.path.isdir(os.path.dirname(new)):
                QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No encuentro la carpeta:\n%s" % new)
                self.tabs.setCurrentWidget(self.t_ws)
                return
            theirs = bool(new) and os.path.isfile(os.path.join(new, WORKSPACE_FILE))
            if new:
                try:
                    prepare_workspace(new)
                except OSError as e:
                    QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No puedo crear la carpeta:\n%s\n\n%s"
                                                  % (new, e))
                    return
            if theirs and QtWidgets.QMessageBox.question(
                    self, "OpenLibrary", "Esa carpeta ya tiene el espacio de trabajo del equipo.\n\n"
                    "Vas a usar sus pestañas, carpetas ocultas y medidas en lugar de las tuyas. ¿Seguir?"
            ) != QtWidgets.QMessageBox.Yes:
                return
            self.settings.set_workspace(new, take_theirs=theirs)
        else:
            self.settings.save()
        super(SettingsDialog, self).accept()
