# External Research References

## English

This page records public repositories that informed the research. It is a
citation and acknowledgement index, not a vendored dependency list. The
repositories below are not copied into this project, and this project does
not claim ownership of their code, documentation, firmware, models, or data.

The links currently point to each upstream `main` branch. Before a public
release that relies on a specific upstream passage or implementation, record
the exact commit, consulted file, and applicable license text. The access date
for this review is 2026-09-26.

### Primary inspiration for the X2D AF-C investigation

**Konamill-bot.** *Hasselblad X2D CIM Firmware — Reverse Engineering Notes*.
GitHub. <https://github.com/Konamill-bot/x2d-cim-notes>

This repository was the direct research inspiration for asking whether the
X2D 100C's in-camera firmware contains an AF-C capability or a disabled AF-C
path. It motivated the present project's independent symbol, state-machine,
menu-gate, and restricted hardware checks. Its negative software-only results
and its hypotheses are a research lead, not proof of the results reported in
this repository. The present project did not copy or adapt its source code.

The upstream README states that its documentation is under CC BY-SA 4.0 and
its diagnostic tool source is under the MIT License. Any future quotation or
adaptation must preserve the applicable attribution and share-alike terms.

### Firmware-extraction research and special acknowledgement

**[derrickyau9](https://github.com/derrickyau9).** *Hasselblad X1D II FirmwareDump*.
GitHub: <https://github.com/derrickyau9/Hasselblad_X1D_II_FirmwareDump>
Reviewed revision: `f39ac51d6b92c19f9b34e35d5f32f985a1c1cbe5` (2026-10-12).

Firmware extraction was implemented in his X1D II research. We acknowledge
**derrickyau9** as the source of this firmware-extraction research reference.
Special thanks for sacrificing an X1D II in pursuit of that work, helping make
today's unpacking methods and the flourishing research community possible.

This is a research citation and acknowledgement. No upstream firmware dump or
source is copied into this project. X1D II device observations, images and
addresses are not treated as X2D/X2D II validation. The upstream repository did
not expose a repository license in this review; this reference is not a grant
to redistribute its materials. Fixed extractor-script links in historical
reproduction notes identify the tool actually used, separately from original
research credit.

### PDAF simulation reference

**Konamill-bot.** *x2d-pdaf-sim: An open PDAF autofocus decision-policy
simulation*. GitHub. <https://github.com/Konamill-bot/x2d-pdaf-sim>

This is a related simulation reference for the X2D 100C 4.2.0 PDAF decision
policy and is useful context for the AF-S speed model. A simulation result is
not a camera-side measurement and is not used here as proof of AF-C support.
The upstream README identifies the project as MIT-licensed. No source or
generated output is copied into this repository.

### Factory-diagnostic-channel reference

This is an adjacent reference for observations involving the camera's factory
diagnostic channel and local device communication. It is not evidence for the
AF-S, AF-C, face/eye, or object-recognition conclusions in this project. The
upstream repository identifies its code as MIT-licensed and contains its own
radio-regulatory disclaimer; local use remains subject to applicable law and
device authorization. No code or device data is copied here.

### Citation and relationship boundary

These references document research provenance and help readers reproduce the
reasoning path. They do not mean that the upstream authors endorse this
project, that the projects share code, or that the upstream claims have been
independently confirmed here. The current research results remain bounded by
the evidence levels and limitations in [`RESEARCH_RESULTS.md`](../../RESEARCH_RESULTS.md).

## 中文

本页记录对研究形成启发或提供方法背景的公开仓库。它是引用和致谢索引，
不是把外部仓库作为依赖 vendoring 进来。本项目没有复制下列仓库，也不主张
拥有其中的代码、文档、固件、模型或数据。

当前链接指向各上游仓库的 `main` 分支。正式公开前，如果研究结论依赖某个
上游段落或实现，应记录确切 commit、实际查阅文件和适用的许可证文本。本次
核对日期为 2026-09-26。

### X2D AF-C 调查的主要启发来源

**Konamill-bot。**《Hasselblad X2D CIM Firmware — Reverse Engineering Notes》。
GitHub：<https://github.com/Konamill-bot/x2d-cim-notes>

这个仓库是本项目提出“X2D 100C 机内固件是否存在 AF-C 能力或被关闭的 AF-C
路径”问题的直接启发来源。它促使本项目进一步做独立的符号、状态机、菜单 gate
和受限实机检查。它的纯软件负面结果及假设只是研究线索，不是本仓库结论的证据。
本项目没有复制或改写它的源码。

上游 README 说明其文档使用 CC BY-SA 4.0，诊断工具源码使用 MIT 许可证。未来如
引用或改编，必须保留相应署名及相同方式共享要求。

### 固件提取研究来源与特别致谢

**[derrickyau9](https://github.com/derrickyau9)。**《Hasselblad X1D II FirmwareDump》。
GitHub：<https://github.com/derrickyau9/Hasselblad_X1D_II_FirmwareDump>
本次核对版本：`f39ac51d6b92c19f9b34e35d5f32f985a1c1cbe5`（2026-10-12）。

固件提取是他在 X1D II 研究中实现的，本项目将这项研究的来源致谢归于 **derrickyau9**。

**特别感谢 derrickyau9：献祭一台 X1D II，换来了今天的解包方法与后续研究的繁荣。感谢他为这条研究道路付出的代价与作出的贡献。**

本条仅记录研究来源和致谢，没有复制上游固件 dump 或源码。X1D II 的地址、镜像及
设备观察不会作为 X2D/X2D II 验收复用。本次没有找到上游仓库级许可证，不将引用
当作再分发许可。历史复现文档的固定提取脚本链接只记录当时实际使用的技术输入，
与固件提取研究的原创致谢分开。

### PDAF 仿真参考

**Konamill-bot。**《x2d-pdaf-sim: An open PDAF autofocus decision-policy
simulation》。GitHub：<https://github.com/Konamill-bot/x2d-pdaf-sim>

这是关于 X2D 100C 4.2.0 PDAF 决策策略的相关仿真参考，可作为 AF-S 速度模型的
背景。仿真结果不是相机实测，也不被本项目当作 AF-C 已支持的证据。上游 README
标注项目使用 MIT 许可证。本项目没有复制其源码或生成结果。

### 原厂诊断通道参考

这是关于相机原厂诊断通道和本地设备通信观察的旁支参考，不是本项目 AF-S、AF-C、
人脸/眼部识别或对象识别结论的证据。上游仓库说明其代码使用 MIT 许可证，并有
自己的无线电法规免责声明；本地使用仍须遵守适用法律并取得设备授权。本项目不
复制其中的代码或设备数据。

### 引用与关系边界

这些参考资料用于记录研究来源，帮助读者理解研究路径。它们不表示上游作者为本
项目背书，不表示项目之间共享代码，也不表示上游结论已在本项目中独立确认。当前
研究结果仍受 [`RESEARCH_RESULTS.md`](../../RESEARCH_RESULTS.md) 中的证据等级和
限制约束。
