# X2D II digital zoom (offline candidate)

## What this is

The body already saves a rectangle of the sensor when you pick 16:9, square, or XPan. That crop only changes the shape. It keeps the full width or the full height. Digital zoom is different: both sides get smaller, and the aspect can stay the same.

This folder calculates the zoom rectangle. It does not switch the camera.

## Applies to

- Body: X2D II 100C, kept separate from first-generation X2D.
- Sensor numbers: public 100 MP figure, 11656×8742, 43.8×32.9 mm, Bayer quad 2. Confirm against firmware 1.3.16.2 before any device test.
- Evidence: the rectangle maths is offline. The crop-mode reading in [research/CROP.md](research/CROP.md) is static analysis of official 1.3.16.2. Not hardware-validated.

## Map

| File | Role |
| --- | --- |
| `crop_geometry.py` | Which rectangle each zoom step uses. |
| `controller.py` | Bar on only while shooting. Bar off, or Review, means the full sensor. |
| `find_crop_strings.py` | Looks through a local extract for crop-related names. |
| `research/CROP.md` | Why the existing crop modes are not digital zoom. |
| `test_crop.py` | Offline checks for the rectangle. |
| `test_find_crop_strings.py` | Offline check for the scanner. Uses a temp file, not firmware. |

## Dependencies

Python 3.11+. No camera, no CIM, no vendor libraries.

## Side effects

Both checks are offline. `find_crop_strings.py` only reads a path you pass. Nothing here opens a device, writes firmware, or changes camera state.

## Checks

From this directory:

```sh
python3 test_crop.py
python3 -m unittest test_find_crop_strings.py
```

## Status

`setCrop_mode_current` only selects an aspect. Every mode keeps a full side, so it cannot be the zoom control. The call that shrinks both sides is not identified. See [research/CROP.md](research/CROP.md). Not tried on a camera.

## What not to add here

No installer, no factory-channel bootstrap, no copied vendor QML or firmware.
