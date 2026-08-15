# Roadmap

Where this project stands and what is open. This file is the single place
open work is tracked — the repository does not use GitHub Issues as its
primary list, and there are deliberately no `TODO` comments in the code
(a todo buried in a source file is a todo nobody reads).

Completed work belongs in [`CHANGELOG.md`](./CHANGELOG.md), not here. Items
leave this file when they land, except in *Decided against*, which exists so
a settled question is not reopened from scratch.

**Status as of 2026-08-15** — v1.4, unreleased, no tag has ever been cut.
CI is green on all six build jobs and on the three-platform test matrix.
`ruff check .` is clean and gated. 86 tests, ~2.5 min, running real ngspice.

---

## Blocked on the maintainer

Nothing here can be moved by a contributor; each needs a decision or an
action only the repository owner can take.

- **Cut the v1.4 release.** The repository has no tags at all, so the
  `release` CI job has never run and no version has ever been published.
  Everything it needs is in place: five build artifacts, green CI, a
  changelog. Bump the date in `CHANGELOG.md` from *unreleased*, then
  `git tag v1.4 && git push origin v1.4`. See
  [`CONTRIBUTING.md`](./CONTRIBUTING.md#releasing).
- **Confirm the single-file Windows build actually launches.** The
  `nuitka-onefile` job builds the exe and runs it with `--smoke` on a clean
  runner, exit 0 — but a report of "double-click does nothing" on a real
  machine is unresolved. Likely causes, in order: the exe predates the
  `skill_assets.zip` step; the ~100 MB self-extraction to `%TEMP%` on a cold
  first launch reads as a hang; antivirus blocking it. `--force-stderr-spec`
  is set, so a crash leaves `%TEMP%\AnalogStudio.err.txt`.
- **English one-page overview (16:9).** Outline agreed; blocked on the
  output format (PDF / PNG / HTML) and on the repository URL and contact to
  put in the footer.

## Open

Ordered by value, not by effort.

- **Test the GUI layer.** Coverage of `app/` excluding the test files is
  **50%**, and the split is lopsided rather than uniform: `app/core/` is at
  **70%** (the sizing package is 83–100% per module), while six UI modules
  are at **0%** — `gmid_tab` (381 statements), `main_window` (136),
  `examples_tab` (140), `circuits_tab` (130), `comparison_tab` (125),
  `browser_tab` (118), plus `settings_dialog` and the small widgets.
  `sizing_tab` is the exception at 51%, reached through `test_sizing.py`.
  The engine is well covered; what users click is not. Worth deciding a
  target before writing tests — offscreen Qt works well (the v1.4 Sizing
  screenshot was captured that way, driving a real optimization), so this is
  tractable, but a GUI test suite is easy to over-build.
- **API keys are stored in plain text.** `llm_client` keeps the LLM key in
  `QSettings` (registry on Windows, an ini file elsewhere). Fixing it means
  a `keyring` dependency, which is platform-specific and has to survive
  three freezing toolchains — a real cost for a key the user pasted in
  themselves. Worth doing only if this app is expected to run on shared
  machines; write down the answer either way.
- **Issue and PR templates.** The repository is public with no templates.
  Bug reports for this project are unusable without three specific facts —
  ngspice version, platform, and whether the user is running from source or
  from one of the five builds — and nothing currently asks for them.
- **`analoggym/README.md` points at `app/core/sizing.py`**, which became a
  package. One word, but that file is inside a vendored tree this project
  does not modify, so it needs an explicit exception rather than a quiet fix.

## Ideas, not commitments

No one has committed to these; they are recorded so the thought is not lost.

- More AnalogGym circuits. Two upstream circuits are deliberately unregistered
  (`Qu_LEC` ships an empty netlist; `Tan_CLIA`'s default widths fall below the
  SKY130 model-bin range) — that exclusion is intentional, not a gap.
- Sizing contracts beyond the amplifier one. Importing a custom design
  currently requires `.subckt <name> gnda vdda vinn vinp vout`; LDOs and other
  topologies have no import path.
- macOS packaging. The test matrix runs on macOS, but no macOS build job
  exists — only Windows and Linux artifacts are produced.

## Decided against

Reopening these is fine, but start from the reasoning, not from zero.

- **Re-capturing the other eight manual screenshots.** Only the Sizing one
  was replaced for v1.4. The tabs behind the rest have not changed materially
  since those images were taken, and re-capturing them through offscreen Qt
  produced emptier screenshots than the ones already committed.
- **Filling in every missing docstring.** Coverage of public definitions was
  raised from 45% to 56% by documenting the two files that define the
  concurrency contract (`SimWorker`, `JobTabMixin`) plus the registry
  dataclasses. The six tabs' `on_job_finished` / `on_job_failed` overrides are
  intentionally left bare — the protocol is stated once, in the mixin.
- **Editing the vendored trees.** `analoggym/`, `circuit-skills/`, `gmoverid/`,
  `ngspice/` and `transistor-models/` are upstream snapshots that the app reads
  as shipped and that dated analyses in this repository cite. Behaviour changes
  are adapted around in `app/`.
- **Weakening the source-leak gate** in `linux-nuitka` to make a build pass.
  That gate — no `app/` `.py` or `.pyc` anywhere in the distribution — is the
  entire reason the Nuitka route exists alongside PyInstaller.
