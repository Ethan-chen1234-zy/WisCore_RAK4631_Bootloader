# RAK4631 Bootloader

这是基于 Adafruit CDC/DFU/UF2 Bootloader 修改的 WisCore RAK4631 专用版本，并修复了 OTA DFU 模式，使其在刷写失败时更具容错能力。

当 OTA 刷写未成功时，Bootloader 会重新进入 OTA DFU 模式，以便再次尝试升级。

[English](README.md)

## 安装

安装 Bootloader 有两种方式，最简单的是使用 UF2 模式。通过这种方式安装可以保留应用固件和各项设置（例如 pubkey、射频参数等）。

### 使用 UF2 文件刷写

1. 双击 RESET 按钮，使 RAK4631 进入 UF2 模式。
2. 将 UF2 文件复制到出现的 U 盘。
3. 设备自动重启后，即运行新的 Bootloader。

## OTA 固件升级（Meshtastic）

本 Bootloader 使用 **Adafruit Legacy BLE DFU**（不是 Nordic Secure DFU / RUI3）。在 Bootloader 与 Meshtastic 已安装的前提下（首次安装通常用 UF2），蓝牙空中升级需使用 **`*-ota.zip`** 包和 **nRF Device Firmware Update** App。

> **说明：** Meshtastic App 负责让设备进入 OTA DFU 模式；实际传包由 nRF DFU App 完成，这是正常流程，需分两步操作。

### 前置条件

- RAK4631 已刷入本 Adafruit Bootloader（非 RUI3）
- 板卡上已运行 Meshtastic 固件
- 目标升级包：从 [Meshtastic 固件发布页](https://github.com/meshtastic/firmware/releases) 下载 `firmware-rak4631-*-ota.zip`
- 手机安装 [nRF Device Firmware Update](https://www.nordicsemi.com/Products/Development-tools/nrf-device-firmware-update)（Android / iOS）

BLE OTA **不要**使用 RUI3 的 zip 或 `.uf2` 文件。

### 操作步骤（已验证）

1. **进入 OTA 模式** — 在 Meshtastic App 中发起 **固件更新**，设备复位后进入 Bootloader 的 BLE OTA 状态。
2. **确认板卡状态** — 蓝、绿 LED 交替闪烁，表示等待手机连接；蓝牙广播名为 **`AdaDFU`**（Legacy DFU）。
3. **退出 Meshtastic** — 完全关闭 Meshtastic App，避免占用 BLE 连接。
4. **打开 nRF Device Firmware Update** — 选择 RAK4631 对应的 `*-ota.zip` 文件。
5. **连接并升级** — 扫描并连接 **`AdaDFU`**，开始升级；过程中保持手机屏幕常亮，直至完成。
6. **自动重启** — 传输完成后设备重启，运行新版本 Meshtastic。

### 建议的 DFU App 参数

| 参数 | 建议值 |
|------|--------|
| Packet Receipt Notification (PRN) | 开启 |
| Number of packets（包数） | 5–8 |
| Request High MTU | 若一开始就失败则关闭；Android 可尝试开启 |
| Keep bond | 关闭 |

若 OTA 失败且应用无效，本 Bootloader（2025 容错修复）会写入 `GPREGRET = 0xA8` 并再次进入 OTA DFU，可按相同步骤重试，无需插 USB。

### OTA 与其他升级方式对比

| 方式 | 工具 | 升级包 |
|------|------|--------|
| 首次安装 / USB | UF2 拖放 | `*.uf2` |
| 蓝牙 OTA（Meshtastic） | nRF Device Firmware Update | `*-ota.zip` |
| USB 串口 DFU | `adafruit-nrfutil dfu serial` | Bootloader 或应用 `.zip` |
| RUI3 设备 | nRF Connect | Nordic 格式（不兼容） |

## 编译

推荐使用 **Docker** 编译（与 CI 环境一致，适用于 Windows / macOS / Linux）。

### 前置条件

- 已安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- 已初始化 Git 子模块：

```bash
git submodule update --init --recursive
```

### 使用 Docker 编译（推荐）

在项目根目录的 PowerShell 中执行：

```powershell
cd D:\Git_code\WisCore_RAK4631_Bootloader

docker run --rm --user root -v "${PWD}:/work" -w /work xlemonx/arm-gnu-toolchain:12.3.1 bash -lc "
  apt-get update -qq &&
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq make python3 python3-pip git &&
  pip3 install adafruit-nrfutil intelhex &&
  make BOARD=wiscore_rak4631_board all &&
  make BOARD=wiscore_rak4631_board copy-artifact
"
```

Linux / macOS 使用相同命令（请按实际路径修改 `cd`）。

**编译产物**（位于 `_bin/wiscore_rak4631_board/`）：

| 文件 | 用途 |
|------|------|
| `update-wiscore_rak4631_board_bootloader-0.4.3_nosd.uf2` | UF2 自更新包（推荐用于刷写） |
| `wiscore_rak4631_board_bootloader-0.4.3_s140_6.1.1.hex` | Bootloader + SoftDevice 完整 hex |
| `wiscore_rak4631_board_bootloader-0.4.3_s140_6.1.1.zip` | DFU 串口升级包 |

中间文件位于 `_build/build-wiscore_rak4631_board/`。

### 使用 WSL 编译（备选）

在 WSL 中安装 Ubuntu 22.04，将 ARM GCC 工具链安装到 `/opt`（不要放在项目目录内），然后执行：

```bash
sudo apt update
sudo apt install -y make git python3 python3-pip wget xz-utils
wget https://developer.arm.com/-/media/Files/downloads/gnu/12.3.rel1/binrel/arm-gnu-toolchain-12.3.rel1-x86_64-arm-none-eabi.tar.xz
sudo tar xf arm-gnu-toolchain-12.3.rel1-x86_64-arm-none-eabi.tar.xz -C /opt
export PATH=/opt/arm-gnu-toolchain-12.3.rel1-x86_64-arm-none-eabi/bin:$PATH
pip3 install adafruit-nrfutil intelhex

cd /mnt/d/Git_code/WisCore_RAK4631_Bootloader
git submodule update --init --recursive
make BOARD=wiscore_rak4631_board all
make BOARD=wiscore_rak4631_board copy-artifact
```

请勿将工具链下载或解压到项目根目录；请使用 Docker，或安装到 `/opt` 等系统路径。
