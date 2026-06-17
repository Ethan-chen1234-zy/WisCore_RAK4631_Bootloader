# RAK4631 Bootloader

This is the Adafruit-based CDC/DFU/UF2 bootloader for WisCore RAK4631 based boards, modified with a fix for OTA DFU mode to make it more resilient to a bad flash.

This bootloader will reboot back to OTA DFU mode after an unsuccessful flash so that you can try again.

[中文说明](README.zh-CN.md)

## Installation

There are two options to install the bootloader, the easiest way is with UF2 mode. Installing the bootloader this way will keep your app firmware intact, along with your settings. (eg. pubkey, radio settings, etc)

### Flashing with UF2 file.

1. Boot the RAK into UF2 mode by double pressing the reset button.
2. Copy the UF2 file onto the RAK4631 drive that appears.
3. The RAK will reboot and you should be running the new bootloader.

> **Windows error `0x800703EE`?** If Explorer shows *"The volume for a file has been externally altered"* near the end of the copy, the flash usually already succeeded — click **Skip**. See [UF2 Windows copy error](doc/uf2_windows_copy_error.md).

## OTA firmware update (Meshtastic)

This bootloader uses **Adafruit Legacy BLE DFU** (not Nordic Secure DFU / RUI3). After the bootloader and Meshtastic are installed (first flash is usually via UF2), application updates over Bluetooth use a **`*-ota.zip`** package and the **nRF Device Firmware Update** app.

> **Note:** The Meshtastic app starts OTA DFU mode; the actual firmware transfer is done with the nRF DFU app. This is expected.

### Prerequisites

- WisCore RAK4631 running this Adafruit bootloader (not RUI3)
- Meshtastic firmware already installed on the board
- Target release: `firmware-rak4631-*-ota.zip` from [Meshtastic firmware releases](https://github.com/meshtastic/firmware/releases)
- Mobile app: [nRF Device Firmware Update](https://www.nordicsemi.com/Products/Development-tools/nrf-device-firmware-update) (Android / iOS)

Do **not** use RUI3 zip files or `.uf2` files for BLE OTA.

### Procedure (verified)

**Option A — Meshtastic app**

1. **Enter OTA mode** — In the Meshtastic app, start a **firmware update**. The device reboots into the bootloader BLE OTA state.
2. **Confirm on the board** — Blue and green LEDs blink alternately. The device advertises as **`AdaDFU`** (Legacy DFU).
3. **Leave Meshtastic** — Fully quit the Meshtastic app so it does not hold the BLE connection.
4. **Open nRF Device Firmware Update** — Select the `*-ota.zip` file for RAK4631.
5. **Connect and upgrade** — Scan, connect to **`AdaDFU`**, and start the update. Keep the phone screen on until finished.
6. **Reboot** — The board restarts into the new Meshtastic firmware when the transfer completes.

**Option B — `tools/trigger_ble_dfu.py` (PC, no Meshtastic app)**

[`tools/trigger_ble_dfu.py`](tools/trigger_ble_dfu.py) replicates the Meshtastic app step that triggers **BLE Buttonless DFU** (Legacy service `0x1530` on RAK4631). It does **not** upload the zip; use nRF Device Firmware Update for that (steps 4–6 above).

```bash
pip install bleak

# List Meshtastic BLE devices
python tools/trigger_ble_dfu.py --scan

# Trigger OTA DFU (headless nodes: default PIN 123456)
python tools/trigger_ble_dfu.py --address AA:BB:CC:DD:EE:FF --forget
```

Then on your phone: open nRF Device Firmware Update, connect to **`AdaDFU`**, and flash `*-ota.zip`.

On Windows, if you see **Insufficient Authentication (ATT 0x05)**, retry with `--forget` or remove the device in Bluetooth settings and pair again.

This script is **not** the same as USB UF2 entry (`meshtastic --enter-dfu`, `pio upload`, or double-reset UF2).

### Recommended DFU app settings

| Setting | Value |
|---------|-------|
| Packet Receipt Notification (PRN) | ON |
| Number of packets | 5–8 |
| Request High MTU | OFF if the transfer fails early; ON otherwise (Android) |
| Keep bond | OFF |

If OTA fails and the application is invalid, this bootloader (2025 fix) sets `GPREGRET = 0xA8` and reboots back into OTA DFU so you can retry with the same steps—no USB required.

### OTA vs other update methods

| Method | Tool | Package |
|--------|------|---------|
| First install / USB | UF2 drag-and-drop | `*.uf2` |
| BLE OTA (Meshtastic) | nRF Device Firmware Update | `*-ota.zip` |
| Enter BLE OTA (PC) | `tools/trigger_ble_dfu.py` + phone DFU app | `*-ota.zip` |
| USB serial DFU | `adafruit-nrfutil dfu serial` | bootloader or app `.zip` |
| RUI3 devices | nRF Connect | Nordic format (not compatible) |

## Build

Recommended: compile in **Docker** (matches CI, works on Windows/macOS/Linux).

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git submodules initialized:

```bash
git submodule update --init --recursive
```

### Build with Docker (recommended)

From the project root in PowerShell:

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

On Linux/macOS, use the same command (adjust the `cd` path).

**Outputs** (in `_bin/wiscore_rak4631_board/`):

| File | Purpose |
|------|---------|
| `update-wiscore_rak4631_board_bootloader-0.4.3_nosd.uf2` | UF2 self-update (recommended for flashing) |
| `wiscore_rak4631_board_bootloader-0.4.3_s140_6.1.1.hex` | Bootloader + SoftDevice hex |
| `wiscore_rak4631_board_bootloader-0.4.3_s140_6.1.1.zip` | DFU serial update package |

Intermediate build files are in `_build/build-wiscore_rak4631_board/`.

### Build with WSL (alternative)

Install Ubuntu 22.04 in WSL, install the ARM GCC toolchain under `/opt` (not in the project directory), then:

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

Do not download or extract the toolchain into the project root; use Docker or install it to a system path such as `/opt`.
