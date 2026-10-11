# Yunmu BLE Meter for Home Assistant (experimental)

[简体中文](#简体中文) · [English](#english)

## 简体中文

一个**非官方、实验性、只读**的 Home Assistant 自定义集成，通过 BLE GATT 本地读取已实测的云木预付费电表（YM-M4-BE）。不需要云木账号、云端服务器或远端 API。

> ⚠️ **不是官方产品，也未经过长期稳定性及电表厂商安全认证。** 目前仅在单台设备上验证了本地报文，Home Assistant / ESPHome Bluetooth Proxy 的实际链路尚待真机验收。对其他云木型号、固件版本不作兼容承诺。

### 已有功能

- 原生 HA 配置流程，支持通过 `YUNM*` 广播自动发现或手动输入蓝牙 MAC 地址。
- 剩余电量 `kWh`、累计用电量 `kWh`、上次成功抄表时间三个传感器，以及设备页面中的 **立即抄表** 按钮（手动读取至少间隔 5 秒）；累计电量采用 `total_increasing`，便于能源统计。
- 通过 HA Bluetooth Manager 解析连接路径，可尝试走具有**主动连接功能**的 ESPHome Bluetooth Proxy。
- 一次连接只发送一个已验证的读取命令；每次结束主动断开。
- 轮换已在实测中成功的 `txMsgId=0/1`，即使超时也继续切换下一个编号，避免无限重复同一请求。
- 默认每 **10 分钟**自动抄表一次，可设 5～120 分钟。可在设备页面的 **配置 → 自动抄表间隔** 直接修改，或在 **设置 → 设备与服务 → Yunmu BLE Meter → 配置** 中修改，保存后自动重载生效。点击设备中的 **立即抄表** 可手动读取一次；抄表进行中或 5 秒内重复点击会拒绝执行。读取失败不会触发高速重试。
- 抄表失败后保留最近一次成功读取的传感器数值（从未成功读取过时仍显示不可用）；连续 **3 次**实际抄表失败时，在 HA 通知中心创建**一条**通知，之后不重复提醒，直到成功一次才重新计数。**上次成功抄表时间**仅在成功时更新；通知不会推送到手机。
- **低电量提醒阈值**：设备页面的配置数字实体可设置剩余电量阈值（0～1000 kWh，默认 **10 kWh**；设置为 **0** 关闭提醒），也可通过集成的 **配置** 页面修改。成功抄表时剩余电量 ≤ 阈值，HA 通知中心提示一次；持续低电量期间不重复提醒，只有重新抄到高于阈值的数值后才会允许下一次提醒。不会因抄表失败或保留的旧数据发送低电量提醒，也不发送手机推送。
- **只读**：不提供充值、清零、拉合闸或任意报文下发。

### 官方小程序兼容性（重要）

协议包含 `txMsgId` 请求编号。实验观察到，重复使用相同编号可能导致电表不回复；本地提前使用官方下一次预计分配的编号后，官方小程序曾提示「设备下发未响应，请稍后重试」。取消并重新发起官方抄表后，该次测试恢复正常。

**目前尚未通过 HCI 记录完全证明这次官方报错由编号碰撞造成，故不能给出可靠的冲突概率。** 官方客户端与本集成同时使用时可能发生读取超时；也不能保证所有设备和异常都能自动恢复。

- 使用官方小程序抄表、充值及重要操作前，建议在 HA **设置 → 设备与服务** 暂时**禁用此集成**；完成后再启用。
- **充值、缴费、拉闸、合闸等敏感流程期间，不要运行本集成。**
- 官方小程序报错后，先停止本集成再使用官方功能，不要高频反复尝试。
- 避免不必要的高频轮询（默认 10 分钟）；与官方小程序的绝对零冲突**无法保证**。

### 通过 HACS 安装（推荐）

如果 Home Assistant 已安装 [HACS](https://www.hacs.xyz/)，可以直接点击：

[在 HACS 中打开 Yunmu BLE Meter](https://my.home-assistant.io/redirect/hacs_repository/?owner=Tenqui-Noir&repository=yunmu-ble-ha&category=integration)

或者在 **HACS → 右上角三个点 → 自定义存储库** 中添加：

```text
https://github.com/Tenqui-Noir/yunmu-ble-ha
```

选择类型 **Integration（集成）**，添加后在 HACS 搜索并下载 **Yunmu BLE Meter (Experimental)**，然后**重启 Home Assistant**，再到 **设置 → 设备与服务 → 添加集成** 搜索 `Yunmu BLE Meter (Experimental)` 并配置蓝牙 MAC 地址。

**前提**：HA 已有可执行主动 GATT 连接的蓝牙适配器或 ESPHome Active Bluetooth Proxy；HACS 负责下载安装，不会提供蓝牙硬件。

### 安装（手动，备选方式）

1. 确保 Home Assistant 已配置蓝牙适配器，或安装 ESPHome **Active Bluetooth Proxy**（仅被动扫描的代理无法连接 GATT）。尤其 HAOS 运行在 Hyper-V 时，通常需要远程主动代理或可直通的蓝牙适配器。
2. 将仓库中的 `custom_components/yunmu_ble` 目录复制到 HA 配置目录下的 `custom_components/yunmu_ble`，重启 HA。
3. 进入 **设置 → 设备与服务 → 添加集成**，搜索 `Yunmu BLE Meter (Experimental)`，输入电表的 BLE MAC 地址，或者从发现提示中确认设备。
4. 设备页面可点击 **立即抄表** 立即读取；可在设备页面直接设置 **自动抄表间隔**，或进入集成的 **配置** 修改；如果读数不可用，请检查 HA 蓝牙日志、可连接适配器和代理的 BLE 覆盖范围。
5. 需暂停抄表时，在设备与服务中禁用集成。初次配置无需通过 BLE 写入任何控制命令。

**尚未真机验收：** 本仓库的自动测试只验证已捕获的 BLE 协议报文，无法覆盖代理实际连接、不同 ROM/固件的通知订阅行为或长期稳定性。安装前建议备份 HA 配置，首次试验完成后用官方小程序确认抄表正常。

### 协议依据

- UART GATT 服务：`49535343-fe7d-4ae5-8fa9-9fafd205e455`
- Write Without Response：`49535343-8841-43f4-a8d4-ecbe34729bb3`
- Notify：`49535343-1e4d-4bd9-ba61-23c647249616`
- 读请求 ID 0：`D4D5D5C4DD`；ID 1：`D4D4D5C7DC`
- Notify：20 字节，每字节 XOR `0x91`，返回值的第二字节回显请求 ID；偏移 7～10、11～14 两个 32 位大端字段分别代表剩余、累计电量（除以 100 得 kWh）。
- 响应末尾完整性/校验字段**尚未破解**：现有实现只检查结构、匹配编号和数值范围，**不能当作已完成 CRC 验证**。
- 0/1 编号轮换适用于当前实验样本，不保证未来固件兼容；切勿将推导的五字节格式用于其他未知电表操作。

### 开发与测试

```bash
python -m pip install pytest ruff
python -m pytest -q
ruff check .
python -m compileall -q custom_components tests
```

后续计划：真机验证 Bluetooth Proxy、完善断线及掉包行为测试、确认 Notify 校验算法；暂不支持写操作。

## English

Experimental, unofficial **read-only** Bluetooth Low Energy integration for Yunmu prepaid electricity meters, based on a single observed YM-M4-BE unit. It exposes remaining electricity (kWh), cumulative consumption (kWh), timestamp of the last successful read, a configurable device-level polling interval (5–120 minutes, default 10), and a rate-limited manual **Read now** button (5-second cooldown). It does not contact Yunmu's servers. After a failed read, previously valid sensor values remain visible, and one Home Assistant persistent notification is created on the third consecutive failure. A successful read resets the failure streak. The configurable low-electricity threshold (0–1000 kWh, 10 kWh by default; 0 disables) creates a separate persistent notification only when a successful reading is at or below the threshold, once until a later reading rises above it. This does not send a mobile push notification.

**Important:** The observed `txMsgId` counter may be subject to duplicate filtering. In one experiment, the official mini-program timed out after a local read intentionally used the expected next ID; cancelling and re-reading restored operation. The root cause and collision frequency are unproven. Disable this integration before payment, recharge, or other important official meter operations. The response's trailing integrity bytes have not yet been decoded, and no complete checksum verification is implemented.

Home Assistant Bluetooth and an active, connectable BLE adapter / ESPHome Bluetooth Proxy are required. Install `custom_components/yunmu_ble` into your HA configuration and restart. This code has offline protocol tests but **has not yet been hardware-tested through HA or an ESPHome proxy**.
