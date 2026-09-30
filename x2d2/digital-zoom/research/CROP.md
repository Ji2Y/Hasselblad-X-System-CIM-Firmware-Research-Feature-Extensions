# X2D II 1.3.16.2 crop call

Static reading of the official 1.3.16.2 container only. The container header says platform `10.00.09.77`, built 2026-07-30. No camera was connected. The firmware file is not in this repo.

## Aspect crop is not digital zoom

`HblmTypes::E_CropMode` changes the shape of the picture. It always keeps the maximum width or the maximum height. It does not zoom.

The stored choice is `CameraSettings::setCrop_mode_current(HblmTypes::E_CropMode, bool)`. The same name exists on `CameraObjectImpl`. `MetadataControl::setCropMode` writes that mode into the file. `Cmd_SetCropMode` and `Worker::CropModeEvent` are the service-side names.

`Common::kCropBorderFRatio*` is a pair of doubles: horizontal inset and vertical inset, as a fraction of the full frame. One of the two is zero, or nearly zero, for every mode below. The other side is what gets trimmed so the aspect changes.

| Mode | Horizontal inset | Vertical inset | Side kept full |
| --- | ---: | ---: | --- |
| 3:2 | 0 | 0.0555 | width |
| 16:9 | 0 | 0.1250 | width |
| 2:1 | 0 | 0.1667 | width |
| 65:24 | 0 | 0.2538 | width |
| 1:1 | 0.1318 | 0.0090 | height |

16:9 keeps every column and cuts an eighth off the top and the bottom. Square keeps the height and cuts the sides. 65:24 is the XPan shape, still at full width. A 2× zoom would cut a quarter off every edge and keep the centre half of both width and height. No row in this table does that.

Modes present: `E_CropMode_None`, `Ratio1to1`, `Ratio7to6`, `Ratio5to4`, `Ratio11to8p5`, `Ratio297to210`, `Ratio3to2`, `Ratio3to2Crop`, `Ratio16to9`, `Ratio2to1`, `Ratio65to24`, plus `All` and `Max`.

`QSizeF Common::cropFactors(HblmTypes::E_CropMode)` is the scale for one of those shapes. `Common::CropData` is the record stored per mode.

## What the zoom control on the camera is

`HblmTypes::E_ZoomLevel` is only `Full`, `Half`, and `Max`. `ZoomFlick`, `ZoomOverlay`, and `ZoomIndicator` are that magnifier. They do not change what is recorded.

## What is still missing

`ImageMemory::toCroppedCopy(const QRect &)` can cut an arbitrary rectangle out of a buffer that is already in memory. That is not a sensor readout window, and it was not tested here.

Digital zoom needs a path that shrinks both sides and can keep the same aspect. `setCrop_mode_current` is the wrong call: every mode it accepts keeps a full side. This note does not name that other path. Not a device test.
