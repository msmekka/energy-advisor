# energy_advisor

A static-analysis tool that flags energy-relevant code patterns — the ones
that decouple from wall-clock time, so a profiler wouldn't already catch
them (polling loops, busy-waits, eager materialization, over-parallelised
I/O-bound work). CLI-first, aimed at both a human in an editor and a
code-generating agent.

Full design, rationale, and phase plan:
[`energy-aware-code-analysis-plan.md`](energy-aware-code-analysis-plan.md) —
read that before this file for anything beyond "where's the code."

Short version of the architecture it lays out: three tiers, never blended
silently. Tier 1 (tree-sitter static detection) finds pattern *shape*
continuously and everywhere. Tier 2 (Cachegrind — not built yet) confirms
with deterministic counts. Tier 3 (RAPL / wall-meter, offline, on one
specific rig) calibrates ratio coefficients that tier 1's findings can
eventually cite. The tool reports ratios ("pattern B costs 4.2× pattern A on
rig X"), not absolute joules.

## Status

Track A (efficiency/energy) is the active work; Track B (bias) is scoped in
the plan but deferred. Per the plan's phase list:

- **Phase 0** (AST tooling) — done.
- **Phase 2** (measurement rig) — the pinning, RAPL reader and Shelly
  cross-validation are done, and the measurement path on top of them now
  exists: a `start`/`stop` pair that brackets a workload, a harness that
  measures one fixture per process, and a flag/no-flag benchmark corpus.
  **No campaign has run on real hardware yet**; the campaign runner and its
  manifest are the next build.
- **Phase 1** (the CLI analyzer, with JSON Lines/SARIF output) — not started.
  `rules/` is rule prototyping and a fixture corpus, not yet wired into an
  `analyze <path>` command.
- **Phase 3** (coefficients) — designed, not built. Post-processing turns rows
  into a decoupling quotient per rule; storage and report format are settled.

## Layout

```
energy-aware-code-analysis-plan.md   # the design doc — start here
rules/        # Tier 1: tree-sitter queries + AST visitors, one directory
              # per rule, run against a fixture corpus. See rules/README.md.
              # Moves under etdc/ once its flat imports are packaged.
etdc/         # "energy-time decoupling" -- the project namespace
  rig/        # Tier 3: calibration harness for the dedicated Linux RAPL rig
              # (rc-mw01) plus Shelly-plug wall-power cross-validation.
              # Start at etdc/rig/README.md -- it is the operator runbook.
              # Most of it only runs on that rig, not on a dev machine.
benchmarks/   # Tier 3 fixtures: flag/ and no-flag/ pairs that RUN, as opposed
              # to the tier-1 corpus in rules/, which only has to PARSE. A
              # tier-1 "no-flag" means "the rule must not fire here"; a tier-3
              # no-flag arm is a measurement control. They are different
              # artifacts, joined by rule_id. See benchmarks/TEMPLATE.py.
.venv/        # local venv (tree-sitter + tree-sitter-python); the rig code
              # is deliberately stdlib-only and needs none of it.
plan/
  Outcomes.md # raw working notes on turning joules into CO2e (see the
              # plan's "Open: joules → CO2e" section) — notes, not a
              # finished writeup
green-ide-extension-review-and-plan.md
              # the original "IDE extension for efficiency & bias feedback"
              # outline that energy-aware-code-analysis-plan.md supersedes.
              # Kept for the record of what changed and why.
helloworldmw/ # default VS Code extension scaffold from before the pivot to
              # CLI-first. Not wired to anything above; the actual AST
              # explorer this project produced now lives in its own repo.
energyadv-ext1.py
              # empty — dead stub from the same pre-pivot period.
```

## Getting started

There's no top-level entry point yet (that's Phase 1). To run what exists:

- `rules/` — `python3 detect.py` runs the tier-1 fixture corpus.
  See [`rules/README.md`](rules/README.md) for the rule
  layout and the contract for adding a new one.
- `etdc/rig/` — the calibration scripts (`rapl.py`, `harness.py`, `sync.sh`,
  `pin_baseline.sh`, `shelly_check.py`, `validate_shelly.py`). Most of these
  need the physical rig (RAPL sysfs access, the Shelly plug on the same
  network). [`etdc/rig/README.md`](etdc/rig/README.md) is the runbook: how to
  pin the rig, run a measurement, and put the machine back.
- `benchmarks/` — each fixture runs standalone, no rig required, which is the
  quickest way to see what a pair actually measures:
  `python3 benchmarks/eager-materialization/flag/sum_list.py 200000`
