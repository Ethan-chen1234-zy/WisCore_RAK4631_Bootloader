# UF2 拖拽烧录时 Windows 报错说明

[English](uf2_windows_copy_error.md)

![](.\image-error.png)

在 Windows 上使用资源管理器将 `.uf2` 文件拖放到 RAK4631 的 UF2 虚拟 U 盘时，复制进度接近完成或刚结束时，可能弹出如下错误：

| 项目 | 内容 |
|------|------|
| 错误码 | `0x800703EE` |
| Win32 错误 | `ERROR_FILE_INVALID` (1006) |
| 提示原文 | 文件所在的卷已被外部更改，因此打开的文件不再有效。 |

**这是 UF2 烧录成功后的正常现象，不是固件损坏。** 弹窗出现时，固件通常已经写入完成；点击 **跳过** 即可，设备会自动重启并运行新固件。

## 如何判断烧录成功

出现以下现象即可认为烧录成功，无需重试：

- UF2 虚拟 U 盘（如 `RAK4631`）从「此电脑」中消失
- 设备自动重启，运行新固件或新 Bootloader
- 复制进度条已走完绝大部分（弹窗出现在收尾阶段）

## 原因说明

### 1. Windows 执行的是「复制文件到 U 盘」

Bootloader 通过 USB 大容量存储（MSC）暴露一个 **GhostFAT 虚拟 FAT 文件系统**。资源管理器拖拽 `.uf2` 时，走的是标准文件复制流程，而不是专用烧录工具协议。

### 2. Bootloader 只关心 UF2 数据块

每个 512 字节扇区若是合法 UF2 块，Bootloader 会将其中的 payload 直接写入内部 Flash，而不是把文件存到真实磁盘上。

相关代码：`src/usb/uf2/ghostfat.c` 中的 `write_block()`。

### 3. 最后一块写完即断开 USB 并重启

当最后一个 UF2 块写入完成后，Bootloader 会：

1. 标记 DFU 完成（`DFU_UPDATE_APP_COMPLETE`）
2. 将 bootloader settings 保存到 Flash
3. 调用 `usb_teardown()` 断开 USB（虚拟 U 盘消失）
4. 跳转到新固件（`bootloader_app_start()`）

相关代码：`src/usb/msc_uf2.c` 中的 `tud_msc_write10_complete_cb()`，`src/usb/usb.c` 中的 `usb_teardown()`。

这是 **设计行为**：UF2 协议约定烧录完成后设备应立即重启运行新固件，不会等待 Windows 完成文件复制的收尾操作。

### 4. Windows 与 Bootloader 的时序竞态

资源管理器复制文件时，大致分为以下阶段：

| 阶段 | 操作内容 | Bootloader 状态 |
|------|----------|-----------------|
| ① 写入数据 | 将 `.uf2` 文件内容写入虚拟盘扇区 | 逐块解析 UF2 并写入 Flash |
| ② 更新元数据 | 更新 FAT 表、目录项、时间戳等 | 虚拟盘仍在线，但数据无实际意义 |
| ③ 关闭文件 | 刷新缓存、关闭文件句柄 | 需要虚拟盘仍然可用 |

Bootloader 在 **阶段 ① 完成** 时即断开 USB 并重启；Windows 的 **阶段 ②③** 尚未完成，就会报 `0x800703EE`——表示正在操作的卷已被设备主动移除。

```
Windows 资源管理器                    Bootloader
      |                                  |
      |---- 复制 .uf2 数据块 ----------->| 写入 Flash
      |                                  | 最后一块完成 → 烧录结束
      |                                  | usb_teardown() → U 盘消失
      |---- 更新 FAT / 关闭文件 --------X| （卷已无效）
      |                                  | 跳转到新固件
      X 弹出 0x800703EE 错误
```

## 常见问题

### 点「重试」有用吗？

通常无效。此时虚拟 U 盘已经消失，重试只会再次失败。若设备已重启并运行新固件，说明烧录已成功，点 **跳过** 关闭对话框即可。

### 点「跳过」会损坏固件吗？

不会。Flash 中的固件在最后一个 UF2 块写入时已经完成；弹窗仅表示 Windows 无法完成文件复制的元数据收尾，与 Flash 内容无关。

### 是所有 UF2 设备都会这样吗？

在 **Windows** 上使用资源管理器拖拽 UF2 时，基于 Adafruit UF2 Bootloader 的 nRF52 板卡（含 RAK4631、Feather nRF52840 等）都可能出现此现象。这是 Windows 文件复制与 UF2「烧完即走」机制之间的竞态，并非 RAK4631 独有缺陷。

Linux 和 macOS 上通常不会出现如此明显的错误弹窗，但底层行为相同（设备在烧录完成后断开虚拟盘）。

### 如何避免这个弹窗？

若希望完全避免该提示，可改用以下方式升级，不走 MSC 拖拽：

| 方式 | 工具 | 升级包 |
|------|------|--------|
| USB 串口 DFU | `adafruit-nrfutil dfu serial` | `.zip` 包 |
| J-Link 烧录 | `nrfjprog` / OpenOCD | `.hex` 文件 |
| 蓝牙 OTA | nRF Device Firmware Update | `*-ota.zip` |

## 技术参考

| 符号 / 位置 | 说明 |
|-------------|------|
| `0x800703EE` | Windows HRESULT，对应 Win32 错误 1006 (`ERROR_FILE_INVALID`) |
| `src/usb/uf2/ghostfat.c` | GhostFAT 虚拟文件系统，UF2 块解析与 Flash 写入 |
| `src/usb/msc_uf2.c` | USB MSC 回调，最后一块完成后触发 DFU 收尾 |
| `src/usb/usb.c` | `usb_teardown()` 模拟 USB 断开 |
| `lib/sdk11/.../bootloader.c` | 保存 settings 后退出 DFU，跳转应用 |
