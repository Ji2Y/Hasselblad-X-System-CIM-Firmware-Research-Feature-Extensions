# X2D II 离线工具

本目录的脚本只读取你自行合法取得并解包的官方固件，不连接相机、不安装或刷写。固件、解包树和原厂数据不随仓库提供。

| 文件 | 用途 | 副作用 |
| --- | --- | --- |
| [inspect_region.py](inspect_region.py) | 1.3.16.2 地区研究的历史解包与线索索引，见 [REGION.md](../research/1.3.16.2/REGION.md) | 依赖仓库本地 `.research-cache`，会在其中写入 `ota.zip`、镜像和提取文件，并写 `initial-evidence.json`；本轮未重新运行 |
| [inspect_color_pipeline.py](inspect_color_pipeline.py) | 解析 `etc/iq/*_config.json`（FlatBuffers 文本 JSON）与 `etc/dispalgo/cm_*.json`，报告调色模块、3D LUT 槽位、每模式启用状态、表数与插值轴、拓扑段中 `MAIN_HNCS`/`MAIN_3DLUT`/`PYRA_3DLUT*` 的启用或旁路 | 只读；JSON 输出到 stdout |
| [cube_lut.py](cube_lut.py) | `.cube` 读写、三线性采样与合成；读写二代 `cube_r` 显示 LUT（`info`、`export`、`compose`） | 只写入你指定且不存在的路径；拒绝 `rcam` 布局 |
| [rcam_lut.py](rcam_lut.py) | ISP `rcam` 3D LUT（16³、12 位、R/G/B 三平面）编解码；`export` 把原厂表导出为 `.cube`；`bake` 把 `look(stock(x))` 写入 `MAIN_3DLUT` 与 `LCDC_3DLUT0/1`，生成同尺寸 IQ 表候选与 `bake-manifest.json` | 只接受已核对哈希的输入；只写入你指定且不存在的路径；不部署 |
| [test_color_pipeline_tools.py](test_color_pipeline_tools.py) | 上述工具的离线测试，仅用合成数据 | 只使用临时目录 |

## 适用对象

- `inspect_color_pipeline.py`：格式通用于本仓库已核对的两份 IQ 表，即 X2D II 1.3.16.2 `hb722_config.json` 与 X2D 4.2.0 `ec1706_config.json`。哈希一致时报告 `known_input`，其他输入报告 `unknown input`，不能视为同一固件。两代结论分别记录在 [X2D II 色彩管线](../research/1.3.16.2/COLOR-PIPELINE-LUT.md) 与 [X2D 色彩管线](../../x2d/research/4.2.0/COLOR-PIPELINE-LUT.md)。
- `cube_lut.py`：只针对 X2D II 1.3.16.2 `/etc/dispalgo` 中 `lut_format: cube_r` 的描述符。
- `rcam_lut.py`：只接受 X2D II 1.3.16.2 `hb722_config.bin` 与 X2D 4.2.0 `ec1706_config.bin`（及其 JSON）的已核对哈希，其他输入直接拒绝。

## 依赖

Python 3.11+，只用标准库。

## 运行

从仓库根目录：

```sh
python3 x2d2/tools/inspect_color_pipeline.py /path/to/extract/system
python3 x2d2/tools/cube_lut.py info my_look.cube
python3 x2d2/tools/cube_lut.py export /path/to/extract/system/etc/dispalgo/cm_mp_pb_sdr.json --index 5 --out outputs/stock5.cube
python3 x2d2/tools/cube_lut.py compose /path/to/extract/system/etc/dispalgo/cm_mp_pb_sdr.json --look my_look.cube --out-dir outputs/cm-look
python3 x2d2/tools/rcam_lut.py export /path/to/extract/system --table main_3dlut --index 0 --out outputs/hb-main-0.cube
python3 x2d2/tools/rcam_lut.py bake /path/to/extract/system --look my_look.cube --out-dir outputs/iq-look [--gamut srgb]
```

测试从本目录运行：

```sh
python3 -m unittest test_color_pipeline_tools.py
```

## 验证结果与状态

- 合成数据测试 15 项通过（离线验证）。
- 对官方 1.3.16.2 的 `cm_mp_pb_sdr`、`cm_mp_lv_ui`、`cm_evf_pb_hdr` 解码后重新编码，结果逐字节相同；单位 look 的 `compose` 输出与原文件逐字节相同（离线验证）。
- `compose` 的结果是 `原厂显示表(look(x))`：look 先作用，原厂面板映射仍在最后一级。回放图像进入显示表时的编码未确认；没有实机验证，也不提供安装方式。
- `rcam_lut.py bake` 用单位 look 时，两代官方 IQ 二进制的输出都与原文件逐字节相同；用测试 look 时，LUT 区域外改动 0 字节（离线验证）。烘焙结果是否被相机正确加载，尚无实机验证；本目录不提供部署或恢复脚本。
- 导出的 `.cube`、合成的 `.bin` 与烘焙的 IQ 表都是原厂数据的派生物，只放在本地 `outputs/`，不提交。
