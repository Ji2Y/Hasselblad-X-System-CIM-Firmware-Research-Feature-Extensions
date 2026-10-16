# 第一代 X2D PDAF 实验记录方法

本页记录 4.2.0 原厂 AF-S/PDAF 只读观察流程。设备脚本仅支持第一代 X2D 100C、固件 4.2.0、55V 镜头及 AF-S；不兼容时会在读取前停止。它们不触发对焦、不写参数或 AF 内存、不替换系统文件，也不接受任意远程 shell 命令。限时日志采集会在设备 `/tmp` 创建私有目录和日志文件，最长 30 秒；可用 `cleanup` 删除本实验创建的文件。

## 固定记录项目

每次实验先建立新的本地记录编号。保留以下实验条件和观察结果：

| 字段 | 记录内容 |
| --- | --- |
| 机型与固件 | 第一代 X2D 100C、4.2.0 |
| 镜头与对焦模式 | 55V、AF-S；由脚本预检 |
| 场景 | 纹理特征、近/远类别、相机和目标是否固定；不要记拍摄地点或人物身份 |
| 操作 | 半按开始/结束的相对时间、重复次数；不要完全按下快门 |
| 日志 | 文件导出是否完整、事件数量、是否有首尾状态、是否出现丢帧迹象 |
| 结果 | 原厂状态机结果、观测到的 `cur_pos`、`peak`、`target_pos`、`conf`；保留它们是未标定日志量的说明 |
| 验证等级 | 原厂实机只读观察、离线分析或合成测试，分开记录 |

不要记录或发布相机序列号、进程号、boot ID、绝对设备时间、随机临时目录、电脑用户名/绝对路径、USB 序列标识、照片或 RAW。仓库中的历史时间均以本次采集开始为 `t0`，原始日志没有公开。

## 30 秒原厂日志观察

需要 Python 3.9+、PyUSB 和系统可用的 libusb。USB 接口必须只连接一台受支持的相机；不需 ADB、相机驱动替换或系统配置更改。先从自己的授权固件副本确认版本，再在相机菜单中选择 AF-S，并安装 55V 镜头。

```sh
cd x2d/CodeTests/pdaf-only-shadow
python3 -m pip install pyusb
python3 -B capture_stock_pdaf.py start
```

启动输出给出短期 `capture_id`。收到 `stock_verified: true` 后，立即对准有清晰纹理的静止目标半按快门约 20 秒；近、远目标实验分开记录，期间不要完全按下快门。记录器会在 30 秒后自动停止，不需要用脚本触发 AF。

确认自动停止后导出：

```sh
python3 -B capture_stock_pdaf.py read --capture-id <本次ID> --output /tmp/pdaf-stock-observation.json
python3 -B capture_stock_pdaf.py cleanup --capture-id <本次ID>
```

导出器检查记录器已停止、文件未轮转、行数在上限内，且分页读取前后的行数和 SHA-256 一致。输出 JSON 已将日志时间改成相对秒数，并剔除 PID、临时路径和设备身份；`complete_file_export` 只说明日志文件完整，`sensor_frame_coverage` 仍为 `unknown`。若相机断开或脚本中止，记录器仍有 30 秒上限；连接恢复后使用原 `capture_id` 清理。

若只需尝试读取现存环形日志，可在半按前运行 `device_readonly_probe.py mark`，保存本机打印的时间标记；结束后运行：

```sh
python3 -B device_readonly_probe.py read --since <本机时间标记> --kind all --output /tmp/pdaf-ring-observation.json
```

这种方式只读最近的 24 条匹配日志，环形缓冲可能已覆盖所需事件；日志缺失不等于相机没有运行 PDAF。

## 相位状态表只读快照

此脚本读取已验证的状态表和采样描述，不抓取全帧，也不执行新的 425 区域计算。需要操作者自行提供与脚本固定 SHA-256 匹配的一代 `libaaa.so`：

```sh
python3 -B read_pdaf425_state.py \
  --library /path/to/authorized-x2d-4.2.0/libaaa.so \
  --samples 8 \
  --output /tmp/pdaf-state-observation.json
```

先在相机上保持 AF-S，并在取景器中对准纹理。脚本会做最多 8 次只读快照，相邻读取间隔 0.5 秒，复核原厂相位函数、采样描述、相机进程身份和 AF-S 状态。输出不含 PID、进程地址、boot ID 或输入路径；`atomic_snapshot: false` 表示顺序读取不代表曝光级同步。输出仍只是局部状态和取样几何，不是完整相位帧、425 个有效区域、实际合焦率或性能测试。

## 日志清理与离线回放

限时记录器的 `read` 输出已自动脱敏。对其他本地旧日志，先将原件留在私有目录，再生成独立的脱敏副本：

```sh
python3 -B sanitize_pdaf_records.py \
  --input /path/to/private/stock.log \
  --output /tmp/stock-sanitized.log
```

脱敏器将设备 epoch 时间改为相对时间，并处理 PID、boot ID、设备序列号、MAC/IP、常见用户路径和临时目录标识。分享前仍要人工检查输出中是否有照片信息、未标记的个人资料或无关日志。不要把原始文件复制进仓库。

用脱敏日志进行离线轨迹检查：

```sh
python3 -B replay_afs.py inspect \
  --input /tmp/pdaf-stock-observation.json \
  --output /tmp/stock-inspection.json
```

`replay_afs.py` accepts the sanitized JSON emitted by `capture_stock_pdaf.py read` or a plain sanitized log produced by `sanitize_pdaf_records.py`.

需要比较滤波器时，必须另行提供显式配置；配置是离线试验参数，不是相机标定值。回放输出使用相对秒数，所有结果保持 `control_allowed: false`，不会形成镜头命令。

## 证据边界与隐私

历史 2026-09-25 记录是两次原厂 AF-S 成功样本，不能推导阈值、普适耗时或新算法效果。2026-10-08 状态表观察只确认当时原厂上下文引用的 972 × 42 取样组及约 90 × 3 的局部窗口；没有获得全画面同帧缓存。测试脚本和本页描述的是观测方法，不会把候选改成可安装升级。

提交前运行仓库发布检查。只发布人工审核后的相对时间摘要、统计值、离线源码和脱敏样例；固件、原厂库、完整设备日志、完整帧、代码签名及任何带身份字段的输出继续留在本地。
