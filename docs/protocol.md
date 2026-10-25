# SMC-Mixer protocol — reverse engineering notes

Target: `Midi Suite.exe` 1.15.0 (Flutter, package `musical_instruments`,
Flutter assets compiled 2026-09-30) and the same application as an Android
arm64 build (`MidiSuite.apk`).

Tools used: `blutter` on the Android `libapp.so` (full class/method names and
ARM64 disassembly), string-table analysis of the Windows `app.so`, and live
traffic against an SMC-Mixer (USB and BLE).

## Transport

### USB MIDI

The application uses `winmm` (`midiOutLongMsg`) through the `flutter_midi_command`
platform channels.  Packets are 8→7 bit packed and wrapped in SysEx:

```
F0 <base128(packet)> F7
```

The same packing is used by the Cuvave/M-VAVE reference implementation
(`pferreir/cuvave-midi`), including the unconditional final partial byte.

### BLE

Service `0000ae40-0000-1000-8000-00805f9b34fb`:

| characteristic | UUID | direction |
|---|---|---|
| command | `0000ae41-…` (write-without-response) | host → device |
| state | `0000ae42-…` (notify) | device → host |

The GATT tunnel carries the **same raw packets** as USB, without the base-128
packing and without `F0`/`F7`: write the packet bytes to `AE41`, the reply
arrives as one or more notifications on `AE42`.  Large replies (for example a
1000-byte read) are split across notifications; the receiver must reassemble
them using the packet header and length field and verify the checksum.

This was verified on hardware: the name request
`00 59 11 00 00 00 FF` returns `SMC-Mixer_007` over GATT, and block reads
return the same bytes as over USB.

The header is `00 59`, exactly like the USB direction.  The older Android
build writes `00 B2` frames on this tunnel; the SMC-Mixer firmware used here
does not answer those, so an implementation should use the `00 59` framing on
both transports.

The second service `0000ae01/ae02` belongs to the OTA firmware channel and
answers with 17-byte random challenges; it is not used for configuration.

## Packet format

```
offset 0   00 59
offset 2   type
offset 3   payload length, u24 little endian
offset 6   payload
offset N   checksum = (~sum(bytes[6:N])) & 0xFF
```

Message types:

| type | name | payload |
|---|---|---|
| 0x00 | ACK | `01` (reply to a successful write/erase) |
| 0x11 | name/version | empty; reply `SMC-Mixer_007\0…` |
| 0x21 | erase | block u8, address u32 LE |
| 0x22 | write | block u8, address u32 LE, length u24 LE, data |
| 0x23 | read | block u8, address u32 LE, length u24 LE; reply = same + data |

Captured exchanges (base-128 encoded on the wire):

```
-> 00 59 11 00 00 00 ff
<- 00 59 11 1b 00 00 "SMC-Mixer_007" 00*14 <chk>

-> 00 59 23 08 00 00 04 00 00 00 00 01 00 00 fa
<- 00 59 23 09 00 00 04 00 00 00 00 01 00 00 01 f9

-> 00 59 22 ... <data>          (write)
<- 00 59 00 01 00 00 01 <chk>   (ACK)
```

Reads larger than 1000 bytes are split into 1000-byte requests by the original
application; the device answers each with one SysEx message of
`15 + length` bytes.

## Memory map

| block | contents | size |
|---|---|---|
| 4 | globals | 128 bytes (application reads at least 1) |
| 5 | user presets | 6282 bytes |

Block 5 = 2 × 3141-byte presets.  The device stores the **index of the active
preset in `globals[0]`** (0-based).  Writing that byte switches the device
immediately; there is no separate “load preset” command.  This was verified on
hardware: with the device running preset 2, writing `0` made the first encoder
send preset 1's CC 16 instead of preset 2's CC 30.

A preset:

| range | contents |
|---|---|
| 0 … 3052 | 43 button records, 71 bytes each |
| 3053 … 3100 | 8 knob records, 6 bytes each |
| 3101 … 3140 | 8 fader records, 5 bytes each |

Button record:

| offset | field |
|---|---|
| 0 | type (message mode) |
| 1 | channel (0-based) |
| 2 | data 1 (note / controller / bank MSB / program) |
| 3 | value 2 (off velocity / bank LSB / release value) |
| 4 | value 1 (on velocity / program / press value) |
| 5 | SysEx length |
| 6 … 69 | SysEx buffer (64 bytes) |
| 70 | LED setting (0xFF = follow the button, 0…127 = feedback note) |

Knob record: `type, curve, channel, controller, min, max`.
Fader record: `type, channel, controller, min, max`.

### Verified message modes

Buttons (type byte):

| value | behaviour (measured) |
|---|---|
| 0 | CC, single value (sends value 2 only) |
| 1 | CC toggle: value 1 on the first press, value 2 on the next |
| 2 | CC momentary: value 1 while pressed, value 2 on release |
| 3 | Program change: `CC0 = data1`, `CC32 = value2`, `PC = value1` |
| 4 | SysEx: the 64-byte buffer is sent as **raw bytes** (no F0/F7 added) |
| 5 | Note: `Note On = data1/value1`, `Note Off = data1` with velocity **0** (`value2` is ignored) |
| 6 | same as 4 (raw bytes) |
| 7, 8 | no message |

The LED byte (offset 70) does not change the button's outgoing message — see
the LED section below.

Knobs (type byte):

| value | behaviour (measured) |
|---|---|
| 0 | CC absolute: `value = round(position * max / 127)`; the encoder is continuous (no detents), byte 4 (`min`) had no observable effect |
| 1 | Channel pressure (absolute) |
| 2 | Pitch bend (14-bit) |
| 3 | CC relative: **`max` is sent for one direction, `min` for the other** (verified with max=127/min=0 → 127/0 and with the factory max=1/min=65 → 1/65) |

`curve` (byte 1) is a response-speed factor: with `curve = 8` the value moved
roughly 2–4× faster than with `curve = 1` for a comparable rotation.

Faders (type byte):

| value | behaviour (measured) |
|---|---|
| 0 | CC absolute (`data1` is the controller); the value is mapped to `min…max` (verified 16…32) |
| 1 | Channel pressure (aftertouch) |
| 2 | Pitch bend (14-bit) |
| 3, 4 | no message |

Channel numbers are stored 0-based; channel 15 produces status `0xBF`
(channel 16).

## Button LEDs (measured)

Byte 70 of a button record is the LED feedback setting.  Two modes are
verified:

* `0xFF` — the LED follows the button itself:
  * type 1 (CC toggle) — the LED latches: on after the first press, off after
    the second;
  * type 2 (CC momentary) — the LED is on only while the button is held;
  * holding Shift lights both Shift and the rightmost transport button
    (firmware behaviour, independent of the configuration).
* `0…127` — the byte is a **MIDI note number**.  Incoming Note On turns the
  LED on; Note Off (or Note On with velocity 0) turns it off.  Verified in a
  CC preset: with button 0's LED byte set to `16`, `90 10 7F` lit the first
  M LED and `90 10 00` cleared it, while the button's own CC message still
  worked.  The factory DAW preset stores each button's note number in this
  byte, which is why DAW feedback can light the LEDs.
  * The note is matched on the button's own MIDI channel (verified on channel
    1; the factory DAW preset puts all buttons on channel 1).
* `0x80…0xFE` — no note feedback was observed; treat these as custom/inactive
  values.

Writing the byte does **not** switch the LED on or off by itself.  With
`0xFF` the firmware only refreshes the LED on button events; with a note
value it only reacts to the matching incoming note.  The byte also does not
change while buttons are pressed, so it is a mode setting, not a live state.

Practical consequence: an application can either let the LED follow the
button (`0xFF`) or drive it directly with Note messages (a note number).
The latter works in CC presets too; it does not require DAW mode.

## Fader LEDs / soft-takeover indicators (measured)

The eight small LEDs under the knobs are **soft-takeover indicators for the
faders**, not knob LEDs.

* They respond to **Pitch Bend** on the fader's channel: the 14-bit value
  (LSB = `data1`, MSB = `data2`; the SMC-Mixer itself sends LSB = 0) is
  compared with the physical fader position.
* If the received value differs from the physical position, the LED blinks;
  when it matches (within the firmware's tolerance), the LED goes off.
* They are only active while the **DAW slot (Preset 1)** is selected.
  Verified by copying the CC preset into slot 1: the indicator still blinked;
  with the same preset in slot 2 it did not react.  Button LED note feedback,
  by contrast, works in both slots.
* No verified way exists to set the indicator steadily on or off independently
  of the fader position: it is a mismatch indicator.

Practical consequence: a host can drive the indicators with Pitch Bend
feedback for the fader's software value — the usual DAW soft-takeover
feedback.  To keep custom CC mappings **and** the indicators, copy the CC
preset into slot 1; this replaces the factory DAW preset, so keep a backup.
The editor's **Device → Test LED feedback…** dialog sends both the Note and
Pitch Bend messages for testing.

## Verified vs inferred

Verified on hardware:

* checksum, packet framing, base-128 packing;
* name/version reply `SMC-Mixer_007`;
* block sizes 4/5 and the 6282-byte user area;
* preset split 43×71 + 8×6 + 8×5 (SysEx markers appear every 71 bytes and
  restart at offset 3141);
* fader record layout and the factory values;
* the button type table and the value 1 / value 2 bytes;
* LED behaviour per button mode, the meaning of the LED byte (0xFF = local
  follow, 0…127 = feedback note) and that note feedback works in CC presets;
* the fader soft-takeover indicators, their Pitch Bend comparison and the
  restriction to the DAW slot;
* the knob field order (`channel` is the third byte) and absolute/relative
  behaviour of knob types 0 and 3 (in relative mode `min`/`max` are the two
  values that are sent);
* the active preset byte (`globals[0]`) and that writing it switches the
  device;
* write path and ACK (`write` + read-back round trip);
* the vendor application performs a factory reset by writing its bundled
  default image (`SSM.bin`) to block 5; this implementation writes a
  generated default preset instead and does not ship the vendor image.

Inferred from the Flutter UI code (dialog labels `Type / Channel / Curve / CC /
Min / Max`, `Type / Channel / CC / Min / Max`, `Type / Channel / Data 1 /
Data 2 / Option / SysEx (HEX)`):

* whether LED values 0x80…0xFE have any function (they produced no note
  feedback; not fully enumerated);
* whether the two SysEx types (4 and 6) differ in any way — both send the
  stored bytes unchanged;
* the meaning of the encoder `min` byte (byte 4) in absolute mode — it had no
  observable effect; the output is scaled by `max` (byte 5) instead.  In the
  factory preset the relative encoder uses `type=3, min=65, max=1`, which may
  be step/acceleration parameters for that mode.

## Application structure (context)

Recovered Flutter libraries of interest:

```
musical_instruments/core/usb/{sysex_codec,midi_transport,usb_connect}.dart
musical_instruments/core/data/addr_data.dart
musical_instruments/core/devices/smc_mixer/smc_mixer_data.dart
musical_instruments/desktop/pages/smc_mixer/{smc_mixer_desktop_page,
    smc_mixer_device_panel,smc_mixer_number_field}.dart
```

The application supports ~30 devices (SMK-25/25II/25Mini/37, SMC-PAD,
SMC-PAD-Pocket, Starry Pad, FootCtrl, FootCtrlPlus, IRBox, …).  Each device has
its own block map and data classes; only the SMC-Mixer was mapped here.
