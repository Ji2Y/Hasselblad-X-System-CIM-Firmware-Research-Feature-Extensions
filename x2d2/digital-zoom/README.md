# X2D II digital zoom (offline candidate)

## Purpose and limit

CFA-aligned crop windows and the shooting-screen rules from the zoom bench: stops at 1.0 / full-frame / 1.5 / 2.0, bar only while shooting, bar-off returns to the full frame.

This does **not** apply a window on an X2D II. There is no capture or preview call in the public 1.3.16.2 tree that accepts an arbitrary sensor rectangle. `SensorWindowSink` is the only integration point.

## Applies to

- Body: X2D II 100C, kept separate from first-generation X2D.
- Sensor numbers: public 100 MP figure, 11656×8742, 43.8×32.9 mm, Bayer quad 2. Confirm against firmware 1.3.16.2 before any device test.
- Evidence: offline. Not hardware-validated.

## Map

| File | Role |
| --- | --- |
| `crop_geometry.py` | Window list. Source of truth. |
| `controller.py` | Mode, bar, zoom, and the sink the camera code must fill in. |
| `test_crop.py` | Offline assertions. |

## Dependencies

Python 3.11+. No camera, no CIM, no vendor libraries.

## Side effects

`python3 test_crop.py` is offline. Nothing in this folder opens a device, writes firmware, or changes camera state.

## Checks

From this directory:

```sh
python3 test_crop.py
```

Asserts: every window is quad-aligned; a stop never reports less zoom than its label; 2.0× is reachable; Review and bar-off release the crop; a square aspect stays square.

## Status

Candidate. The missing piece on the camera is one function: given `{x, y, width, height}` all divisible by 2, set the live readout and the recorded frame to that window, and a matching release that restores the full sensor. Until that function exists, do not ship a menu entry — the bench already treats a hidden crop as a trap.

## What not to add here

No installer, no factory-channel bootstrap, no copied vendor QML or firmware. Those stay out of the public tree the same way the rest of `x2d2/` does.
