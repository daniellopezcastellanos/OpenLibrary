"""Genera openlibrary.ico (varios tamaños) a partir del SVG de la app.

Lo usa build.py para el .exe y los accesos directos de Windows.
"""
import struct

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def svg_to_ico(svg_path, ico_path, sizes=SIZES):
    from PySide6 import QtCore, QtGui, QtSvg

    renderer = QtSvg.QSvgRenderer(svg_path)
    if not renderer.isValid():
        raise RuntimeError("SVG no válido: %s" % svg_path)
    pngs = []
    for s in sizes:
        img = QtGui.QImage(s, s, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        renderer.render(p, QtCore.QRectF(0, 0, s, s))
        p.end()
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        img.save(buf, "PNG")
        pngs.append((s, bytes(buf.data())))
    # ICO con imágenes PNG dentro (Windows Vista en adelante)
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, data = b"", b""
    for s, png in pngs:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        data += png
    with open(ico_path, "wb") as fh:
        fh.write(head + entries + data)
    return ico_path
