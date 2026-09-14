# Project Cairn Log

This file records substantive progress in reverse-chronological order — newest entry at the top, right below this line. Keep each entry short — summary and pointer only; conclusions settle into `cairn/<topic>.md`.

## 2026-09-14 · Effort is the latency lever; #2 and #3 were not

- Asked whether bigger prompts or an MCP server would cut the ~100 s round.
  Measured instead of reasoned: startup is 1.0 s of 101, so neither can —
  the cost is the model emitting ~11 k tokens, nine tenths of them
  reasoning. A smaller model is not it either (haiku 117 s > sonnet 101 s,
  more tokens to the same place).
- `chat(effort=...)` added on the same request-not-guarantee contract as
  `schema`. Loop asks for 'low' (25 s, 3 520 tokens, still 4/4 candidates);
  suggest_setup and explain_run keep the default, being read by a human.
- A/B came back (n=1 per arm, 60 evals): low 1.318 in 12.3 min, default
  1.280 in 26.0 min. Per evaluation the default is 3% better, which one run
  cannot separate from noise; per minute low is far ahead — the default was
  still at 1.534 when low had finished. Kept low, on the equal-time
  reading, and recorded that the curves differ in shape (low plateaus).
- Details and the full table: `cairn/pitfalls.md` → "A CLI agent is not a
  chat endpoint until you disarm it".

## 2026-09-14 · Structured output, and the latency it uncovered

- `chat(schema=...)` added as a request-not-guarantee: Claude Code enforces
  it with `--json-schema`, HTTP providers ignore it and keep parsing
  defensively, callers stay provider-agnostic. Schemas are built per circuit
  from its own variables — up to 56 names that a candidate previously had to
  restate verbatim or be dropped in silence.
- Verified live: 4/4 candidates, 0 missing keys, bare JSON with no fence.
- **The measurement mattered more than the feature.** A real round costs
  88 s with a schema and 112 s without — so the schema is free, and
  `chat()`'s 120 s default was about to make the LLM algorithm fall back to
  Sobol on every wide circuit. Floor raised to 300 s; the Sizing tab's time
  estimate, which counted only ngspice, was reading "2 min" for an hour.
- Corrected the "4-6 s per call" figure recorded yesterday — it was a toy
  prompt. Correction appended, not overwritten: `cairn/pitfalls.md` → "A CLI
  agent is not a chat endpoint until you disarm it".

## 2026-09-14 · AI features can run on a Claude subscription

- Third LLM provider: the locally installed Claude Code CLI, driven through
  `-p --output-format json`. Verified end to end before writing the UI —
  locate, configured, test_connection, a multi-turn JSON exchange, and
  `llm_sizing.suggest_setup` returning a real per-variable bounds dict.
- `chat()`'s contract is unchanged, so `llm_sizing` needed no edits: the
  history is flattened into the single prompt the CLI takes, which is what
  the HTTP providers are re-sent every call anyway. Stateless beat
  `--resume` for exactly that reason.
- The work was mostly *disarming* it, not calling it — tools off, user
  config excluded, empty cwd, fresh session id per call. Details and the
  measured numbers: `cairn/pitfalls.md` → "A CLI agent is not a chat
  endpoint until you disarm it".
- Scope decided by the maintainer: self-use, not published, so the usage-
  terms question raised in the feasibility review does not gate it.

## 2026-09-13 · ROADMAP's Open section is empty

- GUI tests extended from "does it build" to "what does it do with a reply".
  Three cross-tab rules now pinned: a failure re-enables the button, a
  raising render closure is reported not thrown, and gm/ID discards both a
  stale table and a dead one. Mutation-verified. 133 tests, coverage 71%.
- Two standing questions answered by the maintainer and recorded in
  *Decided against* rather than left open: no `keyring` (the env var covers
  the case that motivated it; the dependency must survive three freezing
  toolchains), and Cairn stays at `provider: none` (graduation earns its
  cost only when there is a second project to graduate into).
- English one-page overview delivered as an HTML artifact — the format
  decision that had blocked it.
- Open is now empty. Blocked-on-maintainer still holds one item that needs
  the reporting machine: does the single-file Windows exe launch there.

## 2026-09-11 · Cleared five ROADMAP items in one pass

- `.include` residual closed. Measuring it is what settled it: `.include` /
  `.inc` / `.lib` all pull a file in, and `.include /etc/hostname` comes back
  as `Error in line   <contents>` — in the log the user is reading. One regex
  now covers all four directives at both registration paths. 9 tests; all 7
  behavioural ones verified failing against the unfixed guard.
- API key: `ANALOG_LLM_API_KEY` overrides the stored one and the Settings
  dialog will not write it back. The keyring question stays open — this was
  the half that needed no dependency.
- GUI layer went from six modules at 0%. `test_ui.py` tests what every tab
  shares (job protocol, ngspice enable/disable, log, settings), not what each
  tab draws.
- Issue + PR templates; blank issues off, since the three facts a bug report
  here needs were exactly what nobody was being asked for.
- `analoggym/README.md`'s stale path moved to *Decided against*: the vendored
  tree stays untouched, both READMEs carry the note instead.
- Along the way the coverage run exposed a test writing into the real
  saved-runs store: `sizing.runs_dir` was patched on the package, not on
  `runs.py`. It passed on any empty machine and failed on the second run.
- Details: `cairn/pitfalls.md` → "A netlist is code", "Monkeypatching the
  sizing package patches nothing".

## 2026-09-10 · Windows CI hung 6 h on my own startup-dialog guard

- The v1.4 guard covered `QMessageBox.exec()` but not the Win32
  `MessageBoxW` fallback beside it; both block. The Windows job sat in
  `_report_fatal()` 16:06 → 22:04 and died on GitHub's six-hour limit.
- Fixed by guarding the whole function. Regression test forces
  `sys.platform` so it runs on every platform — against the broken code it
  fails in 1.6 s (verified by reverting the fix), rather than hanging.
- `pytest` job now has `timeout-minutes: 20`. A blocking test never fails on
  its own; the cap is what makes the next one cheap.
- Details: `cairn/pitfalls.md` → "A modal dialog needs someone to click it".

## 2026-09-10 · Default branch renamed to `main`

- The session-generated branch name was the repository's public face; it is
  now `main`. The rename and a push of mine crossed, which re-created the old
  name as a stray branch — deleted, its one commit moved onto `main`.
- `build-windows.yml` hard-coded the old name in its `branches:` filter, so
  until this change a push to `main` touching `app/` would have produced no
  builds, silently. That coupling was the reason to do the rename and the
  workflow edit together.
- Both READMEs' last-commit badge linked to `/commits/main` and 404'd; the
  rename fixed them without an edit.

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
