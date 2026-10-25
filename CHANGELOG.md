# Changelog

All notable changes to this project are documented here.  The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-26

First public release.

### Added

* Independent Linux editor for the M-VAVE / SINCO SMC-Mixer over USB MIDI and
  Bluetooth LE.
* Two-preset editing with active-slot detection and **Activate on device**.
* Visual device panel with the printed M/S/R/■ marks and all eleven transport
  buttons in their backlight colours.
* Per-control editor for buttons, encoders and faders: message modes, channel,
  controller/note, values, SysEx buffer, LED feedback, range and curve.
* Read/save of the complete 6282-byte user block; untouched bytes are
  preserved exactly.
* JSON and raw `.bin` import/export, undo/redo, built-in clean-room defaults.
* Globals hex editor, live traffic monitor and a virtual test output port.
* **Device → Test LED feedback…** with button Note On/Off and fader
  soft-takeover Pitch Bend tests, including fader-position learning.
* Update checking through GitHub Releases with a configurable interval
  (hourly, daily, weekly, monthly or never).  Updates are never installed
  automatically.
* Command-line interface for dumps, restores, raw block access and preset
  copying.
* CI (Python 3.10–3.13) and a release workflow that publishes a wheel, sdist,
  standalone Linux bundle and `SHA256SUMS`.

### Known limitations

* The eight LEDs under the knobs are fader soft-takeover indicators and only
  respond to Pitch Bend while the DAW slot (Preset 1) is active.
* The meaning of most bytes in the 128-byte global block is undocumented; they
  are exposed as raw hex.
* Vendor firmware/application updates are not implemented.
* Only the SMC-Mixer is supported.

[Unreleased]: https://github.com/Davilka/midisuite-linux/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Davilka/midisuite-linux/releases/tag/v1.0.0
