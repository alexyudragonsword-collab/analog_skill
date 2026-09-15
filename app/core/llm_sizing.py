"""LLM-assisted sizing: closed-loop optimizer, run explanation, and
pre-run setup advice.

The optimizer is the fourth ``sizing.optimize`` algorithm ('llm'): the
model proposes candidate sizings in physical units, every candidate is
evaluated by ngspice through the same run_batch/budget/cancel machinery
as the other algorithms, and the measured costs are fed back for the next
round.  A malformed reply falls back to Sobol points for that round, so
the loop can never do worse than random search and never stalls on the
LLM.  All prompts speak physical units — never the normalized [0,1] box.
"""

import numpy as np

from app import paths
from app.core import llm_client
from app.core.mcp_eval_server import TOOL_NAME as MCP_TOOL
from app.core.sizing import SIZING, VarSpec, score_detail

#: cap on netlist text sent to the model (keeps prompts ~2k tokens)
NETLIST_CHARS = 6000
#: rounds of (assistant, user) feedback kept in the rolling history
HISTORY_ROUNDS = 6


# ─────────────────────────────────────────────────────────────────────────────
# Prompt building
# ─────────────────────────────────────────────────────────────────────────────
def _metric_lines(spec, overrides) -> list[str]:
    ov = overrides or {}
    out = []
    for ms in spec.metrics:
        target, hard = ov.get(ms.key, (ms.target, ms.hard))
        out.append(f'  - {ms.key} ({ms.label}, {ms.unit}): '
                   f'{ms.direction} {target:g}'
                   + ('  [HARD constraint, 10x weight]' if hard else ''))
    return out


def _variable_lines(variables: list[VarSpec]) -> list[str]:
    return [f'  - {v.name}: default {v.default:g}, '
            f'range [{v.lo:g}, {v.hi:g}]'
            + ('  (integer)' if v.is_int else '')
            for v in variables]


def describe_circuit(circuit: str, variables: list[VarSpec],
                     overrides: dict | None = None) -> str:
    """Physical context for the model: title, netlist (AnalogGym) or
    parameter semantics (circuit-skills), variables, metric targets."""
    spec = SIZING[circuit]
    lines = [f'Circuit: {spec.title}', '']
    if spec.kind == 'skill':
        lines += ['This is a PTM-process circuit driven through named '
                  'module parameters (W.x entries are device widths in um; '
                  'V* are bias voltages; FCLK is a clock frequency).', '']
    else:
        netlist = (paths.analoggym_dir() / spec.kind / 'netlist'
                   / spec.netlist)
        try:
            text = netlist.read_text(errors='replace')[:NETLIST_CHARS]
            lines += ['SPICE netlist (SKY130; design variables appear as '
                      '{braced} parameters):', '```', text, '```', '']
        except OSError:
            pass
    lines += ['Design variables (propose values INSIDE these ranges):']
    lines += _variable_lines(variables)
    lines += ['', 'Metric targets (cost = weighted violation, 0 when all '
              'targets met; LOWER cost is better):']
    lines += _metric_lines(spec, overrides)
    lines += ['', f'One evaluation runs a real ngspice testbench '
              f'(~{spec.eval_seconds:g} s).']
    return '\n'.join(lines)


#: How hard the model should think per round of the search loop.
#:
#: This runs ~38 times for a 150-evaluation budget and asks for something
#: modest each time: a few plausible points near the current best.  At the
#: provider default that is 101 s a round — an hour of model time for a run
#: whose simulations take two minutes.  At 'low' it is 25 s, with the same
#: four complete candidates coming back.
#:
#: suggest_setup and explain_run deliberately leave this unset: each is
#: called once, the user reads the result, and it is worth the wait.
LOOP_EFFORT = 'low'

_SYSTEM = ('You are an expert analog IC designer sizing a circuit. '
           'You will iteratively propose device sizings; each proposal is '
           'measured with a real SPICE simulation and you get the cost '
           'back. Reason from circuit fundamentals (gm/ID, headroom, '
           'compensation, matching) and from the measured feedback. '
           'Always answer with STRICT JSON, no prose outside it.')


def _ask_candidates(k: int, names: list[str]) -> str:
    example = ', '.join(f'"{n}": <number>' for n in names[:3])
    return (f'Propose {k} new candidate sizings as JSON: '
            f'{{"rationale": "<one sentence>", "candidates": '
            f'[{{{example}, ...}}, ...]}} — each candidate must contain '
            f'every variable ({len(names)} keys), values inside the given '
            f'ranges. Balance exploitation of the current best with '
            f'exploration.')


# ─────────────────────────────────────────────────────────────────────────────
# Closed-loop optimizer (called from sizing.optimize, algo='llm')
# ─────────────────────────────────────────────────────────────────────────────
def candidates_schema(names, lo, hi, k: int) -> dict:
    """JSON Schema for one round's reply, built from this circuit's own
    variables.

    The point is `required`: a candidate has to carry every variable name,
    and the median circuit has 24 of them (``ldo_2`` has 56, up to 26
    characters each).  Asking a model to restate that list verbatim, four
    times a round, for the ~37 rounds a 150-evaluation budget takes, is a
    bet it loses eventually — and _parse_candidates drops an incomplete
    candidate *silently*.  A schema makes the shape unforgeable instead of
    hoped for.

    The bounds go in too, so the model stops spending proposals outside
    the box only to have them clipped onto an edge.
    """
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['rationale', 'candidates'],
        'properties': {
            'rationale': {'type': 'string'},
            'candidates': {
                'type': 'array', 'minItems': 1, 'maxItems': k,
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': list(names),
                    'properties': {
                        n: {'type': 'number', 'minimum': float(a),
                            'maximum': float(b)}
                        for n, a, b in zip(names, lo, hi, strict=True)},
                },
            },
        },
    }


def setup_schema(names) -> dict:
    """JSON Schema for suggest_setup's reply.

    Unlike a candidate this one is deliberately partial — the prompt asks
    for "only variables worth changing" — so there is no `required` list of
    names.  What the schema buys here is `additionalProperties: False` on
    the variables map: a suggestion for a name that is not in this circuit
    is dropped silently today, and now cannot be produced.
    """
    entry = {
        'type': 'object', 'additionalProperties': False,
        'required': ['init', 'lo', 'hi'],
        'properties': {k: {'type': 'number'} for k in ('init', 'lo', 'hi')},
    }
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['rationale', 'variables'],
        'properties': {
            'rationale': {'type': 'string'},
            'budget': {'type': 'integer'},
            'variables': {
                'type': 'object', 'additionalProperties': False,
                'properties': {n: entry for n in names},
            },
        },
    }


def _parse_candidates(reply: str, names, lo, hi, k: int) -> list[np.ndarray]:
    """LLM reply → ≤ k normalized points (clipped into the box)."""
    doc = llm_client.extract_json(reply)
    if isinstance(doc, dict):
        cands = doc.get('candidates', [])
    else:                                       # bare JSON array
        cands = doc
    span = np.where(hi > lo, hi - lo, 1.0)
    out = []
    for cand in cands[:k]:
        if not isinstance(cand, dict):
            continue
        try:
            x = np.array([float(cand[n]) for n in names])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(np.clip((np.clip(x, lo, hi) - lo) / span, 0.0, 1.0))
    if not out:
        raise llm_client.LLMError('reply contained no usable candidate')
    return out


def metric_feedback(circuit: str, metrics: dict | None,
                    overrides=None, limit: int = 5) -> str:
    """One line saying which targets a candidate missed, and by how much.

    Without this the model is told a single scalar — "cost 0.83" — and has
    to guess whether it is short on gain, long on power, or off on phase
    margin.  An analog designer given "DC gain 62 dB, want 100" moves
    deliberately; given 0.83 they can only wander.

    The worst `limit` contributors are named, because the whole point is
    where to push next, and the metrics that are already met say only that
    there is slack there.  That slack matters too, so the count of met
    targets is reported rather than each one.
    """
    if not metrics:
        return 'simulation produced no metrics'
    detail = score_detail(circuit, metrics, overrides)
    missed = sorted((d for d in detail if not d.met),
                    key=lambda d: -d.contribution)
    met = len(detail) - len(missed)
    if not missed:
        return f'all {met} targets met'
    parts = []
    for d in missed[:limit]:
        ms = d.spec
        if d.value is None:
            parts.append(f'{ms.label} MISSING')
            continue
        want = {'max': '>=', 'min': '<=', 'absmin': '|x| <=',
                'target': '='}[ms.direction]
        parts.append(f'{ms.label} {d.value:.4g} {ms.unit} '
                     f'(want {want} {d.target:.4g}, off {d.violation:.0%})')
    more = f' +{len(missed) - limit} more' if len(missed) > limit else ''
    return f'{met}/{len(detail)} met; ' + '; '.join(parts) + more


#: Whether each round's feedback carries the best sizing's operating point.
#:
#: Measured 2026-09-15, one-shot proposals, n=3 vs 4 with zero overlap: shown
#: the operating point, the model moves the variables that size the offending
#: devices **10-12x** more than the rest, where without it the same ratio is
#: ~1 (0.71-1.46) — it is not targeting at all.  It also moves less overall
#: (0.035-0.048 against 0.071-0.152), so it is both more selective and more
#: conservative.  Both p=0.029.
#:
#: What that does *not* show is a better outcome: those same proposals left
#: exactly as many devices out of saturation as before.  Aiming correctly and
#: failing is what a one-shot task looks like, and a loop is the thing that
#: fixes one-shot failures — which is the argument for putting it here, and
#: the whole argument.  It is not evidence that the search converges better.
LOOP_OPERATING_POINTS = True


def _operating_point_note(circuit: str, values: dict | None) -> str:
    """The best sizing's operating point, or '' if it cannot be had.

    Costs one extra ngspice run, and deliberately **not** charged to the
    evaluation budget: the budget bounds the search, and this is an
    observation of a point the search already paid for.  Captured only when
    the best improves, so a plateaued run stops paying for it.

    Never raises — a failed capture must cost the round its extra context,
    not the round itself.
    """
    if not values:
        return ''
    try:
        from app.core.sizing.evaluation import operating_points
        return operating_points(circuit, values)
    except Exception as exc:                          # noqa: BLE001
        print(f'operating point capture skipped: {exc}')
        return ''


def run_loop(circuit: str, variables: list[VarSpec], overrides,
             state: dict, run_batch, budget: int, workers: int,
             chat=None):
    """The 'llm' algorithm body.  state/run_batch come from
    sizing.optimize and enforce budget, cancellation and parallelism."""
    from scipy.stats import qmc
    if chat is None:
        if not llm_client.configured():
            raise llm_client.not_configured_error()
        chat = llm_client.chat
    names = [v.name for v in variables]
    lo = np.array([v.lo for v in variables], float)
    hi = np.array([v.hi for v in variables], float)
    span = np.where(hi > lo, hi - lo, 1.0)
    x0n = (np.array([v.default for v in variables], float) - lo) / span
    sob = qmc.Sobol(len(names), scramble=True, seed=0)

    def fmt_point(xn):
        vals = np.clip(xn, 0, 1) * span + lo
        inner = ', '.join(f'{n}: {v:.4g}'
                          for n, v in zip(names, vals, strict=True))
        return '{' + inner + '}'

    best_seen = float('inf')                    # gates the op capture below
    run_batch([x0n])                            # evaluation #1: defaults
    messages = [
        {'role': 'user',
         'content': describe_circuit(circuit, variables, overrides)
         + f'\n\nThe default sizing {fmt_point(x0n)} measured '
           f'cost {state["best"] if state["best"] is not None else "inf"}. '
           + _ask_candidates(min(workers, 4), names)},
    ]

    while not state['cancel'] and state['dispatched'] < budget:
        k = max(1, min(workers, budget - state['dispatched'], 4))
        points, note = None, ''
        for _ in range(2):                      # one retry on a bad reply
            try:
                reply = chat(messages, system=_SYSTEM,
                             schema=candidates_schema(names, lo, hi, k),
                             effort=LOOP_EFFORT)
                points = _parse_candidates(reply, names, lo, hi, k)
                messages.append({'role': 'assistant', 'content': reply})
                break
            except llm_client.LLMError as exc:
                note = f'(previous reply unusable: {exc}) '
                print(f'llm sizing: {exc} — retrying')
        if points is None:                      # fall back to Sobol points
            print('llm sizing: falling back to Sobol samples this round')
            pts = sob.random(k)
            points = [np.clip(x0n + (p - 0.5) * 0.5, 0.0, 1.0) for p in pts]
            messages.append({'role': 'assistant',
                             'content': '(unusable reply)'})
        costs, mets = run_batch(points, with_metrics=True)
        feedback = [
            f'cand {i + 1}: {fmt_point(p)} -> cost '
            + (f'{c:.4f}' if np.isfinite(c) else 'FAILED')
            + f'  [{metric_feedback(circuit, m, overrides)}]'
            for i, (p, c, m) in enumerate(zip(points, costs, mets,
                                              strict=True))]
        if state['best'] is not None and state['best_x'] is not None:
            best_m = ', '.join(f'{key}={val:.4g}'
                               for key, val in state['best_m'].items())
            best_xn = (np.array([state['best_x'][n] for n in names])
                       - lo) / span
            feedback.append(f'best so far: cost {state["best"]:.4f} at '
                            f'{fmt_point(best_xn)}  metrics: {best_m}')
            if LOOP_OPERATING_POINTS and state['best'] < best_seen:
                best_seen = state['best']
                op = _operating_point_note(circuit, state['best_x'])
                if op:
                    feedback.append('operating point of that best sizing:\n'
                                    + op)
        remaining = budget - state['dispatched']
        if remaining <= 0 or state['cancel']:
            break
        messages.append({'role': 'user', 'content':
                         note + '\n'.join(feedback) + '\n\n'
                         + f'{remaining} evaluations left. '
                         + _ask_candidates(min(k, remaining), names)})
        # rolling window: keep the circuit description + recent rounds
        if len(messages) > 1 + 2 * HISTORY_ROUNDS:
            messages = messages[:1] + messages[-2 * HISTORY_ROUNDS:]


# ─────────────────────────────────────────────────────────────────────────────
# Run explanation & pre-run advice (one-shot calls, worker thread)
# ─────────────────────────────────────────────────────────────────────────────
def explain_run(run, variables: list[VarSpec] | None = None,
                chat=None) -> str:
    """Design critique of a finished run, in English."""
    chat = chat or llm_client.chat
    lines = [run.report()]
    if variables:
        lines += ['', 'Variable bounds:'] + _variable_lines(variables)
    prompt = ('Below is the result report of an automatic analog-circuit '
              'sizing run. Briefly analyse: 1) which metrics meet/miss '
              'their targets and where the bottleneck is; 2) from circuit '
              'fundamentals, which variables are most worth adjusting and '
              'in which direction; 3) whether any variable bounds or metric '
              'targets should be relaxed or tightened. Keep it under 150 '
              'words.\n\n' + '\n'.join(lines))
    return chat([{'role': 'user', 'content': prompt}],
                system='You are an expert analog IC designer. '
                       'Answer in English.').strip()


def suggest_setup(circuit: str, variables: list[VarSpec],
                  overrides=None, chat=None) -> tuple[dict, str]:
    """Pre-run advice: suggested bounds/init per variable + budget/algo.
    Returns (suggestions, rationale); suggestions are clipped sane."""
    chat = chat or llm_client.chat
    prompt = (describe_circuit(circuit, variables, overrides)
              + '\n\nBefore optimizing, suggest a good starting point and '
                'search ranges from circuit fundamentals.  Answer STRICT '
                'JSON only: {"rationale": "<=3 sentences (English)", '
                '"budget": <int>, '
                '"variables": {"<name>": {"init": x, "lo": x, "hi": x}, '
                '...}} — only include variables worth changing.')
    reply = chat([{'role': 'user', 'content': prompt}], system=_SYSTEM,
                 schema=setup_schema([v.name for v in variables]))
    doc = llm_client.extract_json(reply)
    if not isinstance(doc, dict):
        raise llm_client.LLMError('advice reply was not a JSON object')
    known = {v.name: v for v in variables}
    out = {}
    for name, sug in (doc.get('variables') or {}).items():
        if name not in known or not isinstance(sug, dict):
            continue
        v = known[name]
        try:
            lo = float(sug.get('lo', v.lo))
            hi = float(sug.get('hi', v.hi))
            init = float(sug.get('init', v.default))
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(lo) and np.isfinite(hi) and np.isfinite(init)):
            continue
        if hi <= lo:
            lo, hi = v.lo, v.hi
        lo, hi = max(lo, 0.0), hi
        init = min(max(init, lo), hi)
        out[name] = {'init': init, 'lo': lo, 'hi': hi}
    budget = doc.get('budget')
    if isinstance(budget, (int, float)) and 10 <= budget <= 5000:
        out['_budget'] = int(budget)
    rationale = str(doc.get('rationale', '')).strip()
    return out, rationale


# ─────────────────────────────────────────────────────────────────────────────
# Agentic loop (sizing.optimize, algo='llm_agent')
#
# The difference from run_loop is who holds the turn.  There, the app asks
# for k candidates, simulates them, and reports back — the model answers
# questions.  Here the app hands over one prompt and a tool, and the model
# decides what to try, how many at a time, and when what it just learned
# changes its mind.  One CLI invocation for the whole search rather than one
# per round.
#
# It is *not* claimed to search better.  The session that built it measured
# a 33% run-to-run spread on this problem, which is wider than any effect
# either version is likely to have, so that claim could not be supported
# either way.  What it changes is the shape of the control loop.
# ─────────────────────────────────────────────────────────────────────────────
#: Reasoning effort for the agentic loop — deliberately *not* LOOP_EFFORT.
#:
#: The measurement that justified 'low' for run_loop does not transfer.
#: There the model answers the same narrow question ~38 times ("four points
#: near the current best"), and the hour of model time was the whole
#: problem.  Here it takes a handful of turns, and each one reads every
#: result so far and decides what to do next — the thinking *is* the work,
#: and there are few enough turns that lowering it saves minutes rather
#: than an hour.  None means the provider's own default.
#:
#: Named rather than omitted so the next person sees a decision instead of
#: wondering whether it was forgotten.  It was, once.
AGENT_EFFORT = None

AGENT_SYSTEM = (
    'You are an expert analog IC designer sizing a circuit. You have a tool '
    'that simulates candidate sizings with ngspice and returns each one\'s '
    'cost (lower is better, 0 = every target met) and per-metric results. '
    'Work from circuit fundamentals — gm/ID, headroom, compensation, '
    'matching — and from what each simulation tells you. Simulate several '
    'candidates per call when exploring, since they run in parallel; '
    'simulate one when you are testing a specific idea. Keep going until '
    'the budget is spent. Finish with one short paragraph on what you '
    'found; do not restate the numbers.')


def agent_prompt(circuit: str, variables: list[VarSpec], overrides,
                 budget: int, workers: int) -> str:
    return (describe_circuit(circuit, variables, overrides)
            + f'\n\nYou have a budget of {budget} simulations, '
              f'{workers} of which run in parallel. Call '
              f'{MCP_TOOL} to try sizings. Start from the default sizing '
              f'above, then improve on it.')


def run_agent_loop(circuit: str, variables: list[VarSpec], overrides,
                   state: dict, run_batch, budget: int, workers: int,
                   run_agent=None):
    """The 'llm_agent' algorithm body.

    Stands up an EvalService over run_batch, points an MCP server at it,
    and lets one CLI invocation spend the budget through that tool.  The
    app still owns everything that matters: run_batch refuses work past the
    budget and after Cancel, so the worst a confused model can do is make
    calls that come back empty.
    """
    from app.core.eval_service import EvalService

    if run_agent is None:
        from app.core import llm_client
        if not llm_client.configured():
            raise llm_client.not_configured_error()
        cfg = llm_client.get_config()
        if cfg['provider'] != 'claude_code':
            raise llm_client.LLMError(
                'The agentic algorithm needs the Claude Code CLI provider — '
                'it drives a tool, which the HTTP providers are not wired '
                'for here. Switch provider in Settings, or use the '
                'LLM-guided algorithm instead.')
        run_agent = llm_client.run_agent

    names = [v.name for v in variables]
    lo = [float(v.lo) for v in variables]
    hi = [float(v.hi) for v in variables]

    def handler(points):
        # the model sends real values; run_batch works in the unit box
        import numpy as np
        a, b = np.array(lo), np.array(hi)
        span = np.where(b > a, b - a, 1.0)
        xs = [np.clip((np.clip(np.array(p, float), a, b) - a) / span, 0, 1)
              for p in points]
        return run_batch(xs, with_metrics=True)

    with EvalService(handler) as svc:
        return run_agent(
            prompt=agent_prompt(circuit, variables, overrides, budget,
                                workers),
            system=AGENT_SYSTEM,
            vars_spec={'names': names, 'lo': lo, 'hi': hi},
            addr=f'{svc.host}:{svc.port}', token=svc.token,
            effort=AGENT_EFFORT,
            # the whole search happens inside this one call
            timeout=max(600.0, budget * 25.0),
            should_stop=lambda: state['cancel'])
