# Contributing to Analog Studio

Everything below assumes you are working on `app/`, `tools/` or
`studio_circuits/`. The vendored trees are off limits — see
[What you must not change](#what-you-must-not-change).

## Setup

```bash
pip install -r requirements.txt -r requirements-dev.txt
sudo apt install ngspice ...     # or: brew install ngspice
python -m app.main
```

Python 3.11 is what CI uses and what the frozen builds ship. ngspice must be on
`PATH` (or configured in Settings) for anything that simulates; the app runs
without it, with the run buttons disabled.

On a headless machine, set `QT_QPA_PLATFORM=offscreen`.

## The checks

Both of these must pass before you push — CI runs exactly these.

```bash
python -m pytest app/tests/ -v
python -m ruff check .
```

**Tests.** ~86 of them, about 2.5 minutes, because most of them run real
ngspice rather than mocking it. Tests that need the simulator skip themselves
when it is absent (`needs_ngspice`), so a run without ngspice is still worth
something but proves much less.

Two things to know before you debug a failure:

- **Never run two suites at once.** They share the scratch directory and the
  user-data store, so a second concurrent run produces failures that look real
  and are not (`KeyError: 'dcgain'`, saved-run counts off by the other run's
  runs). If a failure surprises you, re-run that test alone first.
- **Patch where the name is looked up.** `app/core/sizing/__init__.py`
  re-exports the package's API; rebinding an attribute there does not affect
  the submodule that calls it. Patch `sizing.optimizer.evaluate`, not
  `sizing.evaluate` — the latter silently does nothing and your test runs
  ngspice for real.

**Lint.** [`ruff.toml`](./ruff.toml) selects the defect-finding rules
(pycodestyle, pyflakes, pyupgrade, bugbear) and documents, with reasons, the
three style rules this codebase deliberately violates. It is pinned to one
minor version so a ruff release cannot turn CI red on its own. The vendored
trees are excluded.

**Smoke test.** `python -m app.main --smoke` builds every tab, renders nothing,
and exits 0. It is the only check that runs against the frozen builds, so keep
it working.

## Regenerating the schematics

The circuit drawings are **rendered from the netlists**, never screenshotted.
Two generators, both needing `schemdraw`:

```bash
python tools/gen_schematics.py           # Circuits tab (circuit-skills)
python tools/gen_sizing_schematics.py    # Sizing tab (20 AnalogGym circuits)
```

The sizing generator asserts netlist fidelity: `Sheet.save()` parses the device
list out of the source netlist and fails if the drawing does not place every
one of them. Adding a circuit means adding `tools/sizing_drawings/<key>.py`
exporting `KEY` and `draw()` — it is auto-discovered.

Rendering is version-sensitive. `schemdraw` is bounded in
`requirements-dev.txt` for that reason; 0.23 reproduces the committed PNGs
pixel-for-pixel except for a 1-px canvas width on `ldo_folded_cascode`. If a
regeneration rewrites images you did not intend to touch, check your schemdraw
version before committing them.

## CI

| Workflow | Jobs | Triggered by |
|---|---|---|
| [`test.yml`](.github/workflows/test.yml) | `lint`, then `pytest` on Ubuntu + Windows + macOS | every push and PR |
| [`build-windows.yml`](.github/workflows/build-windows.yml) | `pyinstaller`, `nuitka`, `nuitka-onefile`, `linux`, `linux-nuitka`, `release` | pushes touching the paths it filters on |

The matrix is not decoration — its first run caught two Linux-shaped
assumptions (a `str(WindowsPath)` comparison against a path that is
deliberately posix, and `timeout` which does not exist on the macOS image).
When a job fails on one platform only, suspect the test before the product.

`linux-nuitka` additionally fails the build if any `app/` `.py` or `.pyc`
leaks into the distribution — that gate is the whole point of the Nuitka
route, so do not weaken it to make a build pass.

## Releasing

Version lives in `app/__init__.py`. To release:

1. Bump `__version__`, and give the `CHANGELOG.md` section its **real** date.
2. Push a tag: `git tag v1.4 && git push origin v1.4`.
3. The `release` job collects all five build artifacts and publishes them.
   Without a tag it skips, which is why it shows as skipped on ordinary runs.

## What you must not change

`analoggym/`, `circuit-skills/`, `gmoverid/`, `ngspice/` and
`transistor-models/` are archived upstream snapshots. The app reads them from
disk exactly as shipped, and analyses in the repo cite them at a specific
vendor date. Do not edit them — if the app needs different behaviour, adapt
around it in `app/`.

The single historical exception is documented in `APP_README.md`: netlist
template paths were quoted so paths with spaces work on Windows.

## Conventions

- Comments explain **why**, not what. Match the density of the file you are in.
- Match the surrounding style rather than importing your own. The codebase
  writes to ~79 columns, uses `l` for channel length and `I` for current
  because the netlists do, and uses `d += a; d += b` in the drawing modules.
- New public functions get a docstring; keep it to what a caller needs.
- Update `CHANGELOG.md` in the same commit as the change it describes.
