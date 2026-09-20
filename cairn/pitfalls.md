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

### A scalar is the weakest feedback channel you can give a model

The LLM-guided optimizer ran for a release telling the model one number per
candidate: `cost 0.83`. The circuit has **nine** metrics — gain, GBW, phase
margin, two PSRRs, CMRR, power, offset, tempco — each with its own target,
direction and weight, and `score()` folded all of them into that number
before the model saw anything.

So the model was asked to propose the next sizing without being told which
spec it had missed, by how much, or which ones had slack to trade away.
That is not a prompt-quality problem, it is a **missing channel**: an
analog designer given "DC gain 62 dB against a target of 100, power 62%
over" moves deliberately, and one given "0.83" can only wander.

What makes it worth remembering is where the information was. It was not
unavailable or expensive — `_eval_one` computed the whole metric dict,
passed it to `score()`, and returned the scalar. The explanation was being
*discarded* one frame below the code that needed it. When an LLM is inside
a loop, treat the feedback line as part of the design and go looking for
what the surrounding code already knows.

The fix also made `score()` the sum of `score_detail()` rather than a
parallel implementation. Two routines computing "the same" violation is how
the number the optimizer minimizes and the story the model is told quietly
stop matching.

Watch the blast radius when you change a shared return type: `run_batch`
feeds four algorithms, and `objective()` — the Powell refinement — returns
`_safe_eval(...)` straight through. Making that a tuple broke the *default*
algorithm while the change was nominally about the LLM one.

**And then the A/B went the other way**, which is the part worth keeping.
One run per arm on `amp_hoilee_affc` at 60 evaluations: with the metric
breakdown 1.4954, with the bare cost 1.3798 — the better-informed arm 8.4%
*worse*.

It would be as wrong to conclude "richer feedback hurts" as it was to
assume it helps, and the reason is an accident worth stealing as a method.
The earlier effort A/B's `low` arm is the *same configuration* as this
one's `cost only` arm, so those two runs are a replicate: **1.3182 and
1.3798, 4.6% apart with nothing changed at all.** The effect being chased
is 1.9x that. One run per arm cannot see it.

So the standing lesson is about the experiment, not the feature: on a
stochastic search driven by a stochastic model, *measure the noise floor
before believing an effect*, and get it almost free by repeating a
configuration you have already run. Three of this session's measurements —
haiku being slower, the schema being free, effort=low being fine — were
large enough to survive a 5% floor. This one is not.

**Correction, same day — the 4.6% floor was itself wrong, by about 7x.**
Replicating to n=3 and n=4:

| arm | runs (best cost, sorted) | median |
|---|---|---|
| with metrics | 1.2365 · 1.4954 · 2.8274 | 1.4954 |
| cost only | 1.3182 · 1.3738 · 1.3798 · 1.7504 | 1.3768 |

The `cost only` arm alone spans **33%** across four runs of one
configuration. A two-run replicate does not measure spread, it samples it
once — and the estimate it gives is a lower bound that reads like a
measurement. Where the first pair happens to land close together, as here,
it will talk you into believing far smaller effects than the setup can
resolve.

Separating an ~8% effect from a 33% spread needs on the order of (33/8)²
more runs per arm — dozens, several hours of simulator and model time. That
is the real price of the question, and worth knowing *before* deciding
whether to ask it. The other thing the replicates showed is that the mean
was the wrong statistic: the arms differ by 27% on means and by 8% on
medians, because one run of three blew up (2.8274, with no LLM fallback in
the log, so a genuine search failure). The interesting difference is in
variance, and n=3 cannot establish that either.

### "Check then create" is a race when the callers are your own threads

`ensure_sky130()` read like careful code: return early if the directory is
there, otherwise extract the zip into a temp tree and `os.replace` it into
place, which is atomic. The atomic step was never the problem. Between the
check and the rename sat a **fixed** temp path and a `shutil.rmtree` of it,
and the callers are `optimize(workers=4)` — four evaluation threads, each
reaching this on the first run.

Two threads both saw the directory missing. The second deleted the first's
half-written tree while it was still extracting into it. The survivor then
renamed whatever remained into place, and every simulation afterwards read
a **partial PDK** — which does not announce itself as corruption, it
announces itself as physics.

The tell was in the log the whole time and reads as noise: two
`Extracting SKY130 PDK …` lines against one `SKY130 PDK ready.`

Three things worth keeping:

- A fast-path check outside a lock is fine; the work behind it still needs
  the lock *and a second check inside it*, because whoever waited must not
  redo what the winner just did.
- `os.replace` being atomic says nothing about the directory you build
  before calling it. Give it a name only this caller can own — the pid is
  enough — so a second *process* cannot clobber it either.
- The failure mode is silent and downstream. Nothing throws; the numbers
  just stop being right. That is the same shape as the two-suites rule
  elsewhere in this file, and the same cause: shared scratch space with no
  owner.

### Declare the metric before the run, and report it when it says no

Operating points were added on a strong prior: the nine metrics say *that*
a sizing failed, the operating point says *why*, and that is the first
thing a designer looks at. The metric was declared in advance — devices out
of saturation, because that is what the information is about — precisely so
the answer could not be chosen afterwards.

It came back null. Five proposals per arm, baseline seven devices in
triode: with the operating points, 7 7 7 7 7; without, 7 7 7 8 8
(p = 0.09). **The model was handed a list naming the seven devices and the
variables that size them, and did not fix them.**

Cost, a secondary metric, separated cleanly: 23 of 25 pairings, U = 2,
p = 0.016, medians 8.15 against 14.41. The temptation is to lead with that
number. Leading with it would mean the experiment had no way to come out
negative, which makes it not an experiment.

So: the information seems to help, by a mechanism that is not the one
argued for, on a measure that was not the one declared — and a mundane
rival explanation is still standing, that a prompt mentioning seven
marginal devices simply induces caution. The next run keeps the proposals
so that can be told apart.

**Correction, 2026-09-16 — the declared metric could not move, and that is
a worse mistake than picking the wrong one.** Declaring it in advance was
right. Never checking whether the *treatment could change it* was not. The
seven devices come back identical at the default sizing, at mid-range, at
the low quartile and at the high quartile — the whole design space. They
are a bias mirror sitting 30–80 mV below Vdsat: a property of the topology,
not a fault. So "the model did not fix them" was never a finding about the
model. **A pre-declared metric with no variance under the treatment is not
a test, it is a guaranteed null**, and it reads exactly like a real
negative result.

One cheap check would have caught it, and it is now the habit: before
running the arms, move the *inputs* across their range and confirm the
metric responds. Four simulations, no model calls.

The same question asked a third way finally answered it. In the loop, with
real cost feedback, the targeting collapses — fourteen rounds went 0.0,
0.9, 1.0, 1.7 and then **exactly 0.0 for the last ten**, the model dropping
those four variables entirely while still moving every other one. That is
the correct behaviour and it is what a search is for: it tried the thing it
was pointed at, the cost did not move, it stopped. Cold, the same data
makes it chase them 10-12x harder.

Which leaves the transferable shape: **information that survives a
cold-start test can still be useless in a loop, because feedback already
supplies what the information was standing in for.** Test a loop feature in
the loop.

Worth keeping alongside the noise-floor lesson above: **a low-variance
proxy makes small effects visible where the end-to-end outcome cannot.**
n=5 was enough here because one-shot proposal quality has no compounding
search randomness in it; the same five runs measured as search outcomes
would have shown nothing at all.

### Run the baseline before the fourth experiment on the treatment

A week of A/B tests on the LLM-guided optimizer — effort, per-metric
feedback, structured output, operating points — and not one of them asked
whether the LLM path beats the three classical algorithms already in the
app. The baseline costs ten minutes of simulator time and no model calls,
and it reorders every other result. `amp_hoilee_affc`, 60 evaluations:

| algorithm | best cost | spread | wall |
|---|---|---|---|
| sobol_powell | 3.306 | — | 112 s |
| optuna | 3.247 | — | 51 s |
| diff_evolution | 1.205 (seed 0) | 0.66–3.31 over five seeds | 45 s |
| LLM loop | 1.377 median | 1.23–2.83 over ten runs | 12–26 min |

The two model-based samplers do nothing at all in 33 dimensions with 60
points. DE at that budget is a 60-point Sobol sample with one generation
of selection — hence the 5x spread across seeds. The LLM loop is the most
*reliable* of the four at this budget and the second best, and per minute
of wall clock DE wins by a factor of twenty. All of the earlier questions
("does the operating point help the loop?") were being asked about the
wrong quantity: the loop was never the fastest way down, and no
improvement to it was going to change that.

The order of operations that would have avoided this: baseline first,
then treatments, then treatments *of the winner*.

### Running the optimizer longer is not a plan until you have checked

DE seed 3 reaches 0.5076 at 600 evaluations, eight of nine targets met,
phase margin 39.7° against 60. The obvious next step — run it to 1200 —
returns **0.5076**. The history shows the last improvement at evaluation
~530; the population had converged and every generation after it was a
no-op. A converged DE looks exactly like a slow one from the outside; the
history is the only thing that tells them apart, and it is recorded.

### Compare the proposal against what the model was shown

Six one-shot proposals from the same DE point each reported **23 of 33
variables changed**, against a prompt that said "change as few as you
can". The model was shown values formatted `.4g`; it echoed them back at
four significant figures; the comparison ran against the full-precision
originals, so every rounded value counted as a change. Against the values
actually in the prompt, each proposal moved **two or three** — the two
compensation capacitors and one of the feed-forward widths, exactly the
"compensation and stability" variables the prompt asked for.

The general form: a model can only return what it was given, so the
baseline for "what did it change" is the prompt, not the state that
produced the prompt. And a suspiciously constant number (23, every time)
is a measurement artefact until shown otherwise.

### One shot gets the knob right and the magnitude wrong

The same six proposals, judged as asked — does phase margin reach 60°
without breaking the eight met targets:

| arm | raw proposal PM | after bisection along its direction |
|---|---|---|
| with-op t0 | 78.3 | **59.9**, 8/9 intact, cost 0.0035 |
| with-op t1 | 49.7 | stalls at 50 with both caps at range top |
| with-op t2 | 49.5 (gain broken) | stalls at 43 |
| metrics-only t0 | 90.2 (offset broken) | **59.8**, 8/9 intact, cost 0.0043 |
| metrics-only t1 | 48.9 | stalls at 50 |
| metrics-only t2 | 88.0 (offset broken) | **60.2**, 8/9 intact, cost 0.0043 |

Zero of six land. Six of six move PM the right way. Three of six overshoot
by 20–30° and, walked back along their own direction with seven
simulations (21 s), sit within 0.2° of the target with nothing else
broken — the first near-feasible sizing this project has produced, from a
point DE could not leave. The three that fail are the three that touched
only the capacitors; the three that succeed are the three that also
widened the AFFC transconductor (`MOSFET_60_2_W_gma_NMOS`), which is the
textbook knob for this topology. The operating point did not change the
odds (2 of 3 with it, 1 of 3 without).

So the model's contribution is *which variables*, and its failure is *how
far*. Those are cheap to separate: a one-dimensional search along the
model's direction costs seven simulations, against 600 for the DE that got
stuck and ~150 s for the model call that picked the direction. The shape
of the thing that works is DE for the bulk, one model call for the
diagnosis, a line search for the number — not a model in the loop.

Caveat in proportion: one circuit, one DE point, six proposals. Enough to
choose the next thing to build, not enough to put a number in a README.

Built the same day as `de_llm_finish` (`llm_sizing.run_finish`): DE to
all but the last 16 evaluations, one call, a six-point scan along the
proposal then three bisection rounds. The prompt tells the model the app
will search along its answer — the one thing this measurement says it
should spend its effort on.

### The finish on eight circuits: round one pays, later rounds rarely do

The maintainer asked for the finish to run more than one round and to be
tried beyond the one circuit it was built on. Both at once, shipped path,
real CLI, four kinds of circuit (amps 600 evaluations, CM OTA 400, LDO
600, circuit-skills 120, three rounds of 16 held back):

| circuit | DE at its cap | after the finish | rounds | wall |
|---|---|---|---|---|
| amp_leung_nmcf | 1.4999 | 1.4999 | 3, none helped (PM 5°) | 17.7 min |
| amp_peng_tcfc | 0.6695 | 0.5817 | 1 helped, 2 did not | 18.7 min |
| amp_ramos_pfc | 1.3094 | 0.7784 | 1 helped (2 variables), 2 did not | 16.0 min |
| amp_fan_smc | 0.4891 | **0.0000** | 3, each helped: 0.058, 0.001, 0 | 11.5 min |
| studio_cm_ota | 0 | 0 | DE alone; finish skipped | 1.8 min |
| ldo_basic | 0 | 0 | DE alone; finish skipped | 8.8 min |
| skill_ota5t | 0.1731 | 0.1492 | 2 helped, 1 did not (gain 37 of 40 dB) | 2.5 min |
| skill_opamp2 | 0.2215 | 0.1326 | 1 helped (IBIAS), 2 did not (gain 65 of 70 dB) | 5.1 min |

Read across the rows, three things are true.

**Where DE stalls short, the first round usually moves it**: five of six
finishes that ran improved in round one, by 13% to 100%, and the two
largest gains came from proposals that touched *two* variables (a
capacitor and the bias current). The one that moved nothing is the one
that started furthest away — phase margin 5°, three targets short — and
that is the case ROADMAP already names as where a one-shot diagnosis has
nothing to say.

**A round after a failed round failed too, five times of five.** The
model's own rationales say why: by round two it is describing a
trade-off it believes is fundamental ("GBW ≈ gm1/2πC0 with C0 Miller-
multiplied", "gain set by IBIAS and the mirror ratio") and proposing
variations on the direction that already lost. Feeding the failure back
did not produce a different idea. So the finish now stops after a round
that improves nothing — which cost nothing on any of the eight and saves
a model call and sixteen evaluations on four of them.

**Rounds that keep paying keep going**: `amp_fan_smc` needed all three,
0.489 → 0.058 → 0.001 → 0, one or two variables each, and would have
stopped one short of feasible under a single round.

Two circuits DE finished by itself, and the early exit spent nothing on
them. The two circuit-skills gain misses (37 of 40 dB on a five-transistor
OTA whose shipped default measures 34, 65 of 70 dB on the two-stage) may
be targets the topology cannot reach in its box; nothing here says either
way.

Proportion again: eight circuits, one run each, DE's fixed seed. Enough
to keep the algorithm and set its stopping rule; a claim about *how
often* it closes the gap wants a second seed per circuit.

**Correction, an hour later — five of six, not five of five.** The
reference amplifier re-run under the 60–90° band (below) ran on the
code from before the stopping rule, and its third round improved after
two failed ones: 1.1242 → 1.0354, 8%, phase margin 156° → 151°, still
61° outside the band. So the rule has one counterexample, and what the
counterexample bought was small. The rule stays: five wasted calls
against one 8% gain. Written down so the next person does not read
"every time" and stop looking.

### Under the band, the reference amplifier is unsolved

`amp_hoilee_affc`, shipped path, 616 evaluations, real CLI, phase
margin as a 60–90° band: DE's fixed seed converges into the same
over-compensated basin as before — 155.8°, offset 3% over, cost 1.12 —
and three finish rounds cannot bring the phase margin down. The model
names the right knobs (the compensation capacitors, the AFFC
transconductor, the feed-forward stage) and every line through them
either leaves the phase where it is or breaks something met. The design
the floor called feasible is the one the band charges 1.1 for, and no
algorithm in the app currently reaches the band on this circuit from
this seed.

That is the price of the ceiling, stated plainly: it removed a solution
without supplying one. It does not say the ceiling is wrong — a 156°
amplifier with its dominant pole below 0.1 Hz is not what anyone asked
for — but it does say the band is the harder problem, and the search
that finds it will be a different search: a seed that does not land in
that basin, or DE told about the ceiling early enough to leave it.

**Both tried, the same night.** Shipped path, 616 evaluations each:

| run | DE at 568 | after the finish | what is left |
|---|---|---|---|
| seed 0 | 1.1242 | 1.0354 | PM 151°, offset 3% over |
| seed 1 | 1.0904 | 1.0904 | PM 25°, offset 45% over |
| seed 2 | 1.2546 | **0.8566** | offset 271 µV vs 100, everything else met |
| seed 0, band as a hard constraint | 1.5489 | 1.5489 | PM met; gain 54 dB, tempco, offset, PSRR− |

Three seeds, three basins, none feasible: over-compensated, under-
compensated, and inside the band with the offset far out. The hard
constraint is the instructive failure — DE obeys the 10x term and
abandons gain to do it, ending worse on the plain cost than any seed
without it. So it is the circuit and the band, not the seed; and
"tell DE about the ceiling harder" is the wrong lever. Seed 2 is the
most promising endpoint (one miss, the finish already cut it by a
third), and the reason it stopped there is in the model's own words:
the offset knob is the input pair, and the input pair is also what
sets the metrics that are met. What would move it is not obvious and
is not claimed.

### A second seed on every circuit

The eight-circuit table above at seed 1, same shipped path, targets as
they were that night (the two circuit-skills gain targets have since
been lowered; the last column says which rows that flips):

| circuit | seed 0: DE → finish | seed 1: DE → finish | under today's targets |
|---|---|---|---|
| amp_leung_nmcf | 1.4999 → 1.4999 | 1.2637 → 1.0786 | — |
| amp_peng_tcfc | 0.6695 → 0.5817 | **0 by DE alone** | — |
| amp_ramos_pfc | 1.3094 → 0.7784 | 1.1263 → 0.9043 | — |
| amp_fan_smc | 0.4891 → **0** | 0.3759 → 0.0669 | — |
| studio_cm_ota | 0 by DE | 0 by DE | — |
| ldo_basic | 0 by DE | 0.9751 → **0** | — |
| skill_ota5t | 0.1731 → 0.1492 | 0.1600 → 0.1600 | both feasible (36.8, 37.0 dB ≥ 36) |
| skill_opamp2 | 0.2215 → 0.1326 | 0.1933 → 0.1933 | seed 0 feasible (65.4 ≥ 64); seed 1 PM 58° |

Sixteen runs. DE alone finishes four; the finish closes two more,
improves seven, and does nothing in three. Under today's targets nine
of sixteen end feasible. The rows disagree between seeds on every
circuit DE does not finish outright — `amp_peng_tcfc` goes from 0.58 to
0 by changing nothing but the seed, `amp_fan_smc` the other way — which
is the 33%-spread lesson again at 600 evaluations instead of 60: the
*seed* is worth more than any single finish round, and a user with an
unfinished result should try another seed before trying anything
cleverer. That is an argument for exposing `seed` in the GUI, recorded
in ROADMAP, not built tonight.

What the finish is for, on this evidence: the last few percent when DE
stops close (`ldo_basic` 0.98 → 0 in eight evaluations; `amp_fan_smc`
0.49 → 0), and a 15–40% cut when it stops mid-way. Not a rescue when it
stops far away.

**Correction, the next morning — "far away" was the wrong measure.**
The maintainer asked for `amp_leung_nmcf` at seed 2 with twice the
budget:

| | cost |
|---|---|
| DE at 552 (what a 600 budget would have left) | 2.0603 — worse than either earlier seed |
| DE at 1000 | 1.0998 |
| DE at 1152, the cap | 1.0998 — four targets short |
| finish round 1: input-pair L, two mirror L, bias current | **0.0355** |
| finish round 2: input-pair W, bias current | **0.0000, all nine met**, PM 68° |

Fifteen minutes. A cost of 1.10 was "far" by the sentence above, and the
finish closed it in eighteen evaluations. The difference from seed 0's
1.50 that nothing could move is not the number but *what* was short:
there, phase margin at 5° — a compensation that had not formed; here,
four misses that all answered to the bias current and three channel
lengths. Distance in cost says nothing about that. What does is whether
the misses share a knob, which is what the model's first rationale
identified and the line search confirmed. Budget mattered too: at 600
this seed was the worst of the three. The cheap sequence for a stuck
circuit, on all of this: another seed, then more budget, then the
finish — and the finish is the part that turns "close" into "done".

### An equality target with no tolerance can never be met

`MetricScore.met` is `violation <= 0.0`; for a `'target'` metric the
violation is `|m − target| / |target|`, which is zero only at exact
equality. Every amplifier and LDO circuit carries phase margin as a
`'target'`, so "9/9 met" and cost 0 are unreachable on them by
construction — the sizing above at 59.86° reads "8/9 met, off 0%". A week
of "nothing reached feasibility" was partly a definition. The fix is a
tolerance (or a direction: `≥ 60` with no penalty above, as the CM OTA
already does at 55°), and it changes cost values, so it is a spec decision
rather than a bug fix to slip in.

**Resolved the same day, by the maintainer's call: `≥ 60`** on every
amplifier, LDO and circuit-skills spec. Cost values measured before the
change are under the old rule; the tables in this file say which. The
`'target'` kind itself is unchanged and unused by the registry.

### CMA-ES: the first search that beats DE on this problem

Four searches were added on the same day and measured on the nine-
circuit protocol, seed 0, 600 evaluations (400 for the OTA, 120 for the
circuit-skills pair), the shipped path, no model calls:

| circuit | DE | CMA-ES | DE + Powell | constrained DE |
|---|---|---|---|---|
| amp_leung_nmcf | 1.4999 | **0.2935** | 0.8321 | 1.5217 |
| amp_peng_tcfc | 0.6695 | **0** | 0.0300 | **0** |
| amp_ramos_pfc | 1.1609 | 1.2801 | **0.8074** | 1.3094 |
| amp_fan_smc | 0.4891 | **0** | 0.5842 | 0.1006 |
| amp_hoilee_affc | 1.1242 | **0** | 0.8792 | **0** |
| studio_cm_ota (400) | 0 | 0 | 0 | 0 |
| ldo_basic | **0.6758** | 0.8685 | 1.2348 | 1.3648 |
| skill_ota5t (120) | 0 | 0 | 0 | 0 |
| skill_opamp2 (120) | 0 | 0 | 0 | **0.2312** |
| feasible / 9 | 3 | **6** | 3 | 4 |
| best or tied / 9 | 4 | **7** | 4 | 4 |
| sum of costs | 5.62 | **2.44** | 4.37 | 4.53 |

**CMA-ES with restarts closes three amplifiers DE leaves open** —
including the reference amplifier under the 60–90° band, which four
DE-based runs and three finish rounds could not reach (phase margin
87.6°, gain 111 dB, feasible by evaluation 500). Its two losses are
`amp_ramos_pfc` (10% behind DE; GBW is the wall for every search
there) and `ldo_basic` (28% behind). Covariance adaptation is the
plausible reason for the amplifier wins — the cost is ill-conditioned
in the box, which DE's fixed mutation ignores — but that is an
explanation, not a measurement; the restart log was not captured on
this tier (the runner kept only the finish's notes; fixed for the next
tier).

**Constrained DE is a different search, not a re-scored one.** SciPy's
acceptance rule (Lampinen) replaces an infeasible parent only with a
trial *no worse on every metric*: it refuses the trade that fixes one
target by breaking another, which the summed cost takes. On the
reference amplifier that refusal is what keeps it out of the 156°
basin and it reaches feasibility; on `skill_opamp2` the same refusal
is what stops it at 0.23 where the other three reach 0. Same rule,
both signs.

**The Powell polish is a modest, uneven gain**: better than DE on four
amplifiers, worse on `amp_fan_smc` and much worse on the LDO, where
150 serial evaluations of Powell bought less than DE's next 150 would
have. Its cost is wall clock — Powell is serial, so those runs took
1.7x DE's time.

**The LDO family is where all three lose to plain DE.** One circuit,
one seed; the seed-1 tier and the DE-vs-portfolio tier at 1200 are
running as this is written.

What it means for the menu: CMA-ES is the candidate default for the
amplifiers, and it needs the seed-1 tier before it becomes one. The
finish still applies on top of any of them — `amp_ramos_pfc` and the
LDO are exactly the "close but not closed" endpoints it was built for —
and wiring it behind CMA-ES is the obvious next algorithm.

**The seed-1 tier and the 1200 tier, the next day.** The full picture:

Both seeds, 600 evaluations (400 for the OTA, 120 for the circuit-skills
pair), the shipped path, no model calls. Bold is best or tied in its row.

| circuit | DE s0 | s1 | CMA-ES s0 | s1 | DE+Powell s0 | s1 | constrained s0 | s1 |
|---|---|---|---|---|---|---|---|---|
| amp_leung_nmcf | 1.4999 | 1.2637 | **0.2935** | **1.0338** | 0.8321 | 1.5674 | 1.5217 | 2.0189 |
| amp_peng_tcfc | 0.6695 | **0** | **0** | **0** | 0.0300 | **0** | **0** | **0** |
| amp_ramos_pfc | 1.1609 | 1.1263 | 1.2801 | **0.4471** | **0.8074** | 1.1184 | 1.3094 | 1.3583 |
| amp_fan_smc | 0.4891 | 0.3759 | **0** | **0** | 0.5842 | 0.0712 | 0.1006 | 0.3759 |
| amp_hoilee_affc | 1.1242 | 1.0904 | **0** | **0** | 0.8792 | **0** | **0** | 1.0904 |
| studio_cm_ota | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| ldo_basic | **0.6758** | 1.4603 | 0.8685 | **0.3611** | 1.2348 | 1.1242 | 1.3648 | 2.3512 |
| skill_ota5t | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| skill_opamp2 | **0** | 0.0138 | **0** | **0** | **0** | **0** | 0.2312 | 0.4892 |
| feasible / 18 | 6 | | **12** | | 8 | | 7 | |
| best or tied / 18 | 7 | | **16** | | 9 | | 7 | |
| sum of costs | 10.95 | | **4.28** | | 8.25 | | 12.21 | |

The 1200-evaluation tier, seed 0, where the portfolio is defined:

| circuit | DE @600 | DE @1200 | portfolio @1200 | CMA-ES @600 |
|---|---|---|---|---|
| amp_leung_nmcf | 1.4999 | 1.4083 | 1.5811 | **0.2935** |
| amp_peng_tcfc | 0.6695 | **0** | 0.1242 | **0** |
| amp_ramos_pfc | 1.1609 | **0.7688** | 1.1639 | 1.2801 |
| amp_fan_smc | 0.4891 | 0.1394 | 0.0310 | **0** |
| amp_hoilee_affc | 1.1242 | 0.9778 | fell back to DE | **0** |
| ldo_basic | 0.6758 | **0.2408** | 0.4917 | 0.8685 |
| the other three | 0 | 0 | 0 | 0 |

**Seed 1 agrees, and then some.** CMA-ES is best or tied on all nine
circuits at seed 1, and on 16 of 18 rows overall; it reaches
feasibility on 12 of 18 against DE's 6, and its two losses at seed 0
(`amp_ramos_pfc`, `ldo_basic`) turn into wins at seed 1 (0.45 against
1.13; 0.36 against 1.46). At 600 evaluations it beats DE *at 1200* on
three amplifiers and ties on one. The restart log, captured this time,
says every seed-1 run was a single CMA-ES run stopped by the budget:
**the IPOP restarts never fired at 600**, so what won here is plain
CMA-ES — covariance adaptation on an ill-conditioned box — and the
restart machinery is untested on this problem.

**The Powell polish is second**, feasible on 8 of 18, and its pattern
is exactly the finish's: it closes what DE leaves close and does
nothing where DE stops far. **Constrained DE is last**, feasible on 7
but with the worst sum by far, because the per-metric acceptance rule
that wins `amp_hoilee_affc` at seed 0 refuses too many trades
elsewhere (seed 1: 2.02, 2.35, 0.49 where DE has 1.26, 1.46, 0.01).
**The portfolio loses on three of the four circuits it can run on**:
two generations per seed is not enough to judge a seed by, and the
384 evaluations spent on the discarded seeds are what the continued
one lacks. It stays in the menu with its warning; it should not be
recommended, and whether it stays at all is the maintainer's call.

The LLM finish, in this light: it was the first thing to close a gap
DE left; CMA-ES now closes most of those gaps by itself at the same
budget, without a model. The finish's remaining place is behind CMA-ES
on what CMA-ES leaves close — `amp_leung_nmcf` and `amp_ramos_pfc` at
seed 1, the LDO at seed 0 — which is a wiring change, not a new idea.

**Wired and run on exactly those three** (`cmaes_llm_finish`, 600
evaluations: CMA-ES to 552, the finish's 48):

| circuit | CMA-ES alone @600 | CMA-ES @552 | + finish | rounds |
|---|---|---|---|---|
| amp_leung_nmcf s1 | 1.0338 | 1.0338 | 1.0338 | 1, nothing (PM 30°, three misses) |
| amp_ramos_pfc s1 | 0.4471 | 0.4471 | **0.2836** | 1 helped (input pair M, cap, bias), 2 nothing |
| ldo_basic s0 | 0.8685 | 0.7390 | 0.7390 | 1, nothing (GBW 37% short) |

One of three helped, none closed. The same shape as behind DE: it
moves what is close (`amp_ramos_pfc`, two misses, 27% and 1%) and has
nothing for what is far (phase margin 30° with three misses; GBW 37%
short). The default `cmaes_llm_finish` stands on that — the finish
costs nothing when it finds nothing beyond one model call and six
evaluations — but the claim it carries is "sometimes the last 40%",
not "closes it".

A discrepancy, recorded rather than explained: the two amplifiers'
CMA-ES trajectories reproduced the standalone runs to the digit; the
LDO's did not (4.32 against 2.65 at evaluation 100, same seed, same
code) and ended better at 552 than the standalone run did at 600. The
amplifiers say the search is deterministic; the LDO says something in
its evaluation is not — a simulation that failed once under load is
the likely candidate, not verified.

### Opus against sonnet on the finish: inside one model's own spread

The maintainer asked whether the diagnosis is model-sensitive. The
same three CMA-ES endpoints, the finish alone with 48 evaluations,
every round asked (`FINISH_STOP_ON_STALL = False`), one run per cell:

| case | start | opus, 3 rounds | sonnet, 3 rounds | sonnet earlier, stall rule |
|---|---|---|---|---|
| amp_leung_nmcf s1 | 1.0338 | **0.9971** (rounds 1 and 3) | 1.0338 | 1.0338 (1 round) |
| amp_ramos_pfc s1 | 0.4471 | 0.4471 | 0.4471 | **0.2836** (round 1) |
| ldo_basic s0 | 0.7390 | **0.5778** (rounds 1 and 2) | 0.7009 (round 2) | 0.7390 (1 round) |
| wall, three rounds | | 4–7 min | 7–9 min | |

Opus improved two of three, by 4% and 22%; sonnet with every round
asked improved one, by 5%. The row that decides how to read this is
`amp_ramos_pfc`: **sonnet's two runs from the same point disagree with
each other** — 37% off in one, nothing in three rounds of the other,
with the first round naming the same three variables both times and
proposing different amounts. A model's proposal is not repeatable
call to call, and that spread (37 points on one row) is larger than
any difference between the two models here. One run per cell cannot
rank them; the honest statement is that opus was faster per call at
the default effort (an hour of calls said so consistently) and not
measurably better.

**Correction to the stall rule's record.** With every round asked, a
round after a failed round improved twice in five chances — opus's
round 3 on `amp_leung_nmcf` (1.5%) and sonnet's round 2 on the LDO
(5%) — where the first sweep had seen none in five. "Five of five"
was the small-sample reading; the rule now rests on "usually not, and
small when it does", against one model call and six to sixteen
evaluations per round. It stays, as a default and not a law, and the
switch exists for whoever wants the rounds anyway.

### Three proposals a round: the spread, used

Built on the repeatability finding: each round asks the same question
three times in parallel, scans all three directions in one batch,
refines the best. Same three endpoints, sonnet, three rounds:

| case | start | ×1, stall rule | ×1, 3 rounds | opus ×1, 3 rounds | **×3, 3 rounds** |
|---|---|---|---|---|---|
| amp_leung_nmcf s1 | 1.0338 | 1.0338 | 1.0338 | 0.9971 | **0.8901** (round 1) |
| amp_ramos_pfc s1 | 0.4471 | 0.2836 | 0.4471 | 0.4471 | **0.2519** (round 2, after a failed round 1) |
| ldo_basic s0 | 0.7390 | 0.7390 | 0.7009 | **0.5778** | 0.6638 (rounds 1 and 2) |
| evaluations | | 6–12 | 18–24 | 18–30 | 60–66 |
| wall | | | 7–9 min | 4–7 min | 10–14 min |

Three of three improved, by 14%, 44% and 10% — the first column in
this whole series to improve every case — and best of all five on two.
The cost is evaluations (three lines scanned a round) and some wall
clock: three concurrent CLI calls do slow each other. What it buys is
what the repeatability row predicted: on `amp_ramos_pfc`, one draw
found the 37% cut once in two tries; three draws found 44%.

**The stall rule, turned off.** `amp_ramos_pfc`'s win came in round
2 after a round 1 in which none of three lines improved — the third
time a round after a failure paid, now 3 of 6 chances, and the largest
gain of the three. With three proposals a round, a failed round is
three draws, not a verdict; the next costs three parallel calls and
thirty evaluations. `FINISH_STOP_ON_STALL` is now off by default; the
first measurement that put it on is above, uncorrected, with its
correction beside it.

### IPOP restarts never fire here; budget does the work

CMA-ES alone at 1200 evaluations on the four rows it left open at 600
(ten-target spec):

| row | @600 | @1200 | restarts |
|---|---|---|---|
| amp_leung_nmcf s1 | 0.8965 | 0.7960 | none |
| amp_ramos_pfc s0 | 0.5781 | 0.5299 | none |
| ldo_basic s0 | 0.8397 | **0, all 8 met** | none |
| ldo_basic s1 | 0.8043 | **0, all 8 met** | none |

Not one run stopped on pycma's own criteria (`tolfun` 1e-6, `tolx`
1e-4) in 1200 evaluations: the search keeps finding hairs of
improvement, so the restart machinery — twice the population from a
fresh point — is dead code on this problem at these budgets. What
moved the rows was the budget itself: both LDO seeds reach every
target by 1000. The lesson is the same as the finish's: "stalled" on
this cost surface has to be defined by the history (no new best in N
evaluations), not by the optimizer's internal tolerances, and if a
restart is ever wanted here it should trigger on that.

### The default on every circuit, once

`cmaes_llm_finish` as shipped — three proposals a round, finish on
stall, CMA-ES resumed after it — on every registered circuit but the
160 s/evaluation comparator, seed 0, 600 evaluations (400 OTA, 120
circuit-skills, 60 the bootstrap switch), the ten-target amplifier
spec with settling time:

| circuit | cost | what is short |
|---|---|---|
| amp_hoilee_affc | **0** | — |
| amp_leung_nmcf | 0.9573 | phase margin 30°, power 20% over |
| amp_leung_nmcnr | 0.2305 | settling 2.46 µs |
| amp_leung_dfcfc1 | 0.5062 | power 30%, gain 92 dB, GBW |
| amp_leung_dfcfc2 | **0** | — |
| amp_peng_acbc | **0** | — |
| amp_peng_iac | **0** (280 evals) | — |
| amp_peng_tcfc | **0** (208 evals) | — |
| amp_qu2017_azc | 0.0067 | settling 2.013 µs |
| amp_ramos_pfc | 0.5396 | power 48%, settling 2.12 µs |
| amp_sau_cfcc | 0.5951 | gain 85 dB, offset, tempco |
| amp_song_dacfc | 0.2581 | phase margin 55°, settling 2.25 µs |
| amp_yan_az | **0** | — |
| amp_fan_smc | **0** (126 evals) | — |
| amp_alfio_raffc | **0** (265 evals) | — |
| ldo_basic | **0** | — (0.18 with the LDO ceiling that went the same day) |
| skill_ota5t / opamp2 | **0** / **0** | — |
| skill_ldo | 0.1270 | loop gain 52 of 55 dB, PSRR 57 of 60 |
| skill_comparator_fast | 0.8994 | latch τ 8.5 of 6 ps, width |
| skill_bootstrap | 0.0683 | Ron ratio 1.26 of 1.2 |
| studio_cm_ota | **0** (96 evals) | — |

**Twelve of twenty-two feasible**, five of them with the search ending
early on stall at cost 0 (126–280 evaluations instead of 600: the
stall rule pays both ways). The four LDO variants are missing from the
table on purpose: at their *shipped defaults* they report output
errors of −4.8 to −5.7 V against a 1.8 V supply and load regulation of
4–15 V/A, which is not a circuit but a metric mapping — `_ldo_metrics`
reads the variants' wrdata columns in `ldo_basic`'s order and the
variants do not write them that way. Registered since v1.4 and never
run until now; ROADMAP has it, and nothing measured on them counts.

> Correction (same day, after the fix): half of that diagnosis was
> wrong. The columns *are* in the same order in all five decks; what
> differs is the arithmetic typed into them (next section). And the
> load-regulation numbers were never a mapping error — 4.3 and 14.7
> are what `ldo_simple` and `ldo_folded_cascode` really do at their
> defaults (78 mV and 224 mV of output swing over 10 mA, relative to
> the output, per ampere). The unit was the lie: the decks compute
> ppavl/avgval/ΔI, which is 1/A, and the spec had labelled it V/A.

Two readings. First, the settling target is tight: four amplifiers end
within 0.5 µs of the 2 µs with everything else met, and two of those
(`amp_qu2017_azc` at 2.013 µs, `amp_leung_nmcnr` at 2.46 µs) would be
feasible at 2.5 µs. The number is ~15 time constants at the GBW
target and was set on one circuit; whether 2 or 2.5 is right is a
design call, and the table is the evidence for making it. Second, the
sweep's cost was one day of simulator time and it found two bugs of
mine (the deleted deck, the variants' mapping) that no nine-circuit
protocol would have. A default is a claim about every circuit; test it
on every circuit.

### Five decks, one author's arithmetic: undo it per deck

The vendored LDO testbenches all print the same five columns in the
same order — `LR Power1 Power2 vos1 vos2` — and all five compute them
with Basic_LDO's numbers typed in: `vos = vout - 4*Vref` (there is a
4:1 divider only in Basic_LDO and `ldo_1`; `ldo_2`, `ldo_simple` and
`ldo_folded_cascode` regulate to the reference itself, so their "vos"
was `vout − 6.4` or `vout − 7.2`), and the reader took the quiescent
current as `Power2/1.8 − 5 mA` on circuits running from 2 V at 10 µA.
At the shipped defaults that read −5.4 V of output error on a circuit
sitting 3 mV from its 1.8 V target.

The fix is a per-circuit bench table (`LdoBench` in `spec.py`, filled
in `registry.py`): the regulated output, the supply, the Vref the deck
subtracts four times, and the two load points. `_ldo_metrics` adds
`4·tb_vref` back to recover `vout`, takes the error against the
circuit's own output, and takes the min-load current off the supply
current with the deck's own supply. The decks are untouched, as the
rule says; the reader carries the knowledge.

| circuit | in / out | loads | Vout error (max / min load) | Iq |
|---|---|---|---|---|
| ldo_basic | 1.8 / 1.6 V | 5–55 mA | −8 / −4 mV | 19 µA |
| ldo_1 | 1.8 / 1.6 V | 1–100 mA | +5 / +6 mV | 21 µA |
| ldo_2 | 1.8 / 1.6 V | 1–100 mA | −30 / −30 mV | 30 µA |
| ldo_simple | 2 / 1.8 V | 10 µA–10 mA | +3 / +81 mV | 291 µA |
| ldo_folded_cascode | 2 / 1.8 V | 10 µA–10 mA | −313 / −89 mV | 1.6 mA |

What kept this alive from v1.4 to v1.6 was that the reader's column
order *was* right, so a test that only checked the keys existed
passed. The test that catches it is the one that says what the number
must be: the output within a few hundred millivolts of the circuit's
own reference at its shipped default. Two more now hold the line: the
bench table is checked against each deck's `.PARAM` and `alter` lines
and the netlist's divider, and the fold is unit-tested from a
fabricated wrdata row.

Three of the four are far from Basic_LDO's targets at their defaults
(costs 19–33 against ldo_basic's 10), and the decks' own conditions
explain part of it: the line-regulation sweep for `ldo_simple` and
`ldo_folded_cascode` runs VDD 1.8→2.2 V for a 1.8 V output, so it
starts in dropout. Whether the variants keep Basic_LDO's targets is
now a design question on real numbers (ROADMAP), not a bug.

### A surrogate over the whole box learns power and little else

Probe for the surrogate-assisted idea (fit a model of sizes → metrics,
optimise on it, verify in SPICE), 2026-09-20, scratchpad
`surr_sample.py` / `surr_fit.py`: Sobol samples, a Gaussian process
(Matern ARD) and a gradient-boosted baseline per metric, held-out
R² / Spearman ρ, then three rounds of CMA-ES on the predicted cost
with eight SPICE verifications each.

| regime | sims complete | learnable (GP R²) | not learnable (R² ≤ 0) | proposals vs SPICE |
|---|---|---|---|---|
| amp_hoilee, whole box, 256 pts, 33 vars | 87 % | power 0.89; GBW, PSR+ ≈ 0.3 | PM, CMRR, PSR−, offset, tempco, settling | predicted 0.02–0.2, real 2.7–21; sample best (1.02) never beaten |
| ldo_basic, whole box, 192 pts, 20 vars | 37 % | Vout error 0.80, PSRR 0.74, LR 0.60 | both phase margins | 1.21 → 1.16 in two rounds; third round 8 of 8 failed sims (cost 95) |
| amp_hoilee, ±10 % box, 160 pts | 98 % | power 0.96, PM 0.74–0.83, GBW 0.48 | gain, PSR, CMRR, offset, tempco, settling | 3.71 → 1.78 → **0.42** in 24 verifications; "predicted 0" was 5.6 twice |

Three readings. The quantities that are smooth in the sizes (power,
phase margin, GBW near an operating point) a model learns from ~150
points; the ones the search actually fights over — offset and tempco
(differences of nearly-equal terms), settling (a threshold-crossing
time), CMRR/PSRR (cancellations) — it does not, in either regime, with
either model. A surrogate of the *cost* is therefore a surrogate of
the easy half. Second, the whole-box model is a fantasy generator in
33 dimensions: its optimum predicts 0.02 and measures 21, and on the
LDO, where 63 % of the box fails to simulate, the model has no notion
of failure and walks the search into the dead region. Third, the
local, refitted loop does work — 3.71 to 0.42 in 24 verifications —
which is the Bayesian-optimisation regime, not "fit once, search for
free": every round is a refit (40–60 s on 4 cores at ~180 points,
O(n³)) plus SPICE. The honest comparison is against CMA-ES at the
same evaluation count, which was not recorded; the sweep's CMA-ES
reaches 0 on this circuit within 600.

The cheapest real test is already installed: pycma ships lq-CMA-ES
(`cma.fmin_lq_surr`, `cma.fitness_models.SurrogatePopulation`), a
local quadratic surrogate of the *ranking* inside CMA-ES, built for
exactly this regime and with no new dependency for the frozen build.
One more `algo` in `optimize()` behind the existing seam, measured on
the eight-circuit protocol, decides whether model assistance earns
its place; a Gaussian-process pipeline should wait for that number.

### lq-CMA-ES: fewer evaluations to the same place, twice the wall clock

The pilot `cmaes_surrogate` against `cmaes`, 2026-09-20, the
eight-circuit protocol at 600 evaluations, seed 0, four workers,
scratchpad `plan-s`. Costs at 100/200/300/600 evaluations, wall time,
and for the surrogate the generations it got out of 600 and the share
of each population it evaluated in SPICE.

| circuit | algo | @100 | @200 | @300 | @600 | wall | gens / evaluated |
|---|---|---|---|---|---|---|---|
| amp_leung_nmcf | lq-CMA-ES | 1.627 | 1.272 | 1.272 | **0.851** | 21.0 min | 80 / 58 % |
| | CMA-ES | 2.253 | 1.711 | 1.539 | 1.285 | 10.9 min | 46 / 100 % |
| amp_peng_tcfc | lq-CMA-ES | 6.203 | 0.604 | 0 | 0 | 29.1 min | 73 / 63 % |
| | CMA-ES | 0.424 | 0 | 0 | 0 | 14.9 min | |
| amp_ramos_pfc | lq-CMA-ES | 1.760 | 1.760 | 1.741 | 1.291 | 22.4 min | 78 / 59 % |
| | CMA-ES | 0.578 | 0.578 | 0.578 | **0.578** | 11.2 min | |
| amp_fan_smc | lq-CMA-ES | 1.196 | 0.851 | 0 | 0 | 21.7 min | 80 / 58 % |
| | CMA-ES | 1.034 | 0.706 | 0 | 0 | 11.5 min | |
| studio_cm_ota | lq-CMA-ES | 0.222 | 0 | 0 | 0 | 8.2 min | 73 / 68 % |
| | CMA-ES | 0 | 0 | 0 | 0 | 3.9 min | |
| ldo_basic | lq-CMA-ES | 1.145 | 0.796 | 0.517 | **0, all 8 met** | 21.6 min | 78 / 64 % |
| | CMA-ES | 1.929 | 1.060 | 1.060 | 1.048 | 10.0 min | |
| skill_ota5t | both | 0 | 0 | 0 | 0 | 0.2 / 0.1 min | 24 / 89 % |
| skill_opamp2 | both | 0 | 0 | 0 | 0 | 0.3 / 0.3 min | 28 / 60 % |

Per evaluation the surrogate is a modest win: two circuits clearly
better (nmcf 0.85 against 1.28; ldo_basic to all targets met where
CMA-ES stalled at a GBW gap), one clearly worse (ramos 1.29 against
0.58 — CMA-ES found its 0.58 inside the first hundred and never moved,
the surrogate never found it), five ties at zero with the surrogate
reaching zero later on two of them (peng_tcfc at 100: 6.2 against
0.42). The mechanism works as advertised: 58–68 % of each population
evaluated, 73–80 generations from 600 evaluations against 46. One
seed per circuit; a 2–1 on six decided rows is not a ranking.

Per minute it is a loss, and structurally so: the model ranks the
population, then evaluates 1, 2, 3, 5 … points at a time and checks
Kendall's tau after each step, so with four workers three sit idle
most of the time — every parallel row took twice the wall clock, and
the two serial skill circuits, where nothing is idle, took the same.
This project's constraint is the wall clock, not an evaluation quota;
"fewer evaluations" is a benefit only where each evaluation is dearer
than the workers it leaves idle. The fix, if the pilot goes further,
is to fill each surrogate step to at least `workers` points (the
threshold check then runs on batches of 4, 6, 9 … instead of 1, 2, 3)
and measure again — until then it stays in the menu as a pilot and
the default stays CMA-ES.

Same lesson as the finish and the seed portfolio: an evaluation-count
win has to be re-read as a minute count before it means anything here.

### A ceiling is a guess about a cost; measure the cost instead

The 90° phase-margin ceiling was put in because a 156° design met
every AC target and was plainly wrong (dominant pole below 0.1 Hz,
gain 144 dB). The ceiling caught it and nothing else — and the only
argument for 90 rather than 100 or 120 was that 156 was on one side of
it. What the design actually costs showed up the first time anyone
stepped it: a unity-gain follower with a 100 mV step never settles
(29 µs window, still 23 mV short), where 78–88° designs settle to 1%
inside a microsecond and a 40° one rings with 31% overshoot and takes
1.4 µs. One transient, +0.1 s per evaluation, and the guess became a
number with both failure modes on its scale. The general form: when a
constraint exists to exclude one bad design, ask what that design
would cost a user, and measure that.

### A failed simulation that looks like the last successful one

The LDO's CMA-ES trajectory would not reproduce between runs while the
amplifiers' reproduced to the digit, and two unrelated LDO sizings —
different widths, lengths, multipliers — reported *byte-identical*
metrics: GBW 1572541 Hz, phase margin 90.0258°, seven digits each.
Re-evaluated in a clean slot, one of them was a real point and the
other's ngspice run died ("Simulation interrupted due to error") and
produced nothing.

`evaluate()` deleted the previous log before every run, so a failed
amplifier run parsed an empty log and came back as missing metrics.
The LDO metrics come from wrdata files, which were not deleted; a
failed LDO run left them in place and the reader returned the slot's
previous point as this one. Under four parallel slots that is a
random earlier point, and a search keeps it if it happens to be good —
which is exactly how a phantom 0.3210 became the "best" of a run.

Fixed by clearing every output of the previous evaluation before a
run. The lesson is the general one: **a parser that reads whatever
file is there cannot tell "this run wrote it" from "the last one did"**.
Delete before you run, or write to a name the run owns. Every LDO
number in the tables above was measured with the old reader and is
suspect; the amplifier numbers are not.

**The LDO rows, re-measured on the fixed reader** (the tables above
keep their old numbers; these replace them):

| ldo_basic | old (suspect) | fixed |
|---|---|---|
| DE s0 / s1 | 0.6758 / 1.4603 | 0.6758 / 1.7482 |
| CMA-ES s0 / s1 | 0.8685 / 0.3611 | 0.8397 / **0.8043** |
| DE + Powell s0 / s1 | 1.2348 / 1.1242 | **0, all 8 met** / 1.4292 |
| constrained DE s0 / s1 | 1.3648 / 2.3512 | 0.9970 / 2.2430 |
| CMA-ES + finish s0 / s1 | 0.3210 / 0.3210 | 1.0477 / 0.7950 |
| DE @1200 s0 | 0.2408 | 0.6758 (converged by 300) |

Three things change. The phantoms were the good-looking numbers: the
0.32s, the 0.36, the 0.24 — a failed run inheriting a good point is a
search's dream and a report's lie. The Powell polish closes the LDO at
seed 0, which no search had honestly done, so its feasible count is
9 of 18, not 8. And the CMA-ES trajectories now reproduce between runs
to the digit at both seeds, which closes the discrepancy recorded
above: it was never the search, it was the reader.

The corrected tallies over 18 rows: feasible DE 6, CMA-ES 12, Powell 9,
constrained 7; CMA-ES best or tied 16 of 18, unchanged — its LDO rows
were never among its wins at seed 0 and stay its win at seed 1.

### The three-proposal finish on nine circuits

`cmaes_llm_finish` as shipped (three proposals a round, no stall rule),
nine circuits, two seeds, next to CMA-ES alone at the same budget; the
LDO rows from the fixed reader:

| circuit | CMA s0 | + finish s0 | CMA s1 | + finish s1 |
|---|---|---|---|---|
| amp_leung_nmcf | 0.2935 | **0.0792** | 1.0338 | **0.7672** |
| amp_ramos_pfc | 1.2801 | 1.2801 | 0.4471 | **0.2821** |
| ldo_basic | 0.8397 | 1.0477 | 0.8043 | **0.7950** |
| the other six | 0 | 0 | 0 | 0 |

Six rows CMA-ES leaves open; the finish improves four (73%, 26%, 37%,
2%), leaves one, and on one ends *worse* than plain CMA-ES at 600 —
`ldo_basic` seed 0, where CMA-ES improved from 1.08 to 0.84 in its
last 90 evaluations and the finish, given those 90 instead, got to
1.05. The reserve is taken from the search whether or not the search
has converged, and here it had not. No row closed. Twelve rows were
already feasible and cost the finish nothing. Feasible count 12 of 18,
same as CMA-ES alone; sum of costs over the 18 rows 4.25 against
CMA-ES's 4.70, LDO rows from the fixed reader in both.

What this says about the default: `cmaes_llm_finish` is the right
default for a user with a model configured — four of six open rows
improve, none closes, and the one loss is a reserve taken too early.
An adaptive reserve — hand the finish the budget only once CMA-ES has
stalled, keep searching otherwise — would have kept the LDO row and is
the obvious next change; ROADMAP has it.

### SciPy batches a constraint only in vectorized mode

`differential_evolution(constraints=...)` documents that a constraint
function may take an `(N, S)` array, and the constraint wrapper does
pass one — but only when `vectorized=True`; otherwise
`_calculate_population_feasibilities` loops over members and calls it
with one point at a time.  The constrained search was written for the
batched case and ran the first circuit at 2.4 s per evaluation against
0.6 s for plain DE with four workers — a factor of four, invisible from
the result (identical cost) and visible only in the wall clock.
`vectorized` excludes `workers`, so the constrained form has to own its
objective in `(N, S)` shape too.  Time a new algorithm against the one
it wraps before reading its numbers.

### ngspice `show` is column-oriented, and the column is the only key

`show m : id,vgs,gm,...` prints devices **three to a block**, one row per
parameter:

```
     device m.xop5.xm14.msky130_f m.xop5.xm19.msky130_f m.xop5.xm13.msky130_f
         id           1.99231e-05           1.99231e-05           1.99231e-05
        vds              0.602269              0.094204              0.602269
```

Nothing in a value row says which device it belongs to. The position does.
Get the alignment wrong — by one column, or by mis-splitting the dotted
instance path — and every operating point is attributed to the wrong
transistor. That does not look like a bug: it looks like a plausible
amplifier with a surprising bias point, and it would go into a prompt as
fact.

Two related traps in the same output:

- The instance name is `m.xop5.xm14.msky130_f`; the netlist calls it
  `xm14`. The useful token is second from the end, not last.
- `show all` on a 30-device amplifier is **3.6 MB**. Ask for the parameters
  you need or the log is unusable — and the deck's own sweep output is
  large enough that the block has to be fenced with markers to be found at
  all.

What makes the data actionable is the last hop, which nothing in ngspice
provides: the netlist line that sizes the device carries the design
variable, `xm10 ... w='MOSFET_9_2_W_gm1_PMOS'`. Without that join an
operating point names something the model is not allowed to change.

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
