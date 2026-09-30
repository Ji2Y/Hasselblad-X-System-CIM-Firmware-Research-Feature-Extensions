"""Offline checks. Run from this directory: python3 test_crop.py"""

from crop_geometry import X2D_100C, ZOOM_MAX, achievable_windows, at_least_index, describe, native_aspect, stops
from controller import RecordingSink, ZoomSession


def main() -> None:
    s = X2D_100C
    windows = achievable_windows(s, native_aspect(s), s.cfa_quad, ZOOM_MAX)
    assert windows[0].width == s.width_px and windows[0].height == s.height_px
    assert all(describe(s, w)["cfa_aligned"] for w in windows)
    for label, zoom in stops(s):
        i = at_least_index(s, windows, zoom)
        got = describe(s, windows[i])["achieved_zoom"]
        assert got + 1e-9 >= zoom, (label, got, zoom)
    top = describe(s, windows[-1])
    assert top["achieved_zoom"] + 1e-9 >= 2.0
    assert abs(top["achieved_zoom"] - 2.0) < 0.01
    h = (s.width_px - windows[-1].width) / 2 / s.width_px
    v = (s.height_px - windows[-1].height) / 2 / s.height_px
    assert h > 0.2 and v > 0.2, (h, v)

    wide = achievable_windows(s, 16 / 9, s.cfa_quad, ZOOM_MAX)
    h = (s.width_px - wide[0].width) / 2 / s.width_px
    v = (s.height_px - wide[0].height) / 2 / s.height_px
    assert h < 0.01 and v > 0.1, (h, v)

    sink = RecordingSink()
    session = ZoomSession(sink=sink)
    session.request_zoom(2.0)
    assert sink.applied is not None
    assert sink.applied.width < s.width_px
    session.set_mode("review")
    assert sink.applied is None and sink.released >= 1
    session.set_mode("shooting")
    assert sink.applied is not None
    session.set_bar(False)
    assert session.readout()["achieved_zoom"] == 1.0
    assert sink.applied is None
    session.set_bar(True)
    session.request_zoom(1.5)
    session.set_aspect(1.0)
    sol = session.readout()
    assert abs(sol["window"].width / sol["window"].height - 1) < 1e-6
    assert sol["cfa_aligned"]
    print(f"ok windows={len(windows)} top={top['achieved_zoom']:.6f}x {top['megapixels']:.2f}MP")


if __name__ == "__main__":
    main()
