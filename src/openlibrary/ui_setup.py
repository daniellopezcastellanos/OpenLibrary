"""Asistente de la primera vez: 1) espacio de trabajo (solo en este equipo o común en el NAS),
2) accesos directos de Windows y puente/botón en 3ds Max.
"""
import os

from . import app_icon, bridge_install, config, shortcuts, theme
from .qt import QtCore, QtWidgets

WS_INTRO = (
    "<b>¿Trabajas solo o con más gente?</b><br><br>"
    "Si la biblioteca la usáis varias personas desde un NAS, elegid todos la misma carpeta del NAS. "
    "OpenLibrary crea dentro la carpeta <b>_OpenLibrary</b> con lo que es del equipo: las pestañas y "
    "sus carpetas, las carpetas ocultas, los iconos de carpeta, las medidas y el mapeado de cada "
    "material, los ajustes de preview y las medidas de fabricante. Lo que cambia uno lo ven los demás "
    "al momento (la app lo mira cada pocos segundos), y si el NAS no está se sigue trabajando con la "
    "última copia.<br><br>"
    "Lo tuyo (ventana, modo claro u oscuro, favoritos, con qué 3ds Max conectas) se queda en tu equipo. "
    "Se puede cambiar cuando quieras en Ajustes › Espacio de trabajo.")

PIN_HINT = ("Para tenerla en la <b>barra de tareas</b>: con OpenLibrary abierta, haz clic derecho en su "
            "icono de la barra de tareas › <b>Anclar a la barra de tareas</b>. Windows no deja que un "
            "programa se ancle solo.")


def max_running():
    """¿Hay algún 3ds Max abierto? (hay que reiniciarlo para que cargue el puente)."""
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq 3dsmax.exe", "/NH"], capture_output=True,
                             text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return "3dsmax.exe" in out.lower()
    except Exception:
        return False


def install(start_menu, desktop, targets, toolbar):
    """Hace lo elegido. Devuelve (hechos, errores) como listas de textos."""
    done, errors = [], []
    for where, ok, label in (("start", start_menu, "menú Inicio"), ("desktop", desktop, "escritorio")):
        if not ok:
            continue
        try:
            shortcuts.create(where)
            done.append("Acceso directo en el %s" % label)
        except Exception as exc:
            errors.append("Acceso directo en el %s: %s" % (label, exc))
    for t in targets:
        try:
            t.install(toolbar=toolbar)
            done.append("Puente en %s%s" % (t.label, " con su botón en la barra" if toolbar else ""))
        except Exception as exc:
            errors.append("%s: %s" % (t.label, exc))
    return done, errors


def report(parent, done, errors, any_max):
    lines = []
    if done:
        lines.append("<b>Listo:</b><br>" + "<br>".join("✔ " + d for d in done))
    if errors:
        lines.append("<b>No se pudo:</b><br>" + "<br>".join("✖ " + e for e in errors))
    if any_max and max_running():
        lines.append("Reinicia 3ds Max para que se conecte%s." % (
            " y aparezca la barra «OpenLibrary»" if any("barra" in d for d in done) else ""))
    if any(d.startswith("Acceso") for d in done):
        lines.append(PIN_HINT)
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle("OpenLibrary")
    box.setIconPixmap(app_icon().pixmap(48, 48))
    box.setTextFormat(QtCore.Qt.RichText)
    box.setText("<br><br>".join(lines) or "No había nada que instalar.")
    box.exec()


class SetupDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None):
        super(SetupDialog, self).__init__(parent)
        self.settings = settings
        self.workspace_changed = False
        self.setWindowTitle("Instalar OpenLibrary")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(620)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 20)
        lay.setSpacing(14)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(16)
        logo = QtWidgets.QLabel()
        logo.setPixmap(app_icon().pixmap(64, 64))
        head.addWidget(logo, 0, QtCore.Qt.AlignTop)
        txt = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("Bienvenido a OpenLibrary")
        title.setStyleSheet("font-size: 16pt; font-weight: 600;")
        txt.addWidget(title)
        self.sub = QtWidgets.QLabel("Paso 1 de 2 · Espacio de trabajo")
        self.sub.setObjectName("Muted")
        self.sub.setWordWrap(True)
        txt.addWidget(self.sub)
        head.addLayout(txt, 1)
        lay.addLayout(head)

        # --- paso 1: espacio de trabajo
        self.pages = QtWidgets.QStackedWidget()
        lay.addWidget(self.pages)
        p1 = QtWidgets.QWidget()
        l1 = QtWidgets.QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(10)
        for para in WS_INTRO.split("<br><br>"):          # un párrafo por etiqueta: Qt no recorta el texto
            lab = QtWidgets.QLabel(para)
            lab.setWordWrap(True)
            lab.setTextFormat(QtCore.Qt.RichText)
            lab.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)
            l1.addWidget(lab)
        self.r_local = QtWidgets.QRadioButton("Solo en este equipo")
        self.r_shared = QtWidgets.QRadioButton("Con más gente, en una carpeta del NAS:")
        self.r_local.setChecked(True)
        l1.addWidget(self.r_local)
        l1.addWidget(self.r_shared)
        prow = QtWidgets.QHBoxLayout()
        prow.setContentsMargins(22, 0, 0, 0)
        self.ws_path = QtWidgets.QLineEdit()
        self.ws_path.setPlaceholderText(r"\\SERVIDOR\BIBLIO")
        self.ws_path.textChanged.connect(lambda _t: self._ws_sync())
        prow.addWidget(self.ws_path, 1)
        b_pick = QtWidgets.QPushButton("Elegir…")
        b_pick.clicked.connect(self._ws_pick)
        prow.addWidget(b_pick)
        l1.addLayout(prow)
        self.ws_state = QtWidgets.QLabel()
        self.ws_state.setObjectName("Muted")
        self.ws_state.setWordWrap(True)
        l1.addWidget(self.ws_state)
        self.r_local.toggled.connect(lambda _on: self._ws_sync())
        l1.addStretch(1)
        r1 = QtWidgets.QHBoxLayout()
        r1.addStretch(1)
        b_next = QtWidgets.QPushButton("Siguiente")
        b_next.setObjectName("Primary")
        b_next.clicked.connect(self._ws_next)
        r1.addWidget(b_next)
        l1.addLayout(r1)
        self.pages.addWidget(p1)

        # --- paso 2: Windows y 3ds Max
        p2 = QtWidgets.QWidget()
        lay2 = QtWidgets.QVBoxLayout(p2)
        lay2.setContentsMargins(0, 0, 0, 0)
        lay2.setSpacing(14)
        self.pages.addWidget(p2)
        self._ws_sync()

        g_win = QtWidgets.QGroupBox("Windows")
        wl = QtWidgets.QVBoxLayout(g_win)
        self.cb_start = QtWidgets.QCheckBox("Acceso directo en el menú Inicio")
        self.cb_start.setChecked(True)
        self.cb_desk = QtWidgets.QCheckBox("Acceso directo en el escritorio")
        self.cb_desk.setChecked(not shortcuts.exists("desktop"))
        wl.addWidget(self.cb_start)
        wl.addWidget(self.cb_desk)
        hint = QtWidgets.QLabel(PIN_HINT)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setTextFormat(QtCore.Qt.RichText)
        wl.addWidget(hint)
        lay2.addWidget(g_win)

        g_max = QtWidgets.QGroupBox("3ds Max")
        ml = QtWidgets.QVBoxLayout(g_max)
        self.max_boxes = []
        targets = [t for t in bridge_install.find_targets() if t.supported]
        if not targets:
            lab = QtWidgets.QLabel("No encuentro 3ds Max %d o superior en este equipo. Puedes instalar el puente "
                                   "más tarde en Ajustes › Instalación." % bridge_install.MIN_VERSION)
            lab.setObjectName("Muted")
            lab.setWordWrap(True)
            ml.addWidget(lab)
        for t in targets:
            v = t.installed_version()
            cb = QtWidgets.QCheckBox("Conectar %s%s" % (t.label, "  (puente %s ya instalado)" % v if v else ""))
            cb.setChecked(True)
            ml.addWidget(cb)
            self.max_boxes.append((cb, t))
        self.cb_toolbar = QtWidgets.QCheckBox("Añadir el botón de OpenLibrary (con su icono) a una barra de "
                                              "herramientas de 3ds Max")
        self.cb_toolbar.setChecked(True)
        self.cb_toolbar.setEnabled(bool(targets))
        ml.addWidget(self.cb_toolbar)
        note = QtWidgets.QLabel("El puente no añade ventanas ni menús: solo deja que arrastres assets desde "
                                "OpenLibrary a la escena. La barra se puede mover o acoplar como cualquier otra.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        ml.addWidget(note)
        lay2.addWidget(g_max)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        b_no = QtWidgets.QPushButton("Ahora no")
        b_no.clicked.connect(self.reject)
        b_ok = QtWidgets.QPushButton("Instalar")
        b_ok.setObjectName("Primary")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self._install)
        row.addWidget(b_no)
        row.addWidget(b_ok)
        lay2.addLayout(row)

    # --- paso 1
    def _ws_folder(self):
        t = self.ws_path.text().strip()
        return config.workspace_dir(t) if t and self.r_shared.isChecked() else ""

    def _ws_pick(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Carpeta del NAS para el espacio de trabajo",
                                                       self.ws_path.text())
        if d:
            self.ws_path.setText(os.path.normpath(d))
            self.r_shared.setChecked(True)

    def _ws_sync(self):
        self.ws_path.setEnabled(self.r_shared.isChecked())
        f = self._ws_folder()
        if not self.r_shared.isChecked():
            self.ws_state.setText("Todo se guarda solo en este equipo.")
        elif not f:
            self.ws_state.setText("Elige la carpeta del NAS donde está (o estará) la biblioteca del equipo.")
        elif os.path.isfile(os.path.join(f, config.WORKSPACE_FILE)):
            self.ws_state.setText("Ya hay un espacio de trabajo en %s: usarás las pestañas y medidas del equipo." % f)
        elif os.path.isdir(os.path.dirname(f)):
            self.ws_state.setText("Se creará %s y tus compañeros podrán unirse eligiendo la misma carpeta." % f)
        else:
            self.ws_state.setText("No encuentro esa carpeta.")

    def _ws_next(self):
        f = self._ws_folder()
        if f:
            if not os.path.isdir(os.path.dirname(f)):
                QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No encuentro la carpeta:\n%s" % os.path.dirname(f))
                return
            try:
                theirs = config.prepare_workspace(f)
            except OSError as e:
                QtWidgets.QMessageBox.warning(self, "OpenLibrary", "No puedo crear la carpeta:\n%s\n\n%s" % (f, e))
                return
            self.settings.set_workspace(f, take_theirs=theirs)
            self.workspace_changed = True
        self.sub.setText("Paso 2 de 2 · Elige dónde quieres tenerla a mano (se cambia en Ajustes › Instalación).")
        self.pages.setCurrentIndex(1)

    def showEvent(self, event):
        super(SetupDialog, self).showEvent(event)
        theme.dark_title_bar(self)

    def done(self, r):
        self.settings.data["setup_done"] = True
        self.settings.save()
        super(SetupDialog, self).done(r)

    def _install(self):
        targets = [t for cb, t in self.max_boxes if cb.isChecked()]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            done, errors = install(self.cb_start.isChecked(), self.cb_desk.isChecked(), targets,
                                   self.cb_toolbar.isChecked())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        report(self, done, errors, bool(targets))
        self.accept()
