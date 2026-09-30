# X2D II 1.3.16.2 crop call

Static reading of the official 1.3.16.2 container only. The container header says platform `10.00.09.77`, built 2026-07-30. No camera was connected. The firmware file is not in this repo.

## What actually crops a picture

The body does not take an arbitrary sensor window. It takes one value from `HblmTypes::E_CropMode`.

The call that stores the current choice is `CameraSettings::setCrop_mode_current(HblmTypes::E_CropMode, bool)`. The same name exists on `CameraObjectImpl`. `MetadataControl::setCropMode` writes it into the file metadata. `Cmd_SetCropMode` and `Worker::CropModeEvent` are the service-side names.

`ImageMemory::toCroppedCopy(const QRect &)` can cut a rectangle out of an image already in memory. That is a copy of a buffer, not evidence that the sensor was read out smaller.

## The modes that exist

`E_CropMode_None`, `Ratio1to1`, `Ratio7to6`, `Ratio5to4`, `Ratio11to8p5`, `Ratio297to210`, `Ratio3to2`, `Ratio3to2Crop`, `Ratio16to9`, `Ratio2to1`, `Ratio65to24`, plus `All` and `Max`.

`Common::kCropBorderFRatio*` is a pair of doubles, horizontal inset and vertical inset, as a fraction of the frame. Checked against the public 11656×8742 sensor:

| Mode | Horizontal inset | Vertical inset |
| --- | ---: | ---: |
| 3:2 | 0 | 0.0555 |
| 16:9 | 0 | 0.1250 |
| 2:1 | 0 | 0.1667 |
| 65:24 | 0 | 0.2538 |
| 1:1 | 0.1318 | 0.0090 |

A 16:9 frame keeps the full width and trims an eighth off the top and the bottom. 65:24 is the XPan cut. There is no 2× entry.

`QSizeF Common::cropFactors(HblmTypes::E_CropMode)` is the scale that goes with a mode. `Common::CropData` is the record stored per mode.

## What the zoom control on the camera is

`HblmTypes::E_ZoomLevel` is only `Full`, `Half`, and `Max`. The screen pieces `ZoomFlick`, `ZoomOverlay`, and `ZoomIndicator` belong to that magnifier. They do not change the recorded crop.

## What this means for digital zoom

A 2× crop, in the same units as the table above, would be an inset of 0.25 on both axes: the centre half of the width and the centre half of the height. No `E_CropMode` value has that inset. Choosing 16:9 or XPan cannot produce it.

So the socket in `controller.py` is this call, not a new sensor command:

- apply: `setCrop_mode_current` with a mode whose border matches the zoom window
- release: `setCrop_mode_current` with `E_CropMode_None`

That mode does not exist yet. Adding one, and checking that the saved file and the live view both follow it, is still undone. This note is not a device test.
