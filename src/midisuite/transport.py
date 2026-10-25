"""Transports for SINCO / M-VAVE devices.

Both transports speak the same packet protocol (``protocol.py``):

* **USB MIDI** — packets are 8→7 bit packed and wrapped in a system exclusive
  message (``F0 … F7``).
* **BLE** — packets are written unchanged to the vendor characteristic
  ``AE41`` of the ``AE40`` service and received as notifications on ``AE42``.

The public API is identical, so the GUI and the CLI do not care which
transport is used.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Iterable

import rtmidi

from . import protocol

CONFIG_PORT_HINTS = ("SMC-Mixer-Private", "SMC-Mixer", "SINCO")

BLE_SERVICE = "0000ae40-0000-1000-8000-00805f9b34fb"
BLE_WRITE = "0000ae41-0000-1000-8000-00805f9b34fb"
BLE_NOTIFY = "0000ae42-0000-1000-8000-00805f9b34fb"


class TransportError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# USB MIDI
# --------------------------------------------------------------------------
def list_ports() -> list[str]:
    """Return the available MIDI output ports (empty if ALSA is unavailable)."""
    try:
        device = rtmidi.MidiOut()
        return list(device.get_ports())
    except Exception:  # headless systems may have no ALSA sequencer
        return []


def find_config_port(hints: Iterable[str] = CONFIG_PORT_HINTS) -> str | None:
    ports = list_ports()
    for hint in hints:
        for port in ports:
            if hint in port and "Private" in port:
                return port
    for hint in hints:
        for port in ports:
            if hint in port and "Master" not in port:
                return port
    return None


# --------------------------------------------------------------------------
# Shared request/response logic
# --------------------------------------------------------------------------
class BaseTransport:
    """Protocol operations shared by the USB and BLE transports."""

    max_write_chunk = 1000

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self._queue_lock = threading.Lock()
        self._inbound: list[bytes] = []
        self._outbound: list[bytes] = []

    # -- transport primitive ----------------------------------------------
    def send(self, packet: bytes, expect: int | None = None) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- monitor queues ----------------------------------------------------
    def _record_inbound(self, packet: bytes) -> None:
        with self._queue_lock:
            self._inbound.append(packet)
            if len(self._inbound) > 512:
                del self._inbound[:-512]

    def _record_outbound(self, packet: bytes) -> None:
        with self._queue_lock:
            self._outbound.append(packet)
            if len(self._outbound) > 512:
                del self._outbound[:-512]

    def pop_raw_packet(self) -> bytes | None:
        with self._queue_lock:
            return self._inbound.pop(0) if self._inbound else None

    def pop_sent_packet(self) -> bytes | None:
        with self._queue_lock:
            return self._outbound.pop(0) if self._outbound else None

    # -- high level operations --------------------------------------------
    def request(self, packet: bytes, expect: int | None = None) -> protocol.Packet:
        return protocol.Packet.parse(self.send(packet, expect))

    def name_and_version(self) -> str:
        packet = self.request(protocol.build_name_request())
        return packet.payload.decode("utf-8", "replace").rstrip("\x00")

    def read(self, block: int, addr: int, length: int) -> bytes:
        if length > 0x1000:
            raise ValueError("read requests are limited to 4096 bytes")
        reply = self.request(protocol.build_read(block, addr, length), expect=8 + length)
        rblock, raddr, rlen, data = protocol.parse_memory_payload(reply.payload)
        if (rblock, raddr) != (block, addr) or len(data) < length:
            raise TransportError(
                "unexpected reply: "
                f"block {rblock}, address {raddr:#x}, length {rlen}"
            )
        return data[:length]

    def read_chunked(self, block: int, addr: int, length: int, chunk: int = 1000) -> bytes:
        data = bytearray()
        while len(data) < length:
            size = min(chunk, length - len(data))
            data += self.read(block, addr + len(data), size)
        return bytes(data)

    def write(self, block: int, addr: int, data: bytes) -> None:
        self.request(protocol.build_write(block, addr, data))

    def write_chunked(
        self, block: int, addr: int, data: bytes, chunk: int | None = None
    ) -> None:
        step = chunk or self.max_write_chunk
        for offset in range(0, len(data), step):
            self.write(block, addr + offset, data[offset : offset + step])
            time.sleep(0.02)

    def erase(self, block: int, addr: int) -> None:
        self.request(protocol.build_erase(block, addr))


class MidiTransport(BaseTransport):
    """Configuration transport over USB MIDI (SysEx with base-128 packing)."""

    def __init__(self, port_name: str | None = None, timeout: float = 5.0):
        super().__init__(timeout)
        self.port_name = port_name or find_config_port()
        if not self.port_name:
            raise TransportError(
                "no SINCO/SMC-Mixer MIDI port found; connect the device via USB"
            )
        self._in = rtmidi.MidiIn()
        in_ports = self._in.get_ports()
        in_index = next(
            (i for i, name in enumerate(in_ports) if name == self.port_name), None
        )
        if in_index is None:
            in_index = next(
                (i for i, name in enumerate(in_ports) if self.port_name in name), None
            )
        if in_index is None:
            raise TransportError(f"input port not found: {self.port_name}")
        self._in.open_port(in_index)
        self._in.ignore_types(sysex=False, timing=False, active_sense=False)

        self._out = rtmidi.MidiOut()
        out_ports = self._out.get_ports()
        out_index = next(
            (i for i, name in enumerate(out_ports) if name == self.port_name), None
        )
        if out_index is None:
            out_index = next(
                (i for i, name in enumerate(out_ports) if self.port_name in name), None
            )
        if out_index is None:
            raise TransportError(f"output port not found: {self.port_name}")
        self._out.open_port(out_index)

        self._buffer = bytearray()
        self._in.set_callback(self._on_message)

    def _on_message(self, message, _data=None) -> None:
        data = bytes(message[0])
        if data[:1] == b"\xf0":
            with self._queue_lock:
                self._buffer.extend(data[1:-1])

    def send(self, packet: bytes, expect: int | None = None) -> bytes:
        attempts = 3
        for attempt in range(attempts):
            with self._queue_lock:
                self._buffer.clear()
            self._out.send_message([0xF0, *protocol.base128_encode(packet), 0xF7])
            self._record_outbound(packet)

            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                with self._queue_lock:
                    raw = bytes(self._buffer)
                if raw:
                    decoded = protocol.base128_decode(raw)
                    try:
                        reply = protocol.Packet.parse(decoded)
                    except ValueError:
                        reply = None
                    if reply is not None and (
                        expect is None or len(reply.payload) >= expect
                    ):
                        self._record_inbound(decoded)
                        return decoded
                time.sleep(0.01)
            if attempt + 1 < attempts:
                time.sleep(0.15)
        raise TransportError("timeout waiting for device reply")

    def close(self) -> None:
        try:
            self._in.close_port()
            self._out.close_port()
        except Exception:
            pass


# --------------------------------------------------------------------------
# BLE (BlueZ D-Bus)
# --------------------------------------------------------------------------
@dataclass
class BleDevice:
    address: str
    name: str
    connected: bool = False
    config_service: bool = False

    @property
    def label(self) -> str:
        state = "connected" if self.connected else "paired"
        return f"{self.name} ({self.address}) · {state}"


def list_ble_devices(scan_seconds: float = 0.0) -> list[BleDevice]:
    """Return known BlueZ devices, optionally running a fresh discovery first."""
    try:
        return _run_once(_list_ble_devices_async(scan_seconds))
    except Exception:
        return []


def _run_once(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _list_ble_devices_async(scan_seconds: float) -> list[BleDevice]:
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        root = bus.get_proxy_object(
            "org.bluez", "/", await bus.introspect("org.bluez", "/")
        )
        manager = root.get_interface("org.freedesktop.DBus.ObjectManager")

        if scan_seconds > 0:
            objects = await manager.call_get_managed_objects()
            adapter_path = next(
                (
                    path
                    for path, ifaces in objects.items()
                    if "org.bluez.Adapter1" in ifaces
                ),
                None,
            )
            if adapter_path:
                adapter = bus.get_proxy_object(
                    "org.bluez",
                    adapter_path,
                    await bus.introspect("org.bluez", adapter_path),
                ).get_interface("org.bluez.Adapter1")
                try:
                    await adapter.call_start_discovery()
                    await asyncio.sleep(scan_seconds)
                except Exception:
                    pass
                finally:
                    try:
                        await adapter.call_stop_discovery()
                    except Exception:
                        pass

        objects = await manager.call_get_managed_objects()
        devices: list[BleDevice] = []
        for path, ifaces in objects.items():
            device = ifaces.get("org.bluez.Device1")
            if not device:
                continue
            address = device.get("Address")
            if not address:
                continue
            name = device.get("Alias") or device.get("Name") or address.value
            raw_uuids = device.get("UUIDs")
            if hasattr(raw_uuids, "value"):
                raw_uuids = raw_uuids.value
            uuids = [str(entry).lower() for entry in (raw_uuids or [])]
            devices.append(
                BleDevice(
                    address=str(address.value),
                    name=str(name.value) if hasattr(name, "value") else str(name),
                    connected=bool(device["Connected"].value)
                    if "Connected" in device
                    else False,
                    config_service=any(uuid.startswith(BLE_SERVICE[:8]) for uuid in uuids),
                )
            )
        devices.sort(key=lambda d: (not d.config_service, d.name.lower()))
        return devices
    finally:
        bus.disconnect()


def extract_packet(buffer: bytearray, expect: int | None = None) -> bytes | None:
    """Pop one complete raw packet from a byte buffer.

    BLE notifications are arbitrary chunks: a reply may arrive in several
    notifications, and several replies may be buffered.  The function skips
    leading noise, waits for a whole packet (header + length + payload +
    checksum) and validates the checksum.
    """
    while len(buffer) >= 7:
        if buffer[0] != 0x00:
            del buffer[0]
            continue
        if buffer[1] != 0x59:
            del buffer[:2]
            continue
        length = int.from_bytes(buffer[3:6], "little")
        total = 7 + length
        if len(buffer) < total:
            return None
        candidate = bytes(buffer[:total])
        try:
            parsed = protocol.Packet.parse(candidate)
        except ValueError:
            del buffer[:1]
            continue
        del buffer[:total]
        if expect is None or len(parsed.payload) >= expect:
            return candidate
    return None


class _AsyncRunner:
    """A private asyncio loop running in a daemon thread."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, coro, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout)

    def stop(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass
        self.thread.join(timeout=2.0)


class BleTransport(BaseTransport):
    """Configuration transport over the vendor BLE GATT service (AE40)."""

    def __init__(self, address: str, timeout: float = 8.0):
        super().__init__(timeout)
        self.address = address
        self.max_write_chunk = 180
        self._runner = _AsyncRunner()
        self._bus = None
        self._notify_iface = None
        self._write_iface = None
        self._rx = bytearray()
        self._rx_event: asyncio.Event | None = None
        try:
            self._runner.call(self._open(), timeout=40.0)
        except TransportError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise TransportError(f"BLE connection failed: {exc}") from exc

    # -- async plumbing ----------------------------------------------------
    def _on_properties(self, _interface, changed, _invalid) -> None:
        value = changed.get("Value")
        if value is None:
            return
        self._rx.extend(bytes(value.value))
        if self._rx_event is not None:
            self._rx_event.set()

    async def _open(self) -> None:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus

        self._rx_event = asyncio.Event()
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        root = self._bus.get_proxy_object(
            "org.bluez", "/", await self._bus.introspect("org.bluez", "/")
        )
        manager = root.get_interface("org.freedesktop.DBus.ObjectManager")

        device_path = None
        device_connected = False
        for _ in range(30):
            objects = await manager.call_get_managed_objects()
            for path, ifaces in objects.items():
                device = ifaces.get("org.bluez.Device1")
                if not device:
                    continue
                address = device.get("Address")
                if address and str(address.value).upper() == self.address.upper():
                    device_path = path
                    device_connected = bool(
                        device["Connected"].value
                        if "Connected" in device
                        else False
                    )
                    break
            if device_path:
                break
            await asyncio.sleep(0.2)
        if not device_path:
            raise TransportError(
                f"BLE device {self.address} not found; pair it first "
                "(bluetoothctl) or scan for it"
            )

        device_obj = self._bus.get_proxy_object(
            "org.bluez",
            device_path,
            await self._bus.introspect("org.bluez", device_path),
        )
        if not device_connected:
            device_iface = device_obj.get_interface("org.bluez.Device1")
            try:
                await device_iface.call_connect()
            except Exception as exc:
                raise TransportError(f"cannot connect to {self.address}: {exc}") from exc

        write_path = notify_path = None
        for _ in range(40):
            objects = await manager.call_get_managed_objects()
            for path, ifaces in objects.items():
                char = ifaces.get("org.bluez.GattCharacteristic1")
                if not char:
                    continue
                uuid = str(char.get("UUID").value).lower() if char.get("UUID") else ""
                if uuid == BLE_WRITE:
                    write_path = path
                elif uuid == BLE_NOTIFY:
                    notify_path = path
            if write_path and notify_path:
                break
            await asyncio.sleep(0.2)
        if not (write_path and notify_path):
            raise TransportError(
                "BLE configuration service not found (is the device in config mode?)"
            )

        write_obj = self._bus.get_proxy_object(
            "org.bluez",
            write_path,
            await self._bus.introspect("org.bluez", write_path),
        )
        self._write_iface = write_obj.get_interface("org.bluez.GattCharacteristic1")

        notify_obj = self._bus.get_proxy_object(
            "org.bluez",
            notify_path,
            await self._bus.introspect("org.bluez", notify_path),
        )
        self._notify_iface = notify_obj.get_interface("org.bluez.GattCharacteristic1")
        notify_props = notify_obj.get_interface("org.freedesktop.DBus.Properties")
        notify_props.on_properties_changed(self._on_properties)
        await self._notify_iface.call_start_notify()

        mtu = 23
        try:
            props = write_obj.get_interface("org.freedesktop.DBus.Properties")
            mtu = int((await props.call_get("org.bluez.GattCharacteristic1", "MTU")).value)
        except Exception:
            pass
        # packet overhead is 15 bytes; ATT payload is MTU - 3
        self.max_write_chunk = max(20, min(400, mtu - 3 - 15))

    async def _send_async(self, packet: bytes, expect: int | None) -> bytes:
        from dbus_fast import Variant

        self._rx.clear()
        self._record_outbound(packet)
        if self._write_iface is None:
            raise TransportError("BLE transport is closed")
        await self._write_iface.call_write_value(
            packet, {"type": Variant("s", "command")}
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        while True:
            reply = self._extract(expect)
            if reply is not None:
                self._record_inbound(reply)
                return reply
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TransportError("timeout waiting for device reply")
            self._rx_event.clear()
            try:
                await asyncio.wait_for(self._rx_event.wait(), remaining)
            except asyncio.TimeoutError:
                continue

    def _extract(self, expect: int | None) -> bytes | None:
        return extract_packet(self._rx, expect)

    async def _close_async(self) -> None:
        if self._notify_iface is not None:
            try:
                await self._notify_iface.call_stop_notify()
            except Exception:
                pass
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                pass

    # -- public API --------------------------------------------------------
    def send(self, packet: bytes, expect: int | None = None) -> bytes:
        return self._runner.call(self._send_async(packet, expect), self.timeout + 10)

    def close(self) -> None:
        try:
            self._runner.call(self._close_async(), timeout=5.0)
        except Exception:
            pass
        finally:
            self._runner.stop()


def open_transport(
    port: str | None = None, ble_address: str | None = None, timeout: float = 5.0
) -> BaseTransport:
    """Create a transport from a port name or a BLE address."""
    if ble_address:
        return BleTransport(ble_address, timeout=max(timeout, 8.0))
    return MidiTransport(port, timeout=timeout)
