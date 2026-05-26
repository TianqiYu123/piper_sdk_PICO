# Piper SDK PICO

这个仓库基于 Piper 机械臂 SDK，当前主要用于通过 MQTT 控制 Piper 机械臂，并用 Meshcat 在浏览器中显示机械臂模型。

当前 `master` 的主运行入口是：

```bash
python demo/meshcat/piper_web.py
```

自动启动脚本 `piper.sh` 也运行这个文件。旧的 `demo/PICO/piper_web.py` 已从 `master` 删除；如需查看删除前版本，请切到 `backup-pico-piper-web-before-delete` 分支。

## 当前状态

| 内容 | 当前入口 |
| --- | --- |
| Web/MQTT 控制 + Meshcat 可视化 | `demo/meshcat/piper_web.py` |
| systemd 启动脚本模板 | `piper_service.txt` |
| 启动包装脚本 | `piper.sh` |
| CAN 单设备激活 | `can_activate.sh` |
| CAN 多设备配置 | `can_config.sh` |
| SDK 接口/协议/消息源码 | `interface/`, `protocol/`, `piper_msgs/` |
| 上游 V1/V2 示例 | `demo/V1/`, `demo/V2/` |
| PICO 旧实验脚本 | `demo/PICO/` |

## 运行环境

建议在 Ubuntu 18.04/20.04/22.04 上运行。机械臂控制依赖 SocketCAN，Windows 只适合阅读和修改代码，不适合直接控制 CAN 设备。

需要安装系统工具。`can_activate.sh` 使用 `ip`、`ethtool`、`can-utils`、`sudo`、`awk`、`grep`；`can_config.sh` 还可能调用 `modprobe gs_usb`：

```bash
sudo apt update
sudo apt install can-utils ethtool iproute2 kmod
```

当前 `piper.sh` 会查找并激活名为 `robotarm` 的 conda 环境。请先安装 Miniforge/Miniconda/Anaconda，并确保 `conda` 在 `PATH` 中；然后按这个名字创建环境：

```bash
conda create -n robotarm python=3.12
conda activate robotarm
```

安装 Python 依赖：

```bash
conda install -c conda-forge numpy scipy pinocchio transforms3d meshcat-python
pip install paho-mqtt python-can piper-sdk typing-extensions
```

注意：

- Pinocchio 的 conda 包名是 `pinocchio`，Python import 名也是 `pinocchio`。
- Meshcat 的 conda-forge 包名是 `meshcat-python`，由 `pinocchio.visualize.MeshcatVisualizer` 调用。
- Piper SDK 的 PyPI 包名建议写作 `piper-sdk`，Python import 名是 `piper_sdk`。老文档里的 `pip install piper_sdk` 通常也能被 pip 归一化处理，但这里统一使用 PyPI 项目名。
- `python-can` 提供 `can` 模块，是 SDK 与 SocketCAN 通信的 Python 依赖。

### 主控脚本依赖清单

`demo/meshcat/piper_web.py` 的非标准库依赖如下：

| import | 安装包 | 用途 |
| --- | --- | --- |
| `numpy` | `numpy` | 关节数组、矩阵运算 |
| `scipy.spatial.transform.Rotation` | `scipy` | 欧拉角/旋转矩阵转换 |
| `scipy.optimize.minimize` | `scipy` | SLSQP 逆运动学优化 |
| `transforms3d.euler` | `transforms3d` | 四元数转欧拉角 |
| `pinocchio` | `pinocchio` | URDF 模型加载、正运动学、Meshcat 可视化接口 |
| `pinocchio.visualize.MeshcatVisualizer` | `pinocchio` + `meshcat-python` | 浏览器 3D 可视化 |
| `paho.mqtt.client` | `paho-mqtt` | MQTT 收发 |
| `piper_sdk` | `piper-sdk` | Piper 机械臂 CAN 控制接口 |
| `can` | `python-can` | `piper-sdk`/本仓库 SDK 底层 CAN 通信 |
| `typing_extensions` | `typing-extensions` | 本仓库 SDK 源码中的类型注解兼容依赖 |

可以用下面的命令做一次 import 自检：

```bash
python -c "import numpy, scipy, transforms3d, pinocchio, meshcat, paho.mqtt.client, can, piper_sdk, typing_extensions; print('ok')"
```

### 旧脚本额外依赖

`demo/PICO/` 和部分 `demo/V1/` 旧脚本不是当前主入口，但如果需要继续运行，还要额外安装：

```bash
conda install -c conda-forge spatialmath-python roboticstoolbox-python
pip install keyboard
```

其中 `keyboard` 在 Linux 上读取全局键盘事件时可能需要 root 权限或额外的输入设备权限。

## 快速启动

在仓库根目录执行。当前主控脚本内部会调用 `bash can_activate.sh can0 1000000`，因此运行用户需要有配置 CAN 的权限；如果脚本需要 `sudo`，终端可能会提示输入密码。

```bash
conda activate robotarm
python demo/meshcat/piper_web.py
```

或者使用包装脚本：

```bash
bash piper.sh
```

`piper.sh` 的行为：

- 启动后先等待 30 秒。
- 自动向上查找包含 `demo/meshcat/piper_web.py` 的仓库目录。
- 激活 `robotarm` conda 环境。
- 循环运行 `demo/meshcat/piper_web.py`，脚本退出后会自动重启。

## MQTT 控制

当前主控脚本使用硬编码 MQTT 配置：

| 配置 | 值 |
| --- | --- |
| Broker | `47.96.170.89` |
| Port | `8003` |
| 默认模式 | `web` |
| Web topic | `arm/pose/web_control` |
| PICO topic | `arm/pose/robot_test_arm` |

消息格式固定为 JSON，`info` 必须是 15 个元素。Web 模式字段顺序如下：

```text
[x, y, z, rx, ry, rz, unused, trigger, joystickX, joystickY, joystickClick, buttonA, buttonB, grip, temp]
```

示例：

```json
{
  "info": [0.0, 0.0, 0.001, 0.0, 0.0, 0.01, 0.0, 0, 0.0, 0.0, 0, 0, 0, 0, 0]
}
```

Web 模式下，前 6 个元素被当作末端位姿增量：

| 字段 | 含义 |
| --- | --- |
| `x`, `y`, `rx`, `ry` | 当前代码会接收并累加，但不直接用于发给机械臂 |
| `z` | 映射到 joint2/joint3/joint5 的联动高度变化 |
| `rz` | 映射到 joint1 旋转 |
| `buttonA = 1` | 切换到 PICO 模式 |
| `buttonB = 1` | 切换回 Web 模式 |
| `temp = 1` | 复位到初始姿态 |

PICO 模式下，前 7 个元素是位姿和四元数，字段顺序如下：

```text
[x, y, z, qx, qy, qz, qw, trigger, joystickX, joystickY, joystickClick, buttonA, buttonB, grip, temp]
```

PICO 模式会把左手坐标系转换为右手坐标系，并在 `trigger = 1` 时根据第一次按下的位置做校准，然后通过 Pinocchio + SLSQP 逆解生成关节角度。`trigger = 0` 会退出当前遥操作状态并回到初始姿态。

注意：`demo/PICO/send_mqtt_message.py` 目前发布到 `arm/pose/test`，而主控脚本默认监听 `arm/pose/web_control`。如果用它测试当前主入口，需要先把脚本里的 topic 改成 `arm/pose/web_control`，或者用自己的 MQTT 客户端发布到正确 topic。

## 机械臂控制流程

`demo/meshcat/piper_web.py` 的启动流程：

1. 调用 `can_activate.sh` 激活 `can0`，波特率 `1000000`。
2. 连接 MQTT broker。
3. 创建 `C_PiperInterface("can0")` 并连接 CAN 端口。
4. 使能 6 个关节和夹爪。
5. 读取 `demo/meshcat/piper_description/urdf/piper_B2.urdf`。
6. 启动 Meshcat viewer。
7. 循环读取 MQTT 最新消息，并发送 `MotionCtrl_2`、`JointCtrl`、`GripperCtrl` 控制机械臂。

控制脚本默认假设 CAN 设备名是 `can0`。如果你的设备名不同，需要同步修改：

- `demo/meshcat/piper_web.py` 中的 `run_can_activation_script()`
- `demo/meshcat/piper_web.py` 中的 `C_PiperInterface("can0")`

## CAN 配置

单个 CAN 设备：

```bash
bash can_activate.sh can0 1000000
```

如果机器插了多个 CAN 设备，需要指定 USB 硬件地址：

```bash
bash can_activate.sh can_piper 1000000 "1-2:1.0"
```

查看 CAN 设备 USB 地址：

```bash
sudo ethtool -i can0 | grep bus
```

如果需要同时配置多个 CAN 设备，使用 `can_config.sh`，并先在脚本内配置每个 USB 口对应的 CAN 名称和波特率。

## 开机启动

`piper_service.txt` 是 systemd 服务模板。使用前需要把路径改成你机器上的实际仓库路径，并确认服务环境能找到 conda 和 `robotarm` 环境。

常用命令：

```bash
sudo systemctl enable piper_service.service
sudo systemctl start piper_service.service
sudo systemctl status piper_service.service
sudo journalctl -u piper_service.service
```

如果 systemd 下 CAN 激活失败，优先检查服务是否有权限执行 `sudo ip link ...`、`sudo ethtool ...`，或改为由系统启动脚本提前完成 CAN 配置。

## 重要注意事项

- 启动主控脚本前，确认机械臂急停、供电、CAN 接线和 USB-CAN 模块状态正常。
- `demo/meshcat/piper_web.py` 会直接发送关节控制指令，请先在安全空间内低速测试。
- 当前 MQTT broker、topic、CAN 名称、URDF 文件名都写在代码里；部署到不同环境时应先检查这些常量。
- Web 模式只对 `z` 和 `rz` 做了实际关节映射，其他位姿字段暂时不是完整 IK 控制。
- `X_LIMIT/Y_LIMIT/Z_LIMIT` 等限位常量目前没有完整接入控制逻辑，实际运行前建议增加限位保护。
- 如果终端出现 `Message NOT sent`，通常是 CAN 设备没有正确连接机械臂，先检查接线和供电，再重新激活 CAN。

## 参考文档

| 内容 | 文档 |
| --- | --- |
| V1 接口说明 | `asserts/V1/INTERFACE_V1.MD` |
| V2 接口说明 | `asserts/V2/INTERFACE_V2.MD` |
| V1 协议说明 | `asserts/V1/PROTOCOL_V1.MD` |
| V2 协议说明 | `asserts/V2/PROTOCOL_V2.MD` |
| V1 消息说明 | `asserts/V1/MSGS_V1.MD` |
| V2 消息说明 | `asserts/V2/MSGS_V2.MD` |
| 常见问题 | `asserts/Q&A.MD` |
| 双臂配置 | `asserts/double_piper.MD` |
