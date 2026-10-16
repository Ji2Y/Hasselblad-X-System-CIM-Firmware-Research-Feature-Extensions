# X2D Code Tests

This public subset contains selected source and offline tests. A single module also contains optional, allowlisted read-only PDAF observations; those scripts are not part of the default offline runner.

- `temporary_af_speed_probe/pdaf-scan-type1-candidate/`: AF-S scan request candidate.
- `temporary_af_speed_probe/standalone_handoff/`: offline extraction and validation helpers.
- `temporary_af_speed_probe/original-menu-candidate/`: menu/page source, the public `X2dNativeMenuLoader.qml` integration component, the twelfth-entry SVG icon, and desktop checks.
- `x2d-afc-research/`: offline AF-C gate patcher and public status summary.
- [ui-response](ui-response/README.md)：本地轨迹解析器的合成时钟、CPU 与统计边界测试。
- `shutter-animation-preview/`: browser/QML animation, read-only timing analysis and offline tests.
- [黑白帧与所有权契约](monochrome-frame-contracts/README.md)：FXGab69 的 PR #9 离线源码子集，保留作者归属与来源许可；实机待验证。

- [PDAF 影子判定与 425 区域候选](pdaf-only-shadow/README.md)：离线计算、同帧快照和适配器契约；另有受限只读 AF-S 记录脚本，未接入原厂回调或镜头控制。
