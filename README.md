# ROV Control Station

Mini ROV 综合上位机控制系统，基于 PySide6 + pygame + OpenCV，实现实时状态监控、视频流显示、过流保护及手柄/键盘遥控。支持串口断线自动重连和手柄热插拔。

## 运行指南

### 环境要求

- Python 3.10+
- 依赖安装：`pip install -r requirements.txt`

### 启动

```bash
python src/main.py
```

所有参数在 `config/config.ini` 中配置，无需命令行参数。

### 键盘控制（无手柄时自动启用）

| 按键 | 动作 | 配置项 |
|------|------|--------|
| W / S | 前进 / 后退 | `key_forward` / `key_backward` |
| A / D | 逆时针 / 顺时针旋转 | `key_yaw_left` / `key_yaw_right` |
| ← / → | 左移 / 右移 | `key_strafe_left` / `key_strafe_right` |
| ↑ / ↓ | 上浮 / 下潜 | `key_ascend` / `key_descend` |
| X | 模式切换（短按正向/长按反向） | `key_mode_toggle` / `key_mode_reverse` |
| Q / E | 夹爪 张开 / 夹紧 | `key_claw_open` / `key_claw_close` |
| P | 截图 | `key_snapshot` |
| R | 录像 | `key_record` |

按键映射可在 `config.ini` → `[keyboard]` 中自定义。

### 手柄控制

插入 Xbox 兼容手柄后自动识别，拔出自动切回键盘模式（每秒检测一次，间隔可配）。摇杆/按键映射可在 `config.ini` 中自定义。

**默认摇杆映射**（Xbox 控制器，WND 坐标系）：

| 摇杆操作 | ROV 动作 | 输出字段 | 配置项 |
|---------|---------|---------|--------|
| 左摇杆 前推 / 后拉 | 前进 / 后退 | thrust_y | `[y]` axis=1, max=5000N |
| 左摇杆 右推 / 左推 | 顺时针 / 逆时针旋转 | yaw_torque | `[yaw]` axis=0, max=1000N·m |
| 右摇杆 右推 / 左推 | 右移 / 左移 | thrust_x | `[x]` axis=2, max=6000N |
| 右摇杆 前推 / 后拉 | 上浮 / 下潜 | thrust_z | `[z]` axis=3, max=6000N |

> 每轴独立配置：`axis` 为 pygame 轴索引，`max` 为最大控制量，`deadzone` 为死区（0~1）。

**默认按键映射**（Xbox 控制器）：

| 按键 | 功能 | 触发方式 | 配置项 |
|------|------|---------|--------|
| X | 运动模式轮换 | 短按正向，长按反向 | `btn_mode = 2` |
| LB | 夹爪张开 | 下降沿触发 | `btn_claw_open = 4` |
| RB | 夹爪夹紧 | 下降沿触发 | `btn_claw_close = 5` |

> 按钮编号为 pygame 索引，`mode_long_press = 400` 为长按判定时间 (ms)，`poll_interval = 1.0` 为手柄热插拔检测间隔 (s)。

---

## 通信协议

统一帧格式：

| 帧头 (2B) | 数据域 (N字节) | 异或校验 (1B) | 帧尾 (2B) |
|-----------|---------------|--------------|-----------|
| 0xFA 0xAF | ...           | XOR(数据域)   | 0xFB 0xBF |

### 下行请求帧（上位机 → 下位机）

**帧类型**: `0x52` ('R') | **长度**: 5 字节

| 字节 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0~1 | header | uint8[2] | 帧头 `0xFA 0xAF` |
| 2 | frame_type | uint8 | `0x52` — 请求传感器数据 |
| 3~4 | tail | uint8[2] | 帧尾 `0xFB 0xBF` |

> 上位机每 200ms 定时发送，下位机收到后回传上行数据帧。

### 下行数据帧（上位机 → 下位机）

**帧类型**: `0x49` ('I') | **长度**: 23 字节

| 字节 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0~1 | header | uint8[2] | 帧头 `0xFA 0xAF` |
| 2 | frame_type | uint8 | `0x49` — 推进器控制指令 |
| 3~6 | thrust_y | float32 LE | Y 推力 (N)，前进为正 |
| 7~10 | thrust_x | float32 LE | X 推力 (N)，右移为正 |
| 11~14 | thrust_z | float32 LE | Z 推力 (N)，下潜为正 |
| 15~18 | yaw_torque | float32 LE | Yaw 扭矩 (N·m)，顺时针为正 |
| 19 | arm_angle | uint8 | 机械臂角度 (0~255) |
| 20 | checksum | uint8 | 字节 2~19 逐字节异或 |
| 21~22 | tail | uint8[2] | 帧尾 `0xFB 0xBF` |

> 上位机每控制周期（默认 125Hz = 8ms）发送，不需要下位机回复。

### 上行数据帧（下位机 → 上位机）

**帧类型**: `0x53` ('S') | **长度**: 15 字节

| 字节 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0~1 | header | uint8[2] | 帧头 `0xFA 0xAF` |
| 2 | frame_type | uint8 | `0x53` — 传感器数据 |
| 3~6 | temperature | float32 LE | 环境温度 (°C) |
| 7 | water_ingress | uint8 | 进水检测 (0=正常, 非0=告警) |
| 8~11 | current | float32 LE | 电机总电流 (A) |
| 12 | checksum | uint8 | 字节 2~11 逐字节异或 |
| 13~14 | tail | uint8[2] | 帧尾 `0xFB 0xBF` |

> 下位机仅在收到下行请求帧 (0x52) 后回传，不会主动推送。温度和进水检测为预留功能。

### 校验方式

异或校验：对数据域所有字节逐字节异或，结果取低 8 位。

```
checksum = byte[2] ^ byte[3] ^ ... ^ byte[N-3]
```

---

## 配置文件

`config/config.ini` 统一管理所有参数：

| 节 | 说明 |
|----|------|
| `[keyboard]` | 键盘按键映射 |
| `[joystick]` | 手柄通用设置 + 热插拔检测间隔 (`poll_interval`) |
| `[x]` `[y]` `[z]` `[yaw]` | 每轴独立配置（轴索引、最大推力、死区） |
| `[speed_modes]` | 速度档位，每档独立可配名称与推力比例 |
| `[serial]` | 串口通信参数 + 断线重连间隔 (`reconnect_interval`) |
| `[camera]` | 摄像头参数 |
| `[control]` | 控制循环频率 |
| `[overcurrent]` | 过流保护阈值 |
| `[media]` | 截图/录像输出路径 |

**速度档位**：按 X 键循环切换，控制量 = 摇杆值 × 轴最大值 × 档位比例。

| 档位 | 配置项 | 默认比例 | 默认名称 | 用途 |
|------|--------|---------|---------|------|
| 0 | `mode0_name` / `mode0_rate` | 30% | SLOW | 精确定位、对接 |
| 1 | `mode1_name` / `mode1_rate` | 60% | MEDIUM | 一般巡检、作业 |
| 2 | `mode2_name` / `mode2_rate` | 100% | FAST | 快速移动、紧急响应 |

---

## 项目结构

```
rov-control-station/
├── config/
│   └── config.ini              # 全部可调参数（由 AppCore 统一加载）
├── src/
│   ├── main.py                 # 程序入口，纯组装
│   ├── AppCore.py              # 编排层：配置加载、子系统创建、数据流编排
│   ├── camera/
│   │   └── Camera.py           # 摄像头采集 + 录像截屏控制模块
│   ├── gui/
│   │   ├── MainWindow.py       # PySide6 主窗口，纯 UI 层
│   │   ├── KeyBridge.py        # Qt → pygame 键盘事件桥接
│   │   └── Ui_MainWindow.py    # Qt Designer 编译生成
│   ├── joystick/
│   │   └── Joystick.py         # 手柄/键盘双输入 + 热插拔检测
│   ├── serial_comm/
│   │   ├── Serial.py           # 串口通信 + 断线自动重连 + 帧收发
│   │   └── CommandBuffer.py    # 循环缓冲区帧解析
│   ├── sensor/
│   │   └── SensorParser.py     # 传感器解析 + 过流监控模块
│   └── utils/
│       ├── Stopwatch.py        # 高精度秒表
│       └── FrameRateLimiter.py # 频率控制器
├── ui/
│   ├── compile_ui.py           # .ui → .py 编译 + PySide6 6.10+ 枚举兼容修复
│   └── main_window.ui          # Qt Designer 布局源文件
├── requirements.txt
└── README.md
```

## 架构

```
                    config.ini (唯一配置入口)
                         │
                         ▼
main.py ──组装──→  AppCore  ──回调──→  MainWindow (纯UI)
  (纯组装)    │    (编排层)  AppCallbacks    │
              │       │                      │
              │       ├── JoystickController  │  Qt Signal
              │       │   (含热插拔检测)       │  (跨线程安全)
              │       ├── SerialComm          │
              │       │   (含断线自动重连)      │
              │       ├── OvercurrentMonitor  │
              │       │   (RLock 线程安全)     │
              │       ├── Camera              │
              │       └── Stopwatch           │
              │                              │
              │  AppCore 内部管理:             │
              │  - 截图/录像路径自动生成        │
              │  - 快捷键回调绑定              │
              │  - 请求帧定时器 (200ms)        │
              │  - 手柄热插拔轮询              │
              │                              │
              └──────── 主循环 125Hz ────────→│
                       (数据推送)             │
                                        KeyBridge
                                     (Qt→pygame 翻译)
```

## 设计原则

| 原则 | 说明 |
|------|------|
| 配置单一入口 | 只有 `AppCore` 读取 `config.ini`，其余模块通过 dict 参数接收 |
| 回调解耦 | `AppCallbacks` 承载所有 AppCore → MainWindow 数据推送，无反向依赖 |
| 纯 UI 层 | `MainWindow` 不依赖 `pygame`/`configparser`/`pyserial`，只做显示和按键转发 |
| 纯组装入口 | `main.py` 只做创建/绑定/启动，不包含路径构造、状态判断或业务逻辑 |
| 动态按键映射 | `KeyBridge` 遍历 `config.ini` 全部按键值自动建立 Qt→pygame 映射 |
| 断线自动恢复 | `SerialComm` 后台线程检测断线 → 等待 → 重连，状态实时通知 UI |
| 手柄热插拔 | `AppCore` 后台轮询 `refresh_joystick()`，插入/拔出自动切换并通知 UI |
| 线程安全 | `OvercurrentMonitor` 使用 `RLock` 保护过流状态，`AppCore` 用 `_state_lock` 保护共享数据 |

## 依赖

| 包 | 版本 | 用途 |
|----|------|------|
| PySide6 | ≥ 6.10 | GUI 框架 |
| pygame | ≥ 2.5 | 手柄/键盘输入 |
| pyserial | ≥ 3.5 | 串口通信 |
| opencv-python | ≥ 4.8 | 摄像头采集 |
| numpy | ≥ 1.24 | 图像数据处理 |
