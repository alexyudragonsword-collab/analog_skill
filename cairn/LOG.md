# Project Cairn Log

This file records substantive progress in reverse-chronological order — newest entry at the top, right below this line. Keep each entry short — summary and pointer only; conclusions settle into `cairn/<topic>.md`.

## 2026-09-10 · v1.4 released — the repository's first

- Tag `v1.4` at `6e020a0`, five packages published. Build run 34462082771,
  all six jobs green including `release`, which had never executed before.
- The pre-emptive fix to that job was load-bearing, and the run proved it:
  `download-artifact` with `merge-multiple` put every file flat in
  `artifacts/`, including `AnalogStudio.exe` — so the old hard-coded
  `artifacts/AnalogStudio-windows-onefile/AnalogStudio.exe` would have
  matched nothing and failed the publish after ~36 min of building.
- The onefile exe is now a release asset rather than a 90-day artifact, so
  the outstanding "double-click does nothing" report can be retested any
  time.

## 2026-09-10 · Startup safety net + first-run splash

- Frozen builds are windowed, so a startup exception reached nobody. `main()`
  now writes `%TEMP%/AnalogStudio-crash.txt` and reports it; the dialog reuses
  an existing QApplication and falls back to the Win32 box, because Qt itself
  is a plausible cause of the failure.
- Building it produced a defect worth remembering: the first version's modal
  dialog **hung** under `--smoke`/offscreen (nobody to click OK) — CI would
  have timed out instead of failing fast. Guarded by `_interactive()`.
- Splash covers QApplication → main window, worded from
  `paths.first_run_expected()`. The scipy import before it cannot be covered:
  it must precede Qt (Nuitka Windows), so no QApplication exists yet.
- 5 tests. Details: `cairn/pitfalls.md` → "A modal dialog needs someone to
  click it".

## 2026-09-10 · Imported netlists could execute shell commands — fixed

- ngspice runs `.control` blocks in batch mode; imported netlists **and**
  their `.PARAM` files are `.include`d verbatim, and directives inside an
  included file execute the same. Reproduced end to end: payload ran, the
  metric report looked normal.
- Guard added at both registration paths — `import_user_circuit()` refuses a
  control block in either file, `load_user_circuits()` re-checks files
  already on disk instead of trusting them.
- 6 regression tests, including one that asserts ngspice really does execute
  the payload, so the guard cannot quietly become pointless.
- Details: `cairn/pitfalls.md` → "A netlist is code"; residual `.include`
  file-read issue tracked in `ROADMAP.md`.

## 2026-08-18 · Project Cairn initialized

- Initialized Project Cairn structure: `AGENTS.md`, one-line `CLAUDE.md`, `.cairn/config.yaml`, this log.
- `git_policy: track` — `cairn/` is committed. The repository is public, so nothing client-private or personally sensitive may be written here.
- Graduation provider deferred (`provider: none`); collected at the first graduation instead.
- Historical migration mode: `inventory_only`. The pre-Cairn documentation is inventoried in `cairn/existing-knowledge.md`, not rewritten.
- `ROADMAP.md` stays at the repository root rather than moving to `cairn/`: it predates Cairn by one day and is already linked from `README.md`, `README.zh-CN.md` and `CONTRIBUTING.md`. `AGENTS.md`'s reading order points at the root file.
- The previous 96-line `CLAUDE.md` was not discarded — its rules moved into `AGENTS.md` and its five failure modes into `cairn/pitfalls.md`. Details: see `AGENTS.md` and `.cairn/config.yaml`.
