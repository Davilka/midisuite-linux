#!/usr/bin/env python3
"""Send a repeating cycle of MIDI messages to the SMC-Mixer to test LED feedback.

Each candidate is "on" for 1.2 s and then "off".  The cycle repeats until the
process is killed.  Every action is logged with a timestamp so an observation
can be mapped back to the message that caused it.
"""

import time

import rtmidi

CANDIDATES = [
    ("CC20 ch1 (button 1)", [0xB0, 0x14, 0x7F], [0xB0, 0x14, 0x00]),
    ("CC28 ch2 (button 2)", [0xB1, 0x1C, 0x7F], [0xB1, 0x1C, 0x00]),
    ("Note20 ch1", [0x90, 0x14, 0x7F], [0x80, 0x14, 0x00]),
    ("CC20 ch1 value 64", [0xB0, 0x14, 0x40], [0xB0, 0x14, 0x00]),
    ("CC30 ch16 (knob)", [0xBF, 0x1E, 0x7F], [0xBF, 0x1E, 0x00]),
    ("CC52 ch1 (transport)", [0xB0, 0x34, 0x7F], [0xB0, 0x34, 0x00]),
    ("CC7 ch1", [0xB0, 0x07, 0x7F], [0xB0, 0x07, 0x00]),
    ("Note60 ch1", [0x90, 0x3C, 0x7F], [0x80, 0x3C, 0x00]),
]

ON = 1.2
OFF = 0.2
GAP = 0.8


def main() -> int:
    outs = []
    for name in rtmidi.MidiOut().get_ports():
        if "SINCO" in name:
            out = rtmidi.MidiOut()
            index = next(i for i, p in enumerate(out.get_ports()) if p == name)
            out.open_port(index)
            outs.append((name, out))
    if not outs:
        print("no SINCO ports")
        return 1
    for name, _ in outs:
        print("sending to", name, flush=True)

    cycle = 0
    try:
        while True:
            cycle += 1
            for label, on, off in CANDIDATES:
                stamp = time.strftime("%H:%M:%S")
                print(f"{stamp} cycle {cycle}: {label} ON", flush=True)
                for _, out in outs:
                    out.send_message(on)
                time.sleep(ON)
                stamp = time.strftime("%H:%M:%S")
                print(f"{stamp} cycle {cycle}: {label} OFF", flush=True)
                for _, out in outs:
                    out.send_message(off)
                time.sleep(OFF)
                time.sleep(GAP)
    except KeyboardInterrupt:
        pass
    finally:
        for _, out in outs:
            out.close_port()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
