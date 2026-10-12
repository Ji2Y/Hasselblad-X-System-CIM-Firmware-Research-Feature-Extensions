# TFLite 模型结构的只读检查

适用于标准 TFLite v3 本地文件，与机型运行兼容性无关。`validate_models.py` 从本项目 2026-10-09 结构审查中抽出，删除本地依赖路径、解密结果依赖、文档写入与原厂模型压缩导出。

依赖 Python 3.9+、tflite 2.18.0 与 flatbuffers 25.12.19，操作者自行安装；不 vendoring。不会解密、读取密钥、加载推理引擎、联网或访问相机。

从仓库根目录运行：

```sh
python3 x2d/tools/model-structure/validate_models.py \
  --input /path/to/authorized-models --output /tmp/model-structure-summary.json
```

只读扫描 `.tflite`，核对标识／schema 版本、模型子图、张量引用、buffer 和算子索引。输出只含相对文件名、摘要与结构计数，不包含权重、输入目录绝对路径、张量名称或模型描述。输出必须不存在并在输入树外。无模型、损坏结构或不合法索引均拒绝；结构解析不证明运行时兼容、安全或正确推理。

本工具用于本地检查，不自动导出任何原厂材料。历史解密／签名／合成输入实机推理及证据限制见 [模型研究报告](../../research/4.2.0/MODEL-DECRYPTION-AND-CPU-RESULTS.md)。
