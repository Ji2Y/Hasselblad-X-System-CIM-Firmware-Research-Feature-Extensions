# X2D II 1.3.16.2：产品变体与开机画面资源

## 适用范围

日期：2026-10-14。对象：X2D II 100C 原厂 1.3.16.2 的 system / vendor 解包树及 `exMCU_hb722.cont`。本轮只读本地固件，解析元数据和图片，未连接相机、读取设备身份或修改固件。

所属机型为 `x2d2`，功能为启动画面与产品配置。本文复用 `research/1.3.16.2/`；工具为 [inspect_startup_variants.py](../../tools/inspect_startup_variants.py)，生成物放 `x2d2/outputs/startup-variants-20261014/`。一代启动研究另见 [X2D 主屏 Logo 定位](../../../x2d/research/4.2.0/STARTUP-LOGO-LOCATION.md)，不把一代地址或变体选择规则用于二代。

## 当前结论

以下均为**静态分析 / 离线验证**：

- 本包二代产品家族标识为 `X2DM2`（ProductID 6）。在已查产品配置、GUI 资源和显示后端中，未找到一代 `Identity/SuVariant` / `su_variant` 所对应的普通 / 大地 / 特殊版选择结构；因此没有证据将本包称为多款二代商业特殊版合集。
- 共享 `Version::HardwareID` 枚举包含 **6 个 X2DM2 标识**：1 个正式标识加 5 个 Prototype / P0 / P1 / P15 / P16 标识。它们属于硬件版本／研发阶段标签，不能计为 6 款零售特殊版。
- vendor 中确认有 **1 张独立 Logo 位图**，`logo.bin` 解码为 1024×768 的黑底白色 H；GUI 另有 1 个哈苏 Logo SVG 图标。二者不是两套特殊版开机画面。
- 未在已解析资源中发现二代大地版、登月版或其他专属品牌开机图。本轮未完整解密早期启动载荷，也未逐个恢复所有 MCU 无名称图片，所以“确认 1 张 Logo”不等于证明所有屏幕、所有启动阶段只有这一张画面。

## 证据与复现

### 1. 六个硬件标识

读取 `camera-system` 的 Qt 6 元数据：`qt_meta_data_ZN7VersionE` 位于 ELF VA `0x457870`，字符串表位于 `0x457ad8`。表内 ProductID 中 `X2DM2 = 6`，HardwareID 中本机型条目为：

| 枚举名 | 数值 | 可确认含义 |
| --- | --- | --- |
| `Hardware_X2DM2` | `0x00000040` | 二代正式硬件标识 |
| `Hardware_X2DM2_Prototype` | `0x80000040` | Prototype 标识 |
| `Hardware_X2DM2_P0` | `0x40000040` | P0 标识 |
| `Hardware_X2DM2_P1` | `0x20000040` | P1 标识 |
| `Hardware_X2DM2_P15` | `0x10000040` | P15 标识 |
| `Hardware_X2DM2_P16` | `0x08000040` | P16 标识 |

这里只恢复了枚举标签和值，没有证明 6 个硬件都曾量产或正在使用。同一表还包含第一代、CFV 等共享产品标识；例如 `Hardware_CFV_Moon` 属于 CFV 标签，不能算二代登月版。

### 2. 与一代的产品变体字段不同

在锁定的 `camera-system`、`prodconfig-tool`、`camera-gui`、`eagle-backend.so` 中检查 ASCII / UTF-16LE / UTF-16BE 的 `Identity/SuVariant` 和 `su_variant`，均未命中。system / vendor 解包树补充扫描这些 ASCII 字面量也未命中。字面量缺失不是对所有隐式、压缩或私有表示的排除证明。

二代产品配置存在 `Identity/SuModel` 与 `Identity/ShellColor`。在 `prodconfig-tool` 的 `ProdInfo::readAll`（`0x1cdb0`）中：

- `Identity/SuModel` 字符串 VA `0x38384`；`0x1cf64` 构造读取键，`0x1cf88` 把转换结果作为单字节存入对象 `+0x28`。
- `Identity/ShellColor` 字符串 VA `0x385dc`；`0x1e2a0` 构造读取键，`0x1e2c4` 把转换结果作为单字节存入对象 `+0x57`。

ShellColor 的存在不能用来推断有多少可购买颜色，也不能证明它会选择不同开机图；本轮未建立允许值枚举与品牌资源的对应关系。

一代已经确认的 `su_variant == 2` 选择大地图、其他值显示 H 的分支，只适用于一代锁定固件，不适用于本包二代。

### 3. 独立 Logo 位图

文件为 vendor 根目录 `logo.bin`，大小 1,179,701 字节，SHA-256：

```text
03fe95b65e39db203061b8f9d367a6f184d8c71bd9f5c7dd67b27ce0b1105576
```

头部为：

```text
width:1024 height:768 offset-x:0 offset-y:0 format:2;
```

头部后载荷为 1,179,648 字节，等于 `1024 × 768 × 3 / 2`。前 786,432 字节的亮度范围为 16…235，剩余色度字节全部为 128。因色度中性，无需假定具体 UV 交错顺序即可恢复灰度内容；预览把亮度映射到 0…255，保持原始几何。

![二代 vendor Logo 解码预览](../../outputs/startup-variants-20261014/logo-luma-preview.png)

内容为黑底白色哈苏 H。本轮没有在已查 system / vendor 用户态文件中找到 `logo.bin` 字面引用，完整的早期加载者与显示阶段未恢复；因此本文确认的是原厂 Logo 资产和像素内容，不把文件存在直接写成已验证的实机冷启动显示链。

### 4. GUI 与肩屏资源核查

`camera-gui` 的嵌入 Qt RCC 资源已全部解析：**1,112 项**，其中常见 PNG / JPEG / BMP / SVG / WebP 后缀图像资源 **470 项**。启动／品牌相关名称只命中 `/icons/ic_logo_hasselblad.svg`；未发现 earth / explorer / moon / startup / splash 等专属画面名称。SVG 是 GUI 图标资源，不能仅因名称有 Logo 就算另一张冷启动背景。

`exMCU_hb722.cont` 中发现 55 个 `qrc:/` 图形资源路径，主要为肩屏曝光、白平衡、驱动模式、电池等图标，没有命中上述启动／特殊版名称。未恢复 MCU 所有无名称纹理，所以不宣称肩屏绝无其他初始化画面。

### 5. 复核工具

从研究仓库根目录运行，替换原厂输入路径：

```sh
python3 -B x2d2/tools/inspect_startup_variants.py \
  --system-root /path/to/x2d2-system-root \
  --vendor-root /path/to/x2d2-vendor-root \
  --mcu /path/to/exMCU_hb722.cont \
  --output x2d2/outputs/startup-variants-20261014
```

依赖 Python、`pyelftools` 和一代目录的通用 [Qt RCC 读取器](../../../x2d/tools/firmware-analysis/qt_rcc_resources.py)，但全部固定地址与输入校验值来自本包二代。工具只写 JSON / PNG 分析产物，不运行原厂程序，不写身份或设备字段。输入原厂文件未随研究仓库提供。

固定输入 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `camera-system` | `a7554605d7d9bcde6e87a050522a4f154eaa056bbe4abc4545a8df9cd1022039` |
| `prodconfig-tool` | `c2b6e86122cc6286dd998b46638b3063bea30d8c85ede83182cd4cd072a217a0` |
| `camera-gui` | `b1b643cb36176cd5a49129dd9bb2be480aa045a96ed1c35c30a779ab5af0801b` |
| `eagle-backend.so` | `7d393c1b0cfecca355b7ca07d357003c25e16fecf8e111a1e03b311c07ab72ab` |
| `exMCU_hb722.cont` | `3e23ad78b1b5cef9321f8f02aac272e740164b7f49bd1d4c7f5b37e1978db1af` |

## 限制与状态

结论限定本包 1.3.16.2，不代表后续固件、另发特殊版包或所有硬件版本。`bootarea.img` / `normal.img` 的早期启动载荷和所有无名称 MCU 图片未完整解码；没有实机启动观察，也没有修改、提交或推送。
