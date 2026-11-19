"""Aspecto de OpenLibrary, el de las apps Open3D: fondo cálido, esquinas rectas, etiquetas y botones en
monoespaciada y mayúsculas, acento ámbar (el libro del icono). Modo claro y oscuro.
"""
import os
import re

from . import icon_path
from .qt import QtCore, QtGui, QtWidgets

# Colores (estilo Open3D: grises cálidos, como el lanzador de las apps; acento ámbar)
LIGHT = dict(BG="#F2F1EE", SIDEBAR="#EDECE8", SURFACE="#F7F6F3", SURFACE_HI="#E6E4DF", BORDER="#D7D5CF",
             BORDER_HI="#B4B1A9", TEXT="#232327", MUTED="#5D5C61", FAINT="#99978F", ACCENT="#D48A00",
             ACCENT_HI="#E99B0C", ACCENT_TEXT="#1A1306", OK="#1E8F57", WARN="#B88700")
DARK = dict(BG="#171719", SIDEBAR="#1C1C1F", SURFACE="#202023", SURFACE_HI="#29292D", BORDER="#323236",
            BORDER_HI="#48484D", TEXT="#ECEBE7", MUTED="#9C9A95", FAINT="#67665F", ACCENT="#F0A93B",
            ACCENT_HI="#FFBE5C", ACCENT_TEXT="#1A1306", OK="#4CC38A", WARN="#F2C230")
# los valores del modo actual (set_mode los cambia)
BG, SIDEBAR, SURFACE, SURFACE_HI = DARK["BG"], DARK["SIDEBAR"], DARK["SURFACE"], DARK["SURFACE_HI"]
BORDER, BORDER_HI, TEXT, MUTED, FAINT = DARK["BORDER"], DARK["BORDER_HI"], DARK["TEXT"], DARK["MUTED"], DARK["FAINT"]
ACCENT, ACCENT_HI, ACCENT_TEXT, OK, WARN = (DARK["ACCENT"], DARK["ACCENT_HI"], DARK["ACCENT_TEXT"], DARK["OK"],
                                            DARK["WARN"])
MODE = "dark"
RADIUS = 0              # esquinas de las tarjetas pintadas (rectas)
MONO_FAMILIES = ("Cascadia Mono", "JetBrains Mono", "Consolas", "Courier New")
# Trazos de los iconos SVG (pensados para fondo oscuro) -> su equivalente en modo claro
_ICON_LIGHT = {"#D4D4D4": "#454C57", "#C9CED6": "#454C57", "#9AA1AC": "#6A717C", "#F1F3F6": "#454C57"}
_icon_cache = {}


def set_mode(mode):
    """Cambia entre "dark" y "light". Después hay que llamar a apply(app)."""
    global MODE
    MODE = "light" if mode == "light" else "dark"
    globals().update(LIGHT if MODE == "light" else DARK)
    _icon_cache.clear()


def mono_family():
    for fam in MONO_FAMILIES:
        if QtGui.QFontInfo(QtGui.QFont(fam)).family().lower() == fam.lower():
            return fam
    return "Consolas"


def mono_font(pt=8.5, bold=False, caps=True, spacing=1.5):
    """Fuente de las etiquetas Open3D: monoespaciada, en mayúsculas y espaciada."""
    f = QtGui.QFont(mono_family())
    f.setPointSizeF(pt)
    f.setBold(bold)
    if caps:
        f.setCapitalization(QtGui.QFont.AllUppercase)
    f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, spacing)
    return f


def is_light():
    return MODE == "light"


FONT_FAMILY = "Segoe UI Variable Text"
FONT_FALLBACK = "Segoe UI"


def color(c):
    return QtGui.QColor(c)


def svg_text(name, tint=None):
    """Texto del SVG de un icono, con los trazos adaptados al modo (o teñidos de un color)."""
    with open(icon_path(name), encoding="utf-8") as fh:
        text = fh.read()
    if tint:
        return re.sub(r'(stroke|fill)="#[0-9A-Fa-f]{6}"', lambda m: '%s="%s"' % (m.group(1), tint), text)
    if MODE == "light":
        for dark, light in _ICON_LIGHT.items():
            text = text.replace(dark, light)
    return text


def icon_from_svg(text, size=64):
    from PySide6 import QtSvg
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(text.encode("utf-8")))
    ic = QtGui.QIcon()
    for px in (size // 2, size):
        pix = QtGui.QPixmap(px, px)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        renderer.render(painter)
        painter.end()
        ic.addPixmap(pix)
    return ic


def icon(name, tint=None):
    """Icono de la carpeta icons/, legible en el modo actual."""
    key = (name, MODE, tint)
    ic = _icon_cache.get(key)
    if ic is None:
        try:
            ic = icon_from_svg(svg_text(name, tint))
        except Exception:
            ic = QtGui.QIcon(icon_path(name))
        _icon_cache[key] = ic
    return ic


def _url(name):
    """Ruta de un icono para la hoja de estilos. En modo claro se usa una copia con los trazos oscuros."""
    path = icon_path(name)
    if MODE == "light":
        try:
            from .config import app_data_dir
            folder = os.path.join(app_data_dir(), "icons_light")
            os.makedirs(folder, exist_ok=True)
            out = os.path.join(folder, name + ".svg")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(svg_text(name))
            path = out
        except OSError:
            pass
    return path.replace("\\", "/")


def stylesheet():
    return """
* { outline: none; }
QWidget { color: %(TEXT)s; font-size: 10pt; }
QMainWindow, QDialog { background: %(BG)s; }
QToolTip { background: %(SURFACE_HI)s; color: %(TEXT)s; border: 1px solid %(BORDER_HI)s;
           border-radius: 6px; padding: 6px 8px; }

/* Zonas de la ventana */
#Header { background: %(SIDEBAR)s; border-bottom: 1px solid %(BORDER)s; }
#Sidebar { background: %(SIDEBAR)s; border-right: 1px solid %(BORDER)s; }
#Main { background: %(BG)s; }
#StatusBar { background: %(SIDEBAR)s; border-top: 1px solid %(BORDER)s; }
#AppTitle { font-size: 12.5pt; font-weight: 600; color: %(TEXT)s; }
#AppVersion { color: %(FAINT)s; font-size: 8.5pt; padding-top: 3px; }
#Caption { color: %(FAINT)s; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }
#FolderTitle { font-size: 14pt; font-weight: 600; }
#Muted, #Status { color: %(MUTED)s; }
#Status { font-size: 9pt; }

/* Pestañas de biblioteca como "pastillas" */
QTabBar#LibTabs { background: transparent; }
QTabBar#LibTabs::tab { background: transparent; color: %(MUTED)s; border: none; border-radius: 8px;
                       padding: 6px 14px; margin: 0 2px; font-weight: 600; }
QTabBar#LibTabs::tab:hover { background: %(SURFACE_HI)s; color: %(TEXT)s; }
QTabBar#LibTabs::tab:selected { background: %(SURFACE_HI)s; color: %(ACCENT)s; }

/* Buscador */
QLineEdit { background: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 8px;
            padding: 6px 10px; selection-background-color: %(ACCENT)s; selection-color: %(ACCENT_TEXT)s; }
QLineEdit:hover { border-color: %(BORDER_HI)s; }
QLineEdit:focus { border-color: %(ACCENT)s; }
QLineEdit#Search { border-radius: 10px; padding: 7px 10px 7px 4px; min-width: 260px; }

/* Botones */
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px; }
QToolButton:hover { background: %(SURFACE_HI)s; }
QToolButton:pressed { background: %(BORDER_HI)s; }
QToolButton:checked { background: %(SURFACE_HI)s; border-color: %(BORDER_HI)s; }
QToolButton#Action { background: %(SURFACE)s; border: 1px solid %(BORDER)s; padding: 6px 12px; }
QToolButton#Action:hover { background: %(SURFACE_HI)s; border-color: %(BORDER_HI)s; }
QToolButton#Action[popupMode="1"], QToolButton#Action[popupMode="2"] { padding-right: 26px; }
QToolButton#Action::menu-indicator { subcontrol-origin: padding; subcontrol-position: right center; right: 8px; }
QToolButton::menu-button { border: none; width: 18px; }
QToolButton::menu-arrow, QToolButton::menu-indicator { image: url("%(chevron)s"); width: 12px; height: 12px; }
QToolButton#Chip { background: transparent; border: 1px solid %(BORDER)s; border-radius: 13px;
                   padding: 3px 12px; color: %(MUTED)s; font-size: 9pt; }
QToolButton#Chip:hover { border-color: %(BORDER_HI)s; color: %(TEXT)s; background: %(SURFACE)s; }
QToolButton#Chip:checked { background: %(ACCENT)s; border-color: %(ACCENT)s; color: %(ACCENT_TEXT)s;
                           font-weight: 600; }
#Inspector { background: %(SIDEBAR)s; border-left: 1px solid %(BORDER)s; }
#Inspector QScrollArea, #Inspector QScrollArea > QWidget > QWidget { background: transparent; }
#Inspector QPushButton { min-width: 0; padding: 7px 8px; }
#Inspector QPushButton#Primary { padding: 9px 8px; }
QTreeView#Folders { selection-background-color: transparent; show-decoration-selected: 0; }
QTreeView#Folders::branch:selected { background: transparent; }
#InspectorName { font-size: 13pt; font-weight: 600; }
QTreeView#Folders::item:selected { background: %(SURFACE_HI)s; color: %(TEXT)s;
                                   border-left: 2px solid %(ACCENT)s; border-radius: 0; }
QToolButton[popupMode="0"]::menu-indicator { image: none; width: 0; }
QToolButton#Primary { background: %(ACCENT)s; color: %(ACCENT_TEXT)s; font-weight: 600; padding: 6px 14px; }
QToolButton#Primary:hover { background: %(ACCENT_HI)s; }

QPushButton { background: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 8px;
              padding: 7px 16px; min-width: 70px; }
QPushButton:hover { background: %(SURFACE_HI)s; border-color: %(BORDER_HI)s; }
QPushButton:pressed { background: %(BORDER_HI)s; }
QPushButton:default, QPushButton#Primary { background: %(ACCENT)s; color: %(ACCENT_TEXT)s;
                                           border-color: %(ACCENT)s; font-weight: 600; }
QPushButton:default:hover, QPushButton#Primary:hover { background: %(ACCENT_HI)s; border-color: %(ACCENT_HI)s; }
QPushButton:disabled, QToolButton:disabled { color: %(FAINT)s; }

/* Árbol de carpetas y listas */
QTreeView, QListView, QListWidget, QTreeWidget { background: transparent; border: none; }
QTreeView::item, QListWidget::item, QTreeWidget::item { padding: 4px 4px; border-radius: 6px; }
QTreeView::item:hover, QListWidget::item:hover, QTreeWidget::item:hover { background: %(SURFACE_HI)s; }
QTreeView::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {
    background: %(SURFACE_HI)s; color: %(ACCENT)s; }
QTreeView::branch { background: transparent; }
QTreeView::branch:has-children:closed { image: url("%(branch_closed)s"); }
QTreeView::branch:has-children:open { image: url("%(branch_open)s"); }
#Sep { background: %(BORDER_HI)s; }
QProgressBar { background: %(BORDER)s; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: %(ACCENT)s; border-radius: 3px; }
QTreeWidget::item { border-radius: 0; }
QListWidget, QTreeWidget { background: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 8px; padding: 4px; }
QHeaderView::section { background: transparent; color: %(MUTED)s; border: none;
                       border-bottom: 1px solid %(BORDER)s; padding: 6px; font-weight: 600; }

/* Desplegables */
QComboBox { background: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 8px; padding: 5px 10px;
            min-height: 18px; }
QComboBox:hover { border-color: %(BORDER_HI)s; }
QComboBox:disabled { color: %(MUTED)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url("%(chevron)s"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: %(SURFACE)s; border: 1px solid %(BORDER_HI)s; border-radius: 8px;
                              padding: 4px; selection-background-color: %(SURFACE_HI)s;
                              selection-color: %(ACCENT)s; }
QLabel#MaxChip { background: transparent; border: none; padding: 4px 6px; color: %(TEXT)s; }

QSpinBox, QDoubleSpinBox { background: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 8px;
                           padding: 5px 8px; }

/* Menús */
QMenu { background: %(SURFACE)s; border: 1px solid %(BORDER_HI)s; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
QMenu::item:selected { background: %(SURFACE_HI)s; color: %(ACCENT)s; }
QMenu::item:disabled { color: %(FAINT)s; }
QMenu::separator { height: 1px; background: %(BORDER)s; margin: 5px 8px; }
QMenu::icon { padding-left: 8px; }

/* Casillas */
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid %(BORDER_HI)s;
                       background: %(SURFACE)s; }
QCheckBox::indicator:hover { border-color: %(ACCENT)s; }
QCheckBox::indicator:checked { background: %(ACCENT)s; border-color: %(ACCENT)s; image: url("%(check)s"); }
QRadioButton::indicator { width: 15px; height: 15px; border-radius: 8px; border: 1px solid %(BORDER_HI)s;
                          background: %(SURFACE)s; }
QRadioButton::indicator:checked { background: %(ACCENT)s; border: 4px solid %(SURFACE)s;
                                  outline: 1px solid %(ACCENT)s; }

/* Deslizador de tamaño */
QSlider::groove:horizontal { height: 4px; background: %(BORDER_HI)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(ACCENT)s; border-radius: 2px; }
QSlider::handle:horizontal { background: %(TEXT)s; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: %(ACCENT_HI)s; }

/* Barras de desplazamiento finas */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: %(BORDER_HI)s; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: %(FAINT)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSplitter::handle { background: transparent; }

/* Barra de información (tarjeta) */
#InfoBar { background: %(SURFACE)s; border: 1px solid %(BORDER)s; border-radius: 12px; }

/* Ajustes */
QTabWidget::pane { border: 1px solid %(BORDER)s; border-radius: 10px; background: %(SIDEBAR)s; top: -1px; }
QTabWidget > QTabBar::tab { background: transparent; color: %(MUTED)s; padding: 8px 16px; border: none;
                            border-bottom: 2px solid transparent; font-weight: 600; }
QTabWidget > QTabBar::tab:hover { color: %(TEXT)s; }
QTabWidget > QTabBar::tab:selected { color: %(ACCENT)s; border-bottom-color: %(ACCENT)s; }
QGroupBox { border: 1px solid %(BORDER)s; border-radius: 10px; margin-top: 14px; padding: 12px 10px 10px 10px;
            font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: %(MUTED)s; }
QLabel:disabled { color: %(MUTED)s; }
QMessageBox { background: %(BG)s; }
""" % dict(globals(), chevron=_url("chevron"), check=_url("check"),
           branch_closed=_url("branch_closed"), branch_open=_url("branch_open")) + open3d_sheet()


def open3d_sheet():
    """Lo que cambia en el estilo Open3D: esquinas rectas, botones con borde y etiquetas en monoespaciada."""
    return """
QLineEdit, QLineEdit#Search, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTreeWidget, QMenu,
QComboBox QAbstractItemView, QToolTip, #InfoBar, QGroupBox, QTabWidget::pane { border-radius: 0; }
QMenu::item, QTreeView::item, QListWidget::item, QTreeWidget::item { border-radius: 0; }
QLineEdit:focus { border-color: %(TEXT)s; }

#Caption { font-family: "%(mono)s"; text-transform: uppercase; font-size: 7.5pt; letter-spacing: 2px; color: %(FAINT)s; }
#AppVersion { font-family: "%(mono)s"; color: %(ACCENT)s; letter-spacing: 1px; }
#FolderTitle { font-size: 15pt; font-weight: 700; }

/* pestañas: texto en monoespaciada con subrayado */
QTabBar#LibTabs::tab { border-radius: 0; padding: 7px 12px 5px 12px; margin: 0 2px; color: %(MUTED)s;
                       border-bottom: 2px solid transparent; font-family: "%(mono)s"; font-size: 8.5pt;
                       text-transform: uppercase;
                       letter-spacing: 1px; }
QTabBar#LibTabs::tab:hover { background: transparent; color: %(TEXT)s; }
QTabBar#LibTabs::tab:selected { background: transparent; color: %(TEXT)s; border-bottom-color: %(ACCENT)s; }
QTabWidget > QTabBar::tab { font-family: "%(mono)s"; font-size: 8.5pt; letter-spacing: 1px;
                            text-transform: uppercase; }

/* botones como los «ABRIR» del lanzador: borde oscuro, sin relleno */
QPushButton, QToolButton#Action { background: transparent; border: 1px solid %(BORDER_HI)s; border-radius: 0;
                                  font-family: "%(mono)s"; text-transform: uppercase; font-size: 8.5pt; font-weight: 700;
                                  letter-spacing: 0.5px; padding: 7px 10px; min-width: 0; }
QPushButton:hover, QToolButton#Action:hover { border-color: %(TEXT)s; background: %(SURFACE_HI)s; }
QPushButton:default, QPushButton#Primary, QToolButton#Primary {
    background: transparent; color: %(TEXT)s; border: 1px solid %(TEXT)s; border-radius: 0; font-weight: 700;
    font-family: "%(mono)s"; font-size: 8.5pt; letter-spacing: 1px; text-transform: uppercase; }
QPushButton:default:hover, QPushButton#Primary:hover, QToolButton#Primary:hover {
    background: %(TEXT)s; color: %(BG)s; border-color: %(TEXT)s; }
#Inspector QPushButton { padding: 7px 6px; }
/* botones con el color de la app (Catalogar, Crear ventana) */
QToolButton#Accent, QPushButton#Accent { background: %(ACCENT)s; color: %(ACCENT_TEXT)s; border: 1px solid %(ACCENT)s;
    border-radius: 0; font-family: "%(mono)s"; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; padding: 6px 14px; }
QToolButton#Accent:hover, QPushButton#Accent:hover { background: %(ACCENT_HI)s; border-color: %(ACCENT_HI)s; }
QToolButton { border-radius: 0; }
QToolButton#Chip { border-radius: 0; font-family: "%(mono)s"; text-transform: uppercase; font-size: 8pt; letter-spacing: 1px;
                   padding: 4px 10px; }
QToolButton#Chip:checked { background: %(TEXT)s; border-color: %(TEXT)s; color: %(BG)s; }

QTreeView#Folders::item:selected { border-left: 2px solid %(ACCENT)s; }
QCheckBox::indicator { border-radius: 0; }
QProgressBar, QProgressBar::chunk { border-radius: 0; }
QScrollBar::handle { border-radius: 0; }
QSlider::handle:horizontal { border-radius: 0; width: 8px; }
""" % dict(globals(), mono=mono_family())


def apply(app):
    app.setStyle("Fusion")
    p = QtGui.QPalette()
    p.setColor(QtGui.QPalette.Window, color(BG))
    p.setColor(QtGui.QPalette.WindowText, color(TEXT))
    p.setColor(QtGui.QPalette.Base, color(SURFACE))
    p.setColor(QtGui.QPalette.AlternateBase, color(SIDEBAR))
    p.setColor(QtGui.QPalette.ToolTipBase, color(SURFACE_HI))
    p.setColor(QtGui.QPalette.ToolTipText, color(TEXT))
    p.setColor(QtGui.QPalette.Text, color(TEXT))
    p.setColor(QtGui.QPalette.Button, color(SURFACE))
    p.setColor(QtGui.QPalette.ButtonText, color(TEXT))
    p.setColor(QtGui.QPalette.Highlight, color(ACCENT))
    p.setColor(QtGui.QPalette.HighlightedText, color(ACCENT_TEXT))
    p.setColor(QtGui.QPalette.Mid, color(FAINT))
    p.setColor(QtGui.QPalette.Link, color(ACCENT))
    p.setColor(QtGui.QPalette.PlaceholderText, color(FAINT))
    for role in (QtGui.QPalette.Text, QtGui.QPalette.WindowText, QtGui.QPalette.ButtonText):
        p.setColor(QtGui.QPalette.Disabled, role, color(FAINT))
    app.setPalette(p)
    f = QtGui.QFont(FONT_FAMILY)
    if not QtGui.QFontInfo(f).exactMatch():
        f = QtGui.QFont(FONT_FALLBACK)
    f.setPointSizeF(10)
    f.setHintingPreference(QtGui.QFont.PreferNoHinting)
    app.setFont(f)
    app.setStyleSheet(stylesheet())


def title_bar(widget):
    """Barra de título de Windows 10/11 a juego con el modo (oscura o clara)."""
    try:
        import ctypes
        hwnd = int(widget.winId())
        val = ctypes.c_int(0 if MODE == "light" else 1)
        for attr in (20, 19):      # DWMWA_USE_IMMERSIVE_DARK_MODE (nuevo / antiguo)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
        # Windows 11: color de la barra (SIDEBAR en BGR)
        c = QtGui.QColor(SIDEBAR)
        cap = ctypes.c_int((c.blue() << 16) | (c.green() << 8) | c.red())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), ctypes.sizeof(cap))
    except Exception:
        pass


dark_title_bar = title_bar


def shadow(widget, blur=24, alpha=90):
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, 4)
    eff.setColor(QtGui.QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)
    return eff
