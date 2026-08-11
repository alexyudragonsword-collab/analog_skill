"""Sizing optimizer over the vendored AnalogGym benchmark circuits.

Each registered circuit is an AnalogGym SKY130 topology (subckt netlist +
.PARAM design-variable file + characterization testbench).  ``evaluate()``
renders the testbench with workspace paths, runs ngspice in batch mode and
extracts the metrics; ``score()`` folds them into a single cost against the
circuit's target specs (lower is better, 0 = every target met);
``optimize()`` minimizes that cost with a bounded, budget-limited Powell
search from the shipped default sizing.

Runs entirely offline — no dependency beyond scipy (already shipped).
The FoM shown in the GUI is ``-cost`` (higher is better).

This module is the package's public face: callers keep writing
``from app.core import sizing`` and ``sizing.evaluate(...)``.  The
implementation is split by responsibility, each layer importing only the
ones above it:

    spec           plain dataclasses + number parsing (stdlib only)
    registry       which circuits exist and what they are judged against
    assets         where a circuit's design files live; variable parsing
    scoring        metrics -> single cost
    evaluation     render testbench -> run ngspice -> metrics / waves
    user_circuits  import the user's own designs into the registry
    report         the completed-run record and its report text
    optimizer      evaluate/score loop under a budget (4 algorithms)
    runs           save / load completed runs in the user-data store
    plots          matplotlib rendering (GUI thread only)

(that listing is a topological order of the package's imports — verified
acyclic; nothing here imports a module below it)

Note for tests: the names below are *re-exports*.  Rebinding one of them
here (``monkeypatch.setattr(sizing, 'evaluate', ...)``) does not affect the
submodule that calls it, which resolved the name in its own globals at
import.  Patch the call site's module instead —
``monkeypatch.setattr(sizing.optimizer, 'evaluate', ...)``.
"""

# ruff: noqa: F401  (this module exists to re-export)

from app.core.sizing.assets import (
    _pkg_root, parse_param_file, parse_variables, schematic_path,
    user_circuits_dir,
)
from app.core.sizing.evaluation import (
    _run_dir, capture_waves, evaluate, netlist_texts,
)
from app.core.sizing.optimizer import optimize, optuna_available
from app.core.sizing.plots import (
    render_comparison, render_convergence, render_wave_comparison,
)
from app.core.sizing.registry import SIZING
from app.core.sizing.report import SizingRun, change_summary
from app.core.sizing.runs import (
    RUN_SCHEMA, list_runs, load_run, run_info, runs_dir, save_run,
)
from app.core.sizing.scoring import score
from app.core.sizing.spec import MetricSpec, SizingSpec, VarSpec
from app.core.sizing.user_circuits import (
    import_user_circuit, load_user_circuits, remove_user_circuit,
)
