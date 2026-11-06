"""One cancellation gate shared by terminal, UI and the executor."""

from __future__ import annotations

import signal
import threading
import time
from contextlib import contextmanager


class Control:
    def __init__(self, *, park=True):
        self.lock = threading.RLock()
        self.generation = 0
        self.paused = False
        self.stopping = False
        self.parking = False
        self.parking_interrupted = False
        self.park = park
        self.reason = ""
        self.interventions = 0
        self.pause_since = 0.0
        self._previous = None

    def pause(self, reason="Operator pause"):
        with self.lock:
            if self.stopping:
                return
            self.generation += 1
            self.paused = True
            self.pause_since = time.monotonic()
            self.reason = reason
            self.interventions += 1

    def resume(self):
        with self.lock:
            if self.stopping:
                return
            self.generation += 1
            self.paused = False
            self.reason = "Resume requested: fresh observation and replan required"

    def replan(self, reason):
        """Invalidate action ownership without counting an autonomous recovery as intervention."""
        with self.lock:
            if not self.stopping:
                self.generation += 1
                self.reason = reason

    def stop(self, *, park=None, reason="Operator stop"):
        with self.lock:
            self.generation += 1
            self.stopping = True
            self.paused = False
            self.reason = reason
            if park is not None:
                self.park = park

    def interrupt(self, *_):
        if self.parking:
            # Karma power_down catches this and still closes the whole session.
            if not self.parking_interrupted:
                self.parking_interrupted = True
                raise KeyboardInterrupt
            return  # Further interrupts must not interrupt final de-energization.
        self.stop(park=False if self.stopping else None, reason="Ctrl+C")

    @contextmanager
    def signals(self):
        old_int = signal.signal(signal.SIGINT, self.interrupt)
        old_term = signal.signal(signal.SIGTERM, lambda *_: self.stop(park=False, reason="SIGTERM"))
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)

    def permits(self, generation):
        return not self.stopping and not self.paused and generation == self.generation
