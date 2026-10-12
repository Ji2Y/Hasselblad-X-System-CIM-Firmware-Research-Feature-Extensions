# 像素位移处理来源

`native/vendor/six_row_kernel.h` 原样来自 [dash8097/Hasselblad-Feature-Extensions](https://github.com/dash8097/Hasselblad-Feature-Extensions/blob/a4c7f5c0483346c686b9938ed87a48f32c5724f6/x2d/CodeTests/pixel_shift_rgb/six_row_kernel.h)，固定提交 `a4c7f5c0483346c686b9938ed87a48f32c5724f6`，SHA-256 `88268bf29f50b0dac35de1e0c08098d3a52444a52310525ffba12aa5b4fcd506`。保留其 SPDX、作者声明及 [MIT 全文](native/vendor/Hasselblad-Feature-Extensions-LICENSE)。四张坐标与通道组织沿用同一来源在提交 `a75e55ddf55e36b97555e32a73250824a2f89f8a` 的公开参考关系。

`merge.c` 是本项目基于上述组织新增的元数据验证、逐行处理与输出；`render.c` 是本项目实验矩阵／白平衡渲染，未复制 Phocus 私有实现。原样保留自有本地研究源码，未包含设备 main、工作器、第三方编译载荷或部署实现。

渲染源码使用 libjpeg API；libjpeg-turbo 3.1.0 属独立 IJG／BSD／zlib 许可，使用者自行提供库和对应许可。没有复制其源码或二进制。JSR 只在研究报告中引用，不复制 JSR 引擎、Controller／RArm 权重或发行程序。
