---
type: project_topic
status: active
summary: "Failure modes in this codebase that are silent, expensive, or look like something else — each one cost real debugging time before it was written down."
tags: [analog-studio, ngspice, pyside6, packaging, testing, security]
contains: [lesson, experience]
created: "2026-08-18"
updated: "2026-09-11"
related: [existing-knowledge]
authoring_mode: ai_generated
---
# Pitfalls

These are not style preferences. Each one below produced a wrong result, a
silent no-op, or a failure that pointed at the wrong culprit.

## Lessons

### A modal dialog needs someone to click it

`QMessageBox.exec()` blocks until OK is pressed. A startup error dialog is
right on a desktop and actively harmful anywhere else: under `--smoke` or an
offscreen/minimal Qt platform there is nobody to click, so the process hangs
until something kills it. Measured while adding the startup safety net — the
first version turned "CI fails fast with a traceback" into "CI job times
out", which is strictly worse than the silent failure it was meant to fix.

`app/main._interactive()` gates it: no dialog under `--smoke`, none on the
offscreen/minimal platforms. The crash file is written first either way, so
nothing depends on the dialog appearing.

**And it bit twice.** The first fix guarded the Qt dialog and left the Win32
`MessageBoxW` fallback in the same function outside the guard — it blocks
identically. The Windows CI job then sat inside `_report_fatal()` for six
hours until GitHub's own limit killed it. Two lessons worth more than the
first one: when a hazard has two branches, guard the *function*, not the
branch you were looking at; and a blocking bug does not fail, it waits, so
the job needs a `timeout-minutes` that is shorter than the runner's. Both
are now in place, and the regression test forces `sys.platform` so it runs
on every platform rather than only where the bug lives.

Related, same file: the fatal handler must **not** construct a QApplication
of its own. Qt is a plausible cause of the very failure being reported — a
missing libEGL on Linux, a missing VC runtime or a bad bundled DLL on
Windows — so it reuses an existing instance, falls back to the Win32 message
box (which needs no Qt at all), and otherwise leaves the traceback on stderr,
which the frozen builds already redirect to a file.

### A netlist is code — ngspice executes `.control` blocks

In batch mode (`-b`) ngspice runs any `.control ... .endc` block it sees,
and such a block may call `shell`. That makes every user-supplied netlist an
executable, not data.

Two properties made this worse than it first looks:

- **Included files count.** Both the imported netlist and its `.PARAM`
  design-variables file are `.include`d verbatim into the rendered testbench
  (`evaluation._render_testbench`, `_write_params`), and a directive inside
  an included file executes exactly as if it were inline — verified. So the
  variables file is an injection point too, not just the netlist.
- **It is silent.** Reproduced end to end through `import_user_circuit` →
  `evaluate` with a real studio netlist plus a four-line control block: the
  payload ran, import reported success, and the metric report came back with
  `tc`/`ivdd25`/`power` looking entirely normal. Nothing in the UI hinted
  that anything had happened.

Measured against ngspice-42 while designing the guard: the directive folds
case and may be indented (`   .CoNtRoL` executes), but splitting it across a
`+` continuation does **not** work — so matching `^\s*\.control` catches
every form that actually runs. None of the 27 shipped circuits contains a
control block, so refusing them costs nothing legitimate; the vendored
*testbenches* do contain them, but those are ours, not user input.

**The residual is closed too** (2026-09-11). `.include` from an imported
netlist was left out of the first fix so the two would be judged separately;
measuring it settled the question. `.include`, its `.inc` abbreviation and
`.lib` all pull a file in — case-folded, space- or tab-indented, path bare
or in either quote style, relative or absolute — and only the `+`
continuation form fails, the same shape as `.control`. What made it worth
closing rather than tolerating is where the contents go: `.include
/etc/hostname` comes back as `Error in line   <contents of the file>`, in
the run log the user is looking at. So the read is not merely attempted, it
is reported. No shipped netlist or variables file uses any of the three —
only our own testbenches do — so the guard now covers all four directives
under one regex.

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

It bit again on 2026-09-11, in the test suite rather than in a test's subject:
`test_runs_dialog_and_warm_start` patched `sizing.runs_dir`, so both
`save_run()` and `list_runs()` kept using the real user-data store. The test
still passed — it saved two runs and read two back — on any machine where
that directory happened to be empty, and failed only on the *second* run,
as `assert 4 == 2`. A patch that does nothing does not announce itself; it
just moves the test's blast radius outside the sandbox.

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
