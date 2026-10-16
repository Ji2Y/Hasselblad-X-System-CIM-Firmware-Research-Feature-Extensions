# X2D II 1.3.16.2：LiDAR 数据链与对焦采用条件

## 适用范围

日期：2026-10-14。对象：X2D II 100C，固件 1.3.16.2。本轮读取已解包的原厂 ELF、配置文本、FlatBuffers 二进制配置与 schema；静态分析，不执行机内程序。没有连接相机、改变配置或部署补丁。

所属机型为 `x2d2`，功能为 LiDAR 辅助对焦。本文放在现有 `research/1.3.16.2/`；复核工具为 [inspect_lidar.py](../../tools/inspect_lidar.py)，本地生成物放 `x2d2/outputs/lidar-inspection-20261014/`。既有 AF-S 分析仍见 [AFS-WITHOUT-LIDAR.md](AFS-WITHOUT-LIDAR.md)。

## 当前结论

以下结论均为**静态分析 / 离线验证**，没有实机验证：

- LiDAR 使用 ADS6401 DTOF 路径。数据经过流过滤器和深度解码库，然后进入 `libaaa.so` 的统计接收、ROI 混合、稳定性判断和对焦结果发布。
- 统计接收有包大小、统计类型、重复标识、点数及环形缓冲索引检查。不能将它概括为一个持续有效的固定距离输入。
- ToF 混合代码存在参考 PDAF 历史峰值的分支；两者的配合不仅发生在最后的 AF-C 控制层。
- AF-S 可以在 PDAF 方向输出通过后继续，无须先通过 ToF；ToF 结果本身还会分档、降档或在特定路径将发布分数置零。
- 原厂 AF-C 配置同时启用 PDAF / ToF，融合设定为 PDAF 主、ToF 辅助及备用。独立 `enable_tof_tracking = 0` 不等于融合关闭。
- 配置文本与所选二进制字段一致。35×35 网格上限、225 点流拓扑和接收端允许的 900 点统计是不同层次的数量，不能等同于实际物理测距点数。

## 证据与复现

### 输入与检查范围

原厂输入未随研究仓库提供。工具锁定以下 ELF、配置及 schema 的 SHA-256，其他输入的大小和哈希写入本地报告：

| 固件内相对路径 | SHA-256 |
| --- | --- |
| `lib64/libaaa.so` | `7d6164eccc734de7087bb778ee72f17a0b3ccf6c0d1f20092c7ebe74a86574ba` |
| `lib64/camera/plugins/stream_filter/libdcam_x2dii_tof_stream_filter.so` | `48b0855a124b507e429895b075aee6f03b6dca845b52aa1eef414ca504328162` |
| `lib64/libadaps_swift_decode.so` | `722984dbfe44ccb154435204b612d1ac5bbd3acbb6644975a0c3ab463836a94c` |
| `etc/aaa/af/af_imx861.json` | `e4f965ed8634c0e14d418d4f57131243d7ea197b8abea2a84d9ee0f934d2ed9e` |
| `etc/aaa/af_imx861.bin` | `3fbf41bd21bbb115c0f5ac5594e22acfc0be46e3ecaf4f168d7111d8a489f9e4` |
| `etc/aaa/af_config.fbs` | `9bff81b307d6d914be733dca96acaa2384b3c0a5f2a7d69a6c513f2994d2ec4a` |

工具依赖 Python 3.9+、`capstone` 和同目录 `inspect_afs.py`，后者复用一代目录的通用 ELF / APS2 读取器；本轮使用二代版本锁定值与地址。检查三个 ELF 的 33 个选定函数（初轮 29 个，模式对照追加 4 个），记录直接调用和完整局部反汇编；复跑既有 AF-S 的 76 条指令、7 个回调与两张结果表检查，并读取 ToF 初始化 / 运行 / 结果三张分派表。直接调用清单不代表已经恢复所有间接调用。

从研究仓库根目录运行，替换输入路径；输出只写本地分析文件：

```sh
python3 -B x2d2/tools/inspect_lidar.py \
  --firmware-root /path/to/x2d2-system-root \
  --output x2d2/outputs/lidar-inspection-20261014
```

输出包括 `lidar-audit.json`、`lidar-disassembly.txt`、`stream-filter-disassembly.txt`、`decode-disassembly.txt` 和带来源行号的 `configuration-excerpts.txt`。JSON 不记录个人输入绝对路径。工具不加载固件库、不执行固件或原厂测试脚本；FlatBuffers 部分只支持本轮选定的表、标量和 uint8 / uint32 向量，正确计入 union 的 type / object 双槽位，不是完整 schema 编译器。

### 1. 数据从哪里进入

`etc/ads6401_hb722.sp` 定义 `x2dii_tof` 流过滤器，`ads6401_hb722.conf` 提供 `TPLG_ADS6401_225DOT_100FPS` 拓扑及普通 / 子帧组合流设置。这是原厂静态配置，不能由名称推导实际 AF 事件的更新率或端到端延迟。

流过滤器 `X2DIITofStreamFilter::onBuffer` 位于该插件 ELF 的 `0x9838`：

| 调用位置 | 接口 | 本轮确认 |
| --- | --- | --- |
| `0x9a0c` | `getConfigFromRcam` | 取得对焦 ROI / 圆形遮罩参数 |
| `0x9a80` | `DepthMapWrapperSetCircleMask` | 向深度包装层设置遮罩 |
| `0x9ba8` | `DepthMapWrapperProcessFrame` | 进入深度处理；返回值影响后续发送路径 |
| `0x9cfc` | `sendDataToRcam` | 发送 ToF 统计与 ROI |

这些地址属于**流插件**，不能与 `libaaa.so` 的地址混用。该插件依赖 `libadaps_swift_decode.so`。后者的 `DepthMapWrapperProcessFrame` 在 `0x2e578`，`0x2e5a8` 调实际 `processFrame`，包含 `DecodeAndComposeDepthXY` / `DecodeAndCompose` 两类调用；选定的 `DecodeAndCompose` 分支调用温度设置、稀疏深度计算与点云输出接口。本轮没有完整恢复 `SwiftDepthCalculator` 内部算法或温度补偿公式。

固件还带 `lib/modules/ads6401.ko`。本轮仅记录其文件哈希及驱动符号层面的存在，未逐条审计驱动的 I/O、寄存器、功率或温度控制实现。

### 2. 对焦库接收的不是单个距离

以下地址均属于锁定版本的 `libaaa.so`。`tof_dtof_ads6401_statistics` 位于 `0x5999d0`：

- `0x5999fc–0x599a0c` 检查输入 `+0x04` 是否为 `0x23cc`；后续 `memcpy` 的包大小也是 `0x23cc`，即 9164 字节。
- `0x599a10–0x599a18` 检查 `+0x10` 是否为 5。schema 的统计类型 5 是 `AF_TOF_STAT_TYPE_DTOF_ADS6401`。
- `0x599a2c–0x599a34` 检查缓冲索引小于 25；`0x599a3c–0x599a58` 比较输入 `+0x14` 与当前记录同位置标识，相同则不复制新记录。
- `0x599a5c–0x599a6c` 允许 `+0x1c` 为 `0xe1` / `0x384`，即 225 / 900。
- `0x599a90–0x599ad4` 更新模 25 的索引、复制统计包并设置更新状态。**25 是该环形存储的容量，不是每次对焦必等 25 帧。**

`tof_dtof_ads6401_run` 在 `0x593ecc / 0x593ed8` 调原始数据列表与 AB 帧处理，在 `0x595a50 / 0x595b98` 调 `_tof_blend` 和 `tof_distance_stable`。包检查与处理路径有直接指令证据；包各字段的全部语义、900 点的生成方式以及所有跨帧对应关系尚未完整恢复。

### 3. 质量门禁与 PDAF 参考分支

`_tof_blend` 位于 `0x589aa0`。配置选择 mesh、深度域混合、前景优先 ROI、平均时间滤波；函数还调用低光、低反差、强点光、无光及移动场景接口。配置的 `iir_weight = 0.1` 不能证明当前选用 IIR，因为 `temporal_filter_type` 实际为 AVG。

一条局部分支有更具体的双向配合证据：

1. `0x58c0dc / 0x58c0e4` 选择算法槽位 1，读取 PDAF 持久峰值；`0x58c10c` 读取其置信分数。
2. `0x58c100` 更新峰值时间滤波，`0x58c13c / 0x58c150` 请求长度 5 的标准差。
3. `0x58c158–0x58c174` 检查分数至少 `0x2ef`（751）、标准差低于当前限值，以及峰值与当前镜头位置差不超过 `0x63`（99）。
4. 通过后 `0x58c184` 用 `get_dist_by_focus_pos` 将 PDAF 峰值转换为距离，随后与 ToF 候选范围比较。

这证明存在“高置信且稳定的 PDAF 结果参与 ToF 候选判断”的软件路径；该路径另有前置门禁，不能说每一帧或每次对焦都会执行，也不能把 751 与混合 AF-S 的峰值分数 80 / 120 当作同一标尺。

`tof_dtof_ads6401_run` 在 `0x5961bc / 0x5968d8` 发布 `object_too_far` / `glass_scene` 标志。名称和调用可确认，具体场景判据尚未完整命名，不能称为已验证的玻璃或遮挡识别。

### 4. 分档与控制采用

`tof_type` 枚举值 4 在初始化表 `0x6cb288` 指向 `0x19da70`，调用 ADS6401 初始化；运行表 `0x6cb2d8` 指向 `0x19ee78`，`0x19ee80` 调 ADS6401 运行入口 `0x590220`。其他 ToF 类型的代码存在不代表本机使用那些分支。

运行入口 `0x598068–0x5980a0` 有结果降档 / 清零条件；`0x5980a4–0x598104` 又依据低光状态及一个浮点量限制结果。浮点量的完整语义尚未命名，不将它直接称为“距离误差”或“遮挡分数”。

结果表 `0x6d223c` 的 0…3 分支为 NG、DIR_OK、OK、SUPER_OK：OK / SUPER_OK 的峰值发布分数为 **80 / 99**。`0x598200` 将发布分数置零；但是 NG 分支 `0x598128` 还存在受另一个条件控制的无穷远候选路径，不能概括为“所有 NG 都立即丢弃全部输出”。`0x59826c` 发布 ToF 峰值，`0x598c98 / 0x598cac` 发布 ToF 信息和物距。

AF-C 在 `0x598228–0x598258` 检查控制配置后，将位置、分数、算法编号 3 与帧标识交给 `afc_ctrl_save_peak_info`。主配置的算法选择 `[1,0,0,1]` 与融合设置已由二进制配置交叉核对：

| 项目 | 二进制值 / 含义 |
| --- | --- |
| `tof.tof_type` | 4，DTOF_ADS6401 |
| `tof.enable_tof_tracking` | 0，独立 ToF tracking 开关 |
| `tof.mesh_max_row / col` | 35 / 35，配置上限 |
| `tof.invalid_distance` | 15000，配置值；本轮未把它认定为保证可用量程 |
| `tof.update_timeout_cnt` | 2，配置值；本轮未恢复它在 ADS6401 的全部消费路径，不能直接换算成失效帧数 |
| `tof.near_distance` | 200，配置值；单位和全部触发路径未完整复核 |
| `tof.stillmode_afs_focus_max_rlt` | 2，即 OK；具体限制路径须结合模式与运行配置 |
| `fusion_enable` | 1 |
| `master_algo_type / slave_algo_type / backup_algo_type` | 0 / 3 / 3，即 PDAF / ToF / ToF |
| `fusion_pos_diff_threshold` | 6.0，文本注明 Fδ 标尺 |

AF-S 的哈苏 start 回调先查询 PDAF 有效性和方向分数，通过可直接返回；ToF 槽位 5 的检查在后。详见既有 [AF-S 门禁证据](AFS-WITHOUT-LIDAR.md#2-不需要先等到-lidar-成功)。

### 5. 距离与镜头位置有关联参数

主配置 `lens_ctrl.distance_to_storke_enable = 1`。镜头条目具有 `tof_params`，包含位置误差界、ROI 圆形遮罩和 `distance_to_storke` 的近端 / 远端位置及多组拟合系数。ADS6401 的 `tof_dtof_ads6401_set_lens_prams_impl` 在 `0x584a20–0x584a34` 将非零系数参数块复制到上下文并标记可用。

这支持距离转镜头行程依赖参数的结论。本轮没有恢复各镜头完整转换公式、所有系数组的 ABI 对应、配置覆盖顺序或实机误差；不能把配置系数直接当成适用于任意镜头的换算公式。

### 6. 模式与算法开关对照（2026-10-14 追加）

AF-S **会参考 ToF，也保留 CDAF**。start 回调允许 PDAF 方向先通过，只证明 ToF 不是该阶段的必要前置条件。未通过时还有其他槽位的检查，ToF 在 `0x1d4fc8–0x1d4ff4`；dir 阶段收集有效且满足评分要求的方向、范围和峰值候选。是否采用某个 ToF 候选还受分数、档位及阶段门禁影响。

追加核对在 start / dir / peak / goto 找到 CDAF 处理调用，分别位于 `0x1d4ee0 / 0x1d53ac / 0x1d79a0 / 0x1da1bc`。所以不能把二代 AF-S 称为纯 PDAF 或纯 PDAF + ToF，也不能反过来说每次成功都执行了完整 CDAF 扫描。

下表为第一代 **4.2.0** 的产品参数与第二代 **1.3.16.2** 的配置对照。第一代通过锁定 ELF 的既有参数审计重新核对，39 条消费指令检查通过；第二代读取 `af_imx861.bin` 的 union 配置表交叉核对文本。

| 算法后端 | 一代总开关 / AF-C 来源资格 | 二代总开关 / AF-C 来源资格 |
| --- | --- | --- |
| CDAF | 开 / 开 | 开 / 开 |
| PDAF | 开 / 开 | 开 / 开 |
| BDAF | 关 / 关 | 关 / 关 |
| VDAF | 关 / 关 | 关 / 关 |
| LDAF | 关 / 关 | 关 / 关 |
| ToF | 关 / 关 | 开 / 开 |

第一代参数与映射依据属于独立版本研究；本次公开迁移不复制其缺失的槽位报告。AF-C 来源资格不是机身当前模式；实际 AF-C 还受总功能资格、机身 AF-C 开关及结果有效性控制。

| 二代模式 / 子功能 | 已确认的原厂开关 | 采用条件与含义 |
| --- | --- | --- |
| AF-S 混合对焦 | CDAF、PDAF、ToF 开 | 哈苏 policy 1 按有效性、分数和阶段仲裁，允许部分阶段由 PDAF 先通过 |
| AF-C 来源处理 | CDAF、PDAF、ToF 开 | `afc.cdaf.enable = 1`、`afc.pd.enable = 1`、`afc.tof.enable = 1` |
| AF-C 位置融合 | PDAF、ToF | 控制名单 `[1,0,0,1]`，PDAF 主、ToF 辅助及备用；名单不含 CDAF |
| MF 辅助 | PDAF 开，ToF / BDAF 关 | `mf_assist_param.enable = 1`；助手掩码仅 PDAF，MF 模式不因此变成自动镜头驱动 |
| AF-S 到峰后的额外精修 | 六类算法掩码全关 | `support_refine_peak = 1` 与有效掩码是两道不同条件，不是默认每次再做 CDAF 精修 |
| 独立 ToF tracking | 关 | `enable_tof_tracking = 0`，与 AF-C 融合开关分开 |

AF-C 的 CDAF 不是被关闭了：`cdaf_scene_get_afc_score`（`0x8b0e0`）读取反差统计 / 指标并处理触发计数，具有场景评分路径。这与 PDAF / ToF 离焦位置融合名单是不同层次，不能用名单没写 CDAF 来推断整个 AF-C 不用 CDAF。

二代 `global.af_feature_cfg` 二进制值为 AF=1、AFC=2、MF=1，其余 DMF / zoom / dzoom / zoom_tracking_af / ir_cut / aft 为 0。schema 将 AFC=2 标为 still + recording 的内部支持资格；它不能证明产品 UI 提供录像功能。类似地，单独的 AFT 通用模块开关不能概括所有主体识别 / ROI 跟踪功能。

`LDAF` 与本机 ADS6401 `ToF` 是两个后端。`afc.laser.enable = 0` 对应另一个激光相关来源，不能据此认定二代 LiDAR 被关闭。BDAF / VDAF 在通用库中有实现，当前两代产品开关仍关闭；第一代的输入、参数与标定限制不在本次二代迁移中复用。BDAF / VDAF 也不能直接等同于主体识别或人脸 ROI。

当前查到的低光等场景配置在上述算法内调整门限、评分和候选，没有发现它们另行打开 BDAF / VDAF / LDAF 的产品开关。具体某次、某镜头、某场景是否覆盖这些配置，仍需运行时证据。

### 7. 评分、门槛与“权重”的区别（2026-10-14 追加）

目前没有在锁定配置中找到按 AF-S / AF-C 指定 CDAF、PDAF、ToF 三路固定百分比的字段。已确认的是分阶段的候选评分、接纳门槛和 AF-C 主 / 辅 / 备用选择。以下数值已经从 `af_imx861.bin` 解码并对照文本；它们不能归一化为三算法的使用占比或准确率。

AF-S 相关标称输出分数：

| 项目 | CDAF | PDAF | ToF |
| --- | --- | --- | --- |
| 峰值分数 | 成功 120、失败 90 | OK 80、SUPER_OK 120 | OK 80、SUPER_OK 99 |
| 方向分数 | 全扫描方向配置 120 | OK 110、SUPER_OK 120 | OK 120、SUPER_OK 130 |
| 峰值范围分数 | 本轮不据其他字段推定 | OK 100、SUPER_OK 120 | OK 100、SUPER_OK 120 |

这些是候选生成端的标称值，输出还可能受质量 / 模式条件调整。混合 policy 的 `find_dir` 配置为方向确认 100、取得峰值门槛 100、取得范围门槛 90；`find_peak` 的确认峰值 / 猜测峰值分数为 100 / 120。start 的 PDAF 先通过路径和 dir 的有效性筛选已核对，所以“方向分数更高”不代表必然覆盖所有阶段，“峰值分数低于某门槛”也不能单独推导整条 ToF 路径从不参与。

AF-C 的控制器门槛是另一接口：

| 来源 | `peak_conf_th` | `peak_super_conf_th` |
| --- | --- | --- |
| PDAF | 400 | 650 |
| ToF | 80 | 95 |

两个来源的置信量和消费者不同，不能据 650 / 95 得出 PDAF 的融合权重约为 87%。位置控制配置只指定 PDAF 为 master、ToF 为 slave / backup；CDAF 的场景评分接口不在这个离焦位置控制名单里，不能因此说它对整个 AF-C 的贡献是 0%。

融合还配置了 `fusion_pos_diff_threshold = 6.0` Fδ、跟踪长度 4、有效计数门槛 2、保留计数门槛 2、标准差门槛 4.0 Fδ。`afc_fusion_ctrl_get_status`（`0x1fc3f0`）按输入状态、历史条件及玻璃场景标志返回不同离散状态，证明控制采用不只是固定系数相乘。本轮没有完整恢复 AF-C 所有状态的目标位置计算公式，因此没有给出亮光 / 暗光 / 遮挡下的动态连续系数表。

MF 助手只有 PDAF 输入开关开启，配置中峰值确认 / 范围确认 / idle 的 PDAF 置信门槛为 800 / 600 / 500；这些也不是百分比。AF-S 到峰后额外精修掩码全零，不能将其写为另一次固定的 CDAF 权重分配。

配置中的 `weight` 还可能属于 CDAF 空间区域、PDAF 网格置信惩罚、ToF 网格混合或时间滤波，例如 `iir_weight = 0.1` 并非 ToF 相对 PDAF 的 10% 权重，且本机时间滤波配置选择 AVG。不能仅凭字段含 weight / blend 就把它当成三后端融合系数。

## 限制与下一步

本轮确认了静态数据链、选定二进制配置和若干实际门禁，没有证明用户某次对焦的选中算法、运行时配置覆盖、遮挡时的准确输出、实际发光 / 更新时序或成像精度。手遮挡可能改变回波和质量，不能仅凭“仍能合焦”断言雷达输出已为零。

进一步静态研究可完整追踪近距 / 超时参数的 ADS6401 消费路径、点云几何与 ROI 对应、镜头转换公式，以及 AF-C 融合选择的全部分支。实机归因需要同场景记录有效性、距离、分数、选中算法、镜头位置与清晰度；本轮没有执行原厂统计抓取脚本或设备操作。

本轮复核通过：三个 ELF 的 33 个选定函数完整反汇编；既有 76 条二代 AF-S 指令审计与 39 条一代参数消费指令检查通过；选定二进制配置字段与文本一致；修改过的二进制配置、schema 及两个新增 ELF 输入均被版本锁定拒绝。Python 语法和本轮 Markdown 本地链接检查通过。生成物仅本地保存，未提交或推送。
