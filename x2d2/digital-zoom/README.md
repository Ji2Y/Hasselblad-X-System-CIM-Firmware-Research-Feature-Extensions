# X2D II digital zoom (offline candidate)

## What this is

The body already saves a rectangle of the sensor when you pick 16:9, square, or XPan. Digital zoom is that same rectangle, drawn smaller and kept centred. It is not a second sensor mode.

This folder calculates the rectangle. It does not switch the camera.

## Applies to

- Body: X2D II 100C, kept separate from first-generation X2D.
- Sensor numbers: public 100 MP figure, 11656×8742, 43.8×32.9 mm, Bayer quad 2. Confirm against firmware 1.3.16.2 before any device test.
- Evidence: offline. Not hardware-validated.

## Map

| File | Role |
| --- | --- |
| `crop_geometry.py` | Which rectangle each zoom step uses. |
| `controller.py` | Bar on only while shooting. Bar off, or Review, means the full sensor. |
| `find_crop_strings.py` | Looks through a local extract for the existing crop call. |
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

On your own machine, against an extract that stays outside this repo:

```sh
python3 find_crop_strings.py /path/to/local/extract
```

A useful hit names something like a crop rectangle or aspect ratio. That name is what `SensorWindowSink.apply` should call, with the window from `crop_geometry.py`. `release` calls the same thing with the full sensor.

## Status

Candidate. The rectangle maths is checked. The name of the existing crop call on 1.3.16.2 is not in this repo, so the camera still shoots full frame.

## What not to add here

No installer, no factory-channel bootstrap, no copied vendor QML or firmware.
