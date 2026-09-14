---
type: project_topic
status: active
summary: "Failure modes in this codebase that are silent, expensive, or look like something else — each one cost real debugging time before it was written down."
tags: [analog-studio, ngspice, pyside6, packaging, testing, security]
contains: [lesson, experience]
created: "2026-08-18"
updated: "2026-09-14"
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

### A CLI agent is not a chat endpoint until you disarm it

Driving Claude Code as an LLM backend looks like swapping one transport for
another. It is not: the thing on the other end defaults to being an agent
with tools, on the user's own machine, reading the user's own
configuration. Four behaviours had to be switched off deliberately, and
three of them are silent when you miss them.

- **It inherits a session from the environment.** With no `--session-id`,
  the CLI picks one up from `CLAUDE_CODE_SESSION_ID` — which is set
  whenever the app is launched from inside a Claude Code session.
  Reproduced: two unrelated `-p` calls came back carrying the *host*
  session's id. A sizing prompt would be appended to the user's own
  conversation. Every call now pins a fresh uuid.
- **It reads the user's project configuration.** Their `CLAUDE.md`, hooks
  and MCP servers load unless `--setting-sources ''` and
  `--strict-mcp-config` are passed. An analog-sizing prompt has no business
  being steered by whatever instructions happen to be on that disk, and
  some MCP servers spawn processes of their own.
- **It keeps its tools.** `--restricted` drops the shell and code-running
  tools and WebFetch; the file tools survive it and need
  `--disallowed-tools`. It is run in an empty temp directory as well, so
  that there is nothing to reach if that list ever goes stale.
- **`--bare` would defeat the whole point.** It looks like the right flag
  for "use this as a plain model" — it is documented as skipping hooks,
  plugins and auto-memory — but it also restricts auth to
  `ANTHROPIC_API_KEY`, never OAuth. On a subscription that means no
  credentials at all.

Two measured numbers, against claude 2.1.270: a call costs ~4–6 s against
~1–2 s for a direct API request, because a whole CLI starts up each time —
so a 15 s timeout that is generous for HTTP is not generous here. And even
with the system prompt replaced and `--restricted` on, the prompt prefix
carries ~34 k tokens of scaffolding; it caches for an hour, so the first
call in a session is the expensive one and the rest read from cache.

**Correction, 2026-09-14 — "4–6 s" was measured on a toy prompt and is not
what this app's calls cost.** Re-measured on a real round of the sizing
loop (`amp_hoilee_affc`: a 7.4 kB prompt with the netlist, asking for four
candidate sizings across 33 variables):

| | |
|---|---|
| with a JSON schema | 88 s |
| without one | 112 s |

Two things follow. The **schema is not the cost** — constrained decoding
came back *faster* than freeform here, so a schema is free and the workload
is what is expensive. And a 120 s timeout, which is what `chat()` defaults
to, sits right on top of that distribution: the LLM algorithm would have
timed out intermittently, retried for another two minutes, and fallen back
to Sobol, quietly ceasing to be the LLM algorithm. The floor is 300 s.

The knock-on is a user-visible one worth remembering when adding any
provider: the Sizing tab estimated run time from `eval_seconds × budget`
alone, which is right to within a rounding error for every other algorithm
and wrong by a factor of thirty for this one. A transport whose latency is
a hundred times an evaluation's is not just a slower transport; it changes
which term dominates.

**And then measure where that latency actually is, because the obvious
answers were wrong.** Breaking down the 101 s:

| | |
|---|---|
| CLI startup and overhead | **1.0 s** |
| model generating | 100.2 s (11 128 output tokens at 111 tok/s) |
| of which the answer | ~1 300 tokens |

So nine tenths of what the model emits is reasoning, and the transport is
free. Two plausible-sounding optimisations die on that table. Batching
rounds into a single invocation — the reason to build an MCP server, or to
hold a session open with `--resume` — buys back one second in a hundred.
And a *smaller* model is not the lever: haiku took **117 s** against
sonnet's 101, because it generated more tokens (14 434) to arrive at the
same place. Token rate is not throughput when the token count moves too.

What does work is asking for less thinking. `--effort low` cuts the round
to **25 s** and the output to 3 520 tokens while the answer itself stays the
same size and still parses 4/4.

Whether it proposes as *well* is a separate question, and it needed a
separate experiment — speed is cheap to measure and quality is not, so do
not let the first stand in for the second. One full optimization per arm
(`amp_hoilee_affc`, 60 evaluations, cost against evaluation count):

  | evals | 10 | 20 | 30 | 40 | 50 | 60 | wall |
  |---|---|---|---|---|---|---|---|
  | low | 1.632 | 1.338 | 1.333 | 1.328 | 1.323 | **1.318** | 12.3 min |
  | default | 3.312 | 2.494 | 1.534 | 1.534 | 1.281 | **1.280** | 26.0 min |

The honest reading is that **the answer depends on which budget is scarce**,
and the two readings disagree. Per evaluation the default wins by 3% — and
at one run per arm, 3% is not distinguishable from run-to-run variation.
Per minute `low` wins by a lot: the default arm was still at 1.534 when
`low` had finished, and `low` passed that level at evaluation 20 of 60.

For a desktop app the scarce budget is the person's afternoon, so `low` is
the default. The shapes differ in a way worth remembering, though: `low`
drops fast and plateaus, the default keeps descending and overtakes it at
the very end. A circuit where the plateau is the wrong answer would be the
reason to revisit this.

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
