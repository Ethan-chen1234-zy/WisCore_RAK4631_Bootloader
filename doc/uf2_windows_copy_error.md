# UF2 drag-and-drop: Windows copy error

[中文说明](uf2_windows_copy_error.zh-CN.md)

![](.\image-error-en.png)

When copying a `.uf2` file onto the RAK4631 UF2 virtual drive in Windows Explorer, you may see this error near the end of the copy:

| Item | Value |
|------|-------|
| Error code | `0x800703EE` |
| Win32 error | `ERROR_FILE_INVALID` (1006) |
| Message | The volume for a file has been externally altered so that the opened file is no longer valid. |

**This is normal after a successful UF2 flash, not a corrupted firmware.** The firmware is usually already written when the dialog appears. Click **Skip** — the board will reboot into the new firmware.

## How to tell the flash succeeded

- The UF2 drive (e.g. `RAK4631`) disappears from **This PC**
- The board reboots and runs the new firmware or bootloader
- The copy progress bar was nearly complete when the dialog appeared

## Why it happens

### 1. Windows thinks it is copying to a real USB drive

The bootloader exposes a **GhostFAT virtual FAT filesystem** over USB Mass Storage (MSC). Drag-and-drop uses the normal file-copy path, not a dedicated flashing protocol.

### 2. The bootloader only cares about UF2 blocks

Each 512-byte sector that is a valid UF2 block has its payload written directly to internal flash (`src/usb/uf2/ghostfat.c`, `write_block()`).

### 3. Last block → USB disconnect → reboot

After the last UF2 block is written (`src/usb/msc_uf2.c`, `tud_msc_write10_complete_cb()`):

1. DFU is marked complete (`DFU_UPDATE_APP_COMPLETE`)
2. Bootloader settings are saved to flash
3. `usb_teardown()` disconnects USB (`src/usb/usb.c`)
4. The new application is started (`bootloader_app_start()`)

This is **by design**: UF2 devices are expected to reboot as soon as flashing finishes. The bootloader does not wait for Windows to finish copy bookkeeping.

### 4. Race between Windows and the bootloader

| Phase | Windows | Bootloader |
|-------|---------|------------|
| ① Data write | Copy `.uf2` contents to the virtual drive | Parse UF2 blocks → write flash |
| ② Metadata | Update FAT, directory entry, timestamps | Virtual drive still up (data ignored) |
| ③ Close file | Flush cache, close handle | Drive must still be present |

The bootloader finishes at the end of **①** and removes the drive. Windows still needs **②** and **③**, which fails with `0x800703EE`.

## FAQ

**Retry?** Usually useless — the drive is already gone. If the board rebooted into the new firmware, click **Skip**.

**Will Skip corrupt the firmware?** No. Flash programming completed when the last UF2 block was written. The dialog only reflects failed copy cleanup on the host.

**Other UF2 boards?** Any Adafruit-style nRF52 UF2 bootloader on Windows can show this. Linux/macOS often show no dialog, but the device still disconnects after flash.

**Avoid the dialog?** Use serial DFU (`adafruit-nrfutil`), J-Link (`.hex`), or BLE OTA (`*-ota.zip`) instead of drag-and-drop.

## References

| Symbol / path | Role |
|---------------|------|
| `0x800703EE` | `ERROR_FILE_INVALID` (1006) |
| `src/usb/uf2/ghostfat.c` | GhostFAT + UF2 → flash |
| `src/usb/msc_uf2.c` | MSC write complete → DFU finalize |
| `src/usb/usb.c` | `usb_teardown()` |
