"""Optional calendar/clock filters, preserving untouched source-clock precision."""

from contextlib import suppress

import numpy as np
from PySide6.QtCore import QDateTime, Qt, QTimeZone, Signal
from PySide6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QHBoxLayout,
    QStackedWidget,
    QWidget,
)

from .field_scrolling import PageDateTimeEdit, PageDoubleSpinBox
from .results_view import clock_origin, clock_times, time_bound
from .theme import light_palette


class TimeField(QWidget):
    returnPressed = Signal()
    valueEdited = Signal()

    def __init__(self, title, *, origin=False):
        super().__init__()
        self.origin, self._clock, self._text, self._changing = origin, None, "", False
        self._default_seconds = None
        self.use = QCheckBox()
        self.use.setAccessibleName(f"Use {title}")
        self.calendar = PageDateTimeEdit()
        self.calendar.setCalendarPopup(True)
        self.calendar.setDisplayFormat("dd MMM yyyy  HH:mm:ss.zzz")
        self.calendar.setAccessibleName(f"{title}: calendar and time")
        self.calendar.setPalette(light_palette())
        self.calendar.calendarWidget().setPalette(light_palette())
        self.calendar.calendarWidget().setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.calendarWidget().setMinimumSize(330, 260)
        self.calendar.setMinimumHeight(38)
        self.calendar.setTimeZone(QTimeZone.utc())
        if origin:
            self.calendar.setSpecialValueText("Not set")
            self.calendar.setDateTime(self.calendar.minimumDateTime())
        else:
            self.calendar.setDateTime(QDateTime.currentDateTimeUtc())
        self.seconds = PageDoubleSpinBox(self)
        self.seconds.setMinimumHeight(38)
        self.seconds.setRange(-1e12, 1e12)
        self.seconds.setDecimals(6)
        self.seconds.setSuffix(" s")
        self.seconds.setAccessibleName(f"{title}: elapsed seconds")
        self.editors = QStackedWidget()
        self.editors.addWidget(self.calendar)
        if origin:
            # Origin always uses the calendar. QStackedWidget reserves the
            # largest minimum width across all its pages, including hidden
            # ones; a native numeric hint can otherwise widen the whole form.
            self.seconds.hide()
        else:
            self.editors.addWidget(self.seconds)
        self.editors.setCurrentWidget(self.calendar if origin else self.seconds)
        self.editors.setEnabled(False)
        self.setMinimumHeight(38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.use)
        layout.addWidget(self.editors, 1)
        self.use.toggled.connect(self._enabled)
        self.calendar.dateTimeChanged.connect(self._edited)
        self.seconds.valueChanged.connect(self._edited)
        self.calendar.editingFinished.connect(self.returnPressed.emit)
        self.seconds.editingFinished.connect(self.returnPressed.emit)

    def text(self):
        return self._text

    def _enabled(self, checked):
        self.editors.setEnabled(checked)
        if not self._changing:
            if checked:
                if self.origin and not self._text:
                    self.setText(QDateTime.currentDateTimeUtc().toString(Qt.ISODateWithMs))
                    self.valueEdited.emit()
                elif self._default_seconds is not None:
                    self._text = str(self._default_seconds)
                else:
                    self._edited()
            else:
                self.clear()
                self.valueEdited.emit()

    def _edited(self, *_):
        if self._changing or not self.use.isChecked():
            return
        if self.editors.currentWidget() is self.seconds:
            self._text = str(self.seconds.value())
        else:
            format = (
                Qt.ISODateWithMs
                if self._clock and self._clock.get("timezone")
                else "yyyy-MM-ddTHH:mm:ss.zzz"
            )
            self._text = self.calendar.dateTime().toString(format)
        self.valueEdited.emit()

    def setText(self, text):
        # The exact ISO value remains unchanged until the user edits a field;
        # QDateTime's millisecond display must not round nanosecond source clocks.
        import pandas as pd

        self._changing = True
        try:
            self._text = str(text).strip()
            self.use.setChecked(bool(self._text))
            self.editors.setEnabled(bool(self._text))
            if not self._text:
                if self.origin:
                    # An unchecked origin must not display a previous file's date.
                    self.calendar.setDateTime(self.calendar.minimumDateTime())
                return
            try:
                seconds = float(self._text)
            except ValueError:
                stamp = pd.Timestamp(self._text)
            else:
                if not np.isfinite(seconds):
                    return
                self.seconds.setValue(seconds)
                if self._clock is None or self.origin:
                    return
                stamp = clock_times([seconds], self._clock)[0]
            if pd.isna(stamp):
                return
            if stamp.tz is None:
                stamp = stamp.tz_localize("UTC")
            zone = self._zone()
            self.calendar.setTimeZone(zone)
            self.calendar.setDateTime(
                QDateTime.fromMSecsSinceEpoch(int(stamp.value // 1_000_000), zone)
            )
        except (ValueError, TypeError, OverflowError):
            pass  # Validation remains atomic in the shared filter operation.
        finally:
            self._changing = False

    def _zone(self):
        if not self._clock or not self._clock.get("timezone"):
            return QTimeZone.utc()
        zone = QTimeZone(self._clock["timezone"].encode())
        return (
            zone
            if zone.isValid()
            else QTimeZone(int(clock_origin(self._clock).utcoffset().total_seconds()))
        )

    def set_clock(self, clock):
        old, text = self._clock, self._text
        if not self.origin and old is not None and clock is None and text:
            with suppress(ValueError, TypeError):
                text = str(time_bound(text, old))
        self._clock = clock
        self.editors.setCurrentWidget(
            self.calendar if self.origin or clock is not None else self.seconds
        )
        self.setText(text)
        if not text and self._default_seconds is not None:
            self.clear()

    def set_default(self, seconds):
        if self._text or not np.isfinite(seconds):
            return
        self._default_seconds = float(seconds)
        self.setText(str(seconds))
        self.clear()

    def clear(self):
        if self._default_seconds is not None:
            self.setText(str(self._default_seconds))
        self.setText("")
