---
type: project_topic
status: active
summary: "Failure modes in this codebase that are silent, expensive, or look like something else — each one cost real debugging time before it was written down."
tags: [analog-studio, ngspice, pyside6, packaging, testing]
contains: [lesson, experience]
created: "2026-08-18"
updated: "2026-08-18"
related: [existing-knowledge]
authoring_mode: ai_generated
---
# Pitfalls

These are not style preferences. Each one below produced a wrong result, a
silent no-op, or a failure that pointed at the wrong culprit.

## Lessons

### Monkeypatching the sizing package patches nothing

`app/core/sizing/__init__.py` re-exports the package API. Rebinding an
attribute there does **not** affect the submodule that calls it — the
submodule resolved the name in its own globals at import time.

Patch the call site's module: `sizing.optimizer.evaluate`, never
`sizing.evaluate`.

Getting this wrong is silent, not loud. When the sizing module was split into
a package, `test_verify_hook` kept patching the facade; the fake was ignored,
the test ran ngspice for real for **168 seconds**, and then failed on an
assertion that made it look like a product regression. Patched correctly it
takes 7.5 s.

### Two test suites at once produce believable lies

The suites share the ngspice scratch directory and the user-data store. A
second concurrent run yields `KeyError: 'dcgain'` (raw files overwritten
mid-read) and saved-run counts inflated by the other run's runs
(`assert 4 == 2`). Both look exactly like real defects.

Always re-run a surprising failure **alone** before diagnosing it.

### Workspace is disposable; user data is not

`ANALOG_WORK_DIR` is versioned scratch, and `paths._prune_old_workspaces()`
deletes sibling version directories on the first launch of a new version.

Anything the user created — saved runs, imported circuits — must live under
`paths.user_data_dir()` instead. This was not hypothetical: up to v1.3 both
lived in the workspace, so every upgrade silently destroyed them, while the
manual promised they persisted. `paths._migrate_user_data()` now rescues them
before the prune.

### Paths into SPICE are not ordinary paths

- ngspice's `.include` is **unquoted** and truncates at a space — an install
  directory containing a space breaks model loading.
- `wrdata` strips single quotes but **not** double quotes; a double-quoted
  path becomes part of the filename.
- Model paths are written with forward slashes on every platform via
  `ngspice_common.spath()`. Compare against `Path.as_posix()`, never
  `str(path)` — a `str(WindowsPath(...))` comparison passes on Linux and fails
  only on Windows, which is how it survived until the CI matrix grew a Windows
  job.

### Matplotlib runs on the GUI thread only

Jobs return a **render closure**; the tab calls it in `on_job_finished()`.
`render_lock.py` enforces the GUI/worker exclusion. A job that draws directly
will appear to work and then corrupt output under load.

### Schematic rendering is version-sensitive

The 20 Sizing schematics are regenerated from netlists, and the output depends
on the `schemdraw` version. 0.23 reproduces the committed PNGs
pixel-for-pixel except for a 1-px canvas width on `ldo_folded_cascode`. If a
regeneration rewrites images you did not touch, check the version before
committing them — `requirements-dev.txt` bounds it for this reason.

## Experience

### The single worker thread is a constraint, not a design flourish

`SimWorker` is one thread rather than a pool because the vendored skill scripts
write scratch files to fixed paths; two concurrent gm/ID sweeps would overwrite
each other's intermediates. The Sizing optimizer parallelizes *inside* its own
job, where it controls the scratch layout. Do not "optimize" this into a pool.

### A cross-platform CI matrix pays for itself immediately

Adding Windows and macOS to the test matrix caught two Linux-shaped
assumptions on its very first run: the `str(WindowsPath)` comparison above, and
`timeout` (GNU coreutils) used in a workflow step, which does not exist on the
macOS image. When a job fails on one platform only, suspect the test before the
product.
