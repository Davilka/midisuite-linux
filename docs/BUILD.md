# Building and releasing

## Requirements

* Linux x86-64
* Python 3.10+ with `venv`
* System packages for building/running:
  * Debian/Ubuntu: `libasound2-dev libgl1 libegl1 libxkbcommon-x11-0 libdbus-1-3 libfontconfig1`
  * Fedora: `alsa-lib-devel mesa-libGL mesa-libEGL libxkbcommon dbus-libs fontconfig`
  * Arch: `alsa-lib libgl libxkbcommon dbus fontconfig`

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Run the tests and the linter:

```bash
pytest -q
ruff check src tests tools
```

Run the application from the source tree:

```bash
midisuite-gui
# or
python -m midisuite.ui.app
```

## Build a wheel and sdist

```bash
pip install build
python -m build --outdir dist
```

This produces:

```
dist/midisuite_linux-<version>-py3-none-any.whl
dist/midisuite_linux-<version>.tar.gz
```

Install the wheel with `pip install dist/*.whl`.

## Build the standalone bundle

The bundle is a self-contained directory built with PyInstaller (it includes
Python, PySide6 and python-rtmidi, so the target machine does not need Python):

```bash
scripts/build-bundle.sh            # version from pyproject.toml
scripts/build-bundle.sh 1.2.3      # explicit version
```

Output:

```
dist/midisuite-gui-linux-x86_64-<version>.tar.gz
```

Unpack and run:

```bash
tar xzf midisuite-gui-linux-x86_64-<version>.tar.gz
cd midisuite-gui-linux-x86_64
./midisuite-gui
```

The archive also contains `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`,
`docs/` (`INSTALL.md`, `protocol.md`, `BUILD.md`, `CLEAN_ROOM.md` and both
screenshots) and a desktop file plus icon in `contrib/`; `README-bundle.txt` explains how to install it
into `~/.local`.

### Manual PyInstaller invocation

The script is a thin wrapper around:

```bash
pyinstaller --noconfirm --clean --windowed --name midisuite-gui \
    --distpath build/pyinstaller/dist \
    --workpath build/pyinstaller/work \
    --specpath build/pyinstaller \
    packaging/launcher.py
```

PyInstaller ships hooks for PySide6 and collects the Qt plugins automatically;
`python-rtmidi` is a C extension and is collected as a normal module.

## Publishing the repository

The project is prepared for `https://github.com/Davilka/midisuite-linux.git` with
the default branch `main`.  The release workflow embeds the actual repository
name in the bundle, so update checking keeps working after a rename; only the
links in `README.md`, `docs/INSTALL.md`, `pyproject.toml` and the badges need
to be adjusted in that case.

```bash
git remote add origin https://github.com/Davilka/midisuite-linux.git
git push -u origin main
```

Before the first push, check that no local data is included:

```bash
git status --short
git ls-files backups dist .venv || true
```

The `.gitignore` already excludes `backups/`, `dist/`, `.venv/`, caches and
the generated `src/midisuite/_build_info.py`.  In the GitHub repository
settings:

* enable **Actions** (the CI and Release workflows are in `.github/workflows`);
* add a short description and topics such as `linux`, `midi`, `smc-mixer`,
  `bluetooth`, `pyside6`;
* enable **Private vulnerability reporting** (see `SECURITY.md`);
* keep the default branch `main`.

## Releases

Releases are produced by `.github/workflows/release.yml`.

### Publishing from a tag (recommended)

```bash
git tag -a v1.0.0 -m "Midi Suite 1.0.0"
git push origin v1.0.0
```

The workflow runs the lint/tests, builds the wheel, the sdist and the
standalone bundle, and creates a GitHub release named
`Midi Suite 1.0.0` with these assets attached:

```
midisuite_linux-1.0.0-py3-none-any.whl
midisuite_linux-1.0.0.tar.gz
midisuite-gui-linux-x86_64-1.0.0.tar.gz
SHA256SUMS
```

Release notes are generated automatically from the commits since the previous
tag.

### Publishing manually

Open **Actions → Release → Run workflow**, enter the version without the `v`
(for example `1.0.1`) and run it.  The workflow builds the assets and creates
(or updates) the `v1.0.1` tag and release.

### Update repository in the bundle

The release workflow exports `MIDISUITE_UPDATE_REPO=${{ github.repository }}`
before calling `scripts/build-bundle.sh`; the script writes
`src/midisuite/_build_info.py` (git-ignored) so the released bundle knows
where to look for updates.  For a local build:

```bash
MIDISUITE_UPDATE_REPO=owner/repository scripts/build-bundle.sh
```

Without it the updater stays disabled until a repository is set in
**Help → Preferences**.

### Versioning

The workflow rewrites `[project].version` in `pyproject.toml` from the tag
before building, so the tag is the single source of truth for the release
number.  `src/midisuite/__init__.py::__version__` is only used by the CLI
`--version` output; keep it in sync when preparing a release.

### CI

`.github/workflows/ci.yml` runs on pushes to `main`/`master` and on pull
requests: lint, unit tests on Python 3.10–3.13 and a headless GUI smoke test.

No repository secrets are required — the release workflow uses the automatic
`GITHUB_TOKEN` with `contents: write` permission, which is declared in the
workflow file.

## Troubleshooting

* **`error creating ALSA sequencer client object`** — the ALSA sequencer has a
  hard client limit (64).  Close unused MIDI applications before starting the
  editor.
* **PyInstaller bundle does not start** — run it from a terminal to see the
  traceback; on minimal systems install `libgl1`, `libegl1`,
  `libxkbcommon-x11-0` and `libfontconfig1`.
* **No `SINCO … SMC-Mixer-Private` port** — the controller must be connected
  over USB; the `Master` port is the DAW port and is not used for
  configuration.
