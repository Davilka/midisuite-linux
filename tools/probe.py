#!/usr/bin/env python3
"""Interactive probe for mapping SMC-Mixer controls to preset bytes.

Run from the project root:

    python tools/probe.py backup out.bin
    python tools/probe.py listen 60
    python tools/probe.py patch --preset 0 --control button --index 0 --byte 2 --value 64
    python tools/probe.py restore out.bin

``patch`` writes a single byte inside one control record and nothing else.
Use ``restore`` (or ``patch`` with the old value) to undo it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from midisuite.devices.smc_mixer import (  # noqa: E402
    BLOCK_GLOBAL,
    BLOCK_USER,
    BUTTON_COUNT,
    BUTTON_SIZE,
    GLOBAL_SIZE,
    KNOB_COUNT,
    KNOB_OFFSET,
    KNOB_SIZE,
    PRESET_SIZE,
    SLIDER_COUNT,
    SLIDER_OFFSET,
    SLIDER_SIZE,
    USER_SIZE,
    SmcMixer,
)
from midisuite.transport import MidiTransport, find_config_port  # noqa: E402

CONTROL_LAYOUT = {
    "button": (BUTTON_COUNT, BUTTON_SIZE, 0),
    "knob": (KNOB_COUNT, KNOB_SIZE, KNOB_OFFSET),
    "slider": (SLIDER_COUNT, SLIDER_SIZE, SLIDER_OFFSET),
}


def open_transport() -> MidiTransport:
    port = find_config_port()
    if not port:
        raise SystemExit("device not found")
    return MidiTransport(port)


def read_mixer(transport: MidiTransport) -> SmcMixer:
    return SmcMixer(
        transport.read_chunked(BLOCK_GLOBAL, 0, GLOBAL_SIZE),
        transport.read_chunked(BLOCK_USER, 0, USER_SIZE),
    )


def cmd_backup(args) -> int:
    with open_transport() as transport:
        mixer = read_mixer(transport)
        name = transport.name_and_version()
    Path(args.output).write_bytes(bytes(mixer.user))
    print(f"saved {args.output}: {len(mixer.user)} bytes, device {name}")
    return 0


def cmd_restore(args) -> int:
    data = Path(args.input).read_bytes()
    if len(data) != USER_SIZE:
        raise SystemExit(f"expected {USER_SIZE} bytes, got {len(data)}")
    with open_transport() as transport:
        transport.write_chunked(BLOCK_USER, 0, data)
    print(f"restored {args.input}")
    return 0


def control_offset(preset: int, control: str, index: int) -> int:
    count, size, base = CONTROL_LAYOUT[control]
    if not 0 <= index < count:
        raise SystemExit(f"{control} index must be 0..{count - 1}")
    return preset * PRESET_SIZE + base + index * size


def cmd_patch(args) -> int:
    with open_transport() as transport:
        mixer = read_mixer(transport)
        offset = control_offset(args.preset, args.control, args.index)
        record = bytearray(mixer.user[offset : offset + CONTROL_LAYOUT[args.control][1]])
        before = bytes(record)
        if not 0 <= args.byte < len(record):
            raise SystemExit(f"byte must be 0..{len(record) - 1}")
        record[args.byte] = args.value & 0xFF
        mixer.user[offset : offset + len(record)] = record
        transport.write_chunked(BLOCK_USER, 0, bytes(mixer.user))
        after = bytes(record)
    print(f"offset {offset} ({args.control} {args.index + 1}, preset {args.preset + 1})")
    print(f"  before: {before.hex(' ')}")
    print(f"  after : {after.hex(' ')}")
    return 0


def cmd_listen(args) -> int:
    import rtmidi

    wanted = getattr(args, "port_filter", None)
    ports = [
        name
        for name in rtmidi.MidiOut().get_ports()
        if ("SMC-Mixer" in name or "SINCO" in name)
        and (not wanted or wanted in name)
    ]
    inputs = []
    for name in ports:
        midi_in = rtmidi.MidiIn()
        index = next(
            (i for i, p in enumerate(midi_in.get_ports()) if p == name), None
        )
        if index is None:
            continue
        midi_in.open_port(index)
        midi_in.ignore_types(sysex=False, timing=False, active_sense=False)
        inputs.append((name, midi_in))
        print(f"listening: {name}")

    start = time.time()
    try:
        while args.seconds == 0 or time.time() - start < args.seconds:
            for name, midi_in in inputs:
                message = midi_in.get_message()
                if message:
                    data = bytes(message[0])
                    stamp = time.strftime("%H:%M:%S")
                    print(f"{stamp} {name.split(':')[-1].strip():32s} {data.hex(' ')}", flush=True)
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        for _, midi_in in inputs:
            midi_in.close_port()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup")
    backup.add_argument("output")
    backup.set_defaults(func=cmd_backup)

    restore = sub.add_parser("restore")
    restore.add_argument("input")
    restore.set_defaults(func=cmd_restore)

    patch = sub.add_parser("patch")
    patch.add_argument("--preset", type=int, default=0)
    patch.add_argument("--control", choices=sorted(CONTROL_LAYOUT), required=True)
    patch.add_argument("--index", type=int, required=True)
    patch.add_argument("--byte", type=int, required=True)
    patch.add_argument("--value", type=lambda s: int(s, 0), required=True)
    patch.set_defaults(func=cmd_patch)

    listen = sub.add_parser("listen")
    listen.add_argument("seconds", type=int, nargs="?", default=0,
                        help="0 = until interrupted")
    listen.add_argument("--port-filter", default=None,
                        help="only listen to ports containing this substring")
    listen.set_defaults(func=cmd_listen)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
