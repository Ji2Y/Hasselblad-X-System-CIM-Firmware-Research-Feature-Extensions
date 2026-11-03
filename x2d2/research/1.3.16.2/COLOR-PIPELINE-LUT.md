# X2D II 1.3.16.2 色彩管线与自定义 LUT 可行性

2026-11-03。只读官方固件的静态分析与电脑端离线验证；没有连接相机，没有安装、刷写或运行机内程序。第一代 X2D 的对应记录见 [X2D 4.2.0 色彩管线](../../../x2d/research/4.2.0/COLOR-PIPELINE-LUT.md)，两代地址与结论不互相套用。

## 适用范围

- 机型：X2D II 100C。
- 固件：官方 [1.3.16.2 CIM](https://cdn.hasselblad.com/firmware/X2D_II_100C_Firmware/1.3.16.2/X2DII_100C_v1_3_16_2%281%29.cim)，364814336 字节，本次计算 SHA-256 `9789d6a9843d388034bc12341ad9a97585c25cb98cf11a0da8b768399b4842f6`。容器头平台 `10.00.09.77`，2026-07-30。
- 解包：公开 [hasselblad-cim-firmware-extractor](https://github.com/YuHaoyua/hasselblad-cim-firmware-extractor) 修订 `768664267cb44621c3c12595ee9cc538020b1b94` 的常量，六个外层条目 MD5 校验通过；`ota.zip` SHA-256 `7ccd5df4dab8d098d9895973fb62bcedcaa379f75fb044408a8263ce2d1f9a57`。system/vendor 文件系统在本地重建。固件、解包文件与原厂 LUT 均不随仓库提供。
- 主传感器模块 `IMX861BQR`（`etc/iq/dji_rcam.conf`），ISP 平台为 DJI `rcam_ng` / E2（库内源码路径 `hardware/dji/common/camera/rcam_ng/rcam_user/platform/E2/...`）。

| 输入（system 分区相对路径） | SHA-256 |
| --- | --- |
| `etc/iq/hb722_config.json` | `2a4fd76e5299937a6607da8454add17e9746347c54adcf5da1360799de634286` |
| `etc/iq/hb722_config.bin` | `ce58c7e668fd41af0547e0df7d8545159a3ab2619ad4eabb8931544dadb81436` |
| `etc/iq/config.fbs` | `59ec3b0d019b9e8873f3d005c041b4e3ca1a2b930c503c110c51531f8bd30e40` |
| `lib64/librcam.so` | `3dd5b37b3db18b3e6b54271e1501b4dd337e101c06cdd386a896b1547b662f66` |
| `lib64/libduml_hal.so` | `adfb1cf834584d5c2d3e7b8a49c8ff78a919f007b4fe4ee5442a658dafc71d20` |
| `lib64/weston/eagle-backend.so` | `7d393c1b0cfecca355b7ca07d357003c25e16fecf8e111a1e03b311c07ab72ab` |
| `lib64/camera/plugins/libdcam_plugins_AIO.so` | `1924f9aca6d5f4f92ff482f6a864579d303a890fcef3427053f35d9b00bd4135` |
| `lib64/camera/plugins/disp/libdcam_disp_wayland.so` | `ac69eaa52742d97cf758a6082cb8ffdcff939fa242231c79dd2181836ca623e7` |
| `bin/camera-gui` | `b1b643cb36176cd5a49129dd9bb2be480aa045a96ed1c35c30a779ab5af0801b` |
| `bin/camera-service` | `51b9e02f8bfebf388be8dfa163c8e512bee19aeb8ae37a6712727ccc6f26a52d` |
| `etc/dispalgo/cm_mp_pb_sdr.json` / `.bin` | `a3a92a814a3bd603b5037be83d8f624ece13ee8889f00582bd7b89de8df0c35f` / `197817efae19968d67e8b875cd4a78aafbd28bd59b55d988bb3c8d2f01268a94` |

## 一句话结论

机内有三层互相独立的 LUT：ISP 调色 LUT（决定 JPEG/HEIF 的颜色）、ISP 输出端按用途选择的 LUT（预留了 `user` 槽，但静态照片主帧明确旁路）、显示端色彩管理 LUT（只影响屏幕观看）。ISP 调色 LUT 的布局已经解码。因此把自定义 `.cube` 同时烘焙进取景显示与 JPEG/HEIF 有了可离线复现的同尺寸 IQ 表候选（第 7 节与“B 的离线候选”），但部署方式与实机效果都未验证。只改屏幕观看的显示 LUT 方案也有工具。三格式输出需要改相机服务。RAW 不受任何机内 LUT 影响。

## 当前结论

### 1. 调色在哪里定义（静态分析）

ISP 调校表是 FlatBuffers 文本 JSON（`hb722_config.json`，27 MB，无引号键、`//` 注释），`config.fbs` 是其 schema，`hb722_config.bin` 是同名二进制形式。`dji_rcam.conf` 把 `IMX861BQR` 绑定到 `hb722_config.bin`。表内包含：

- 模块：`MAIN_WBC`、`MAIN_CCM`、`MAIN_HNCS`、`MAIN_GAMMA`（normal / ei / lowlight 三套）、`MAIN_3DLUT`、`MAIN_GTM`、`MAIN_R2Y`，输出金字塔 `PYRA_CSC_*`、`PYRA_3DLUT0..2`，显示控制 `LCDC_3DLUT0/1` 与 `LCDC_LUTCTRL0/1`。`iq_table.module` 的声明顺序为 WBC → RLTM → 去马赛克 → PFR → CCM → HNCS → gamma → 3DLUT → GTM → R2Y，推测即硬件顺序；拓扑段内的模块列表顺序不一致，不能直接当作处理顺序。
- IQ 模式只有 `global`、`preview0/1/3`、`still0..4`。schema 中的 `video0..`、`IQ_COLOR_MODE_D_LOG`、`FILM_A..F` 等是 DJI 通用枚举，本机表没有对应的调校块；`iq_table.color` 只有 `IQ_COLOR_MODE_DEFAULT`。
- `camera.dlog_num: 10` 与 `user_ei` 表（EI 100–25600，low/high gain）在表头存在，但本机没有视频 IQ 模式，不能据此认为 D-Log 已经可用。

### 2. HNCS 硬件块不是静态照片颜色的来源（静态分析）

schema 中有名为 `mod_main_hncs` 的模块：含 RGB↔YCbCr 系数（`r2y_coe_cfg`、`y2r_coe_cfg`）、暗部 / 灰度参数，以及 4 块 `lut_2d_mem0..3`（各 8192 值），按 `color_temp` 4 点（2800/4000/5500/6500 K）插值。它是 Cb/Cr 二维色度 LUT。

但所有静态照片渲染与回放段都**旁路** `MAIN_HNCS`、**启用** `MAIN_3DLUT`：`frog_raw_reprocess_2-r2y-still`、`..._scap3_enh_normal`、`..._scap3_enh_hdr`、`frog_raw_reprocess_12-ycc-still_quick`、`frog_raw_reprocess_4-r2y-pb` 等。`MAIN_HNCS` 只在 `common_recording_still_1-raw_writer-ycc-sub_back-data_mux0` 及其 `-video` 两个实时段出现。因此，JPEG/HEIF 中可见的“哈苏色彩”由 CCM（`lmtx_fw`，按 `cc_color_temp`×`color_hiso` 插值）、gamma 与 `MAIN_3DLUT` 共同决定。模块名与营销名 HNCS 相同，但不能据此证明它是该名称的全部实现。

### 3. 三层 LUT 的分布（静态分析；尺寸由离线工具核对）

| 层 | 位置 | 数据 | 在照片中的状态 |
| --- | --- | --- | --- |
| ISP 调色 | `MAIN_3DLUT.lut_data` | 8 张 × 6144 字，按 `cc_color_temp`（2400/3050/5550/9100 K）× `color_gamut`（sRGB/P3）插值 | `still0..4` 均 `module_en_lut=1`、`tlut_en=1` |
| ISP 输出 | `PYRA_3DLUT0..2.tlut` | 5 张 × 6144 字，按 `lut3d` 槽选择 | 主帧与增益图缩略图段 `pyra_main_frame-pp_3dlut_disable`、`pyra_gain_map_thumbnail-pp_3dlut_disable` 旁路 |
| ISP 显示 | `LCDC_3DLUT0/1.tlut` | 8 张 × 6144 字，按 `cc_color_temp` × `liveview_scenario` 插值 | 只影响取景显示 |
| 合成器显示 | `/etc/dispalgo/cm_*.bin` | 见第 5 节 | 只影响屏幕 |

槽位映射 `camera.lut3d`：`iq_lut3d_d_log`→0、`iq_lut3d_rec_709`→1、`iq_lut3d_rec_2100_hlg`→2、`iq_lut3d_rec_2100_pq`→3、**`iq_lut3d_user`→4**，`iq_lut3d_dji_709` 复用 0；`local_lut3d_num: 5`。`PYRA_3DLUT*.tlut_en = [0,1,1,1,1]`，即 D-Log 槽本身为直通。schema 的 `lut_usage` 枚举为 `video, hdmi, lcd, remote, still`，`lut_device` 为 `pyra0..2, lcdc0..1`。

每张 ISP LUT 为 6144 个 32 位字，与 `cm_*_lv_sdr_fastpre.json` 所称的 `rcam` 格式（24576 字节）相同。布局已解码，见第 7 节。

### 4. 机内已存在的用户 LUT 基础设施（静态分析）

- `librcam.so` 的调试命令表含 `iq [load [json file] | reload | userlut [lut_file] [lut_type] [lut_size]]`，错误提示 `use iq:userlut:[lut_file]:[lut_type]:[lut_size]`。同表还有 `getreg`、`setreg`、`loadisp`、`bypass`。相关符号有 `_update_disp_userlut`、`dcam_adj_update_userlut`、`UsCtrlId_Set_3dlutParam`（日志 `3dlut param: usage %d, path [%s]`），以及断言 `lut3d_v2 doesn't support DIQ_lut3d_type_iq_lut3d_user!`。
- `bin/cam_dt_cmdline` 通过本地 socket（`dcam_dbg_get_sock_addr`、`sendto`）把 `rcam ...` 命令送进相机服务，原厂工厂测试脚本使用它。到达该入口需要机内 shell；本项目不公开取得方式，也未验证 `lut_type`、`lut_size` 的含义及作用目标。
- `libdcam_plugins_AIO.so`：`_get_pyra_3dlut_param_from_user_setting(DCAM_FILTER_3DLUT_PARAM)`、`_update_user_lut`，以及提示 `pyra-3dlut%d wasn't configured in stream profile. So it must be bypassed in segment[%s] of IQ table`。说明 user 槽要由流配置与 IQ 段共同打开。
- `libdcam_disp_wayland.so` 解析流参数 `3dlut=`（`usage, id, mode`）与 `3dlut_min_interval_us=`，含 `m_3dlutMode != DCAM_3DLUT_MODE_USER` 判断。本机 `camera-service` 未见发送 `3dlut=` 的字符串（一代 4.2.0 有，见一代记录）。
- `libduml_hal.so` 含完整 `.cube` 工具：`load_rgb_3dlut_from_cube_file`（`LUT_3D_SIZE%[^0-9]%d`）、`save_rgb_3dlut_to_cube_file`、`do_3dlut_trans_by_trilinear_interpolation`、`disp_3dlut_combine`、`disp_hal_3dlut_cube_files_merge`，以及平台格式转换 `disp_hal_3dlut_plt_fmt_*`。`bin/test_disp` 暴露 `3dlut_transform $input_lut_path $out_bin_path`、`3dlut_file_merge`、`3dlut_file_trans`。

这些是 DJI 平台的通用能力。原厂 GUI 中没有找到导入 LUT 的菜单或文件选择入口（`camera-gui` 字符串中未见 `.cube`、`userlut`）。

### 5. 显示端色彩管理（静态分析 + 离线验证）

Weston 后端 `eagle-backend.so` 的 `DispAlgoColorMgmt` / `DispAlgoColorMgmtInterp::parseLutFile` 读取 `/etc/dispalgo/cm_*.json`。`mp` 为主屏，`evf` 为取景器；`lv` 为取景，`pb` 为回放；`sdr`、`hdr`、`hdr_thumb`、`ui`、`fastpre` 为用途。每个描述符给出 `lut_format`、`lut_bit_depth`、`lut_width`，以及按 `sdr_ref_white` 分档的 `param_list`（主屏 30/180/327/591/800/1000，EVF 30/180/327/591/800）。GUI 侧 `PanelMonitor::onLut(WaylandMonitor::LutUsage, ...)` 接收这些表，经 `LutProvider` / `LutTextureFactory` 与 QML `Lut`（`SdrLut`、`HdrLut`、`HdrBaseLut`、`FastPreviewLut`、`UiLut`）进入着色器。另有测试窗口可用 `image://lutstore/<luturl>` 加载 LUT。

`cube_r` 布局已离线确认：`lut_width`³ 节点，R 下标最快，RGB 三元组，uint16 小端，`lut_bit_depth` 位码值，`param_count` 张依次排列。14 个描述符的 `.bin` 大小全部与该公式一致（`cm_mp_lv_sdr_fastpre`、`cm_evf_lv_sdr_fastpre` 为 `rcam` 格式 16³ 12 位，大小同样一致）。对 `cm_mp_pb_sdr`、`cm_mp_lv_ui`、`cm_evf_pb_hdr` 解码后重新编码，结果与原文件逐字节相同。`cm_mp_pb_sdr` 第 6 张（`sdr_ref_white=1000`）的最大码值为 0.858，`sdr_ref_white=30` 的第 1 张白点约为 395/1023。这些表是面板色域映射与亮度分档，不是创意风格 LUT。

### 6. 视频相关的静态事实

本机有 `libdcam_shooter_video_single.so`，以及 `venc` 插件 `libdcam_venc_h26x.so`、`libdcam_venc_prores.so`、`libdcam_venc_proresraw.so`；没有一代那样的 MP4 写入插件，IQ 表也没有视频拓扑或视频 IQ 模式。社区的视频实现不在本仓库，本文不评价其路径。若视频走取景流，`PYRA_3DLUT` 的 `user` 槽是 DJI 平台为 video/hdmi/lcd 用途设计的位置，但本机是否允许该流打开它，尚待验证。

### 7. ISP `rcam` LUT 布局（静态分析 + 离线验证）

布局取自 `libduml_hal.so` 的 `lookup_rgb_pixel_plt_fmt`（`0x74fb0`）与 `set_rgb_pixel_to_plt_fmt_lut`（`0x74c88`）的反汇编：

- 一张表 = 6144 个小端 uint32 = 3 个 2048 字的平面，依次为输出 R、G、B。
- 节点 (r, g, b) 各取 0..15，位于字 `r*128 + g*8 + (b >> 1)`；偶数 b 用 bit 0..11，奇数 b 用 bit 16..27。
- 网格节点为 0、273、…、4095（12 位均匀），`MAIN_3DLUT` 与 `LCDC_3DLUT` 的 `pre_gamma` / `gamma_en` 均为 0。

按此布局解码后，`MAIN_3DLUT` 的灰轴与恒等映射相差不超过 1 个码值。所以照片的 3D LUT 只改色相与饱和度，不改灰阶；例如饱和蓝在第 0 张表中被明显压暗。`cm_*_lv_sdr_fastpre.bin` 用同一布局也能解码为平滑表。`PYRA_3DLUT` 的 D-Log、Rec.709、`user` 三个槽是同一张表。

表序为第一轴最快：`MAIN_3DLUT` 索引 = 色温 + 4 × 色域，因此 0–3 为 sRGB、4–7 为 P3。`LCDC_3DLUT0/1` 内容相同，8 张表均与照片表不同，推测为显示适配版本。

离线验证：对官方 `hb722_config.bin` 所有 `MAIN_3DLUT` / `LCDC_3DLUT0/1` 表逐张解码再编码，并按上述位置写回，结果与原文件逐字节相同。

### 8. 色彩矩阵与 gamma（静态分析，含未确认项）

- 照片渲染段 `frog_raw_reprocess_2-r2y-still` 启用 WBC、CCM、GAMMA、3DLUT、R2Y，旁路 RLTM、GTM、HNCS，所以成片颜色是全局映射，不含局部色调映射。
- `MAIN_CCM.lmtx_fw`：16 组 × 48 值。每组 48 值是 8 份相同的 6 个系数，即全局矩阵，没有分色相扇区。共 4 种取值，对应 4 个色温点。6 个系数应为行和为 1 的 3×3 矩阵的非对角项（尺度推测为 1/4096），但排列顺序未确认。
- `MAIN_GAMMA` 正常曲线：257 点，输出 16 位。按“`lut_div` 为分段步长指数”解释时，相邻段的斜率在边界处减半，因此该假设被否定。`lut_div` 是 7 选 1 的索引值（`simple_val_idx_v5`），曲线更像均匀索引；它在中间调比 sRGB 亮，并压缩高光。输入的曝光尺度未确认。
- `awb_imx861.json` 的 `awb_ccm`（5500 K）行和不为 1，是 AWB 统计用矩阵，不是渲染矩阵。

## 自定义 LUT 拍摄可行性评估

| 方案 | 影响什么 | 依据 | 主要障碍 | 评级 |
| --- | --- | --- | --- | --- |
| A. 回放 / 复看时套用 LUT | 屏幕观看，不改文件 | `cube_r` 已解码；`cube_lut.py compose` 离线生成 `显示表(look(x))` | 需要替换 `/etc/dispalgo` 文件或在运行时调用合成器 `set_3dlut`，两者都需要系统写入或 shell；回放图像送入合成器时的编码（sRGB/P3、SDR/HDR）未确认 | 格式离线验证，未实机 |
| B. 取景 + JPEG/HEIF 同时烘焙 | 屏幕与输出文件 | `rcam` 布局已解码；`rcam_lut.py bake` 离线生成同尺寸 `hb722_config.bin` 候选 | 部署需要替换 system 分区中的 IQ 表，或用未验证的 `iq load` 运行时载入；P3 表与显示表的合成顺序为近似；HDR HEIF 增益图一致性未知 | 离线候选已验证，未实机 |
| C. 三格式输出（RAW + 原厂 HEIF + LUT JPEG） | 输出文件 | 见“三格式输出”一节 | 固件没有该格式；每张需要两次 ISP 渲染 | 需要改 `camera-service`，不建议 |
| D. RAW（3FR/FFF/DNG） | 无 | RAW 写入段不含 3DLUT | 机内 LUT 不进入 RAW | 不适用 |

### B 的离线候选

`rcam_lut.py bake` 把每张选中的表替换为 `look(stock(x))`，默认处理 `MAIN_3DLUT` 与 `LCDC_3DLUT0/1`。

- **照片表：** look 作用在原厂 3D LUT 的输出之后。3D LUT 之后的照片段只剩 R2Y 与 YUV 处理，所以效果等价于“原厂 JPEG 再套 `.cube`”，并保留哈苏原厂调色。
- **P3 表：** 以 sRGB 为基准、按增量方式处理，sRGB 外的颜色保留残差。`--gamut srgb` 只改 sRGB 表，P3 表保持原厂。
- **显示表：** look 同样接在后面。若显示表内含面板校正，这一顺序只是近似。

离线验证结果（X2D II 1.3.16.2，合成 look，不涉及实机）：

- 单位 look：输出与原文件逐字节相同。
- 测试 look：
  - LUT 区域之外改动 0 字节；
  - 解码后的节点与期望值相差不超过 0.5 个 12 位码值。
- 与“原厂表插值后再套 33³ look”比较：
  - 温和 look：平均 0.02、最大 3.14（8 位刻度）；
  - 强非线性 look（S 曲线 + 冷暖分离）：平均 1.14，p95 3.90，p99 9.13，最大 18.93。

误差来自相机表只有 16³，强风格在高饱和边缘会变粗。

部署与恢复都没有实现，也没有测试。可行方式有两种：替换 `/system/etc/iq/hb722_config.bin`（需要系统写入；恢复为写回原文件并核对 SHA-256），或用 `iq load [json file]` 在运行时载入（只影响当次运行，但需要修改后的 JSON，本工具不生成）。两者都需要用户另行明确授权。

## 三格式输出（静态分析）

- `E_ImageFormat` 只有 `Raw`、`Jpeg`、`Heif`、`RawJpeg`、`RawHeif`，没有三格式组合。
- 照片 JPEG/HEIF 由同一次 RAW 重处理（`frog_raw_reprocess_*`）经同一 `MAIN_3DLUT` 生成，所以烘焙后 JPEG 与 HEIF 都会带上 look。
- 若要同一张同时得到原厂 HEIF 与 LUT JPEG，每张需要第二次 ISP 重处理与编码，还要新的格式项、文件命名与缓冲管理。这些需要修改哈苏 `camera-service`，不是改表能做到的；1 亿像素下的时间与内存也未评估。
- 可行的替代：
  - RAW + 烘焙 JPEG：RAW 保持中性底片。
  - 色域开关（假设）：用 `--gamut srgb` 只烘焙 sRGB 表，让菜单中的色彩空间在 sRGB（LUT）与 P3（原厂）之间切换。`E_ColorProfile` 到 IQ `color_gamut` 的映射以及 AdobeRGB 的处理未确认。
  - `STILL_RAW_PLAYBACK` 拓扑说明机内能在回放时重处理 RAW。以后做“回放中按 LUT 重新导出 JPEG”在架构上可以设想，但工作量大。

## 在 Lightroom 中复现哈苏色彩

- **能直接导出的：** `rcam_lut.py export` 可把原厂照片 3D LUT（各色温 / 色域）导出为 `.cube`。它只是渲染的最后一级，输入是哈苏矩阵与 gamma 之后的 RGB。直接套在 Lightroom 的 Adobe 渲染上只能近似。
- **完整复现要三者合一：** 矩阵 + gamma + 3D LUT，均以相机原生 RGB 为输入。Lightroom 侧有两种载体：
  - DCP：ForwardMatrix、ProfileToneCurve，以及基于 HSV 的 LookTable，需要把 3D LUT 拟合成 HSV 形式；
  - ACR 增强配置文件：线性基底加 RGB 表。
- **待确认：** 矩阵系数的排列与尺度，以及 gamma 的输入尺度。它们需要至少一组同一画面的 RAW + 机内 JPEG 来标定与验证；最好拍色卡，并在日光与钨丝灯下各一组。
- **色温限制：** 相机按 4 个色温点插值；DCP 只支持双光源，单张 LUT 不随色温变化，因此只能近似。
- **使用边界：** 导出的原厂表与生成的配置文件是厂商数据的派生物，只保存在本地，不提交、不分发。

## 建议次序

1. 用户提供 RAW + 机内 JPEG 样张，离线标定矩阵与 gamma；这一步同时检验第 7、8 节的解码。
2. 若要实机：先只读确认目标机型、固件与 `hb722_config.bin` 哈希。再在可恢复的方式下替换单个候选，检查取景、成片与回放，最后恢复并核对哈希。

任何实机步骤都需要用户单独明确授权，并先写好恢复方法；本文不授权任何设备操作。

## 证据与复现

离线工具位于 [x2d2/tools](../../tools/README.md)。从仓库根目录运行，输入是自行合法取得并解包的 system 分区：

```sh
python3 x2d2/tools/inspect_color_pipeline.py /path/to/extract/system
python3 x2d2/tools/cube_lut.py export /path/to/extract/system/etc/dispalgo/cm_mp_pb_sdr.json --index 5 --out outputs/stock5.cube
python3 x2d2/tools/cube_lut.py compose /path/to/extract/system/etc/dispalgo/cm_mp_pb_sdr.json --look my_look.cube --out-dir outputs/cm-look
python3 x2d2/tools/rcam_lut.py export /path/to/extract/system --table main_3dlut --index 0 --out outputs/hb-main-0.cube
python3 x2d2/tools/rcam_lut.py bake /path/to/extract/system --look my_look.cube --out-dir outputs/iq-look
```

- 检查器只读文件，向 stdout 输出 JSON；若 `hb722_config.json` 的 SHA-256 与上表一致，会报告 `X2D II 100C 1.3.16.2`。本文的模式、段、槽位、表数与轴长均来自该报告。
- `cube_lut.py` 只写入你指定且不存在的路径。`compose` 用单位 look 合成时与原文件逐字节相同（本次在 `cm_mp_pb_sdr` 上核对，约 2 秒）。生成物属于派生的原厂数据，放在本地 `outputs/`，不提交。
- `rcam_lut.py` 只接受上表哈希的 `hb722_config.bin` / `.json`，在二进制中只替换 LUT 数组，并输出 `bake-manifest.json`（输入 / 输出 / look 哈希与逐表状态）。第 7 节与“B 的离线候选”的数字均来自它。
- 合成测试：`cd x2d2/tools && python3 -m unittest test_color_pipeline_tools.py`（15 项，仅用合成数据，通过）。
- 未收录：固件、解包树、原厂 LUT 及其导出的 `.cube`、`hb722_config.*` 与烘焙产物。

## 限制与下一步

- 全部为静态分析或离线验证，没有实机验证；不同固件版本须重新核对哈希与结论。
- `rcam` 布局由反汇编与逐字节往返证实，但烘焙后的表是否被相机按预期加载与插值，尚无实机证据。未反汇编 `librcam` 中 `userlut` 的参数解析与作用目标。
- 未确认 `MAIN_3DLUT` 与 `MAIN_HNCS` 的硬件顺序，也未确认实时取景实际使用哪个拓扑段（`TPLG_IMX861BQR_LIVEVIEW_12K_11BIT_60FPS` 的 `segment_map` 只列出副通路段）。
- 未确认 `E_ColorProfile_AdobeRGB` 如何实现（IQ 的 `color_gamut` 只有 sRGB/P3）。
- 矩阵系数排列 / 尺度与 gamma 输入尺度未确认，需要 RAW + 机内 JPEG 样张标定。
- 下一项离线工作：用样张标定矩阵与 gamma；之后生成运行时 `iq load` 所需的 JSON 候选，并为 Lightroom 生成可验证的配置文件。
