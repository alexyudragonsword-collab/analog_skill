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

Nothing, as of 2026-09-15. The one item that lived here for the whole of
this project's public life — "double-click does nothing" on the single-file
Windows build — was reported resolved by the maintainer.

**The root cause was not recorded.** Three candidates were instrumented for
it (a crash leaves `%TEMP%\AnalogStudio-crash.txt`, a slow first unpack
shows the splash, SmartScreen shows neither), and any of them would have
been worth writing down; none was. So a recurrence starts from zero rather
than from the answer. If it comes back, ask which of the three it looked
like before touching anything.

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
- Let `init_runtime()` honour an `ANALOG_WORK_DIR` that is already set.
  Today it assigns one derived from `repo_root()`, so the scratch tree is
  fixed per checkout and a long-running experiment cannot coexist with the
  test suite — which is why AGENTS.md has to forbid running them together
  rather than the code simply keeping them apart. Individual tests already
  isolate themselves this way (`_isolate_workspace`); the gap is that a
  whole run cannot. Small, but it turns a standing rule people must
  remember into something the code enforces. There is a workaround in the
  meantime — run the suite from a copy of the tree, since `repo_root()`
  follows `paths.py` (CONTRIBUTING has the two lines) — which lowers the
  urgency without making the gap less real.
- Follow up the operating-point result. One-shot proposals improve with the
  data on cost (23/25 pairings, p=0.016) but do **not** fix the saturation
  problem they describe, which was the declared metric and came back null.
  Two readings survive and are worth separating, because they imply
  different work: the model is reasoning about headroom, or the prompt
  merely mentions that seven devices are marginal and that induces caution.
  Keeping the proposed sizings and diffing them against the default would
  tell — a conservative arm makes smaller moves. Cheap, and it decides
  whether feeding operating points into the search loop is worth building.
- Decide whether `llm_agent` earns its place beside `llm`. It exists on
  architectural grounds — the model chooses what to simulate rather than
  answering a fixed question per round — and deliberately carries no claim
  about search quality, since the 33% run-to-run spread measured on this
  problem makes such a claim unsupportable at any affordable sample size.
  Two things would settle it without needing that: whether its written
  account of a run is worth reading (one person, a few runs), and whether
  it reliably spends the budget — the first real run stopped at 9 of 12,
  which the round-based loop never does. If the narrative is the value,
  say so in the docs and stop pretending the cost curve is the point.
- Settle whether the LLM loop's per-metric feedback earns its place. It is
  on by default as a judgment call, not a measured win: at n=3 vs n=4 on
  `amp_hoilee_affc` the medians are 1.4954 with it and 1.3768 without, and
  the no-feedback arm's own spread across four runs is 33%, so nothing is
  resolvable. The interesting signal is variance, not mean — the arm with
  feedback produced both the best run of the experiment and the worst.
  Answering it properly costs dozens of runs per arm, several hours; worth
  doing only alongside some other reason to burn that time.
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
