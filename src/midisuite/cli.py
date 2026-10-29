"""Command line interface: dump, restore and inspect an SMC-Mixer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .devices.smc_mixer import (
    BLOCK_GLOBAL,
    BLOCK_USER,
    GLOBAL_SIZE,
    USER_SIZE,
    SmcMixer,
)
from .transport import (
    BaseTransport,
    TransportError,
    find_config_port,
    list_ble_devices,
    list_ports,
    open_transport,
)


def _open(args) -> BaseTransport:
    if args.ble:
        return open_transport(ble_address=args.ble)
    port = args.port or find_config_port()
    if not port:
        raise SystemExit(
            "device not found: connect the SMC-Mixer via USB or pass --ble <address>"
        )
    return open_transport(port=port)


def _read_mixer(transport: BaseTransport) -> SmcMixer:
    globals_ = transport.read_chunked(BLOCK_GLOBAL, 0, GLOBAL_SIZE)
    user = transport.read_chunked(BLOCK_USER, 0, USER_SIZE)
    return SmcMixer(globals_, user)


def cmd_ports(args) -> int:
    usb = list_ports()
    for port in usb:
        print(f"USB  {port}")
    for dev in list_ble_devices():
        print(f"BLE  {dev.label}")
    if not usb and not list_ble_devices():
        print("no MIDI ports or BLE devices found")
    return 0


def cmd_info(args) -> int:
    with _open(args) as transport:
        source = getattr(transport, "port_name", None) or getattr(
            transport, "address", "?"
        )
        print(f"transport: {type(transport).__name__}  ({source})")
        print(f"name:      {transport.name_and_version()}")
    return 0


def cmd_dump(args) -> int:
    with _open(args) as transport:
        name = transport.name_and_version()
        mixer = _read_mixer(transport)
    out = Path(args.output)
    if out.suffix.lower() == ".json":
        out.write_text(mixer.to_json(name), encoding="utf-8")
    else:
        out.write_bytes(bytes(mixer.user))
    print(f"saved {out} ({len(mixer.user)} bytes, device {name!r})")
    return 0


def cmd_restore(args) -> int:
    path = Path(args.input)
    raw = path.read_bytes()
    if path.suffix.lower() == ".json":
        mixer = SmcMixer.from_json(raw.decode("utf-8"))
    else:
        mixer = SmcMixer(bytes(GLOBAL_SIZE), raw)
    if args.dry_run:
        print(f"would write {len(mixer.user)} bytes to block {BLOCK_USER}")
        return 0
    with _open(args) as transport:
        transport.write_chunked(BLOCK_USER, 0, bytes(mixer.user))
        transport.commit(BLOCK_USER)
    print(f"restored {path} to the device")
    return 0


def cmd_factory(args) -> int:
    mixer = SmcMixer.default()
    if args.dry_run:
        print("would write the built-in defaults")
        return 0
    with _open(args) as transport:
        transport.write_chunked(BLOCK_USER, 0, bytes(mixer.user))
        transport.commit(BLOCK_USER)
    print("factory defaults written")
    return 0


def cmd_copy_preset(args) -> int:
    with _open(args) as transport:
        mixer = _read_mixer(transport)
        source = mixer.preset(args.source - 1)
        mixer.set_preset(args.target - 1, source)
        transport.write_chunked(BLOCK_USER, 0, bytes(mixer.user))
        transport.commit(BLOCK_USER)
    print(f"preset {args.source} copied to preset {args.target}")
    return 0


def cmd_get(args) -> int:
    with _open(args) as transport:
        data = transport.read_chunked(args.block, args.addr, args.length)
    print(data.hex(" "))
    return 0


def cmd_put(args) -> int:
    data = bytes.fromhex(args.data.replace(" ", ""))
    with _open(args) as transport:
        transport.write(args.block, args.addr, data)
        if args.block in (BLOCK_GLOBAL, BLOCK_USER):
            transport.commit(args.block)
    print(f"wrote {len(data)} bytes to block {args.block} @ {args.addr:#x}")
    return 0


def cmd_raw(args) -> int:
    packet = bytes.fromhex(args.packet.replace(" ", ""))
    with _open(args) as transport:
        reply = transport.send(packet)
    print(reply.hex(" "))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="midisuite", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--port", help="MIDI port name (default: auto detect)")
    parser.add_argument(
        "--ble", metavar="ADDRESS", help="use BLE instead of USB (device MAC)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list MIDI ports").set_defaults(func=cmd_ports)
    sub.add_parser("info", help="query device name and version").set_defaults(func=cmd_info)

    dump = sub.add_parser("dump", help="read the configuration into a file")
    dump.add_argument("output")
    dump.set_defaults(func=cmd_dump)

    restore = sub.add_parser("restore", help="write a configuration file to the device")
    restore.add_argument("input")
    restore.add_argument("--dry-run", action="store_true")
    restore.set_defaults(func=cmd_restore)

    factory = sub.add_parser(
        "reset", aliases=["factory"], help="write the built-in default preset"
    )
    factory.add_argument("--dry-run", action="store_true")
    factory.set_defaults(func=cmd_factory)

    get = sub.add_parser("get", help="read raw bytes from a memory block")
    get.add_argument("block", type=lambda s: int(s, 0))
    get.add_argument("addr", type=lambda s: int(s, 0))
    get.add_argument("length", type=lambda s: int(s, 0))
    get.set_defaults(func=cmd_get)

    put = sub.add_parser("put", help="write raw hex bytes to a memory block")
    put.add_argument("block", type=lambda s: int(s, 0))
    put.add_argument("addr", type=lambda s: int(s, 0))
    put.add_argument("data", help="hex byte string")
    put.set_defaults(func=cmd_put)

    copy = sub.add_parser("copy-preset", help="copy one preset over the other")
    copy.add_argument("source", type=int, choices=[1, 2])
    copy.add_argument("target", type=int, choices=[1, 2])
    copy.set_defaults(func=cmd_copy_preset)

    raw = sub.add_parser("raw", help="send one raw packet (hex) and print the reply")
    raw.add_argument("packet")
    raw.set_defaults(func=cmd_raw)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (TransportError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
