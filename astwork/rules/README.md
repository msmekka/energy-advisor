# rules/

Tier-1 static detection: tree-sitter queries (plus some remaining AST
visitors) that flag energy-smell shapes in Python source. See
[`working-notes.md`](working-notes.md) and the top-level
[energy-aware-code-analysis-plan.md](../../energy-aware-code-analysis-plan.md)
for the full design — this file just orients you in what's actually in this
directory.

## Layout

Each rule is a directory: `<rule-name>/rule.scm` (the tree-sitter query) plus
`<rule-name>/fixtures/{flag,no-flag}/source.py` (one labelled example snippet
per side — `flag/source.py` should trigger the rule, `no-flag/source.py`
should not). Fixture files used to be named after the pattern they exercised
(`busy-wait.py`, `subzerowhile.py`); they're now uniformly `source.py` so the
path alone (`<rule-name>/fixtures/flag/`) tells you what a file is, and a
rule can eventually hold more than one `source.py` variant without a naming
collision.

```
polling-loop/
  rule.scm               # while <cond>: ... time.sleep(<literal>) ...
  fixtures/flag/source.py
  fixtures/no-flag/       # (empty — negatives not written yet)
busy-wait/
  rule.scm                # while <cond>: <single call-expression body>
  fixtures/flag/source.py # subprocess.poll() spin loop
  fixtures/no-flag/       # (empty)
redundant-iteration/
  fixtures/flag/source.py # invariant recomputation inside a for-loop
  # no rule.scm yet — still AST-only, via ForLoopAnalyzer in astanalyzers.py
untested-boundaries/
  fixtures/flag/source.py
  # no rule.scm yet — still AST-only, via IfAnalyzer in astanalyzers.py
eager-materialization/
  rule.scm                # stub query, not written yet — see below
  fixtures/flag/source.py # sum(list-comprehension) instead of a generator
```

`fixtures/no-flag/` being empty for every rule is a known gap, not an
oversight — per the working notes, negatives are the harder, more valuable
half of a fixture corpus and haven't been harvested yet.

`redundant-iteration` and `untested-boundaries` are registered as rule types
(see below) and have fixtures, but no `.scm` query — they're the two
original Phase 0 AST analyzers (`ForLoopAnalyzer`, `IfAnalyzer`), not yet
ported to tree-sitter. `eager-materialization` is mid-port in the other
direction: `rule.scm` exists (correctly named, correctly wired to the
`eager_materialization` counter) but its query body is still an empty stub
(`(call function ))`), so it's invalid tree-sitter syntax and matches
nothing — `get_ts_match_counts` catches `QueryError` for exactly this case
and prints a warning rather than crashing the run.

`busy-wait/rule.scm` anchors its `call` capture inside `condition:`
(`while process.poll() is None:`) rather than the body — the body itself
is required to be a bare `pass`/`continue`, matching the same shape
`BusyWaitAnalyzer.is_no_op_while` in `astanalyzers.py` checks on the AST
side (also wired in via `detect.py`'s `special_hdlr` hook — see "Adding a
rule" below for what that means for counting). Verified against
`fixtures/flag/source.py` with a direct tree-sitter query run, not just by
inspection.

## Adding a rule

The current contract, as `detect.py` and `shared_state.py` actually enforce
it:

1. Create `<rule-name>/` with `fixtures/flag/source.py` (and ideally
   `fixtures/no-flag/source.py`, though as noted above nobody's done that
   part yet).
2. Add `<rule-name>/rule.scm` — the filename is load-bearing: `detect.py`
   hardcodes `RULES_FILENAME = "rule.scm"` and looks it up by string-joining
   `rule_type_path + RULES_FILENAME`, so anything else (`rules.scm`, plural,
   was the mistake `eager-materialization` shipped with initially) is
   silently never found.
3. Add a matching field to the `Violations` dataclass in `shared_state.py`,
   snake_case to match the dataclass's field-naming convention.
4. Register the rule in `detect.py`'s `rule_types` dict: key is the
   (hyphenated) directory name, `"counter"` must be the *exact* `Violations`
   field name (snake_case) from step 3 — these are two independently-typed
   strings with no shared source of truth, so a rule's directory name and
   its counter name can legitimately differ (`eager-materialization` →
   `eager_materialization`), and it's easy to paste one where the other
   belongs. `detect.py` catches the resulting `AttributeError` and prints
   `Counter not found for ruletype ...` rather than crashing, but the
   counter silently never increments until the mismatch is caught.
5. Optionally give the entry a `special_hdlr` — a function that runs an
   AST-side detector instead of (not in addition to) counting `rule.scm`
   matches. `busy-wait` is the one example: its counter is driven entirely
   by `BusyWaitAnalyzer` in `astanalyzers.py`, because "no sleep call
   anywhere in the loop body" isn't expressible as a single tree-sitter
   query. `detect.py` used to run both the query count *and* the handler
   for these rules, double-counting every fixture; it now runs exactly one
   or the other.

A rule can be registered in `rule_types` before its `rule.scm` exists, or
before that query is valid — `get_ts_match_counts` catches both
`FileNotFoundError` (missing file, `redundant-iteration` and
`untested-boundaries`'s current state) and `QueryError` (present but invalid
syntax, `eager-materialization`'s current state) and treats either as zero
matches with a printed warning, rather than crashing the whole run.

## Driver: `detect.py`

For each rule type, walks `fixtures/flag/`, runs `rule.scm` against every
file via tree-sitter, and (for rules with a registered handler in
`rule_types`) runs a supplementary AST pass *instead of* counting query
matches — see step 5 above. Results tally into `shared_state.py`'s
`violations_tracker` (a shared dataclass instance — this is why
`shared_state.py` exists as its own module: something both
`astanalyzers.py` and `detect.py` import). Renamed from `detect_ts.py`.

## `astanalyzers.py`

Pre-tree-sitter AST visitors, some superseded and some not:

- `BusyWaitAnalyzer` — active, backs the `busy-wait` rule (see gap above).
- `ForLoopAnalyzer`, `IfAnalyzer` — the original Phase 0 analyzers
  (redundant-iteration / untested-boundary / magic-number detection).
  Per the working notes these are slated to be ported to tree-sitter
  queries, not extended further in AST form.

## Setup

Runtime needs `tree_sitter` + `tree_sitter_python`, pinned per the working
notes' gotcha about API churn across versions — neither is currently listed
in `requirements.txt` (that file only has `pyRAPL`/`black`, which look like
carryover from elsewhere, not what this directory actually imports). A
working venv already exists at `../measure/rules_venv` if you need one in a
hurry; otherwise `pip install tree-sitter tree-sitter-python` into whatever
environment you're using.

```
python3 detect.py
```

runs the whole fixture corpus and prints the final `violations_tracker`.

## Local-only files

A few files here are gitignored and specific to this machine, not part of
what a fresh clone gets: `tsanalyzers.py` (WIP, unused stub), `src/`
(Track-B/bias-advisor scratch fixtures, unrelated to Track A), `measure_code`
(a stray tar archive), and `mwrecurse.pem` (an SSH key — gitignored via
`*.pem`, keep it that way, and consider moving it out of the repo tree
entirely rather than relying on `.gitignore` to keep it uncommitted).
