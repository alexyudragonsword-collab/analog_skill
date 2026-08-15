# CLAUDE.md

Guidance for Claude Code working in this repository.
Read [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full developer workflow;
this file is the short version plus the things that are easy to get wrong here.

## What this is

**Analog Studio** — a PySide6 desktop workbench for analog IC design, driving
ngspice locally. Six tabs: gm/ID designer, ngspice examples, curve browser,
comparison plots, block-level circuits, and automatic device sizing over 27
SKY130 / PTM circuits. Current version is in `app/__init__.py`.

The repository also archives three Claude skills (`ngspice/`, `gmoverid/`,
`transistor-models/`) plus two vendored circuit collections.

## Hard rules

**Never modify the vendored trees**: `analoggym/`, `circuit-skills/`,
`gmoverid/`, `ngspice/`, `transistor-models/`. They are upstream snapshots that
the app reads from disk as shipped, and the analysis documents cite them at a
specific vendor date. If behaviour needs to change, adapt around them in
`app/`. (`ruff.toml` excludes them for the same reason.)

**Never run two test suites concurrently.** They share the ngspice scratch
directory and the user-data store. A second run produces failures that look
real but are not — `KeyError: 'dcgain'`, saved-run counts inflated by the other
run. Always re-run a surprising failure alone before diagnosing it.

**Do not weaken the source-leak gate** in the `linux-nuitka` CI job. It fails
the build when any `app/` `.py`/`.pyc` reaches the distribution; that gate is
the entire point of the Nuitka build route.

## Commands

```bash
python -m app.main                      # run (QT_QPA_PLATFORM=offscreen if headless)
python -m app.main --smoke              # build every tab, exit 0
python -m pytest app/tests/ -v          # ~86 tests, ~2.5 min, real ngspice
python -m ruff check .                  # must be clean; config in ruff.toml
python tools/gen_sizing_schematics.py   # redraw the 20 Sizing schematics
```

Both `pytest` and `ruff check .` must pass before pushing — CI runs exactly
these, plus the same tests on Windows and macOS.

## Layout

```
app/core/sizing/   the Sizing engine, split by responsibility; import graph is
                   strictly one-directional and verified acyclic:
                   spec -> registry -> assets -> scoring -> evaluation ->
                   user_circuits -> report -> optimizer -> runs -> plots
app/core/          worker (single background thread), circuits, gm/ID services,
                   LLM client, ngspice locator, model registry
app/ui/            main_window + six tabs; job_mixin.py is the shared
                   submit/cancel/failure protocol every tab uses
app/paths.py       frozen-vs-source path resolution, workspace sync, user data
tools/             schematic generators (drawings are rendered from netlists)
```

## Things that bite

**Monkeypatching the sizing package.** `app/core/sizing/__init__.py` re-exports
the API. Rebinding an attribute there does *not* affect the submodule that
calls it — patch the call site's module (`sizing.optimizer.evaluate`, not
`sizing.evaluate`). Getting this wrong is silent: the test runs ngspice for
real and takes minutes.

**Workspace vs user data.** `ANALOG_WORK_DIR` is versioned scratch and is
*deleted* on upgrade by `paths._prune_old_workspaces()`. Anything the user
created — saved runs, imported circuits — must live under
`paths.user_data_dir()` instead. Never put user data in the workspace.

**Paths into SPICE.** ngspice's `.include` is unquoted and truncates at a
space, and `wrdata` strips single quotes but not double. Model paths are
written with forward slashes on every platform via `ngspice_common.spath()`, so
compare against `Path.as_posix()`, not `str(path)`.

**Matplotlib is GUI-thread only.** Anything rendering must run there;
`render_lock.py` enforces the GUI/worker exclusion.

**Schematic rendering is version-sensitive.** If regenerating rewrites images
you did not touch, check your `schemdraw` version before committing.

## Conventions

- Comments say **why**, not what; match the density of the file you are in.
- ~79 columns. `l` is channel length and `I` is current because the netlists
  say so; the drawing modules use `d += a; d += b`. `ruff.toml` documents why
  those rules are off — follow the local style, do not import your own.
- Update `CHANGELOG.md` in the same commit as the change it describes.
- Commit and push only to the branch you were told to use. Do not push tags or
  open pull requests unless asked.
