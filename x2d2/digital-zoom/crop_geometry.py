"""CFA-aligned digital-zoom windows for the 100 MP X sensor.

Source of truth for the bench. A labelled stop never reports less zoom than
its name: the list includes the first window that reaches the cap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

REF_35_W_MM = 36.0
REF_35_H_MM = 24.0
ZOOM_MAX = 2.0


@dataclass(frozen=True)
class Sensor:
    width_px: int = 11656
    height_px: int = 8742
    width_mm: float = 43.8
    height_mm: float = 32.9
    cfa_quad: int = 2


# Public 100C figure. Confirm against X2D II 1.3.16.2 before a device test.
X2D_100C = Sensor()


@dataclass(frozen=True)
class Window:
    x: int
    y: int
    width: int
    height: int


def _hyp(a: float, b: float) -> float:
    return math.sqrt(a * a + b * b)


def _align_down(v: float, q: int) -> int:
    return int(math.floor(v / q) * q)


def sensor_diag_px(s: Sensor) -> float:
    return _hyp(s.width_px, s.height_px)


def sensor_diag_mm(s: Sensor) -> float:
    return _hyp(s.width_mm, s.height_mm)


def native_aspect(s: Sensor) -> float:
    return s.width_px / s.height_px


def pitch_um(s: Sensor) -> float:
    return 1000.0 * s.width_mm / s.width_px


def full_frame_zoom(s: Sensor) -> float:
    return sensor_diag_mm(s) / _hyp(REF_35_W_MM, REF_35_H_MM)


def _win_diag(w: Window) -> float:
    return _hyp(w.width, w.height)


def centre_window(s: Sensor, width: int, height: int, q: int) -> Window | None:
    x = _align_down((s.width_px - width) / 2, q)
    y = _align_down((s.height_px - height) / 2, q)
    if x < 0 or y < 0 or x + width > s.width_px or y + height > s.height_px:
        return None
    return Window(x, y, width, height)


def achievable_windows(s: Sensor, aspect: float, q: int, zoom_max: float) -> list[Window]:
    target = aspect if aspect > 0 else native_aspect(s)
    step = math.floor(q) if q >= 1 else s.cfa_quad
    diag = sensor_diag_px(s)
    height = _align_down(min(s.height_px, s.width_px / target), step)
    out: list[Window] = []
    seen: set[str] = set()
    while height >= step:
        width = _align_down(height * target, step)
        if width < step:
            break
        if width <= s.width_px:
            w = centre_window(s, width, height, step)
            if w is not None:
                key = f"{width}x{height}"
                if key not in seen:
                    seen.add(key)
                    out.append(w)
                if diag / _win_diag(w) >= zoom_max - 1e-9:
                    break
        height -= step
    return out


def describe(s: Sensor, w: Window) -> dict:
    q = s.cfa_quad
    crop_mm = _win_diag(w) * pitch_um(s) / 1000.0
    return {
        "window": w,
        "achieved_zoom": sensor_diag_px(s) / _win_diag(w),
        "megapixels": w.width * w.height / 1e6,
        "crop_diagonal_mm": crop_mm,
        "equivalent_factor_35mm": _hyp(REF_35_W_MM, REF_35_H_MM) / crop_mm,
        "cfa_aligned": (
            w.x % q == 0 and w.y % q == 0 and w.width % q == 0 and w.height % q == 0
        ),
    }


def at_least_index(s: Sensor, windows: list[Window], zoom: float) -> int:
    if not windows:
        return -1
    diag = sensor_diag_px(s)
    for i, w in enumerate(windows):
        if diag / _win_diag(w) >= zoom - 1e-9:
            return i
    return len(windows) - 1


def stops(s: Sensor) -> list[tuple[str, float]]:
    return [
        ("1.0", 1.0),
        ("FF", full_frame_zoom(s)),
        ("1.5", 1.5),
        ("2.0", ZOOM_MAX),
    ]
