> 历史联调记录；当前功能和验证状态以 README.md 与 VALIDATION.md 为准。

## 0.2.0b8
- 整理三个主控件名称，保留稳定unique_id。
- 蜂鸣声归为HA配置项，默认桥接不包含。
- 净水TDS改名饮用水TDS，与官方App一致。
- 附只选三个控制实体的HomeKit桥接说明。

## 0.2.0b7
- 按实机反馈纠正75/85/100℃档位映射（205/203/204）。
- 对具有i2 Pro特征且缺少对应字段的设备禁用自来水TDS、AQP旧实体。
- 水量实机验证通过，累计用水和水质等级仍待适配。

## 0.2.0b6
- 基于用户确认点击顺序加入8个水温、7个水量档位。
- 限定档位编码，不发送出水或任意自定义数值。
- 沿用实际状态确认和超时处理。

## 0.2.0b5
- 新增有对照证据的制冷模式和蜂鸣声试验控制。
- 制冷组合原子发送、变化字段确认、整体状态检查、禁止并发和自动重发。
- 温度/水量映射未确认，保持原控制范围。

## 0.2.0b4
- 增加限时、限量、白名单控制变化采集按钮。
- 记录现有订阅中的 desired 快照和 reported 变化，不把快照当成原始指令。
- 拒绝异常 state 格式，保留现有控制范围。

## 0.2.0b3
- 补齐实机 PC5in1FilterLife 字段及相关诊断数值。
- 对制冰设备停用尚未验证的旧接口用水量显示。

## 0.2.0b2
- 增加四种实测制冷模式的只读显示，未知组合保持未知。
- 修复带数字的诊断字段被遗漏，扩展明确设备参数数值白名单。
- 保持制冷写入禁用。

# 0.2.0b1

- Correct custom component layout and per-device configuration.
- Password and SMS setup with explicit selection, reauthentication, v1 migration.
- Remove fixed model fallback control mappings; resolve 55°C from metadata.
- Preserve zero readings; missing state is unknown, stale/disconnected state unavailable.
- TLS WebSocket MQTT handshake/subscription/keepalive/ACKs/reconnection/cleanup.
- Wait for reported device state after settings commands, rather than treating socket send as success.
- Allowlisted diagnostics for protocol investigation; no arbitrary write service.
- Drop raw payload/credential logging and personal-looking upstream sample strings.
- MIT attribution, installation, rollback, i2 Pro investigation and publishing documentation.
- No ice-control or auto-dispense implementation. Pending real device and live cloud testing.
