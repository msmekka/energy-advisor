# Handoff — pick up here

Last updated 2026-10-13. Written so a fresh session can start work without
re-deriving context. **Deliberately an index, not a duplicate:** anything
already written down lives in `rules/README.md`, `etdc/rig/README.md`,
`rules/working-notes.md`, or `energy-aware-code-analysis-plan.md`. What's here
is the decisions and state that aren't recorded anywhere else.

## The one-line framing

**etdc = energy-time decoupling.** The project reevaluates what we deem
"efficient" code once energy, not elapsed time, is the cost being minimised.
Race-to-idle means fastest usually *is* lowest-energy, so the interesting
territory is where the two come apart. A rule that fires only where time and
energy move together is "a speed rule in a green hat" and isn't worth having.

**This is a detection project, not a remediation one.** Avoid "the fix" /
"the rewrite" framing. The vocabulary is `flag/` and `no-flag/` — shape
present, shape absent.

## Layout

```
rules/        tier 1 — tree-sitter queries, detect.py, findings.py
etdc/
  rig/        tier 3 — rapl.py, shelly_check.py, validate_*.py, pin_baseline.sh
plan/         this file, Outcomes.md, latest_summary.txt
preso/        RC talk assets
.venv/        tree-sitter + tree-sitter-python (rig code is stdlib-only)
```

Run tier 1 with `cd rules && ../.venv/bin/python detect.py [--out f.jsonl]`.
Expected counters: `eager_materialization=4, polling_loop=1, busy_wait=1,
untested_boundaries=1`. That's the regression test.

Branch `etdc-restructure` @ `30af0b8` is the last checkpoint. Not merged to
`main`.

## Settled decisions

| decision | why |
|---|---|
| Grain is a **site**. Per-file / per-function / per-check-in are `GROUP BY` over rows. | Not an architecture choice, so don't commit to one. Per-file is the current default because `detect.py` already walks files. |
| **Never sum coefficients.** | A coefficient is cost per *execution*; static analysis finds *sites*. Summing assumes each site runs once — wrong by orders of magnitude. A per-file joule total would be a count in a joule costume. |
| Plan for **per-check-in** (changed lines only) as the eventual default view. | Every static-analysis tool developers tolerate converged there. Pre-existing findings are what gets a tool muted. |
| Tier-1 fixtures and tier-3 benchmarks are **separate artifacts**, joined by `rule_id`. | Fixtures must *parse* and stay minimally judgeable; benchmarks must *run* deterministically with tunable N. One file serving both corrupts both. |
| The tier-1↔tier-3 join key is **`rule_id`**, not the fingerprint. | Tier 3 yields a coefficient per rule. Fingerprints only matter later, for measuring a *specific* harvested site across commits. |
| `etdc` is the namespace; `__init__.py` files stay **empty of imports**. | A benchmark child imports `etdc.rig.rapl` inside a measured window; convenience imports would drag siblings in. |
| No `pip install` on the rig — `python3 -m etdc.rig.rapl` from the repo root. | Rig work runs as root (`energy_uj` perms, `sudo pin_baseline.sh`) and `sudo` won't see a user venv. Keeps the stdlib-only property. |

## Rig design (agreed, not yet built)

The rig is an instrument for **validating rules**, not improving programs. The
second arm is a *control* that isolates the shape, not a recommended remedy.
Output is the decoupling quotient — a quality score for the detector:

```
energy_ratio = E_flag / E_no-flag
time_ratio   = T_flag / T_no-flag
decoupling   = energy_ratio / time_ratio      # ~1.0 => speed rule in a green hat
```

- **4 pairs for eager-materialization, not 60.** Only split on inferences with
  a mechanism argument: `short_circuits` (any/all lose the early exit *as well
  as* the allocation) and `materialised` list-vs-set (different allocator path
  + hashing). Check `spelling` once, then collapse it — the two spellings
  likely compile to near-identical work.
- **`trip_count` is the x-axis, not a category.** Sweep N over 4–5 values per
  pair. The decoupling hypothesis is about memory traffic, which scales with N,
  so one N gives one point and no idea whether the ratio grows or flattens.
  Once `ratio(N)` exists, `impact_confidence` upgrades from a bucket to an
  interpolation.
- **Freeze N per pair, same N for both arms.** Different N per arm makes the
  ratio meaningless.
- **Interleave arms** (flag, no-flag, flag, no-flag…), never 30 of one then 30
  of the other. Highest-value, lowest-cost methodological choice here: thermal
  drift aliases directly onto the arm difference if the arms are blocked in
  time. Compute a ratio *per adjacent pair* and report that distribution.
- **The child measures itself.** Subprocess per run (fresh interpreter,
  `taskset` to the pinned core), but the child reads RAPL around its own hot
  loop. Bracketing the whole `exec` puts ~20–30 ms of interpreter startup
  inside the window.
- **One JSONL row per run, never an aggregate.** Raw per-domain deltas, rig
  provenance on *every* row (host, CPU, kernel, governor, turbo, SMT, Python
  version). You can re-derive a mean from rows; you can't recover rows from a
  mean, and rig time is the scarcest input.
- Benchmarks live at `benchmarks/<rule-name>/{flag,no-flag}/`, outside the
  package, run by path and never imported.

## Next action: `start`/`stop` in `etdc/rig/rapl.py`

`sample(seconds)` is `read → time.sleep(seconds) → read`, so it can only
sample a window, never bracket a workload. That's the blocker for everything
above. **The user is writing this; the next session reviews it.** There are
uncommitted edits to `rapl.py` already in the checkpoint.

Pointers given (all verified or reasoned, in priority order):

1. **Same order of clock-vs-counter reads in both calls.** Reading ~5 sysfs
   files takes real time; if `start` and `stop` differ in order the overhead
   lands inside one window and outside the other, biasing avg power one way.
   Same order both ends and it cancels in the subtraction.
2. **Discover domains once, outside the window.** `sample()` lazily defaults
   `domains=None`; the new pair must take the dict, or a benchmark loop
   re-walks sysfs inside every measured region.
3. **Reimplement `sample()` on top of the pair** — it's the only regression
   test, and it's why `start`/`stop` belong *in* `rapl.py` rather than a new
   module (a separate module would need `rapl` to import it back). The
   benchmark child also needs the primitive, not the orchestrator.
4. **Return raw per-domain deltas; compute no total.** Σpackage + dram with
   `psys` excluded is an aggregator decision, revisable only if the reader
   keeps everything.
5. **Sort domains at discovery** (by sysfs path, which keeps the subzone
   hierarchy visible). Order is already stable *within* a pair if the same
   dict is passed; sorting buys reproducibility *across* invocations, since
   `os.walk` order isn't guaranteed.
6. **Let read errors propagate; the runner records a failed row.** Never
   substitute zero — a zero is indistinguishable from an idle window.
7. **Check the `energy_uj` permission bits on the rig.** Commonly 0400
   root-only (PLATYPUS / CVE-2020-8694). Decide: children as root, or
   `pin_baseline.sh` relaxes and `--restore` puts it back. This shapes the
   subprocess model.
8. **Test it on the Mac via a fake sysfs tree.** `RAPL_ROOT` is a module
   constant and `read_uj` takes a path, so `discover_domains(root=…)` pointed
   at a temp dir with `name`/`energy_uj`/`max_energy_range_uj` files exercises
   the arithmetic, the wraparound branch, and the symmetry without the rig.

**Wraparound is a non-issue — settled, don't re-litigate.**
`max_energy_range_uj = 262143328850` µJ = **262,143 J** (not 262 J; the digits
`262143` mislead). Cross-check: ÷ (2^32 − 1) ≈ 61.03 µJ, exactly the standard
client energy unit. Wrap period is ~4.9 h at 15 W, ~6 days at idle. So: read
at both ends, **no polling**, and **keep the existing single-wrap
correction** — a window still has a ~1-in-3 chance of straddling a wrap
somewhere across a full ~1200-run campaign, and a double wrap is impossible at
these rates.

## Deferred, in rough priority order

- `rules/` → `etdc/rules/`. Needs `from findings import …` /
  `from astanalyzers import …` converted to package-relative imports — a code
  change, not a rename.
- `etdc/rig/measurements/` → `runs/` (changes script defaults).
- `.DS_Store` is tracked in `rules/` and `rules/busy-wait/`. Needs a
  `.gitignore` entry plus `git rm --cached`.
- `rules/working-notes.md` wasn't audited for stale paths after the
  restructure. `rules/README.md` line ~295 was spot-fixed to `.venv`.
- SARIF export, as a converter at the edge (`findings → sarif`), with the flat
  JSONL staying primary. Gotchas already written up in `rules/README.md`:
  1-based lines *and* character columns, exclusive `endColumn`,
  `partialFingerprints` keyed on the snippet rather than the line.
- A `flag/inside-loop/` fixture. Every current eager-materialization fixture is
  a module-level one-liner, so `enclosing_function`/`enclosing_loop_depth` are
  `None`/`0` across the whole corpus and aren't regression-guarded. They were
  verified by a 13-case table instead.
- `removal_preserves_semantics` is reasoning about Python semantics, not a
  tested claim. Worth a unit test if anything leans on it.

## Working agreements

- **Don't write code until it's explicitly agreed.** An offer engaged with
  approvingly is not a go-ahead. Discussing a design, or confirming a
  constraint on it, is still discussion.
- **Be conservative with token/compute spend.** One targeted verification over
  an exhaustive table; no unprompted full regressions or doc updates bundled
  into a turn that didn't ask for them. This is a stated value, not just a
  budget — fitting for a project about energy-aware tooling.
- Explain mechanics before producing files; this is a learning project.
