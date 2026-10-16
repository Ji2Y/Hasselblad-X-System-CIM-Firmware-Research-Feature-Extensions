# X2D II 1.3.16.2 显示链与低亮度深灰偏绿

## 范围与状态

对象为 X2D II 100C 1.3.16.2 解包文件。本轮用户反馈是“低亮度深灰有不均匀偏绿”；尚未获得同一灰阶、不同亮度、不同观看角度的实测，后屏分析优先，EVF 配置单列。

[哈苏官方产品说明](https://www.hasselblad.com/x-system/x2d-ii-100c/)确认二代后屏为 3.6 英寸 OLED。产品说明的峰值亮度规格不能替代本轮灰阶和面板均匀性测量。

本轮只做静态分析与离线解析：33 个输入文件锁定 SHA-256，完整反汇编 17 个函数，核对 14 组 LUT 的文件长度、位宽、亮度锚点、重复表与灰轴节点。没有连接相机、执行原厂测试程序、修改固件、读取面板 NVM 或做实机补偿。

文件归属：二代显示固件离线研究；文档复用 `x2d2/research/1.3.16.2/`，工具复用 `x2d2/tools/`，生成证据位于 `x2d2/outputs/display-inspection-20261014/`。原厂输入与本机依赖未收录，输出默认仅本地保存。

## 当前结论

1. **静态 / 离线验证：显示软件具备亮度控制和随亮度插值的全局色彩 LUT。** 后屏、EVF、实时取景与回放配置独立。不能把其中一个 LUT 的修改当作所有画面的修正。
2. **离线验证：后屏实时取景 UI 的六个亮度锚点实际只有两张不同的表。** `30 / 180 / 327` 三张逐字节相同，`591 / 800 / 1000` 三张逐字节相同。前一组没有额外的、彼此不同的低亮度 RGB 映射；这并不说明该组没有任何色彩校正。
3. **静态 / 离线验证：本轮解析的 LUT 是 RGB 色彩立方体，不是屏幕位置补偿图。** 它们能调整相同输入颜色的全屏输出，不能对同一灰色在屏幕左边和右边施加不同校正。
4. **推断：用户描述更符合低灰阶色度 / 亮度不均问题，仍需排除观看角度、内容和显示模式因素。** 固件入口已经明确，但不能由静态 LUT 或症状直接确定偏绿的物理原因和所需系数。
5. **尚未证实：整机是否已有其他层级的 deMura。** 所查 `eagle-backend.so` 的 `.rodata` 没有包含 `mura` 的字符串，解析到的配置没有空间坐标图。面板内部补偿、个体出厂数据、内核驱动内部路径和运行时覆盖未核查；不能据此断言整机没有补偿。

## 显示软件中的具体入口

主要 ELF 为 `lib64/weston/eagle-backend.so`。它包含 `EagleVop`、`DispAlgoAutoBacklight`、`DispAlgoColorMgmtInterp`、LUT 格式转换及显示 HAL。

| 函数 | ELF 虚拟地址 | 本轮核实的行为 |
| --- | --- | --- |
| `initDispAlgoVop(EagleVop*)` | `0xa9080` | VOP 0 分支引用 `ab_mp*.json` 和 `cm_mp*.json`；VOP 1 分支引用 EVF 对应配置，并调用 `dispalgo_add_algorithm` |
| `DispAlgoAutoBacklight::calculate` | `0xb5428` | 调用 `dss10_bright_control_algo_sw`，更新亮度结果 |
| `DispAlgoAutoBacklight::update` | `0xb56b0` | 读取模式与 DBV 结果并调用 `setPanelHighBrightness` |
| `DispAlgoHal::setPanelHighBrightness` | `0xb2380` | 获取面板信息并调用 `duss_hal_display_panel_set_high_brightness` |
| `DispAlgoColorMgmtInterp::initParams` | `0xbbee8` | 读取 JSON 的监控开关、参数列表、LUT 类型 / 位宽 / 边长 / 通道数和文件路径；注册状态订阅 |
| `DispAlgoColorMgmtInterp::parseLutFile` | `0xbc468` | 核对文件大小，逐表读取并建立 LUT 对象 |
| `DispAlgoColorMgmtInterp::getLutsForInterp` | `0xbcd90` | 根据目标参数和 LUT factor 选择表，包含单表与范围外分支 |
| `DispAlgoColorMgmtInterp::workingLoop` | `0xbd000` | 获取状态，选择 LUT，调用线性插值与格式转换，输出共享内存或 `setRcamTdLut` |
| `DispAlgoLutProcessor::interpolateLinear` | `0xc3d20` | 计算两表 factor 间的比例，遍历立方体三个索引逐节点混合 RGB |
| `DispAlgoLutProcessor::calculateLutBytes(LutType)` | `0xc37d8` | 返回 `cubeWidth³ × channels × byteDepth` |
| `DispAlgoLut::getF` | `0xc3848` | 根据立方体的三个颜色索引与格式计算存储位置，读取三个输出通道 |
| `DispAlgoHal::setRcamTdLut` | `0xb28b8` | 调用 `duss_hal_display_plane_tdlut_set` |
| `EagleVopPlane::set3dLut` | `0x9cdd0` | 独立显示平面的 LUT 设置入口 |

这些是静态可达路径。没有运行时追踪，不能声称某一实际画面已经执行了所有分支，也没有把 `setPanelHighBrightness` 的参数解释为已知的 PWM / DC 调光机制。

## 模式配置与表数量

文件在 `etc/dispalgo/`。命名中的 `mp` 与后屏 VOP 0 配置分支对应，`evf` 与 VOP 1 对应；`lv` 为实时取景配置，`pb` 为回放配置。

后屏多表锚点 A：`[30, 180, 327, 591, 800, 1000]`。

EVF 多表锚点 B：`[30, 180, 327, 591, 800]`。

所有色彩 JSON 的 `monitor_backlight=true`、`param_name="sdr_ref_white"`。锚点是内部参数，**不是菜单百分比，也不是本轮测量出的 nit**。`lut_bit_depth` 表示 LUT 码值位宽，不能直接当作物理屏幕原生位深。

| 用途 | 后屏配置 | 后屏表 | EVF 表 | 格式 / 存储码值 |
| --- | --- | --- | --- | --- |
| 取景 UI | `cm_mp_lv_ui.json` | 6，A | 1，`[100]` | `cube_r`，16³，10 bit |
| 取景 SDR / fast preview | `cm_mp_lv_sdr_fastpre.json` | 1，`[100]` | 1，`[100]` | `rcam`，16³，12 bit |
| 回放 UI | `cm_mp_pb_ui.json` | 6，A | 5，B | `cube_r`，16³，10 bit |
| 回放 fast preview | `cm_mp_pb_fastpre.json` | 6，A | 5，B | `cube_r`，16³，10 bit |
| 回放 SDR | `cm_mp_pb_sdr.json` | 6，A | 5，B | `cube_r`，28³，10 bit |
| 回放 HDR | `cm_mp_pb_hdr.json` | 6，A | 5，B | `cube_r`，28³，10 bit |
| 回放 HDR thumbnail | `cm_mp_pb_hdr_thumb.json` | 6，A | 5，B | `cube_r`，28³，10 bit |

EVF 文件名把相同后缀的 `mp` 换成 `evf`。所有 JSON 对应 `.bin` 长度均与上述立方体尺寸、通道数、2 字节存储和表数量完全匹配。

亮度配置是 `ab_mp.json` / `ab_mp_pb.json` 与 `ab_evf.json` / `ab_evf_pb.json`：

- `bright_control_en=1`；取景配置 `hdr_display_en=0`，回放配置为 1。
- 后屏手动亮度映射的输入范围为 `0..100`，输出参数为 `30..1000`；EVF 输出参数为 `30..800`。
- 后屏 DBV 映射有 4096 点，输出 `0..4095`；EVF 输出 `0..2047`。这是软件控制范围，不等于实际使用全部档位，也不能仅凭这些数值判断调光频率。
- 后屏环境光映射在暗环境的初始输出为 180，而手动映射最低输出为 30。因此用户的“低亮度”应区分手动档位与自动亮度状态；两者不必处于同一面板工作点。
- `panel_mode_split_value=800` 为算法配置值，其与面板寄存器、物理调光和具体色度变化之间的关系仍需实测。

## 低灰节点揭示什么

后屏回放 SDR 表 `cm_mp_pb_sdr.bin`，30 锚点的灰轴节点：

| 立方体索引 `(r,g,b)` | 原始输出 RGB 码值 |
| --- | --- |
| `(0,0,0)` | `(0,0,0)` |
| `(1,1,1)` | `(12,13,12)` |
| `(2,2,2)` | `(24,26,24)` |
| `(3,3,3)` | `(36,39,36)` |

可见表本身已允许灰轴通道不相等。但这些是送往后续显示链的数字码值，**不能因为 G 数值较高就认定它是屏幕偏绿的原因**：面板的 R/G/B 发光响应可能不同，这也可能是原厂校正的一部分。28³ 表的输入节点物理间距没有恢复，本轮不把索引 1 擅自解释成某一百分比灰阶。

后屏实时取景 UI：

- 30 / 180 / 327 锚点各表 SHA-256 完全相同；第一非黑灰轴节点均为 `(67,67,68)`。
- 591 / 800 / 1000 锚点各表 SHA-256 完全相同；第一非黑灰轴节点均为 `(53,53,54)`。

因此，可以研究为低亮度 UI 引入更细的独立色彩标定，但目前不存在由这些数字直接推出的可靠“绿色减少百分之几”。

## 为什么全局 LUT 无法单独消除局部绿斑

现有已解析路径可概括为：

`RGB_out = LUT_mode,brightness(RGB_in)`

相同输入灰色在不同位置得到同一输出码值。若左侧绿色子像素响应较强、右侧正常，全局降低 G 会同时影响两侧，容易使正常区域偏品红。更复杂的 RGB 色彩立方体也没有屏幕 `(x,y)`，仍不能独立识别这两个位置。

针对局部不均，需要类似：

`RGB_out = F_panel(x, y, RGB_in, brightness[, temperature])`

这是方案表达，不是已恢复的二代接口。应基于当前这块面板测量，按位置、通道、灰阶和亮度工作点建立修正；黑节点保留为零，灰阶之间连续过渡。不能给所有相机套一张凭目测制作的固定“减绿图”。

显示计量厂商 [TechnoTeam 的 deMura 说明](https://www.technoteamvision.com/products/display_metrology/lmk_demura/index_eng.html)将测量值配准到实际像素，并按灰阶和颜色通道获取数据。SID 论文 [A Low Grayscale Uniformity Improvement Scheme for OLED Based on Auto Demura](https://sid.org/Portals/sid/Files/SID-Digest/docs/P-237.pdf)讨论像素驱动差异、逐面板 offset 与灰阶相关补偿。这些支持上述工程原则，不能用来证明这台相机的具体缺陷来源或预估改善幅度。

## 可行修正路线与取舍

| 路线 | 能改善的范围 | 本轮状态与限制 |
| --- | --- | --- |
| 避开最差低亮度档位 | 若不均随面板工作点减弱，可立即降低可见程度 | 原厂已有亮度入口；需比较同一灰图不同档位。只是不均可见度的缓解 |
| 低亮度专用全局 LUT | 整体低灰偏绿、随亮度发生的整屏色度变化 | 已找到多表与插值入口；需要实测 RGB 响应并同时考虑取景 UI、预览、回放各表。局部残差仍存在 |
| 更高面板工作亮度 + 内容数字压暗 | 面板驱动工作点改变后，若低灰均匀性更好，可能缓解 | 属于待验证假设。降低内容码值也可能再次落入低灰差区；不能保证有效。会改变色调曲线、有效灰阶和 HDR 余量，须联动校正 |
| 按面板位置补偿 | 固定位置的绿斑、条带和亮暗块 | 本轮未找到可直接填入空间地图的接口。需恢复已有面板补偿接口，或在覆盖最终显示各平面的处理阶段增加位置相关运算 |

空间补偿若只加到 QML UI，会漏掉独立预览 / 照片平面；若固定在图像内容坐标，缩放和平移照片会让校正错位。它必须随屏幕位置固定，并正确处理颜色空间、图层、透明度、旋转与显示输出。这里的补偿应限定在显示链，不能改变保存照片的像素。

最低限度的判别流程：

1. 保持正视、同一内容、同一显示模式和稳定环境光，关闭自动亮度的变化干扰。
2. 比较一组近黑到中灰的全屏中性图，例如 8 bit 测试源的 `8 / 16 / 24 / 32 / 48 / 64`；这些是测试源码值，不是经过显示 LUT 后的输出码值。
3. 在最低、较低和中等亮度分别观察 / 测量；记录不均是否固定在屏幕位置、是否随角度变化，以及取景 UI 和照片回放是否一致。
4. 均匀偏绿优先量测全局灰轴并标定 LUT；固定局部残差则需要位置相关补偿。正式校准用有校正能力的成像色度测量；普通相机的镜头渐晕、摩尔纹、曝光、白平衡和传感器噪声不能当成面板修正图。

本轮没有生成可刷入的补偿表：缺少个体面板测量和完整驱动 / 空间补偿入口，任何具体 RGB 增益、DBV 下限或寄存器数值都还没有有效依据。已经完成的是入口定位、格式核对和方案边界判断。

## 复现与证据

离线工具：[inspect_display.py](../../tools/inspect_display.py)。它复用已审核的 ELF / APS2 读取器及反汇编函数，依赖 `capstone`；不执行固件动态库或测试脚本。

从仓库根目录运行，预先准备匹配版本的解包 `system` 目录与 Python 依赖：

```sh
python3 -B x2d2/tools/inspect_display.py \
  --firmware-root /path/to/x2d2-system-root \
  --output x2d2/outputs/display-inspection-20261014
```

产物：`display-audit.json` 与 `display-disassembly.txt`；不复制原厂 LUT 二进制。输入哈希全部列在工具中，重点输入：

| 相对输入路径 | SHA-256 |
| --- | --- |
| `lib64/weston/eagle-backend.so` | `7d393c1b0cfecca355b7ca07d357003c25e16fecf8e111a1e03b311c07ab72ab` |
| `etc/dispalgo/ab_mp.json` | `a8a75ba7f876ac44d7573cdaa5da8a39aadccacc463027b6b00b48624147f2e1` |
| `etc/dispalgo/cm_mp_lv_ui.bin` | `564b7634e6f8dc512a037e7574ae6b1bd60eaa007ee531bded999ba19314b5ad` |
| `etc/dispalgo/cm_mp_pb_sdr.bin` | `197817efae19968d67e8b875cd4a78aafbd28bd59b55d988bb3c8d2f01268a94` |

另外只读检查过 `libdisplay-server.so`、`libduml_hal.so`、显示插件、测试程序字符串和面板测试脚本。原厂面板测试脚本包含服务停止、面板开关及寄存器写入，未执行；脚本中的初始化数值没有作为 mura 修正方案。

## 验证结果与未解决项

- 离线检查通过：33 个输入哈希、18 份 JSON、14 组 LUT 长度 / 锚点 / 位宽、12 组 `cube_r` 灰轴解码、17 个函数完整反汇编。
- 后屏取景 UI 的重复表分组为 `[[30,180,327],[591,800,1000]]`，逐字节确认。
- 后屏和 EVF、单表和多表、RGB 立方体与屏幕空间图已分开记录。
- 未解决：实际模式和亮度档位、面板型号和驱动工作机制、个体工厂补偿数据、空间补偿接口、灰阶实测和改善幅度。
- 本地研究文件已写入；无相机操作、提交或推送。
