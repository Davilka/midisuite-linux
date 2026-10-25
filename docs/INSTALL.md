# Installation

The editor runs on Linux (x86-64) and talks to the SMC-Mixer through the ALSA
MIDI sequencer (PipeWire and JACK are fine, they expose ALSA MIDI ports).

There are three ways to install it:

| Option | Best for | Needs Python? |
|---|---|---|
| [1. Prebuilt bundle](#1-prebuilt-bundle-from-releases) | most users | no |
| [2. Wheel with pip / pipx](#2-wheel-with-pip-or-pipx) | users who manage Python environments | yes |
| [3. From source](#3-from-source) | development and patches | yes |

## Requirements

* Linux x86-64
* A working ALSA MIDI stack (`/dev/snd/seq`; PipeWire/WirePlumber or JACK are
  supported)
* The SMC-Mixer connected over **USB** (configuration port
  `SINCO … SMC-Mixer-Private`) or **Bluetooth LE**, paired with BlueZ
* For the bundle: `libgl1`, `libegl1`, `libxkbcommon-x11-0`, `libfontconfig1`
  (usually already installed on a desktop system)

The controller does not need any special udev rules: the editor uses the ALSA
sequencer, not the raw USB device.

## 1. Prebuilt bundle from Releases

1. Open the repository’s **Releases** page and download
   `midisuite-gui-linux-x86_64-<version>.tar.gz`.
2. Verify the download (optional):

   ```bash
   sha256sum midisuite-gui-linux-x86_64-<version>.tar.gz
   # compare with the SHA256SUMS asset of the same release
   ```

3. Unpack and run:

   ```bash
   tar xzf midisuite-gui-linux-x86_64-<version>.tar.gz
   cd midisuite-gui-linux-x86_64
   ./midisuite-gui
   ```

4. Install it into your home directory (recommended):

   ```bash
   mkdir -p ~/.local/opt ~/.local/bin \
            ~/.local/share/applications \
            ~/.local/share/icons/hicolor/scalable/apps

   rm -rf ~/.local/opt/midisuite
   mv midisuite-gui-linux-x86_64 ~/.local/opt/midisuite
   ln -sf ~/.local/opt/midisuite/midisuite-gui ~/.local/bin/midisuite-gui

   cp ~/.local/opt/midisuite/contrib/midisuite.svg \
      ~/.local/share/icons/hicolor/scalable/apps/midisuite.svg

   sed "s|Exec=midisuite-gui|Exec=$HOME/.local/opt/midisuite/midisuite-gui|" \
       ~/.local/opt/midisuite/contrib/midisuite.desktop \
       > ~/.local/share/applications/midisuite.desktop

   update-desktop-database ~/.local/share/applications 2>/dev/null || true
   ```

   Make sure `~/.local/bin` is in your `PATH`; the application then starts
   from the menu as **Midi Suite** or from a terminal as `midisuite-gui`.

The bundle contains everything it needs (Python, Qt, python-rtmidi).  It also
ships `README.md`, `LICENSE`, `docs/` and `contrib/` (desktop file and icon).

## 2. Wheel with pip or pipx

Download `midisuite_linux-<version>-py3-none-any.whl` from Releases, then:

```bash
python -m venv ~/.local/share/midisuite/venv
~/.local/share/midisuite/venv/bin/pip install --upgrade pip
~/.local/share/midisuite/venv/bin/pip install midisuite_linux-<version>-py3-none-any.whl
ln -sf ~/.local/share/midisuite/venv/bin/midisuite-gui ~/.local/bin/midisuite-gui
```

or, with [pipx](https://pipx.pypa.io/):

```bash
pipx install midisuite_linux-<version>-py3-none-any.whl
```

The wheel pulls in `PySide6` and `python-rtmidi`; on distributions where
`python-rtmidi` has no wheel, the ALSA headers are required
(Debian/Ubuntu: `sudo apt install libasound2-dev`).

## 3. From source

```bash
git clone https://github.com/Davilka/midisuite-linux.git
cd midisuite-linux
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"      # omit [dev] for a normal install
```

Run it:

```bash
midisuite-gui
```

or, without installing entry points:

```bash
python -m midisuite.ui.app
```

The command line interface is available as `midisuite`:

```bash
midisuite --help
midisuite info
midisuite dump cfg.json
```

## First run

1. Connect the SMC-Mixer with a USB cable, or pair it over Bluetooth LE:

   ```bash
   bluetoothctl scan on
   bluetoothctl pair AA:BB:CC:DD:EE:FF   # use your device address
   bluetoothctl trust AA:BB:CC:DD:EE:FF
   ```

2. Start `midisuite-gui`.
3. Select `USB  SINCO … SMC-Mixer-Private` or `BLE  SMC-Mixer (address)` and
   press **Connect**.  The **Scan BLE** button runs a fresh discovery if the
   device is not listed yet.
4. Press **Read from device**.
5. Click a knob, fader or button on the panel and edit it on the right.
6. Press **Save to device** to write the configuration back.

The device keeps two independent presets.  After **Read** the editor selects
the slot the device is currently running (marked “active on device” in the
selector); use **Activate on device** to switch the hardware to the other
slot.

The **Test message** button sends the selected control’s MIDI to a virtual
output port called **MidiSuite Test**, which appears in your DAW after the
first click.  Use it to verify the mapping without touching the hardware.

### LED feedback

The device has three groups of lights:

* **Button LEDs** (M/S/R/□ and the transport row).  Byte 70 of a button record
  selects the mode:
  * `0xFF` — the LED follows the button itself (toggle latches, momentary
    lights only while held);
  * `0…127` — the LED is controlled by incoming **Note On/Off** with that note
    number.  Set it in the inspector: **LED → MIDI note…**.
  Note feedback works in CC presets too.
* **Eight LEDs under the knobs** — these are **fader soft-takeover
  indicators**, not knob LEDs.  They respond to **Pitch Bend** on the fader’s
  channel: a value different from the physical fader makes the LED blink, a
  matching value turns it off.  They only work while the **DAW slot
  (Preset 1)** is active.
* **Transport LEDs** behave like the other button LEDs.

Open **Device → Test LED feedback…** to send these messages without a DAW.
Pick the MIDI output (the USB `…SMC-Mixer-Master` port is selected
automatically), choose a button and send Note On/Off, or choose a fader,
press **Learn from device** and move the fader, then **Blink** / **Match**.

To keep custom CC mappings **and** the fader indicators, copy your CC preset
into slot 1 — this replaces the factory DAW preset, so export a backup first.
Button LED note feedback does not require this.

## Updates

The editor only **checks** whether a newer release exists and points you to
its page — it never downloads or installs anything automatically.

* **Help → Check for updates…** runs a check immediately.
* The automatic check runs in the background at the interval selected in
  **Help → Preferences**:

  | Setting | Behaviour |
  |---|---|
  | Every hour | checks at most once an hour |
  | Once a day (default) | checks at most once every 24 hours |
  | Once a week | checks at most once every 7 days |
  | Once a month | checks at most once every 30 days |
  | Never | no automatic checks; the menu item still works |

  The interval is evaluated at startup and every 10 minutes while the
  application is running; the last check time is stored in the settings.

* The repository is configured in **Help → Preferences** (format
  `owner/repository`).  Release builds embed it automatically, so normally
  there is nothing to configure.  Source installs have no embedded repository;
  set `Davilka/midisuite-linux` (or your fork) there.
* When a newer version is found, a dialog shows the release notes and a
  **Open release page** button.  Updating is a manual step: download the new
  bundle/wheel from the release page (see below).

## Updating by hand

* **Bundle:** download the new archive from the release page and repeat the
  installation steps (the `mv` replaces the old directory).
* **Wheel:** `pip install --upgrade <new-wheel>` or `pipx upgrade midisuite-linux`.
* **Source:** `git pull` and re-run `pip install -e .`.

## Uninstalling

```bash
# bundle install
rm -rf ~/.local/opt/midisuite
rm -f ~/.local/bin/midisuite-gui
rm -f ~/.local/share/applications/midisuite.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/midisuite.svg

# wheel / pipx install
pipx uninstall midisuite-linux      # or: rm -rf ~/.local/share/midisuite

# settings
rm -rf ~/.config/midisuite-linux
```

## Settings

Window geometry, the last used MIDI port, the update interval and the update
repository are stored in `~/.config/midisuite-linux/smc-mixer.conf`.  Deleting
that file resets the user interface settings; it does not touch the device.

## Troubleshooting

**No `SINCO … SMC-Mixer-Private` port**

* Check the cable and that the device is powered:
  `lsusb | grep -i 4353` should show `Jieli Technology SINCO`.
* `aconnect -l` should list a `SINCO` client with a `…-Private` port.
* The `…-Master` port is the DAW/performance port.  It is not used for
  configuration, but it is used by **Device → Test LED feedback…**.

**No BLE device in the list**

* Pair the controller first (`bluetoothctl pair <address>`), then press
  **Scan BLE** in the toolbar.
* `bluetoothctl info <address>` should report `Paired: yes`.
* The BLE configuration service is `0000ae40-…`; the editor writes to
  `AE41` and listens on `AE42`.
* If the device was connected by another application, it is still reachable:
  BlueZ shares the connection between GATT clients.

**`error creating ALSA sequencer client object`**

The ALSA sequencer has a hard limit of 64 clients.  Close unused MIDI
applications (some controller tools create one client per binding) and try
again.

**The bundle does not start**

Run it from a terminal to see the error.  On minimal systems install the Qt
runtime dependencies:

```bash
# Debian / Ubuntu
sudo apt install libgl1 libegl1 libxkbcommon-x11-0 libfontconfig1
# Fedora
sudo dnf install mesa-libGL mesa-libEGL libxkbcommon fontconfig
```

**Wayland issues**

Qt picks the platform automatically.  If the window or menus misbehave, force
X11 (XWayland):

```bash
QT_QPA_PLATFORM=xcb midisuite-gui
```

**The device answers but nothing changes**

Press **Save to device** — edits are kept in memory until saved.  The status
bar shows `saved to device` on success.  The editor writes the whole user
block (6282 bytes), preserving bytes it did not touch.

**Reset to a known state**

The **Reset to defaults** button writes a built-in preset generated by the
application (not the vendor factory data).  To keep your current state, use
**Export…** first; **Import…** restores it later.
