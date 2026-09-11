## What this changes

<!-- What the change does, and why it is worth doing. If it fixes something,
     describe the failure — the symptom is what the next reader searches for. -->

## How it was verified

<!-- What you actually ran, and what it said. "Tests pass" is weaker than
     "99 passed in 3:01"; a fix is worth more when you can say the new test
     fails against the old code. -->

```
python -m pytest app/tests/ -v     # paste the summary line
python -m ruff check .             # must be clean
```

## Checklist

- [ ] `python -m pytest app/tests/ -v` passes — run alone, never two suites at
      once (they share the ngspice scratch dir and the user-data store).
- [ ] `python -m ruff check .` is clean.
- [ ] `CHANGELOG.md` is updated **in the same commit** as the change it
      describes, if this is a user-visible change.
- [ ] No vendored tree was touched: `analoggym/`, `circuit-skills/`,
      `gmoverid/`, `ngspice/`, `transistor-models/`.
- [ ] No `TODO` comments — open work goes in `ROADMAP.md`.
- [ ] `ROADMAP.md` updated if this lands an item or settles a question.

<!-- Schematics are generated, not drawn: if you changed a sizing netlist,
     re-run `python tools/gen_sizing_schematics.py` and commit the result. -->
