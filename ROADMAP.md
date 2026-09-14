# Roadmap

Where this project stands and what is open. This file is the single place
open work is tracked — the repository does not use GitHub Issues as its
primary list, and there are deliberately no `TODO` comments in the code
(a todo buried in a source file is a todo nobody reads).

Completed work belongs in [`CHANGELOG.md`](./CHANGELOG.md), not here. Items
leave this file when they land, except in *Decided against*, which exists so
a settled question is not reopened from scratch.

**Status as of 2026-09-13** — **v1.4 released**, the repository's first
(tag `v1.4`, five packages). CI is green on all six build jobs and on the
three-platform test matrix. `ruff check .` is clean and gated. 133 tests,
~2.5 min, running real ngspice; coverage of `app/` is 71%.

---

## Blocked on the maintainer

Nothing here can be moved by a contributor; each needs a decision or an
action only the repository owner can take.

- **Confirm the single-file Windows build actually launches.** The
  `nuitka-onefile` job builds the exe and runs it with `--smoke` on a clean
  runner, exit 0 — but a report of "double-click does nothing" on a real
  machine is unresolved. Diagnosing it is now much easier: a startup failure
  writes `%TEMP%\AnalogStudio-crash.txt` and says so in a dialog, and a slow
  first launch shows a splash saying the assets are being unpacked. So the
  three candidate causes are now distinguishable rather than guesswork — a
  crash leaves the file, a slow unpack shows the splash, and SmartScreen
  blocking shows neither. The exe no longer expires either — it is a
  [v1.4 release asset](https://github.com/alexyudragonsword-collab/analog_skill/releases/tag/v1.4)
  now, not a 90-day artifact. Still needs one run on the reporting machine.

## Open

Nothing, as of 2026-09-13 — which is a statement about this list, not about
the project. Everything that was here has either landed (see
[`CHANGELOG.md`](./CHANGELOG.md)), been answered and moved to *Decided
against*, or turned out to need the maintainer's own machine and sits above.
The next item comes from *Ideas* below, or from a bug report.

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
- Make the LLM-guided algorithm cheaper per round. Through the Claude Code
  CLI a round measures ~90 s against ~3.5 s for an evaluation, so a
  150-evaluation run is about an hour and the model calls are essentially
  all of it. Levers, none tried: a smaller model for the loop and a large
  one only for `suggest_setup`; more workers so each round proposes more
  points; or keeping one CLI session alive with `--resume` instead of
  paying the cold start every round — that last one would make `chat()`
  stateful, which is exactly the trade rejected when the provider was
  added, so it needs a better reason than speed alone.

## Decided against

Reopening these is fine, but start from the reasoning, not from zero.

- **A `keyring` dependency for the LLM API key** (asked and answered
  2026-09-13). The key is stored in plain text by `QSettings`, and
  `ANALOG_LLM_API_KEY` already covers the case that motivated changing it —
  a machine the user shares. What `keyring` would add is protection for
  users who never learn the variable exists, at the price of a
  platform-specific package that has to survive PyInstaller, Nuitka and
  Nuitka-onefile on two platforms, for a key its owner pasted in by hand.
  The dialog and both manuals now state where the key lives, so the user
  who cares can act on it. Reopen if this app is ever expected to run where
  its users do not control the machine.
- **Connecting a knowledge base to Project Cairn now** (asked and answered
  2026-09-13). Cairn stays at `provider: none`. The local half — `LOG.md`,
  the topic notes, the audit — works without one, and graduation only earns
  its setup cost when there is a second project to graduate *into*. The
  trigger for reopening is that second project, not a calendar date.
- **Testing what the tabs draw.** The GUI tests stop at the reply: every
  tab's `on_job_finished` / `on_job_failed` is driven with a fabricated
  result, which is where the shared bugs live (a button left disabled after
  a failure, a stale gm/ID table installed as if current, a render closure
  that raises inside a Qt slot). Going further — asserting on pixels, widget
  geometry, or the contents of a rendered PNG — buys little: those change
  every time the layout does, and the plotting itself is covered at the
  `app/core/` level against real ngspice. `sizing_tab` sits at 56% for this
  reason, not by omission.
- **Re-capturing the other eight manual screenshots.** Only the Sizing one
  was replaced for v1.4. The tabs behind the rest have not changed materially
  since those images were taken, and re-capturing them through offscreen Qt
  produced emptier screenshots than the ones already committed.
- **Filling in every missing docstring.** Coverage of public definitions was
  raised from 45% to 56% by documenting the two files that define the
  concurrency contract (`SimWorker`, `JobTabMixin`) plus the registry
  dataclasses. The six tabs' `on_job_finished` / `on_job_failed` overrides are
  intentionally left bare — the protocol is stated once, in the mixin.
- **Fixing `analoggym/README.md`'s stale path.** It points the Sizing tab at
  `app/core/sizing.py`, which became a package in v1.4. Correcting one word
  costs less than this entry — but a snapshot edited for local convenience
  stops being a snapshot, and dated analyses in this repository cite these
  files as fetched. The discrepancy is noted in both READMEs instead, where
  a reader of *this* project will actually meet it.
- **Editing the vendored trees.** `analoggym/`, `circuit-skills/`, `gmoverid/`,
  `ngspice/` and `transistor-models/` are upstream snapshots that the app reads
  as shipped and that dated analyses in this repository cite. Behaviour changes
  are adapted around in `app/`.
- **Weakening the source-leak gate** in `linux-nuitka` to make a build pass.
  That gate — no `app/` `.py` or `.pyc` anywhere in the distribution — is the
  entire reason the Nuitka route exists alongside PyInstaller.
