# rules/

Tier-1 static detection: tree-sitter queries (plus some remaining AST
visitors) that flag energy-smell shapes in Python source. See
[`working-notes.md`](working-notes.md) and the top-level
[energy-aware-code-analysis-plan.md](../../energy-aware-code-analysis-plan.md)
for the full design — this file just orients you in what's actually in this
directory.

## Layout

Each rule is a directory: `<rule-name>/rule.scm` (the tree-sitter query) plus
`<rule-name>/fixtures/{flag,no-flag}/` (labelled example snippets — `flag/`
should trigger the rule, `no-flag/` should not).

```
polling-loop/
  rule.scm              # while <cond>: ... time.sleep(<literal>) ...
  fixtures/flag/         # subzerowhile.py
  fixtures/no-flag/      # (empty — negatives not written yet)
busy-wait/
  rule.scm               # while <cond>: <single call-expression body>
  fixtures/flag/         # busy-wait.py (subprocess.poll() spin loop)
  fixtures/no-flag/      # (empty)
```

`fixtures/no-flag/` being empty for both rules is a known gap, not an
oversight — per the working notes, negatives are the harder, more valuable
half of a fixture corpus and haven't been harvested yet.

`busy-wait/rule.scm` anchors its `call` capture inside `condition:`
(`while process.poll() is None:`) rather than the body — the body itself
is required to be a bare `pass`/`continue`, matching the same shape
`BusyWaitAnalyzer.is_no_op_while` in `astanalyzers.py` checks on the AST
side (also wired in via `detect_ts.py`'s `special_hdlr` hook, so both fire
on the same fixtures). Verified against `fixtures/flag/busy-wait.py` with a
direct tree-sitter query run, not just by inspection.

## Driver: `detect_ts.py`

For each rule type, walks `fixtures/flag/`, runs `rule.scm` against every
file via tree-sitter, and (for rules with a registered handler in
`rule_types`) also runs a supplementary AST pass. Results tally into
`shared_state.py`'s `violations_tracker` (a shared dataclass instance —
this is why `shared_state.py` exists as its own module: something both
`astanalyzers.py` and `detect_ts.py` import).

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
python3 detect_ts.py
```

runs the whole fixture corpus and prints the final `violations_tracker`.

## Local-only files

A few files here are gitignored and specific to this machine, not part of
what a fresh clone gets: `tsanalyzers.py` (WIP, unused stub), `src/`
(Track-B/bias-advisor scratch fixtures, unrelated to Track A), `measure_code`
(a stray tar archive), and `mwrecurse.pem` (an SSH key — gitignored via
`*.pem`, keep it that way, and consider moving it out of the repo tree
entirely rather than relying on `.gitignore` to keep it uncommitted).
