"""Cached, replaceable UI previews; scientific analysis has its own worker."""

from __future__ import annotations

import traceback
from collections import OrderedDict
from collections.abc import Callable, Hashable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from typing import TypeAlias

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

PreviewKey: TypeAlias = tuple[int, Hashable]
PreviewOperation: TypeAlias = Callable[[], object]
PreviewResult: TypeAlias = tuple[PreviewKey, object, str | None, str | None]


class CachedPreview(QObject):
    """Compute one preview at a time, delivering only the latest requested value."""

    value_ready = Signal(object)
    failed = Signal(str)
    diagnostic = Signal(str)
    _completed = Signal(object)

    def __init__(
        self, parent: QObject | None = None, *, delay: int = 120, capacity: int = 16
    ) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay)
        self._delay = delay
        self._timer.timeout.connect(self._dispatch)
        self._completed.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        self._capacity = capacity
        self._cache: OrderedDict[PreviewKey, object] = OrderedDict()
        self._generation = 0
        self._desired: tuple[PreviewKey, PreviewOperation] | None = None
        self._published: PreviewKey | None = None
        self._future: Future[object] | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False

    @property
    def pending(self) -> bool:
        return not self._closed and (self._future is not None or self._timer.isActive())

    def is_requested(self, key: Hashable) -> bool:
        return self._desired is not None and self._desired[0] == (self._generation, key)

    def request(self, key: Hashable, operation: PreviewOperation) -> None:
        if self._closed:
            return
        cache_key = self._generation, key
        if cache_key in self._cache:
            self._desired = cache_key, operation
            self._timer.stop()
            self._published = cache_key
            self._cache.move_to_end(cache_key)
            self.value_ready.emit(self._cache[cache_key])
        elif self._desired is None or self._desired[0] != cache_key:
            self._desired = cache_key, operation
            self._timer.start(self._delay)

    def cancel_pending(self) -> None:
        self._timer.stop()
        self._desired = None

    def clear(self) -> None:
        self.cancel_pending()
        self._generation += 1
        self._cache.clear()
        self._published = None

    def shutdown(self) -> None:
        self._closed = True
        self.cancel_pending()
        if self._executor is not None:
            # Closing a window must not wait for a pandas scan. The running
            # read-only operation may finish, but cannot update the closed UI.
            self._executor.shutdown(wait=False, cancel_futures=True)

    @Slot()
    def _dispatch(self) -> None:
        if self._closed or self._future is not None or self._desired is None:
            return
        key, operation = self._desired
        if key == self._published:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="paradigma-preview"
            )
        self._future = self._executor.submit(operation)

        def completed(future: Future[object]) -> None:
            details: str | None = None
            error: str | None
            try:
                value, error = future.result(), None
            except Exception as exc:  # noqa: BLE001 -- Deliver arbitrary preview failures to Qt.
                # Preview operations are arbitrary; retain the stack across threads.
                value, error = None, f"{type(exc).__name__}: {exc}"
                details = traceback.format_exc()
            if not self._closed:
                # The parent window may have been deleted before delivery.
                with suppress(RuntimeError):
                    self._completed.emit((key, value, error, details))

        self._future.add_done_callback(completed)

    @Slot(object)
    def _receive(self, payload: PreviewResult) -> None:
        self._future = None
        if self._closed:
            return
        key, value, error, details = payload
        if details:
            self.diagnostic.emit(details)
        if key[0] == self._generation and error is None:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)
        if self._desired is not None and self._desired[0] == key:
            self._published = key if error is None else None
            if error:
                self._desired = None
                self.failed.emit(error)
            self.value_ready.emit(value)
        elif self._desired is not None and not self._timer.isActive():
            self._timer.start(0)
