# X2D II 1.3.16.2：IBIS、经纬度与地球自转

## 范围与结论

对象为 X2D II 100C 1.3.16.2 原厂 system 解包文件。本轮只做静态 / 离线分析，没有运行原厂二进制、连接相机、设置坐标或测试防抖效果。

**关系确实存在，且证据分为两个层次：**

- **静态 / 离线验证：经纬度进入 IBIS 控制链。** `camera-service` 收到 `gps_position` 后，调用 `IbisControl::setGpsCompensation`，通过已核对的虚函数表到达 `Ibis::setGpsCompensation`，构造专门的坐标补偿消息并交给 `Ibis::sendMessage`。
- **官方资料：地球自转补偿是该输入的用途。** [哈苏官方 FAQ](https://www.hasselblad.com/x-system/x2d-ii-100c-faq/)在 “HOW DO I MAKE THE MOST OF 10-STOP STABILISATION?” 中说明：连接 Phocus Mobile 时取得当前经纬度，结合定位和罗盘信息补偿地球自转影响；地理信息有效 4 小时，位置显著变化后应更新。

官方网页于 2026-10-15 核查。它说明产品功能和使用建议；本轮没有从 1.3.16.2 的控制器代码恢复出 4 小时定时器、坐标过期后的处理或补偿公式，不能把网页说明写成这些底层细节均已反汇编验证。

## 机内数据路径

下图的手机定位来源由官方说明支持；其余列出的机内函数在指定版本 ELF 中静态核对。机内 `phocus` 的 DBus 代理已找到，但没有获取手机 App 源码或抓取真实网络流量。

```text
Phocus Mobile 提供当前位置（官方说明）
          ↓
机内 phocus：CameraProxyDbus::set_gps_position
          ↓ DBus
camera-service：CameraObjectImpl::doSet_gps_position
          ↓ 读取 latitude / longitude，double 转 float
IbisControl::setGpsCompensation
          ↓ 已核对 Ibis vtable 的 0xe8 槽
Ibis::setGpsCompensation(float, float)
          ↓
IbisSetGpsCompensationMessage
          ↓
Ibis::sendMessage → DUSS 请求 / 传输接口
          ↓
后续 IBIS 控制处理（内部地球自转公式尚未恢复）
```

这条路径明确把经纬度送给 IBIS，证据超过了单独搜索到 GPS 字符串或照片地理标签。

### camera-service 函数证据

| 函数 | ELF 虚拟地址 | 核实的行为 |
| --- | --- | --- |
| `CameraObjectImpl::doSet_gps_position` | `0x1f76c0` | 检查经纬度字段，分别经 `QVariant::toDouble` 读取；在 `0x1f78e8 / 0x1f78ec` 转成 float，`0x1f78f4` 调用 IBIS 控制入口 |
| `IbisControl::setGpsCompensation` | `0x21bd80` | 执行状态检查，经虚表 `0xf8 / 0x100` 查询初始化与链接状态；在 `0x21beb0` 经虚表 `0xe8` 发送经纬度 |
| `Ibis::setGpsCompensation` | `0x2f07d8` | `0x2f0820` 构造坐标补偿消息，`0x2f0834` 调用 `sendMessage` |
| `IbisSetGpsCompensationMessage` 构造函数 | `0x2f5998` | 把操作字节和两个 32 bit 浮点坐标放入消息载荷 |
| `Ibis::getGpsCompensation` | `0x2f08b8` | 构造读取补偿坐标的消息并发送 |
| `IbisGetGpsCompensationMessage` 构造函数 | `0x2f5b08` | 与设置消息配套的读取消息 |
| `IbisResponseParser::parseGpsCompensationResponse` | `0x2f6578` | 检查响应状态，读取两个 float 返回值 |
| `Ibis::sendMessage` | `0x2ef5b0` | 将专用消息包装为 DUSS 请求并交给传输接口 |
| `IbisCtrlMessage` 构造函数 | `0x2f4aa8` | 构造 IBIS 控制消息的公共头和载荷空间 |

`IbisControl` 存在提前返回分支，入口存在不代表每次调用都成功生效。没有实机验证这些状态位和请求结果。

### 关键间接调用已解开

`IbisControl` 调用接口虚函数，因此只看直接 `bl` 列表会漏掉 `Ibis::setGpsCompensation`。本轮核对 `_ZTV4Ibis` 在 `0x8cc630` 的四个 `R_AARCH64_RELATIVE` 重定位：

| 接口虚表偏移 | 重定位槽地址 | 目标 |
| --- | --- | --- |
| `0xe8` | `0x8cc728` | `0x2f07d8`，`Ibis::setGpsCompensation` |
| `0xf0` | `0x8cc730` | `0x2f08b8`，`Ibis::getGpsCompensation` |
| `0xf8` | `0x8cc738` | `0x2f0b38`，`Ibis::isInitialized` |
| `0x100` | `0x8cc740` | `0x2f1380`，`Ibis::isLinkUp` |

虚表对象开头的 16 字节 ABI 头与接口偏移已分开计算。

### 坐标与另外两个二进制

设置消息在 `0x2f5a18..0x2f5a40` 复制 9 字节坐标子载荷：操作字节、latitude float、longitude float；坐标暂存分别是 `0x2f5a1c: stur s9,[sp,#1]` 和 `0x2f5a20: stur s8,[sp,#5]`。该子载荷没有单独的罗盘航向或有效期字段，不能由此确定这些信息在整机里的来源和生命周期。

- `bin/phocus` 中 `CameraProxyDbus::set_gps_position` 位于 `0x17ddf0`，创建 DBus 方法调用并发送参数映射；`doSet_gps_position` 包装函数位于 `0x15bde8`。
- `bin/ibistool` 有对应设置 / 读取补偿坐标的命令类，及明确的 latitude / longitude 说明。只读取其符号与反汇编，没有执行任何工具命令。

没有因为名称含 GPS 就推断存在机内独立 GNSS 接收机。当前明确的产品级位置来源是官方所说的 Phocus Mobile。

## 内置 GPS 与 X1D 热靴配件兼容性

2026-10-15 补充核查：

- **X2D II 100C：**官方公开的位置输入方案是 Phocus Mobile 提供经纬度。本轮在解包 system / vendor 中未找到名称含 GPS / GNSS / NMEA / u-blox 的专用文件；已验证的软件通路是外部坐标注入 IBIS。文件名搜索的阴性结果不能单独证明芯片绝对不存在，本轮也没有拆机或完整原理图；不把软件里的 `GpsCompensation` 类名当作内置 GPS 模块的证据。目前没有核实到官方支持的二代热靴 GPS 配件或兼容入口。
- **X1D 初代外置 GPS：**[原厂用户手册的 GPS MODULE 章节](https://cdn.hasselblad.com/55d73c50-253d-4339-886b-3165ce563e01_x1d_user-guide-book_v1_5-170704.pdf)说明热靴 GPS 自动供电、每秒更新位置并给图像标记坐标；同时明确它仅适用于 X1D，不应接到其他相机，否则可能损坏模块或相机。因此不能因热靴机械尺寸相近就把它直接用于 X2D II。此结论是配件兼容性与原厂限制，不是本轮进行了电气测试。
- **X1D II 50C：**[官方产品页](https://www.hasselblad.com/x-system/x1d/)明确为内置 GPS。这和 X2D II 100C 是不同机型，不能把名称里的 “II” 混为同一套定位硬件。

本轮确认的二代坐标链针对 IBIS。照片地理标签需要另外核查图像元数据写入路径，不能由防抖收到坐标直接推断每张照片都会写入 GPS EXIF。

## 为什么地球自转会影响防抖

以下是物理解释模型，**不是本轮恢复出的哈苏控制器源码公式**。

陀螺仪测量相机相对惯性空间的角速度。相机相对地面静止时，仍随地球一起转动。因此可把读数概念性拆为：

`陀螺仪读数 ≈ 相对地面的机身转动 + 地球自转在机身三轴上的投影 + 零偏 + 噪声`

普通地景和相机共同随地球转动。控制器若把自转分量当作相对地景的手抖并积分，会产生多余的传感器位移。定位与方向信息帮助把已知的背景转动分量分离出来，降低长时间积分中的误差。

手机定位负责地理参考；IMU 负责快速运动测量。GPS 位置数据没有替代陀螺仪的高频测角作用。

地球平均自转角速度约为 `7.292115 × 10⁻⁵ rad/s`，即 `0.004178°/s` 或 `15.041°/h`，来源为 [IERS / 巴黎天文台常数表](https://hpiers.obspm.fr/eop-pc/index.php?index=constants)。

采用北 / 东 / 地向下的当地坐标系，纬度为 φ 时，其一般表达为：

`Ω_local = [Ω cosφ, 0, −Ω sinφ]`

再结合相机姿态转换到机身坐标轴。纬度影响水平与竖直分量，罗盘 / 姿态信息参与确定轴向投影。经度在哈苏内部算法中的具体用途没有恢复，不能自行断言它用于磁偏角模型或其他特定计算。

地球自转分量通常远小于明显的手抖，但长曝光积分和高像素分辨率会提高它的重要性。静止零偏估计、温度补偿和滤波也会影响最终结果，不能仅凭自转角速度直接预测相机误差。

## 数量级示例

[哈苏原始规格表](https://cdn.hasselblad.com/f/77891/x/a5e78b1d54/x2d-ii-100c-datasheet-multi-language.pdf)给出 3.76 μm 像素间距。

仅用于理解数量级，假设：100 mm 实际焦距；自转分量全部投影到一个影响像面平移的转动轴；该分量未经扣除或滤波就被完整积分；小角度近似成立。则多余位移约为 `f Ω t`：

| 时间 | 理想化多余位移 | 按 3.76 μm 换算 |
| --- | --- | --- |
| 1/125 s | 0.058 μm | 0.016 像素 |
| 0.1 s | 0.729 μm | 0.194 像素 |
| 1 s | 7.292 μm | 1.94 像素 |
| 2 s | 14.584 μm | 3.88 像素 |
| 4 s | 29.168 μm | 7.76 像素 |

这是某一分量完全进入控制链时的理想化量级示例，**不是未连接手机时二代的实测拖影**。真实投影可接近零，还受姿态、零偏估计、滤波、控制策略和实际焦距影响；不适用于直接计算所有方向的 roll 边缘位移。

## 实际使用含义与证据边界

- 按官方建议，需要发挥长曝光防抖时，在拍摄前连接 Phocus Mobile 更新经纬度；地理位置显著变化或超过官方说明的有效期后更新。
- 官方也建议使用较长时间后，把相机放到稳定表面静置一段时间。它与零偏估计的常见原理相符，但具体校准过程和时间并未在本轮恢复。
- 没有证据说明缺少新定位会关闭整个 IBIS，也没有恢复坐标过期后的默认位置、静止估计或其他降级策略。
- 不能由本轮得出“GPS 多带来几档”“不连接就固定少几档”或“一切防抖提升都来自地球自转补偿”。实际档数需要按明确测试条件比较。
- 官方 10 档指标有其镜头与 CIPA 测试条件，不等于所有焦距、拍摄方向和手持方式下都能达到同一结果。

## 文件地图、复现与验证

归属：二代 IBIS 固件离线研究。文档复用本版本研究目录，工具为 [inspect_ibis.py](../../tools/inspect_ibis.py)，生成物位于 `x2d2/outputs/ibis-gps-inspection-20261015/`，不默认随仓库交付。

工具依赖 `capstone` 和既有 ELF / APS2 读取器；原厂固件与外部 Python 环境未收录。从仓库根目录运行：

```sh
python3 -B x2d2/tools/inspect_ibis.py \
  --firmware-root /path/to/x2d2-system-root \
  --output x2d2/outputs/ibis-gps-inspection-20261015
```

该命令仅写本地报告与选定函数反汇编，不执行名称中提到的原厂工具。输出 `ibis-gps-audit.json` 和三个 `*-disassembly.txt`。

| 原厂输入 | SHA-256 |
| --- | --- |
| `bin/camera-service` | `51b9e02f8bfebf388be8dfa163c8e512bee19aeb8ae37a6712727ccc6f26a52d` |
| `bin/phocus` | `18277451dd784610ea67561f55db7caf10073e29ae434122172715092e6b77fb` |
| `bin/ibistool` | `12e33a659960db53ec54cd47784e02a750bf96f82b26c0df4df4629c65432450` |

验证通过：3 个输入哈希、15 个函数完整反汇编、GPS setter 直接调用及 4 个虚表重定位。公式示例使用外部物理常数离线计算，和原厂算法恢复分开标注。

尚未完成：控制器内部地球自转扣除和零偏估计实现、罗盘来源、4 小时定时器、失效降级、真实网络与设备调用、性能对比。上述缺项不影响“经纬度确实送入 IBIS”和“官方明确说明用于地球自转补偿”这两个结论。

只写入本地研究文件；没有修改相机、提交或推送。
