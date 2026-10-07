"""Cached, replaceable UI previews; scientific analysis has its own worker."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot


class CachedPreview(QObject):
    """Compute one preview at a time, delivering only the latest requested value."""
    value_ready = Signal(object)
    failed = Signal(str)
    _completed = Signal(object)

    def __init__(self, parent=None, *, delay=120, capacity=16):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay)
        self._delay = delay
        self._timer.timeout.connect(self._dispatch)
        self._completed.connect(self._receive, Qt.QueuedConnection)
        self._capacity = capacity
        self._cache = OrderedDict()
        self._generation = 0
        self._desired = self._published = self._future = self._executor = None
        self._closed = False

    @property
    def pending(self):
        return not self._closed and (self._future is not None or self._timer.isActive())

    def is_requested(self, key):
        return self._desired is not None and self._desired[0] == (self._generation, key)

    def request(self, key, operation):
        if self._closed:
            return
        key = self._generation, key
        if key in self._cache:
            self._desired = key, operation
            self._timer.stop()
            self._published = key
            self._cache.move_to_end(key)
            self.value_ready.emit(self._cache[key])
        elif self._desired is None or self._desired[0] != key:
            self._desired = key, operation
            self._timer.start(self._delay)

    def cancel_pending(self):
        self._timer.stop()
        self._desired = None

    def clear(self):
        self.cancel_pending()
        self._generation += 1
        self._cache.clear()
        self._published = None

    def shutdown(self):
        self._closed = True
        self.cancel_pending()
        if self._executor is not None:
            # Closing a window must not wait for a pandas scan. The running
            # read-only operation may finish, but cannot update the closed UI.
            self._executor.shutdown(wait=False, cancel_futures=True)

    @Slot()
    def _dispatch(self):
        if self._closed or self._future is not None or self._desired is None:
            return
        key, operation = self._desired
        if key == self._published:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paradigma-preview")
        self._future = self._executor.submit(operation)

        def completed(future):
            try:
                value, error = future.result(), None
            except Exception as exc:
                value, error = None, f"{type(exc).__name__}: {exc}"
            if not self._closed:
                try:
                    self._completed.emit((key, value, error))
                except RuntimeError:
                    pass  # The parent window was deleted before delivery.

        self._future.add_done_callback(completed)

    @Slot(object)
    def _receive(self, payload):
        self._future = None
        if self._closed:
            return
        key, value, error = payload
        if key[0] == self._generation:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)
        if self._desired is not None and self._desired[0] == key:
            self._published = key
            if error:
                self.failed.emit(error)
            self.value_ready.emit(value)
        elif self._desired is not None and not self._timer.isActive():
            self._timer.start(0)
