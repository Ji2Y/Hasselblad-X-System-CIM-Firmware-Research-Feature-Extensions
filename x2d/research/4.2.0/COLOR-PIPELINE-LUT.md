# X2D 4.2.0 色彩管线与自定义 LUT 可行性

2026-11-03。只读官方固件的静态分析与电脑端离线检查；没有连接相机，没有安装、刷写或运行机内程序。第二代的对应记录见 [X2D II 1.3.16.2 色彩管线](../../../x2d2/research/1.3.16.2/COLOR-PIPELINE-LUT.md)；两代传感器、IQ 表和显示栈不同，本文结论只适用于第一代。

## 适用范围

- 机型：X2D 100C。
- 固件：官方 [4.2.0 CIM](https://cdn.hasselblad.com/firmware/X2D-100C-Firmware/4.2.0/X2D_100C_v4_2_0.cim)，175245312 字节，SHA-256 `5ae67d16a24b00f9300e3e9c1323e7d149248ad36975e12c4fa8da633b438e03`；`ota.zip` SHA-256 `03c7e1e508bf17246e0be3e0b39d821683845561571dea57c09fcf0a3c9d736b`。两者与仓库既有记录一致。容器头平台 `10.00.25.21`，2025-10-31。
- 主传感器模块 `IMX461BQR`（`etc/iq/dji_rcam.conf` → `ec1706_config.bin`），ISP 平台为 DJI `rcam_ng` / E2。

| 输入（system 分区相对路径） | SHA-256 |
| --- | --- |
| `etc/iq/ec1706_config.json` | `b4dd1b02de7ce052cf4fd49806fabfb037f98aa0c6194aa28366b71791b545ad` |
| `etc/iq/ec1706_config.bin` | `ad416dccda717d2a196a859e664229c5f8e2665ecf65ab545603121a51451097` |
| `etc/iq/config.fbs` | `55f9ce0841b0445e45a358dc1f6e913f8efd55b80ed51a8311bf583ee21fa651` |
| `lib64/librcam.so` | `72ebc8deebce4a29047c475e77ab4edbf2860abb1f572fea45260fe17ad0bda5`（与 AF 研究所锁定值相同） |
| `lib64/libduml_hal.so` | `77875f6f47a2137e5461c61789d44fdd8537e7359c8d7b43ec7ee4737fd15bb3` |
| `lib64/camera/plugins/disp/libdcam_disp_wayland.so` | `d8b4efa285a53287c29823b1310e3ca1d078b5b6c1c30ad5e2f2d2375516dc89` |
| `bin/camera-service` | `fbcf828f73bca13f0c8b95e7dd0b95ac483ae36954ec06179098c8a1a65f9f82` |
| `bin/camera-gui` | `16391452abdc69de9e0807e065c0f4ab3f1ccb5fc288f6fc4e6f5cb3bdca12e0`（与 GUI 研究所锁定值相同） |

## 当前结论

### 1. 调色结构（静态分析）

`ec1706_config.json` 与二代同属 FlatBuffers 文本 JSON 格式，模块集合基本相同：`MAIN_CCM`、`MAIN_HNCS`、`MAIN_GAMMA`、`MAIN_3DLUT`、`MAIN_GTM`、`PYRA_3DLUT0..2`、`LCDC_3DLUT0/1`。IQ 模式为 `global`、`preview0..2`、`still0..1`，以及 **`video0`**。

| 表 | 数据 | 插值轴 | 状态 |
| --- | --- | --- | --- |
| `MAIN_3DLUT.lut_data` | 11 张 × 6144 字 | `cc_color_temp` 11 点（2400–10000 K），无色域轴 | `preview0..2`、`still0..1`、`video0` 均启用 |
| `MAIN_HNCS.lut_2d_mem0..3` | 4 × 8192 值 | `color_temp` 4 点 | 照片与回放段均旁路 |
| `MAIN_CCM.lmtx_fw` | 2112 值 | `cc_color_temp` 11 × `color_hiso` 4 | — |
| `PYRA_3DLUT0..2.tlut` | 5 张 × 6144 字 | `lut3d` 槽 | `tlut_en = [0,1,1,1,1]` |
| `LCDC_3DLUT0.tlut` | 99 张 × 6144 字 | `cc_color_temp` 11 × `user_scenario` 3 × `hardware_version` 3 | 显示 |

槽位映射与二代相同：D-Log 0、Rec.709 1、HLG 2、PQ 3、**`user` 4**。

照片拓扑 `TPLG_IMX461BQR_STILL_14BIT` 的段 `frog_raw_reprocess_2-r2y-stat_gen`、`-fast_preview`、`-still`、`frog_raw_reprocess_2-r2y`，以及回放 `STILL_RAW_PLAYBACK` 的各段，全部旁路 `MAIN_HNCS`、启用 `MAIN_3DLUT`。与二代相同，成片颜色来自 CCM、gamma 与 `MAIN_3DLUT`，不来自名为 HNCS 的二维色度块。

### 2. 已在使用 `user` 槽：LCD 补偿 LUT（静态分析）

`camera-service` 中，`MetadataControl::setDispEngCompensationLut()` 旁的流参数字符串是 `3dlut=lcd,0,user;`；同一程序还有 `CameraObjectImpl::setDispEngLut`，两者的调用关系未经反汇编确认。`libdcam_disp_wayland.so` 按 `usage, id, mode` 解析 `3dlut=`，`camera-system` 含合成器协议请求 `eagle_compositor.set_3dlut`。按函数名推断，一代屏幕取景的 LCD 3D LUT 以 `user` 模式承载原厂的屏幕补偿表。自定义 look 若走这条路，必须与补偿表合成，不能直接替换，否则会丢失面板校正。

### 3. 其他用户 LUT 入口（静态分析）

- `librcam.so` 与二代一样含调试命令 `iq [load [json file] | reload | userlut [lut_file] [lut_type] [lut_size]]`、`UsCtrlId_Set_3dlutParam`（日志 `3dlut param: usage %d, path_len [%d], path [%s].`）、`_update_disp_userlut`、`rcam_calib_update_userlut`。`libdcam_disp_e2_lcdc.so` 含 `_update_user_lut`。
- `libduml_hal.so` **没有** `.cube` 解析函数（`load_rgb_3dlut_from_cube_file`、`disp_3dlut_combine` 均未出现），也没有 `/etc/dispalgo` 显示色彩管理目录。二代新增的这两项不能套用到一代。
- `camera-gui` 有 `LutProvider`、`LutTextureFactory` 类，但没有二代的 `PanelMonitor::onLut` 与 `SdrLut` 等对象；其用途未追踪。
- `bin/copy_3dluts_files` 并非程序：它是 12288 字节的数据，形状符合 16³×RGB 8 位，每个三元组的第一分量最快递增。没有找到引用它的字符串，用途未知。

### 4. 视频基础（静态分析）

IQ 表含 `video0` 模式，以及拓扑 `TPLG_IMX461BQR_VIDEO_4K2160_12BIT_30FPS`、`VIDEO_8K3428_11BIT_24FPS`、`VIDEO_4K1296_12BIT_60FPS`、`VIDEO_12K_11BIT_10FPS`。插件目录含 `libdcam_shooter_video_single.so`、`libdcam_venc_h26x.so`、`libdcam_venc_prores.so`、`libdcam_venc_proresraw.so`、`libdcam_mp4_stream_writer.so` 等。`MAIN_3DLUT` 在 `video0` 启用，`PYRA_3DLUT*` 的 `user` 槽对应 DJI 平台的 video/hdmi/lcd 用途。社区的视频实现不在本仓库；这里只记录固件中存在的调校与插件，不代表视频 LUT 已可用。

## 自定义 LUT 拍摄可行性评估

| 方案 | 依据 | 主要障碍 | 评级 |
| --- | --- | --- | --- |
| A. 取景 / 监看 LUT | `3dlut=lcd,0,user` 已在原厂路径使用；`iq userlut` 调试入口 | `user` 槽已被补偿表占用，新 look 必须与之合成；一代没有 `.cube` 解析库，需在电脑端转换为 `rcam` 布局，而该布局未解码；调试入口需要 shell | 有明确接入点，未验证 |
| B. 视频输出 LUT | `video0` 与 `PYRA_3DLUT` `user` 槽 | 取决于社区视频实现走哪条流；需要流配置与 IQ 段同时打开该槽 | 待验证 |
| C. LUT 烘焙进 JPEG | `MAIN_3DLUT` 11 张色温表 | 需要修改 IQ 表或拓扑，且每张都要与原厂调色合成；输入为 ISP 内部 RGB | 风险最高，仅静态证据 |
| D. RAW | RAW 写入段不含 3DLUT | 机内 LUT 不进入 RAW | 不适用 |

与二代相比，一代的屏幕端 LUT 只能走 ISP `rcam` 格式，没有可直接复用的 `cube_r` 文件，因此一代的方案 A 难度高于二代的回放方案。

## 证据与复现

从仓库根目录运行同一只读检查器（格式通用；结论按本机输入单独记录）：

```sh
python3 x2d2/tools/inspect_color_pipeline.py /path/to/x2d-4.2.0/system
```

若 `ec1706_config.json` 哈希与上表一致，报告 `known_input` 为 `X2D 100C 4.2.0 ec1706_config.json`；`dispalgo` 为空列表。本文的模式、段、槽位、表数与轴长均来自该报告。`cube_lut.py` 只处理二代 `cube_r` 文件，不适用于一代。固件、解包树与原厂表不随仓库提供。

## 限制与下一步

- 全部为静态分析，没有实机验证；不能据此认为取景 LUT、视频 LUT 或烘焙 LUT 已可用。
- `rcam` LUT 布局、`userlut` 参数含义、补偿表的数据来源（IQ `LCDC_3DLUT` 还是外部文件）均未确认。
- 下一项离线工作：确认 `setDispEngCompensationLut` 的调用时机，以及 `user` 模式表来自何处；之后才能设计“补偿表 ∘ look”的合成。
