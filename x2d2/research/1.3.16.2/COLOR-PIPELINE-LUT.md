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

机内有三层互相独立的 LUT：ISP 调色 LUT（决定 JPEG/HEIF 的颜色）、ISP 输出端按用途选择的 LUT（预留了 `user` 槽，但静态照片主帧明确旁路）、显示端色彩管理 LUT（只影响屏幕观看）。导入自定义 `.cube` 只改变屏幕观看效果，这一层最可行：格式已离线解码，并有可复现的合成工具。要把 LUT 烘焙进 JPEG/HEIF，就必须改动 ISP 调色表或拍摄拓扑，风险最高，目前只有静态证据。RAW 不受任何机内 LUT 影响。

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

每张 ISP LUT 为 6144 个 32 位字。它与 `cm_*_lv_sdr_fastpre.json` 所称的 `rcam` 格式（16³×3×16 位 = 24576 字节）字节数一致，但字内排列未解码（相邻值并非按 R 优先的 RGB 三元组）。本文不声称已知 ISP LUT 的节点布局。

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

## 自定义 LUT 拍摄可行性评估

| 方案 | 影响什么 | 依据 | 主要障碍 | 评级 |
| --- | --- | --- | --- | --- |
| A. 回放 / 复看时套用 LUT | 屏幕观看，不改文件 | `cube_r` 已解码；`compose` 工具离线生成 `显示表(look(x))` | 需要替换 `/etc/dispalgo` 文件或在运行时调用合成器 `set_3dlut`，两者都需要系统写入或 shell；回放图像送入合成器时的编码（sRGB/P3、SDR/HDR）未确认；HDR 表另成一套 | 最可行；格式离线验证，未实机 |
| B. 取景时套用 LUT（监看） | 屏幕观看，不改文件 | `iq userlut`、`_update_disp_userlut`、`LCDC_3DLUT*`、合成器 plane 3D LUT | ISP `rcam` 布局未解码；调试入口需要 shell；必须保留面板映射，可用 `disp_3dlut_combine` 或离线合成 | 有入口，未验证 |
| C. LUT 烘焙进 JPEG/HEIF | 输出文件 | `MAIN_3DLUT` 在所有照片段启用 | 8 张表（4 色温 × sRGB/P3）均需与原厂调色合成，且输入是 ISP 内部 gamma 后 RGB，不是标准 Rec.709；需要修改 IQ 表（`hb722_config.bin`）或用 `iq load/reload`；`user` 槽在主帧段被旁路，改拓扑会影响 HDR 增益图与缩略图一致性 | 风险最高，仅静态证据 |
| D. RAW（3FR/FFF/DNG） | 无 | RAW 写入段不含 3DLUT | 机内 LUT 不进入 RAW；只能在后期或随 RAW+JPEG 的 JPEG 中体现 | 不适用 |

建议次序：先做 A 的离线到实机验证（只读确认回放图像编码 → 单张表替换 → 恢复），再考虑 B；C 至少要先解码 `rcam` 布局并建立“原厂 LUT 不变 → 输出不变”的回归检查之后才值得尝试。任何实机步骤都需要用户单独明确授权，并先写好恢复方法；本文不授权任何设备操作。

## 证据与复现

离线工具位于 [x2d2/tools](../../tools/README.md)。从仓库根目录运行，输入是自行合法取得并解包的 system 分区：

```sh
python3 x2d2/tools/inspect_color_pipeline.py /path/to/extract/system
python3 x2d2/tools/cube_lut.py export /path/to/extract/system/etc/dispalgo/cm_mp_pb_sdr.json --index 5 --out outputs/stock5.cube
python3 x2d2/tools/cube_lut.py compose /path/to/extract/system/etc/dispalgo/cm_mp_pb_sdr.json --look my_look.cube --out-dir outputs/cm-look
```

- 检查器只读文件，向 stdout 输出 JSON；若 `hb722_config.json` 的 SHA-256 与上表一致，会报告 `X2D II 100C 1.3.16.2`。本文的模式、段、槽位、表数与轴长均来自该报告。
- `cube_lut.py` 只写入你指定且不存在的路径。`compose` 用单位 look 合成时与原文件逐字节相同（本次在 `cm_mp_pb_sdr` 上核对，约 2 秒）。生成物属于派生的原厂数据，放在本地 `outputs/`，不提交。
- 合成测试：`cd x2d2/tools && python3 -m unittest test_color_pipeline_tools.py`（11 项，仅用合成数据，通过）。
- 未收录：固件、解包树、原厂 LUT 及其导出的 `.cube`、`hb722_config.*`。

## 限制与下一步

- 全部为静态分析或离线验证，没有实机验证；不同固件版本须重新核对哈希与结论。
- 未解码 ISP `rcam` LUT 的字内布局，也未反汇编 `librcam` 中 `userlut` 的参数解析与作用目标。
- 未确认 `MAIN_3DLUT` 与 `MAIN_HNCS` 的硬件顺序，也未确认实时取景实际使用哪个拓扑段（`TPLG_IMX861BQR_LIVEVIEW_12K_11BIT_60FPS` 的 `segment_map` 只列出副通路段）。
- 未确认 `E_ColorProfile_AdobeRGB` 如何实现（IQ 的 `color_gamut` 只有 sRGB/P3）。
- 下一项离线工作：反汇编 `disp_hal_3dlut_plt_fmt_*` 以解码平台格式；离线比较 `MAIN_3DLUT` 与 `LCDC_3DLUT` 的同色温表，判断取景与成片是否共用同一调色。
