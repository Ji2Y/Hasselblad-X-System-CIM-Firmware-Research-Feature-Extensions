# External Inputs and Validation Boundary

This repository does not include official firmware, extracted system/vendor trees, vendor libraries, encrypted models, Qt binaries, device logs or generated native artifacts.

Offline tools require users to supply legally obtained inputs and must verify the exact hashes documented by each module. Optional dependencies include pyelftools, Capstone, PyUSB, Pillow, NumPy, SoundFile, dissect.extfs, brotli, pycryptodome, Qt/PySide and an ARM64-capable compiler. Install only the dependencies needed for the selected offline workflow.

Source presence does not imply device compatibility. Static analysis, offline validation, device verification and user feedback remain separate evidence levels.

## 2026-10-12 迁入范围

新收录对焦／白平衡四份只读检查脚本、脱敏主题报告、TFLite 结构检查和像素位移本地处理库。输入／输出都通过显式路径传递，固件与模型不随库提供；检查脚本的生成证据默认留在输入树外的新本地目录。

对焦／白平衡依赖 pyelftools 0.32 与 Capstone 5.0.6；模型结构依赖 tflite 2.18.0 与 flatbuffers 25.12.19。像素位移合成需要 POSIX C11 编译器，渲染另需 libjpeg API，开发版为 libjpeg-turbo 3.1.0。依赖未 vendoring。

新工具不包含相机部署后端。历史完整工具包检查、实拍及 JSR 处理的原始输入／日志没有全部公开，不能宣称只下载研究库就能重建这些结果。独立 Startup Studio 与工具包引用保留原许可，不按根 MIT 重新授权。
