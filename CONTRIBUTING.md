# Contributing

Thanks for helping with Midi Suite for Linux.  The project is an independent
implementation for the M-VAVE / SINCO SMC-Mixer; please keep it that way.

## Scope

* Device support: **SMC-Mixer** only.  The protocol layer is device
  independent, but new devices need their own memory map and tests.
* Platform: Linux (ALSA sequencer; PipeWire/JACK via ALSA is fine).
* Python 3.10+ with PySide6 and python-rtmidi.

## Development setup

```bash
git clone https://github.com/Davilka/midisuite-linux.git
cd midisuite-linux
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Run the checks before sending a pull request:

```bash
ruff check src tests tools
pytest -q
```

The GUI can be started without a device:

```bash
QT_QPA_PLATFORM=offscreen python - <<'PY'
from PySide6.QtWidgets import QApplication
from midisuite.devices.smc_mixer import SmcMixer
from midisuite.ui.app import MainWindow

app = QApplication([])
window = MainWindow()
window.mixer = SmcMixer.default()
window.refresh_views()
window.show()
window.select_control("button", 0)
app.processEvents()
print("GUI smoke test passed")
PY
```

## Hardware testing

The SMC-Mixer has no undo for a bad write.  Before any experiment that writes
to **block 5** (the presets):

1. Read and save the whole 6282-byte user block (`midisuite dump cfg.bin`).
2. Record which preset (slot 1 or 2) is active — `globals[0]`.
3. Prefer changing a single byte, read it back, and restore it immediately.
4. Verify afterwards that the user block is byte-identical to the backup.

Good practices for protocol work:

* document what was **observed** separately from what is inferred;
* include the request/reply bytes and the firmware/device version;
* test both USB and BLE when the change affects the transport;
* never publish vendor firmware, factory preset dumps, or assets from the
  original application.

The current measured protocol and the list of verified facts are in
[`docs/protocol.md`](docs/protocol.md).  If you discover something new, add it
there and, when possible, a regression test.

## Code style

* Python 3.10-compatible syntax.
* `ruff check src tests tools` must pass.
* Keep UI text short; the application is translated manually where needed.
* UI labels follow the hardware markings (M, S, R, ■, transport symbols).
* Prefer small, focused commits with an imperative subject line.

## Pull requests

A pull request should contain:

* the problem and the observed behaviour;
* the change and its user-visible effect;
* the test command/results;
* a note about hardware testing (device, connection, firmware) if relevant.

Please do not include your local `backups/` directory, `.venv/`, `dist/` or
generated `_build_info.py` in commits — they are ignored by default for a
reason.

## Reporting bugs

Open a GitHub issue with the template.  Useful details:

* distribution and version, Python version, install method (bundle, wheel,
  source);
* connection (USB or BLE), port name, device firmware;
* exact steps, expected and actual result;
* relevant Monitor output (remove personal data such as the Bluetooth
  address).

Security issues: see [`SECURITY.md`](SECURITY.md).
