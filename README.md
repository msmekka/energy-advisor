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
the plan but deferred. Per the plan's phase list: Phase 0 (AST tooling) and
most of Phase 2 (measurement rig + RAPL/Shelly cross-validation) are done;
Phase 1 (the actual CLI analyzer, with JSON Lines/SARIF output) hasn't
started — `astwork/rules/` is rule prototyping and a fixture corpus, not yet
wired into a `analyze <path>` command; Phase 3 (coefficients) and beyond are
further out.

## Layout

```
energy-aware-code-analysis-plan.md   # the design doc — start here
astwork/
  rules/      # Tier 1: tree-sitter queries + AST visitors, one directory
              # per rule, run against a fixture corpus. See astwork/rules/README.md.
  measure/    # Tier 3: calibration harness for the dedicated Linux RAPL rig
              # (rc-mw01) plus Shelly-plug wall-power cross-validation.
              # See astwork/measure/README.md. Most of it only runs on that
              # rig, not on a dev machine.
Outcomes.md   # raw working notes on turning joules into CO2e (see the
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

- `astwork/rules/` — `python3 detect.py` runs the tier-1 fixture corpus.
  See [`astwork/rules/README.md`](astwork/rules/README.md) for the rule
  layout and the contract for adding a new one.
- `astwork/measure/` — the calibration scripts (`rapl.py`,
  `shelly_check.py`, `validate_shelly.py`, `pin_baseline.sh`). Most of these
  need the physical rig (RAPL sysfs access, the Shelly plug on the same
  network); see
  [`astwork/measure/README.md`](astwork/measure/README.md).
