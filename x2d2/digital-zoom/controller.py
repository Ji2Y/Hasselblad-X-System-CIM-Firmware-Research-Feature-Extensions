"""Shooting-screen rules around the window list.

The camera side implements SensorWindowSink. This module never talks to a
device. Turning the bar off, or leaving shooting, releases the crop so a
hidden crop cannot be shot by accident.
"""

from __future__ import annotations

from dataclasses import dataclass

from crop_geometry import (
    ZOOM_MAX,
    Sensor,
    Window,
    X2D_100C,
    achievable_windows,
    at_least_index,
    describe,
    native_aspect,
    sensor_diag_px,
)


class SensorWindowSink:
    """Replace these two methods with the real capture/preview call once known."""

    def apply(self, window: Window) -> None:
        raise NotImplementedError

    def release(self) -> None:
        raise NotImplementedError


@dataclass
class RecordingSink(SensorWindowSink):
    applied: Window | None = None
    released: int = 0

    def apply(self, window: Window) -> None:
        self.applied = window

    def release(self) -> None:
        self.released += 1
        self.applied = None


class ZoomSession:
    def __init__(self, sensor: Sensor = X2D_100C, sink: SensorWindowSink | None = None):
        self.sensor = sensor
        self.sink = sink or RecordingSink()
        self.aspect: float | None = None
        self.mode = "shooting"
        self.bar_on = True
        self.requested = 1.0
        self._rebuild()
        self._push()

    def _rebuild(self) -> None:
        aspect = native_aspect(self.sensor) if self.aspect is None else self.aspect
        self.windows = achievable_windows(self.sensor, aspect, self.sensor.cfa_quad, ZOOM_MAX)
        i = at_least_index(self.sensor, self.windows, self.requested)
        self.index = max(0, i)

    @property
    def live(self) -> bool:
        return self.mode == "shooting" and self.bar_on and self.index > 0

    def _current(self) -> Window:
        return self.windows[self.index]

    def _push(self) -> None:
        if self.live:
            self.sink.apply(self._current())
        else:
            self.sink.release()

    def set_aspect(self, aspect: float | None) -> None:
        self.aspect = aspect
        self._rebuild()
        self._push()

    def set_mode(self, mode: str) -> None:
        if mode not in ("shooting", "review"):
            raise ValueError(mode)
        self.mode = mode
        self._push()

    def set_bar(self, on: bool) -> None:
        self.bar_on = on
        if not on:
            self.index = 0
            self.requested = 1.0
        self._push()

    def request_zoom(self, zoom: float) -> None:
        if not (self.mode == "shooting" and self.bar_on):
            return
        self.requested = min(max(zoom, 1.0), ZOOM_MAX)
        i = at_least_index(self.sensor, self.windows, self.requested)
        if i >= 0:
            self.index = i
        self._push()

    def step(self, steps: int) -> None:
        if not (self.mode == "shooting" and self.bar_on):
            return
        self.index = min(max(self.index + steps, 0), len(self.windows) - 1)
        w = self._current()
        self.requested = sensor_diag_px(self.sensor) / (w.width**2 + w.height**2) ** 0.5
        self._push()

    def readout(self) -> dict:
        return describe(self.sensor, self._current())
