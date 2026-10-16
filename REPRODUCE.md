# Reproduce the Offline Research / 离线研究复现

Read [DISCLAIMER.md](DISCLAIMER.md) first. The public tree supplies offline analysis, interface source and desktop checks. Camera configuration writers and deployment/recovery commands are excluded. The PDAF module has an opt-in, narrowly allowlisted AF-S observation workflow in [PDAF425-RECORDING.md](x2d/CodeTests/pdaf-only-shadow/PDAF425-RECORDING.md); other device observations remain evidence summaries.

## Run repository-contained checks

Use Python 3.9 or later from the repository root:

```sh
python3 -m pip install -r x2d/CodeTests/temporary_af_speed_probe/standalone_handoff/requirements.txt
python3 -B scripts/reproduce_offline.py
```

The runner checks publication boundaries, the menu Loader source/icon, AF-S candidates, object-recognition contracts, shutter timing and synthetic UI traces. It does not connect to a camera. Optional Qt/native desktop checks are documented in the [Doom](x2d/doom/README.md) and [Shimeji](x2d/shimeji-overlay/README.md) modules.

For tests using operator-supplied firmware extraction roots, provide all four read-only directories:

```sh
python3 -B scripts/reproduce_offline.py \
  --source-system-root /path/to/x2d2-system-root \
  --source-vendor-root /path/to/x2d2-vendor-root \
  --target-system-root /path/to/x2d-system-root \
  --target-vendor-root /path/to/x2d-vendor-root
```

The directories are read-only inputs and are never copied into this repository. They must come from firmware the operator is authorized to use. Vendor firmware, libraries, models and generated compilation units are not distributed.

## Research entry points

| Area | Entry | Reproduction scope |
| --- | --- | --- |
| Menu | [source and tests](x2d/CodeTests/temporary_af_speed_probe/original-menu-candidate/README.md) | Source QML, SVG and desktop checks |
| AF-S | [candidate](x2d/CodeTests/temporary_af_speed_probe/pdaf-scan-type1-candidate/README.md) | Exact-version offline hash gates and byte-diff checks |
| AF-C | [research](x2d/CodeTests/x2d-afc-research/README.md) | Offline model/layout and gate analysis |
| Recognition | [contracts and audit](x2d/object-recognition/README.md) | Firmware compatibility and synthetic frame contracts |
| Doom | [module](x2d/doom/README.md) | Engine/audio builds and desktop input checks |
| Shimeji | [module](x2d/shimeji-overlay/README.md) | Native desktop engine, transparent QML and synthetic traces |
| Shutter | [preview](x2d/CodeTests/shutter-animation-preview/README.md) | Browser/QML preview and timing analysis |
| PDAF / spectral AWB | [read-only tools](x2d/tools/firmware-analysis/focus-and-spectral/README.md) | Pinned operator-provided ELF/configuration inputs, static evidence only |
| PDAF 425 candidate | [source and contracts](x2d/CodeTests/pdaf-only-shadow/PDAF425.md) | Synthetic C/Python checks, pinned-input offline build/audit and separate read-only AF-S observation; no callback registration or autofocus control |
| Pixel shift | [offline library](x2d/pixel-shift/README.md) | Host C build, miniature output and synthetic sparse RAW fixtures; no capture |
| Model structure | [schema checks](x2d/tools/model-structure/README.md) | Operator-provided TFLite schema/index inspection; no decryption/inference |

## 中文说明

本公开树主要提供离线分析、界面源码和桌面检查，不包含相机配置写入或设备部署／恢复命令。只有 PDAF 模块单独提供受限的只读观察方法，具体前提、临时日志清理和脱敏步骤见该模块说明；这不构成部署入口。

在仓库根目录运行上面的离线套件。默认不提供固件输入时，依赖外部输入的用例会跳过；需要时显式指定四个只读固件目录。Qt／原生桌面检查按对应模块说明执行，不自动下载依赖。

离线候选、能够显示的菜单或接口契约通过，不代表相机性能、稳定性或跨机型兼容性已通过验收。

## 2026-10-12 新增源码复现

像素位移套件需要主机 `cc`，只生成临时合成稀疏文件，完整原片与四亿 DNG 不公开。模型结构的合成夹具检查需要 tflite 2.18.0 和 flatbuffers 25.12.19；缺少依赖会明确跳过，不算完成结构检查。对焦／光谱脚本须由操作者提供固定版本输入，命令见其 README。

本次发布不会运行相机部署、推理或真实图像采集。原始完整工具包、原厂输入、模型、照片及部分历史设备证据未提供，不能仅凭本库重建全部报告。独立 Startup Studio 以其版本化源码与许可为准，不包含在本库离线套件内。

## 2026-10-13 JSR 实拍对照记录

[简要对比与科研图](x2d/research/4.2.0/JSR-METAL-COMPARISON.md)只随库提供摘要和两张 PNG；详细数据留在本地。私有 RAW、已删除的完整 DNG、JSR 运行时及模型未提供，不能只下载本仓库重跑该实验。

## 2026-10-16 PDAF 实验源码归档

默认离线套件新增 12 项影子判定器、13 项 425 区域核心检查及 1 项适配器合成场景；需要主机 C11 编译器，适配器测试还使用 AddressSanitizer / UndefinedBehaviorSanitizer。缺少编译器会明确跳过对应检查，不能计作通过。版本锁定 ARM64 构建与二代依赖审计按[模块说明](x2d/CodeTests/pdaf-only-shadow/PDAF425.md)另行提供输入；输出必须留在输入树外的新本地位置。

PDAF 硬件观察是显式的可选步骤，不属于默认离线套件。本次只读脚本要求操作者自备固定版本输入和目标相机；它们不触发 AF，只有限时日志会写入并清理实验自有的临时文件。原始日志与固件不公开，脱敏输出和完整边界见[记录方法](x2d/CodeTests/pdaf-only-shadow/PDAF425-RECORDING.md)。
