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

## 研究目标

这项研究要回答的是：X2D / X2D II 的用户能否带着自己的色彩风格拍摄，而不只是在后期套用。具体分四个问题：

1. 哈苏色彩（HNCS）在机内由哪些模块、哪些表决定，可否读取。
2. 自定义 `.cube` LUT 能否同时出现在取景屏（LCD/EVF）上并烘焙进 JPEG/HEIF，而 RAW 保持不变。
3. 能否一次拍摄同时得到 RAW、原厂 HEIF 与带 LUT 的 JPEG。
4. 能否把哈苏色彩复现为 Lightroom 配置文件或 LUT，在后期得到同样的效果。

方法限定为离线固件分析：只读官方固件，编写可复现的检查、导出与烘焙工具，不连接相机。实机安装、恢复与验证是后续步骤，需要用户另行明确授权。各问题的当前答案见下文与“限制与下一步”。

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

### 5. ISP LUT 解码后的一代事实（静态分析 + 离线验证）

二代记录中由 `libduml_hal.so` 反汇编得到的 `rcam` 布局，对一代 `ec1706_config.json` 的全部表同样成立：16³、12 位、R/G/B 三平面。一代 `libduml_hal.so` 没有这两个函数，布局是用一代表的逐字节往返单独核对的。核对结果：

- **全部表逐字节往返：** 对 `ec1706_config.bin` 的 `MAIN_3DLUT`（11 张）与 `LCDC_3DLUT0/1`（各 99 张，内容相同）解码再编码后写回，结果与原文件逐字节相同。
- **灰轴：** `MAIN_3DLUT` 灰轴与恒等映射相差不超过 9 个 12 位码值，所以照片 3D LUT 基本不改灰阶。
- **LCD 表布局：** `LCDC_3DLUT0` 的 99 张表按 色温(11) × `user_scenario`(3) × `hardware_version`(3) 排列，第一轴最快：
  - 0–10 与 `MAIN_3DLUT` 0–10 逐字节相同：取景显示与成片使用同一套调色。
  - 11–32 为恒等表（场景 1、2）。
  - 33–98 与照片表相差约 2000–2600 码值，推测为不同屏幕硬件版本叠加了面板补偿；具体机身属于哪个版本，静态无法确定。
- **色彩矩阵：** `MAIN_CCM.lmtx_fw` 为 44 组（11 色温 × 4），每组 8 份相同的 6 个系数，即全局矩阵，共 11 种取值。大量系数恰为 −1229（约 −0.30，按 1/4096），像是寄存器限幅；矩阵本身不是完整的相机到输出色彩变换，其余部分由 3D LUT 承担。

## 自定义 LUT 拍摄可行性评估

| 方案 | 依据 | 主要障碍 | 评级 |
| --- | --- | --- | --- |
| A. 取景 / 监看 LUT | `3dlut=lcd,0,user` 已在原厂路径使用；`iq userlut` 调试入口 | `user` 槽已被补偿表占用，新 look 必须与之合成；一代没有 `.cube` 解析库，需在电脑端转换为 `rcam` 布局，而该布局未解码；调试入口需要 shell | 有明确接入点，未验证 |
| B. 视频输出 LUT | `video0` 与 `PYRA_3DLUT` `user` 槽 | 取决于社区视频实现走哪条流；需要流配置与 IQ 段同时打开该槽 | 待验证 |
| C. LUT 同时烘焙进取景与 JPEG | `rcam_lut.py bake` 把 `look(stock(x))` 写入 `MAIN_3DLUT` 与 `LCDC_3DLUT0/1` | 部署需要替换 system 分区的 IQ 表，或用未验证的 `iq load`；硬件版本 1、2 的显示表含面板补偿，look 接在其后只是近似；恒等表保持不变 | 离线候选已验证，未实机 |
| D. RAW | RAW 写入段不含 3DLUT | 机内 LUT 不进入 RAW | 不适用 |

与二代相比，一代没有 `cube_r` 显示文件；但取景表 0–10 就是照片表，所以烘焙后取景与成片天然一致。

方案 C 的离线验证（X2D 4.2.0，合成 look，不涉及实机）：

- 单位 look：输出与原文件逐字节相同。
- 测试 look：
  - LUT 区域外改动 0 字节；
  - 节点与期望值相差不超过 0.5 码值；
  - 每个显示数组中 77 张非恒等表被烘焙，22 张恒等表保持不变。
- 与“原厂表插值后再套 33³ look”比较（8 位刻度）：
  - 温和 look：平均 0.02、最大 2.32；
  - 强非线性 look：平均 1.02，p95 3.26，p99 6.92，最大 26.59。

误差来自相机表只有 16³。部署与恢复都未实现、未测试，需要用户另行明确授权。

三格式输出与 Lightroom 复现的方法分析见二代记录对应章节。其中的结论按机型分开：一代没有 P3 色域轴，因此也没有二代那种色域开关的可能。

## 证据与复现

从仓库根目录运行同一只读检查器（格式通用；结论按本机输入单独记录）：

```sh
python3 x2d2/tools/inspect_color_pipeline.py /path/to/x2d-4.2.0/system
python3 x2d2/tools/rcam_lut.py export /path/to/x2d-4.2.0/system --table main_3dlut --index 0 --out outputs/x2d-main-0.cube
python3 x2d2/tools/rcam_lut.py bake /path/to/x2d-4.2.0/system --look my_look.cube --out-dir outputs/x2d-iq-look
```

若 `ec1706_config.json` 哈希与上表一致，报告 `known_input` 为 `X2D 100C 4.2.0 ec1706_config.json`；`dispalgo` 为空列表。本文的模式、段、槽位、表数与轴长均来自该报告。`rcam_lut.py` 只接受上表哈希的 `ec1706_config.bin` / `.json`。`cube_lut.py` 只处理二代 `cube_r` 文件，不适用于一代。固件、解包树与原厂表不随仓库提供。

## 限制与下一步

- 全部为静态分析，没有实机验证；不能据此认为取景 LUT、视频 LUT 或烘焙 LUT 已可用。
- `userlut` 参数含义、补偿表的数据来源（IQ `LCDC_3DLUT` 的硬件版本表，还是外部文件）、机身的显示硬件版本均未确认。烘焙表是否被相机按预期加载，尚无实机证据。
- 下一项离线工作：确认 `setDispEngCompensationLut` 的调用时机，以及 `user` 模式表来自何处；之后才能设计“补偿表 ∘ look”的合成。
