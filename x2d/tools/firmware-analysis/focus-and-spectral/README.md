# 对焦与光谱链路离线检查

对象：X2D 100C 4.2.0；跨版本工具另读 X2D II 1.3.16.2。四份脚本只读本地 ELF／配置、验证固定哈希并生成离线证据，不执行固件、不联网、不连接设备。原厂输入和反汇编输出不随本仓库提供。

| 文件 | 职责 |
| --- | --- |
| inspect_pdaf.py | 两代 PDAF 调用、固定结果接口容量 |
| inspect_sampling_geometry.py | 编译采样地址及配置几何，避免将其当作物理相位像素数量 |
| compare_focus_strategies.py | 两代控制调用、镜头位置对齐及融合依赖 |
| inspect_firmware.py | 一代 AS7341 驱动结构、自动白平衡调用与权重 |

依赖 Python 3.9+、pyelftools 0.32、Capstone 5.0.6。前三份工具要求输入目录含 `x2d-system-root/` 与 `x2d2-system-root/`，各自是对应版本的 system 解包根；第四份直接读一代 system 根。输入哈希在源码中固定，版本不符拒绝。

从仓库根目录运行，输出必须是输入树外尚不存在的目录：

```sh
python3 x2d/tools/firmware-analysis/focus-and-spectral/inspect_pdaf.py \
  /path/to/firmware-analysis --output /tmp/x2d-pdaf-audit
python3 x2d/tools/firmware-analysis/focus-and-spectral/inspect_sampling_geometry.py \
  /path/to/firmware-analysis --output /tmp/x2d-sampling-audit
python3 x2d/tools/firmware-analysis/focus-and-spectral/compare_focus_strategies.py \
  /path/to/firmware-analysis --output /tmp/x2d-focus-control-audit
python3 x2d/tools/firmware-analysis/focus-and-spectral/inspect_firmware.py \
  /path/to/x2d-system-root --output /tmp/x2d-spectral-audit
```

适配自本项目 2026-10-07／08 的只读工具；本次将输出改为显式新目录并拒绝写入输入树。生成证据可能包含原厂符号、配置摘录和反汇编，默认留本地，不能未经内容审核公开。

对应报告：[425 区域](../../../research/4.2.0/PDAF-425-BOUNDARIES.md)、[采样几何](../../../research/4.2.0/PDAF-SAMPLING-GEOMETRY.md)、[策略对照](../../../research/4.2.0/FOCUS-STRATEGY-PORT-BOUNDARIES.md)、[白平衡](../../../research/4.2.0/SPECTRAL-WHITE-BALANCE.md)。静态或离线通过不代表实机性能。
