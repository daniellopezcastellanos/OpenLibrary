"""Lee en segundo plano (3dsmaxbatch) las caras, vértices, desplazamiento y animación de varios .max.

Algunos .max antiguos dejan a Max colgado al abrirlos sin interfaz: si un archivo no avanza en STALL
segundos se da por fallido, se cierra ese Max y se sigue con el siguiente.
"""
import os
import time

from . import batchpreview, config, modelstats
from .qt import QtCore

STALL = 150          # segundos sin avanzar con un archivo
STARTUP = 120        # lo que tarda en arrancar 3dsmaxbatch, aparte


class StatsRunner(QtCore.QObject):
    progress = QtCore.Signal(int, int)        # hechos, total
    updated = QtCore.Signal(str)              # archivo con datos nuevos
    finished = QtCore.Signal(int, int)        # leídos, fallidos

    def __init__(self, cache, parent=None):
        super(StatsRunner, self).__init__(parent)
        self.cache = cache
        self.proc = None
        self.queue = []            # pendientes
        self.chunk = []            # los del Max que está corriendo
        self.seen = 0              # líneas del registro ya leídas de este chunk
        self.total = 0
        self.ok = 0
        self.fail = 0
        self.log = None
        self.t_last = 0.0
        self.cancelled = False
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    def running(self):
        return self.proc is not None

    def start(self, files):
        files = [f for f in dict.fromkeys(files) if f and os.path.isfile(f)]
        if not files:
            return False
        if self.running():
            new = [f for f in files if f not in self.queue and f not in self.chunk]
            self.queue += new
            self.total += len(new)
            return True
        if not batchpreview.find_maxbatch():
            raise RuntimeError("No encuentro 3dsmaxbatch.exe (viene con 3ds Max).")
        self.queue = files
        self.total, self.ok, self.fail, self.cancelled = len(files), 0, 0, False
        self._launch()
        return True

    def cancel(self):
        self.cancelled = True
        self.queue = []
        if self.proc is not None:
            batchpreview.kill_tree(self.proc)

    # --- interno ---------------------------------------------------------
    def _launch(self):
        if not self.queue or self.cancelled:
            self._end()
            return
        self.chunk, self.queue = self.queue, []
        self.seen = 0
        script, self.log = modelstats.prepare(os.path.join(config.app_data_dir(), "batch"), self.chunk)
        proc = QtCore.QProcess(self)
        proc.setProgram(batchpreview.find_maxbatch())
        proc.setArguments([script])
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyRead.connect(proc.readAll)
        proc.finished.connect(lambda *_a, p=proc: self._on_finished(p))
        proc.errorOccurred.connect(lambda e, p=proc: self._on_finished(p) if e == QtCore.QProcess.FailedToStart
                                   else None)
        self.proc = proc
        self.t_last = time.time() + STARTUP
        self.timer.start()
        proc.start()

    def _read(self):
        """Lo nuevo del registro: guarda los datos y cuenta hechos y fallidos."""
        lines = []
        try:
            with open(self.log, "r", encoding="utf-8-sig", errors="replace") as fh:
                lines = [l.lstrip("﻿").rstrip("\r\n") for l in fh if l.strip()]
        except OSError:
            return
        for line in lines[self.seen:]:
            parts = line.split("\t")
            try:
                i = int(parts[1]) - 1
            except (IndexError, ValueError):
                continue
            f = self.chunk[i] if 0 <= i < len(self.chunk) else None
            st = modelstats.parse_stats(parts[2:]) if parts[0] == "ok" else None
            if f and st is not None:
                self.cache.put(f, st)
                self.ok += 1
                self.updated.emit(f)
            elif f:
                self.cache.put(f, {"error": True})
                self.fail += 1
                self.updated.emit(f)
        if len(lines) > self.seen:
            self.seen = len(lines)
            self.t_last = time.time()
            self.progress.emit(self.ok + self.fail, self.total)

    def _tick(self):
        if self.proc is None:
            return
        self._read()
        if time.time() - self.t_last > STALL:
            batchpreview.kill_tree(self.proc)      # _on_finished salta el atascado y sigue

    def _on_finished(self, proc):
        if proc is not self.proc:
            return
        self._read()
        self.proc = None
        self.timer.stop()
        # si se ha cerrado antes de acabar (atascado o roto): ese archivo falla y se sigue con el resto
        if self.seen < len(self.chunk) and not self.cancelled:
            stuck = self.chunk[self.seen]
            self.cache.put(stuck, {"error": True})
            self.fail += 1
            self.updated.emit(stuck)
            self.queue = self.chunk[self.seen + 1:] + self.queue
            self.progress.emit(self.ok + self.fail, self.total)
        self.chunk = []
        self._launch()

    def _end(self):
        self.timer.stop()
        self.cache.save()
        self.finished.emit(self.ok, self.fail)
