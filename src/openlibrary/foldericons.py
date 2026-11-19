"""Iconos y colores de las carpetas del árbol.

El icono se deduce del nombre de la carpeta (árboles, sofás, sillas, edificios...) con una
lista de palabras; la persona puede cambiarlo y ponerle un color desde el menú de la carpeta.
Lo elegido se guarda en los ajustes del usuario ("folder_marks").
"""
import os
import re
import unicodedata

from . import theme

# Paleta para marcar carpetas
COLORS = [
    ("Rojo", "#E5484D"), ("Naranja", "#F76B15"), ("Ámbar", "#F0A93B"), ("Verde", "#46A758"),
    ("Turquesa", "#12A594"), ("Azul", "#3E8BF0"), ("Violeta", "#8E6CEF"), ("Rosa", "#E667A5"),
    ("Gris", "#8B93A0"),
]

_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" '
         'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">%s</svg>')

# nombre -> (texto del menú, dibujo)
ICONS = {
    "folder": ("Carpeta", '<path fill="%(fill)s" d="M3 6.500A1.500 1.500 0 0 1 4.500 5h4.300l2 2.200h8.700A1.500 1.500 0 0 1 21 '
                          '8.700v9.800a1.500 1.500 0 0 1-1.500 1.500h-15A1.500 1.500 0 0 1 3 18.500z"/>'),
    "tree": ("Árbol", '<path d="M12 21v-7"/><path d="M9.500 21h5"/><path fill="%(fill)s" d="M12 3a4.500 4.500 0 0 1 4.300 '
                      '3.200A4 4 0 0 1 15.500 14h-7a4 4 0 0 1-.800-7.800A4.500 4.500 0 0 1 12 3z"/>'),
    "plant": ("Planta", '<path fill="%(fill)s" d="M8 15h8l-1 6H9z"/><path d="M12 15V9"/>'
                        '<path d="M12 10c0-3 2-5 5.500-5 0 3-2 5-5.500 5z"/><path d="M12 12.500c0-2.500-2-4.500-5.500-4.500 0 '
                        '3 2 4.500 5.500 4.500z"/>'),
    "sofa": ("Sofá", '<path d="M6 11V8a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v3"/><path fill="%(fill)s" d="M3 13a1.800 1.800 0 0 '
                     '1 3.600 0v1.500h10.800V13A1.800 1.800 0 0 1 21 13v5H3z"/><path d="M6 18v2M18 18v2"/>'),
    "chair": ("Silla", '<path d="M7 3v9M17 3v9M7 6.500h10"/><path fill="%(fill)s" d="M6 12h12v3H6z"/>'
                       '<path d="M7 15v6M17 15v6"/>'),
    "table": ("Mesa", '<path fill="%(fill)s" d="M3 7h18v2.500H3z"/><path d="M5.500 9.500V19M18.500 9.500V19M5.500 14h13"/>'),
    "bed": ("Cama", '<path d="M3 19v-9M21 19v-5a2 2 0 0 0-2-2H3"/><path fill="%(fill)s" d="M3 15.500h18V17H3z"/>'
                    '<path d="M6 12V9.500a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V12"/>'),
    "lamp": ("Lámpara", '<path fill="%(fill)s" d="M8.500 3h7l3 8h-13z"/><path d="M12 11v9M8.500 20h7"/>'),
    "building": ("Edificio", '<path fill="%(fill)s" d="M5 21V4h9v17"/><path d="M14 9h5v12M3 21h18"/>'
                             '<path d="M8 8h3M8 12h3M8 16h3"/>'),
    "door": ("Puerta / ventana", '<path fill="%(fill)s" d="M6.500 21V3.500h11V21"/><path d="M4 21h16M14.500 12.500v1"/>'),
    "car": ("Vehículo", '<path fill="%(fill)s" d="M4 16.500v-4l2-5h12l2 5v4z"/><path d="M4.500 12.500h15"/>'
                        '<circle cx="7.500" cy="17" r="1.600"/><circle cx="16.500" cy="17" r="1.600"/>'),
    "person": ("Personas", '<circle fill="%(fill)s" cx="12" cy="7" r="3.200"/><path d="M5.500 20.500v-1.500a6.500 6.500 0 0 1 '
                           '13 0v1.500"/>'),
    "bath": ("Baño", '<path fill="%(fill)s" d="M3 12h18v2a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5z"/>'
                     '<path d="M6 12V6a2 2 0 0 1 4 0M7 19l-1 2M17 19l1 2"/>'),
    "kitchen": ("Cocina", '<path d="M7 3v18M5 3v4a2 2 0 0 0 4 0V3"/><path d="M16.500 21V3c-2.500 2-2.500 7 0 9"/>'),
    "decor": ("Decoración", '<path d="M9.500 3h5"/><path fill="%(fill)s" d="M10.500 3c0 3-4.500 5-4.500 10a6 6 0 0 0 12 '
                            '0c0-5-4.500-7-4.500-10"/><path d="M6.500 11h11"/>'),
    "image": ("Texturas / mapas", '<rect fill="%(fill)s" x="3.500" y="4.500" width="17" height="15" rx="2"/>'
                                  '<circle cx="9" cy="10" r="1.500"/><path d="M4 17l5-4 4 3 3-2.500 4 3.500"/>'),
    "box": ("Caja", '<path fill="%(fill)s" d="M12 3l8 4.500v9L12 21l-8-4.500v-9z"/><path d="M4 7.500l8 4.500 8-4.500M12 12v9"/>'),
    "star": ("Estrella", '<path fill="%(fill)s" d="M12 3.500l2.600 5.300 5.900.900-4.250 4.100 1 5.800L12 16.900 6.750 19.600l1-5.800'
                         'L3.500 9.700l5.900-.900z"/>'),
}

# Palabras (sin acentos, en minúsculas) -> icono. Gana la primera que aparezca en el nombre.
KEYWORDS = [
    ("image", ("z-maps", "maps", "mapas", "textur", "hdri")),
    ("tree", ("arbol", "tree", "arbust", "bosque", "palm", "forest")),
    ("plant", ("plant", "veget", "flor", "flores", "flower", "jardin", "garden", "macet", "cesped", "grass")),
    ("building", ("edific", "building", "arquitect", "ciudad", "city", "casa", "house", "equipam", "comercial",
                  "hospital", "aeropuerto", "educacion", "deportiv", "exposicion")),
    ("door", ("puerta", "ventana", "door", "window")),
    ("person", ("person", "people", "human", "gente", "figur")),
    ("car", ("coche", "car", "vehic", "bus", "camion", "truck", "moto", "bici", "bicicleta", "ambulanc", "transport",
             "avion", "barco")),
    ("bath", ("bano", "bath", "sanitar", "aseo", "grifer")),
    ("kitchen", ("cocina", "kitchen", "electrodom", "vajilla")),
    ("bed", ("cama", "bed", "dormitor")),
    ("lamp", ("lamp", "lampara", "ilumin", "light", "luz", "luces", "farola", "colgante")),
    ("chair", ("silla", "chair", "taburete", "stool", "banco", "asiento")),
    ("table", ("mesa", "table", "escritorio", "desk", "aparador", "armario", "estanter")),
    ("sofa", ("sofa", "butaca", "sillon", "couch", "armchair", "mobiliario", "mueble", "furniture")),
    ("decor", ("decor", "accesor", "escultur", "jarron", "vase", "cuadro", "cortina", "alfombra", "textil")),
]


def _plain(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


_guessed = {}


def guess(folder_name):
    """Icono para una carpeta según su nombre ("folder" si no suena a nada)."""
    hit = _guessed.get(folder_name)
    if hit is None:
        hit = _guessed[folder_name] = _guess(folder_name)
    return hit


def _guess(folder_name):
    name = _plain(folder_name)
    tokens = re.findall(r"[a-z0-9]+", name)
    for icon_name, words in KEYWORDS:
        for w in words:
            if "-" in w:
                if w in name:
                    return icon_name
                continue
            for t in tokens:
                # palabra entera (o su plural); las largas valen también como comienzo ("arbol" -> "arboles")
                if t == w or t == w + "s" or (len(w) >= 5 and t.startswith(w)):
                    return icon_name
    return "folder"


_cache = {}


def make_icon(name, color=None):
    """QIcon del dibujo `name`; con color, trazo de ese color y relleno suave."""
    if name not in ICONS:
        name = "folder"
    key = (name, color, theme.MODE)
    ic = _cache.get(key)
    if ic is None:
        if color:
            stroke, fill = color, color + '" fill-opacity="0.220'
        else:
            stroke, fill = ("#6A717C" if theme.is_light() else "#9AA1AC"), "none"
        body = ICONS[name][1] % {"fill": fill}
        ic = theme.icon_from_svg(_HEAD % (stroke, body))
        _cache[key] = ic
    return ic


def swatch(color):
    return theme.icon_from_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                               '<circle cx="12" cy="12" r="7.500" fill="%s"/></svg>' % color)


def mark_key(folder):
    return os.path.normcase(os.path.normpath(folder))
