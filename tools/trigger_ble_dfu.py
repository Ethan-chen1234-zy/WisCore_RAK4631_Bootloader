#!/usr/bin/env python3
"""
Trigger BLE Buttonless DFU on Meshtastic nRF52 boards (e.g. RAK4631 / Adafruit BLEDfu).

Replaces the Meshtastic Android app "firmware update / enabling DFU" step so you can
use nRF Device Firmware Update (AdaDFU) or nrfutil without opening the Meshtastic app.

Requires: pip install bleak

Typical workflow:
  1. Close Meshtastic app (nothing else should hold the BLE link).
  2. python trigger_ble_dfu.py --scan
  3. python trigger_ble_dfu.py --address AA:BB:CC:DD:EE:FF --forget
     (headless devices: default PIN 123456; override with --pin)
  4. Open nRF Device Firmware Update, AdaDFU, upload your .zip

If you see "Insufficient Authentication" (ATT 0x05):
  - Retry with --forget (clears a stale Windows bond), then run again.
  - Or remove the device in Windows Settings > Bluetooth, re-pair via Meshtastic app once,
    then run this script again.

This enters BLE DFU bootloader (GPREGRET=0xB1). It is NOT the same as:
  meshtastic --enter-dfu   (USB UF2 bootloader via Admin protobuf)
  pio upload / 1200bps     (USB UF2 via serial touch)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError:
    print("bleak is required: pip install bleak", file=sys.stderr)
    sys.exit(1)

# Nordic Legacy DFU (Adafruit BLEDfu) — default on RAK4631 when BLE_DFU_SECURE is unset.
LEGACY_SERVICE = "00001530-1212-EFDE-1523-785FEABCD123"
LEGACY_CONTROL = "00001531-1212-EFDE-1523-785FEABCD123"
LEGACY_PAYLOAD = bytes([0x01, 0x04])  # START_DFU + IMAGE_TYPE_APPLICATION

# Nordic Secure DFU (BLE_DFU_SECURE builds, e.g. some Seeed boards).
SECURE_SERVICE = "0000FE59-0000-1000-8000-00805F9B34FB"
SECURE_BUTTONLESS_NO_BONDS = "8EC90003-F315-4F60-9FB8-838830DAEA50"
SECURE_BUTTONLESS_WITH_BONDS = "8EC90004-F315-4F60-9FB8-838830DAEA50"
SECURE_PAYLOAD = bytes([0x01])

SUBSCRIPTION_SETTLE_S = 0.5
TRIGGER_TIMEOUT_S = 5.0
CONNECT_TIMEOUT_S = 20.0
PAIR_TIMEOUT_S = 12.0
DEFAULT_NAME_PREFIX = "Meshtastic"
DEFAULT_PIN = "123456"  # Meshtastic headless / FIXED_PIN default
IS_WINDOWS = sys.platform == "win32"


def _is_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "0x05" in text or "insufficient authentication" in text or "insufficient authorization" in text


def _has_char(client: BleakClient, service_uuid: str, char_uuid: str) -> bool:
    svc = client.services.get_service(service_uuid)
    if svc is None:
        return False
    return svc.get_characteristic(char_uuid) is not None


async def _trigger(
    client: BleakClient,
    char_uuid: str,
    payload: bytes,
    label: str,
    *,
    use_indicate: bool,
) -> None:
    """Enable notify/indicate, write trigger bytes, tolerate reboot-before-ACK."""
    notified = asyncio.Event()

    def _on_notify(_handle: int, _data: bytearray) -> None:
        notified.set()

    # bleak: pass winrt/cb kwargs only when needed; start_notify works for both on most backends.
    notify_kwargs: dict = {}
    if use_indicate:
        notify_kwargs["indication"] = True

    await client.start_notify(char_uuid, _on_notify, **notify_kwargs)
    await asyncio.sleep(SUBSCRIPTION_SETTLE_S)

    print(f"Writing {label} buttonless DFU trigger ({payload.hex()})...")
    try:
        await asyncio.wait_for(
            client.write_gatt_char(char_uuid, payload, response=True),
            timeout=TRIGGER_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, BleakError) as exc:
        # Device often reboots before the ATT write response arrives — expected.
        print(f"Write finished with {type(exc).__name__} (normal if device rebooted): {exc}")

    try:
        await asyncio.wait_for(notified.wait(), timeout=1.0)
        print("DFU trigger notification/indication received.")
    except asyncio.TimeoutError:
        pass

    try:
        await client.stop_notify(char_uuid)
    except BleakError:
        pass


async def _winrt_pair_with_pin(client: BleakClient, pin: str) -> None:
    """Windows MITM pairing with passkey — bleak.pair() only does Just Works (no PIN)."""
    from winrt.windows.devices.enumeration import (
        DeviceInformation,
        DevicePairingKinds,
        DevicePairingProtectionLevel,
        DevicePairingRequestedEventArgs,
        DevicePairingResultStatus,
    )

    backend = client._backend
    if backend._requester is None:
        raise BleakError("Cannot pair: not connected")

    device_information = await DeviceInformation.create_from_id_async(
        backend._requester.device_information.id
    )
    custom_pairing = device_information.pairing.custom

    def handler(_sender, args: DevicePairingRequestedEventArgs) -> None:
        kind = args.pairing_kind
        print(f"BLE pairing ceremony: {kind!r}")

        if kind == DevicePairingKinds.PROVIDE_PIN:
            print(f"Submitting BLE PIN {pin} (MITM pairing for DFU)...")
            args.accept_with_pin(pin)
        elif kind == DevicePairingKinds.DISPLAY_PIN:
            print(f"Peripheral displays PIN {args.pin} — confirm on device if needed.")
            args.accept()
        elif kind == DevicePairingKinds.CONFIRM_PIN_MATCH:
            print(f"Confirm PIN match (peripheral PIN {args.pin})...")
            args.accept()
        elif kind == DevicePairingKinds.CONFIRM_ONLY:
            args.accept()
        else:
            print(f"Unknown pairing kind {kind!r}, calling accept()")
            args.accept()

    token = custom_pairing.add_pairing_requested(handler)
    ceremony = (
        DevicePairingKinds.PROVIDE_PIN
        | DevicePairingKinds.DISPLAY_PIN
        | DevicePairingKinds.CONFIRM_PIN_MATCH
        | DevicePairingKinds.CONFIRM_ONLY
    )
    try:
        pairing_result = await asyncio.wait_for(
            custom_pairing.pair_with_protection_level_async(
                ceremony,
                DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION,
            ),
            timeout=PAIR_TIMEOUT_S,
        )
    finally:
        custom_pairing.remove_pairing_requested(token)

    if pairing_result.status not in (
        DevicePairingResultStatus.PAIRED,
        DevicePairingResultStatus.ALREADY_PAIRED,
    ):
        raise BleakError(f"PIN pairing failed: {pairing_result.status.name}")

    print(
        f"PIN pairing OK ({pairing_result.status.name}, "
        f"protection={pairing_result.protection_level_used.name})"
    )


async def _ensure_paired(client: BleakClient, pin: Optional[str]) -> None:
    """Raise link encryption to MITM level required by Meshtastic BLEDfu."""
    if not client.is_connected:
        raise BleakError("Cannot pair: not connected")

    if IS_WINDOWS and pin:
        await _winrt_pair_with_pin(client, pin)
        return

    try:
        await asyncio.wait_for(client.pair(), timeout=PAIR_TIMEOUT_S)
        print("BLE pairing completed.")
    except AssertionError as exc:
        raise BleakError(
            "BLE pairing failed: connection handle invalid after unpair/disconnect. "
            "Retry the command."
        ) from exc
    except asyncio.TimeoutError:
        print("pair() timed out (device may already be paired — continuing).")
    except BleakError as exc:
        if "not supported" in str(exc).lower():
            return
        raise


async def _forget_bond(address: str) -> None:
    """Drop OS bond on Windows. Must use a separate connect/unpair/disconnect cycle."""
    client = BleakClient(address, timeout=CONNECT_TIMEOUT_S, pair=False)
    try:
        await client.connect()
        print("Removing stale OS bond (unpair)...")
        try:
            await client.unpair()
            print("Unpair succeeded.")
        except BleakError as exc:
            print(f"unpair() note: {exc}")
    finally:
        try:
            if client.is_connected:
                await client.disconnect()
        except BleakError:
            pass
    # WinRT needs a moment before the next GATT session.
    await asyncio.sleep(1.0)


async def _connect_client(
    address: str,
    *,
    pair: bool,
    pin: Optional[str],
    forget: bool,
) -> BleakClient:
    if forget:
        await _forget_bond(address)

    # Do not use bleak pair=True on Windows — it skips PIN and cannot satisfy MITM.
    client = BleakClient(address, timeout=CONNECT_TIMEOUT_S, pair=False)
    await client.connect()
    if not client.is_connected:
        raise RuntimeError(f"Could not connect to {address}")

    if pair:
        await _ensure_paired(client, pin)

    # Windows: reconnect once after MITM pairing so encrypted ATT is active for DFU.
    if IS_WINDOWS and pair:
        print("Reconnecting after pairing (Windows)...")
        await client.disconnect()
        await asyncio.sleep(0.5)
        await client.connect()
        if not client.is_connected:
            raise RuntimeError(f"Could not reconnect to {address}")

    return client


async def _run_dfu_trigger(client: BleakClient) -> None:
    # Match Meshtastic Android: Secure (FE59) first, then Legacy (1530).
    if _has_char(client, SECURE_SERVICE, SECURE_BUTTONLESS_NO_BONDS):
        await _trigger(
            client,
            SECURE_BUTTONLESS_NO_BONDS,
            SECURE_PAYLOAD,
            "secure (no bonds)",
            use_indicate=True,
        )
    elif _has_char(client, SECURE_SERVICE, SECURE_BUTTONLESS_WITH_BONDS):
        await _trigger(
            client,
            SECURE_BUTTONLESS_WITH_BONDS,
            SECURE_PAYLOAD,
            "secure (bonds)",
            use_indicate=True,
        )
    elif _has_char(client, LEGACY_SERVICE, LEGACY_CONTROL):
        await _trigger(
            client,
            LEGACY_CONTROL,
            LEGACY_PAYLOAD,
            "legacy (Adafruit BLEDfu)",
            use_indicate=False,
        )
    else:
        raise RuntimeError(
            "No DFU service found (expected FE59 or 1530). "
            "Is this a Meshtastic nRF52 build with BLE enabled?"
        )


async def trigger_buttonless_dfu(
    address: str,
    *,
    pair: bool,
    pin: Optional[str],
    forget: bool,
) -> None:
    client = await _connect_client(address, pair=pair, pin=pin, forget=forget)
    try:
        await _run_dfu_trigger(client)
    except BleakError as exc:
        if _is_auth_error(exc) and not forget:
            print(
                "\nAuthentication failed — retrying after unpair + PIN re-pair...",
                file=sys.stderr,
            )
            await client.disconnect()
            client = await _connect_client(address, pair=True, pin=pin, forget=True)
            await _run_dfu_trigger(client)
        else:
            raise
    finally:
        if client.is_connected:
            await client.disconnect()

    print("Done. Device should be in BLE DFU mode — use nRF Device Firmware Update / AdaDFU.")


async def scan_devices(name_prefix: str, timeout: float) -> list[tuple[str, str]]:
    print(f"Scanning {timeout:.0f}s for BLE devices named '{name_prefix}'* ...")
    found: list[tuple[str, str]] = []
    devices = await BleakScanner.discover(timeout=timeout)
    for dev in devices:
        name = dev.name or ""
        if name.startswith(name_prefix):
            found.append((dev.address, name))
    return found


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trigger BLE Buttonless DFU on Meshtastic nRF52 (RAK4631 etc.)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--address",
        "-a",
        metavar="MAC",
        help="BLE address (e.g. AA:BB:CC:DD:EE:FF). Required unless --scan.",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan and list Meshtastic BLE devices, then exit.",
    )
    parser.add_argument(
        "--name-prefix",
        default=DEFAULT_NAME_PREFIX,
        help=f"Name prefix for --scan (default: {DEFAULT_NAME_PREFIX})",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=8.0,
        help="Seconds to scan (default: 8)",
    )
    parser.add_argument(
        "--no-pair",
        action="store_true",
        help="Skip BLE pairing (only if OS bond is already valid).",
    )
    parser.add_argument(
        "--pin",
        default=DEFAULT_PIN,
        help=f"BLE pairing PIN for headless FIXED_PIN devices (default: {DEFAULT_PIN}).",
    )
    parser.add_argument(
        "--forget",
        action="store_true",
        help="unpair() before connecting — fixes stale Windows bonds (ATT 0x05).",
    )
    return parser.parse_args(argv)


def _print_auth_help(pin: str) -> None:
    print(
        "\nInsufficient Authentication (ATT 0x05) — DFU needs MITM-encrypted BLE.\n"
        f"Headless Meshtastic nodes use fixed PIN {pin}.\n"
        "\nTry:\n"
        "  1. Close Meshtastic app and any other BLE tools.\n"
        f"  2. python trigger_ble_dfu.py -a <MAC> --forget --pin {pin}\n"
        "  3. If still failing: Windows Settings > Bluetooth > remove the device,\n"
        "     then run step 2 again.\n",
        file=sys.stderr,
    )


async def async_main(args: argparse.Namespace) -> int:
    if args.scan:
        devices = await scan_devices(args.name_prefix, args.scan_timeout)
        if not devices:
            print("No matching devices found.")
            return 1
        for addr, name in devices:
            print(f"  {addr}  {name}")
        return 0

    if not args.address:
        print("Error: --address is required (or use --scan to find devices).", file=sys.stderr)
        return 2

    pair = not args.no_pair
    pin = None if args.no_pair else str(args.pin)
    await trigger_buttonless_dfu(
        args.address.upper(),
        pair=pair,
        pin=pin,
        forget=args.forget,
    )
    return 0


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(asyncio.run(async_main(args)))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130) from None
    except BleakError as exc:
        print(f"BLE error: {exc}", file=sys.stderr)
        if _is_auth_error(exc):
            _print_auth_help(args.pin)
        else:
            print(
                "\nHints:\n"
                "  - Close Meshtastic app / other apps using the radio.\n"
                "  - Retry with --forget\n",
                file=sys.stderr,
            )
        raise SystemExit(1) from exc
    except AssertionError as exc:
        print(
            "BLE internal error (connection lost during pairing). Retry with --forget.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
