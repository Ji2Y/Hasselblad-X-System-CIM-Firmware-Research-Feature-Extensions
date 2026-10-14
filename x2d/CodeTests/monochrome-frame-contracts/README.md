# FXGab69 黑白帧与所有权离线实验

收录日期：2026-10-14。所属第一代 X2D 100C、固件 4.2.0 研究，职责为黑白帧转换及编码／取景接口的电脑端契约检查。它是实验源码，实际黑白照片与相机端 ABI 均未验收。

## 来源与作者

实现与原始测试作者为 **[FXGab69](https://github.com/FXGab69)**，来源为 toolkit PR #9。大库中的两笔源码迁入提交保留原始 Author 名称、邮箱和日期，整理者记为 Committer；因筛选与路径调整，迁入提交的 SHA 与原提交不同。

| 原提交 | 对应内容 |
| --- | --- |
| `fedb1abbd2ea73b2510c464867029ee607e9a4aa` | 公开 0.4.12 基线上的源码提案 |
| `4d7254a5f85b9ab8a39c7395bc96da059f354c27` | JPEG 私有帧别名与所有权拒绝逻辑修订 |

[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)记录逐文件原始路径、来源 SHA-256、当前 SHA-256 和整理改动。16 个 C／头文件及 6 个 C 测试保持来源字节不变；6 个 Python 测试仅调整本地目录，其中 native 测试保留帧转换用例。作者实现不归为整理者独立创作。

## 文件地图

| 位置 | 职责 |
| --- | --- |
| native/cfv_mono.c、cfv_mono_jpeg.c | 私有 YUV8 帧转换与编码请求契约 |
| native/cfv_mono_vmem.c、cfv_mono_jpeg_bridge.c | 合成 VMem 回调、独立缓冲区、别名拒绝与编码完成边界 |
| native/cfv_mono_preview.c、cfv_mono_display.c | 取景私有帧、保留原始 LUT／叠加层及提交后的所有权 |
| native/cfv_mono_heif_bridge.c、cfv_mono_heif_format.c | HEIF 独立帧与两种条件式 10 位打包布局；未独立确认布局时拒绝转换 |
| tests/ | 6 个 C 合成夹具及对应 Python 编译／运行入口 |
| LICENSE | 来源项目的完整许可 |

`cfv_mono_*` 名称沿用来源接口以避免改写算法，不表示本库完成其他机型适配。所有厂商回调在这里由电脑端夹具替代，未接入原厂运行时；不会生成相机可用版本。

## 离线复现

依赖 Python 3.9+、本机 C11 编译器 `cc`／Clang 和编译器的 AddressSanitizer／UndefinedBehaviorSanitizer 支持。无需原厂固件、设备库、照片或 Python 第三方包。

从仓库根目录运行：

```sh
python3 -B -m unittest discover -s x2d/CodeTests/monochrome-frame-contracts/tests -p 'test_*.py' -v
```

编译和合成数据只写入电脑临时目录，运行结束清理；入口不访问相机。无设备状态变更，因此本收录内容无设备恢复操作。生成二进制和日志不随源码分发。

## 验证与限制

- **离线验证，2026-10-14：** macOS／Python 3.13 上 6 项测试全部通过、无跳过；覆盖源帧保持、缓冲区／句柄别名、异常编码完成、取景所有权和条件式 HEIF 打包。HEIF 格式测试启用地址与未定义行为检查。
- **来源完整稿的离线检查：** 固定 `4d7254a` 上 240 项执行、30 项因未提供的专有输入跳过；属于来源测试结果，不能与这里的 6 项相加。
- **实机验证：** 本次未连接设备；JPEG／HEIF 成片、RAW 彩色保持、取景、厂商 ABI、缓存同步及回调完成时机均待独立验收。合成夹具成功不证明真实缓冲区所有权或相机安全性。

原 PR #3 的问题和历史结论见[离线审查](../../research/4.2.0/MONOCHROME-CANDIDATE-REVIEW.md)。此次只收录 PR #9 的上述离线子集；下一步应先补齐真实帧布局、所有权与编码完成证据，不能直接将本目录视为已实现的相机功能。

## 许可

本目录来源代码与测试继续按 [X2D/907 Noncommercial Distribution License 1.0](LICENSE) 分发，保留其完整原文与版权声明；大库根 MIT 不替换此目录的来源许可。整理改动已在清单和提交说明标注，不表示原作者对整理版本的背书。
