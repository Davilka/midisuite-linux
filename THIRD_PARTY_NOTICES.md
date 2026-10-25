# Third-party notices

Midi Suite itself is released under the MIT license (see [`LICENSE`](LICENSE)).
The application and the standalone bundle use the following third-party
components.  This file is a good-faith summary, not legal advice; the license
texts and source distributions of the components govern their use.

## Runtime dependencies

| Component | License | Project |
|---|---|---|
| PySide6 / Qt 6 | LGPL-3.0 (or commercial) | <https://www.qt.io/qt-6/lgpl> · <https://pypi.org/project/PySide6/> |
| python-rtmidi | MIT | <https://github.com/SpotlightKid/python-rtmidi> |
| dbus-fast | MIT | <https://github.com/Bluetooth-Devices/dbus-fast> |
| Python | PSF-2.0 | <https://www.python.org/psf/license/> |

The standalone bundle links the Qt/PySide6 shared libraries dynamically.
Those libraries are unmodified.  You may replace them with compatible
versions; the corresponding Qt/PySide6 source code is available from the Qt
project and the PySide6 source distribution.  The bundle does not include
vendor firmware, vendor application assets or vendor factory presets.

## Build and packaging tools

| Component | License | Project |
|---|---|---|
| PyInstaller | GPL-2.0-or-later with the PyInstaller bootloader exception | <https://pyinstaller.org/> |
| setuptools / build | MIT | <https://pypi.org/project/setuptools/> · <https://pypi.org/project/build/> |
| pytest / ruff | MIT | <https://pytest.org/> · <https://docs.astral.sh/ruff/> |

The build tools are not part of the application's runtime license; the
PyInstaller exception applies to the generated bootloader.

## Trademarks

M-VAVE, CUVAVE, SINCO and SMC-Mixer are trademarks of their respective
owners.  This project is not affiliated with or endorsed by them.  The names
are used only to describe compatibility.
