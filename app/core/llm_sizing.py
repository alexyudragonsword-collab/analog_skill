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
from app.core.sizing import SIZING, VarSpec

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


_SYSTEM = ('You are an expert analog IC designer sizing a circuit. '
           'You will iteratively propose device sizings; each proposal is '
           'measured with a real SPICE simulation and you get the cost '
           'back. Reason from circuit fundamentals (gm/ID, headroom, '
           'compensation, matching) and from the measured feedback. '
           'Always answer with STRICT JSON, no prose outside it.')


def _ask_candidates(k: int, names: list[str]) -> str:
    example = ', '.join('"%s": <number>' % n for n in names[:3])
    return (f'Propose {k} new candidate sizings as JSON: '
            f'{{"rationale": "<one sentence>", "candidates": '
            f'[{{{example}, ...}}, ...]}} — each candidate must contain '
            f'every variable ({len(names)} keys), values inside the given '
            f'ranges. Balance exploitation of the current best with '
            f'exploration.')


# ─────────────────────────────────────────────────────────────────────────────
# Closed-loop optimizer (called from sizing.optimize, algo='llm')
# ─────────────────────────────────────────────────────────────────────────────
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


def run_loop(circuit: str, variables: list[VarSpec], overrides,
             state: dict, run_batch, budget: int, workers: int,
             chat=None):
    """The 'llm' algorithm body.  state/run_batch come from
    sizing.optimize and enforce budget, cancellation and parallelism."""
    from scipy.stats import qmc
    if chat is None:
        if not llm_client.configured():
            raise llm_client.LLMError(
                'LLM not configured — set provider/model/API key in '
                'Settings before using the LLM-guided algorithm.')
        chat = llm_client.chat
    names = [v.name for v in variables]
    lo = np.array([v.lo for v in variables], float)
    hi = np.array([v.hi for v in variables], float)
    span = np.where(hi > lo, hi - lo, 1.0)
    x0n = (np.array([v.default for v in variables], float) - lo) / span
    sob = qmc.Sobol(len(names), scramble=True, seed=0)

    def fmt_point(xn):
        vals = np.clip(xn, 0, 1) * span + lo
        return '{' + ', '.join(f'{n}: {v:.4g}'
                               for n, v in zip(names, vals)) + '}'

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
                reply = chat(messages, system=_SYSTEM)
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
        costs = run_batch(points)
        feedback = [f'cand {i + 1}: {fmt_point(p)} -> cost '
                    + (f'{c:.4f}' if np.isfinite(c) else 'FAILED')
                    for i, (p, c) in enumerate(zip(points, costs))]
        if state['best'] is not None and state['best_x'] is not None:
            best_m = ', '.join(f'{key}={val:.4g}'
                               for key, val in state['best_m'].items())
            best_xn = (np.array([state['best_x'][n] for n in names])
                       - lo) / span
            feedback.append(f'best so far: cost {state["best"]:.4f} at '
                            f'{fmt_point(best_xn)}  metrics: {best_m}')
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
    reply = chat([{'role': 'user', 'content': prompt}], system=_SYSTEM)
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
