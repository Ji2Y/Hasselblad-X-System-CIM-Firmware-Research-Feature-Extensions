# Third-Party Notices

This file is a release checklist, not a claim that every referenced dependency is redistributed.

## 2026-10-14 FXGab69 黑白离线源码收录

[黑白帧与所有权实验](x2d/CodeTests/monochrome-frame-contracts/README.md)收录 FXGab69 在 toolkit PR #9 中的 28 个源码／测试文件，固定来源为 `fedb1abbd2ea73b2510c464867029ee607e9a4aa` 和 `4d7254a5f85b9ab8a39c7395bc96da059f354c27`。两笔迁入提交保留来源 Author，整理者作为 Committer；逐文件哈希与测试路径调整见[来源清单](x2d/CodeTests/monochrome-frame-contracts/SOURCE_MANIFEST.json)。[完整来源许可](x2d/CodeTests/monochrome-frame-contracts/LICENSE)随目录保留，大库 MIT 不替换它；原作者实现不归为本项目独立创作。

## 2026-10-13 JSR 对照记录

[JSR 简要报告与两张科研图](x2d/research/4.2.0/JSR-METAL-COMPARISON.md)引用上游 PR #2／#3；未复制其实现、字节码或模型。本地单张基线及绘图使用 rawpy 0.27.1／LibRaw 0.22.1（早期基线）及 0.22.2（同位置复算）、NumPy 2.2.6、Pillow 12.3.0、Matplotlib 3.10.9，均未 vendoring，各依赖许可独立适用。

## 2026-10-12 新增公开范围

- [pixel-shift 处理模块](x2d/pixel-shift/README.md)：复用固定 MIT 六行内核，原作者署名、精确提交和完整许可见 [模块来源](x2d/pixel-shift/THIRD-PARTY.md)。自有处理库未复制 Phocus 私有代码。libjpeg-turbo、JSR 及其权重未 vendoring。
- tflite 2.18.0 与 flatbuffers 25.12.19：可选本地结构检查／合成夹具依赖，不复制其源码、二进制、模型或权重。安装包中的原许可证适用。
- [Startup Studio](https://github.com/radium-wang/hasselblad-startup-studio)：仅引用其独立项目。初版 v0.1.4 的 MIT 与后续 MIT + Commons Clause 必须按版本区分，本研究库 MIT 不替换其许可。
- [FXGab69 黑白候选](x2d/research/4.2.0/MONOCHROME-CANDIDATE-REVIEW.md)：明确作者与固定来源，本库仅提供本项目的审查结论，未复制完整候选实现。
- IMaH 上游工具仅作研究来源链接，未迁入密钥表、厂商模型、解密程序或设备接口。

The citation-only external research records are maintained in
[`x2d/references/EXTERNAL-RESEARCH.md`](x2d/references/EXTERNAL-RESEARCH.md).
They document provenance and acknowledgement; they are not vendored into this
repository.

## Public references used by the research

- `WeiCheng97/Hasselblad-X2d-series-5g-unlock` — public X2D protocol reference; upstream repository reports an MIT license. Before release, record the exact commit used and identify any files that contain copied or adapted code.
- [derrickyau9/Hasselblad_X1D_II_FirmwareDump](https://github.com/derrickyau9/Hasselblad_X1D_II_FirmwareDump/tree/f39ac51d6b92c19f9b34e35d5f32f985a1c1cbe5) — firmware-extraction research implemented in the author's X1D II work; acknowledged as the original research reference. Citation only: no upstream firmware dump or source is copied here. No repository license was identified in the 2026-10-12 check; this citation does not grant redistribution rights. Historical extractor-script snapshots in reproduction notes identify the actual past input and are separate from original research credit.
- `Konamill-bot/x2d-pdaf-sim` — related X2D 100C 4.2.0 PDAF simulation reference; upstream README reports an MIT license. No source or generated output is copied here.
- `Konamill-bot/x2d-cim-notes` — primary inspiration for the X2D AF-C investigation; documentation reports CC BY-SA 4.0 and diagnostic tools report MIT. No source or documentation is copied here.
- Qt Declarative 6.4.1 — compiled-QML format and API reference. Qt components may use different commercial, LGPL, GPL or third-party licenses; this repository does not redistribute Qt binaries.
- PyUSB, pyelftools, Capstone, Unicorn, Pillow, NumPy, SoundFile, dissect.extfs, brotli and pycryptodome may be optional local tools. They are not vendored here; users should review the license of the version they install.

## Release requirement

Before making the GitHub repository public, replace each general entry above with an exact version/commit, the files that use or adapt it, the nature of the modification and the required copyright/license text. Do not use the project MIT license to overwrite third-party notices.

## Shimeji 模块的固定依赖（2026-10-07）

[x2d/shimeji-overlay](x2d/shimeji-overlay/README.md) 的新增引擎适配、QML 与模块工具按 GPL-3.0-or-later 授权，附独立 LICENSE；此处没有复制第三方引擎、Qt 或角色素材。

- libshijima：pixelomer，提交 `361f452f3e89cdfaf04624db1c7641e3db410da9`，GPL-3.0-or-later。native/engine.cc 使用其 API；上游源码由使用者提供，构建脚本校验版本。
- pugixml：Arseny Kapoulkine，提交 `27b68329de32cf9c601ca8eb6c588fd639960c40`，MIT，libshijima 的固定子模块；分发构建结果须保留其原始 LICENSE.md。
- Duktape 2.7.0：Duktape authors，MIT，libshijima 内的解释器依赖；分发构建结果须保留 duktape.cc 内的 LICENSE.txt/AUTHORS.rst 及相关版权说明。
- Qt / PySide6 Essentials 6.4.1：电脑端验证依赖，未随仓库分发；使用安装包对应的 Qt/PySide 和第三方许可。
- Neuron：来自 qingchenyouforcc/NeurolingsCE-Qt 提交 `b76816fbe52c51d617a4b5e1aa16c0e026f9e02f` 的 mascot_pack/Neuron；来源 README 声明官方包 CC-BY-NC-SA-4.0。info.json 署名 Paccha（https://linktr.ee/paccha_），配置 promote、dalekcraft。只记录来源，不复制 XML/PNG 或预览。角色非商业素材许可与 GPL/MIT 源码授权分开，不能把角色素材宣称为本仓库 MIT 开源内容。

相应固定版本来源链接及构建步骤见模块 README。若自行分发引擎或素材，须另带所分发版本的完整第三方版权/许可及对应源码，不把本仓库的许可文件代替上游声明。

## Doom 模块的固定依赖（2026-10-07）

[x2d/doom](x2d/doom/README.md) 的平台适配、音频混音/桥、QML、构建/运行工具和测试按 GPL-2.0-or-later 授权，附完整 GPL v2 文本；根 MIT 不适用。没有复制上游引擎、游戏 WAD、Qt 或原厂二进制。

- [ozkl/doomgeneric](https://github.com/ozkl/doomgeneric/tree/dcb7a8dbc7a16ce3dda29382ac9aae9d77d21284)：提交 `dcb7a8dbc7a16ce3dda29382ac9aae9d77d21284`，GPL-2.0；核心源文件声明 GPL-2.0-or-later 并保留 Id Software、Simon Howard 等作者声明。新增 native 文件使用其平台/声音接口；构建器读取使用者的未修改上游工作树，不把其源码迁入仓库。自行分发引擎时保留所使用上游的逐文件版权、GPL 和对应源码。
- [Freedoom 0.13.0](https://github.com/freedoom/freedoom/releases/tag/v0.13.0)：Phase 1 `freedoom1.wad` 为本次输入，SHA-256 `7323bcc168c5a45ff10749b339960e98314740a734c30d4b9f3337001f9e703d`。官方 ZIP 内 COPYING.txt 声明 Copyright © 2001–2024 Contributors to the Freedoom project，三条款 BSD，CREDITS 列作者。未随本仓库提供；素材许可独立于引擎 GPL。
- Qt / PySide6 Essentials 6.4.1：界面 API 和电脑端验证依赖，未分发源码/二进制，使用对应 Qt/PySide 与第三方许可。
- Zig 0.13.0、Clang：使用者本机构建工具，未分发。
- pyelftools 0.32、Capstone 5.0.6、PyUSB 1.3.1：固定 Python 工具依赖，未 vendoring；原许可由其安装包提供。Unicorn 仅为未验收的可选分支模拟依赖。
- `trial_usb.py` 是本项目编写的本次试验传输器，协议来自第一代 4.2.0 静态研究及原有自有试验；外部 5G 项目仅作邻近协议引用，没有从中复制代码。未迁入其他功能、维护协议或通用 shell CLI。
- `build_loader.py` 从本项目自有被动 Loader 生成器抽出纯离线函数；Qt 编译格式用于互操作，原厂字节只从使用者输入本地生成，没有随源码提供。

本模块 GPL 不授予原厂固件、库、商业 WAD 或商标的再分发权；下载的依赖和自行分发的构建结果应分别保留相应许可、版权及对应源码。
