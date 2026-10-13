# rules/

Tier-1 static detection: tree-sitter queries (plus some remaining AST
visitors) that flag energy-smell shapes in Python source. See
[`working-notes.md`](working-notes.md) and the top-level
[energy-aware-code-analysis-plan.md](../../energy-aware-code-analysis-plan.md)
for the full design — this file just orients you in what's actually in this
directory.

## Layout

Each rule is a directory: `<rule-name>/rule.scm` (the tree-sitter query) plus
`<rule-name>/fixtures/{flag,no-flag}/` labelled example snippets — `flag/`
should trigger the rule, `no-flag/` should not. Fixture files used to be
named after the pattern they exercised (`busy-wait.py`, `subzerowhile.py`);
they're now uniformly `source.py` so the path alone
(`<rule-name>/fixtures/flag/`) tells you what a file is.

Once a rule needs more than one snippet per side, each variant gets its own
subdirectory and the filename stays `source.py`:
`fixtures/flag/<variant>/source.py`. `eager-materialization` is the first
rule to use this; the others are still flat at
`fixtures/flag/source.py`. `detect.py` walks with `os.walk`, so both depths
work and no driver change was needed. Keep **one match site per file** — the
counter is `len(matches)` summed over files, so a file with two sites is
indistinguishable from two files with one, which makes a regression hard to
localise.

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
  rule.scm                      # 2 patterns: comprehension arg, ctor wrapper
  fixtures/flag/
    list-comprehension/         # sum([... for ...])
    set-comprehension/          # any({... for ...})
    ctor-wrapper/               # sum(list(... for ...))
    nested-comprehension/       # two for_in_clauses — counter regression guard
  fixtures/no-flag/
    generator/                  # the fix: sum(... for ...)
    non-reducer/                # sorted([...]) — needs the whole list
    dict-comprehension/         # sum({k: v for ...}) — reduces over keys
    already-a-sequence/         # sum(d.values()), sum([1, 2, 3])
```

`fixtures/no-flag/` is empty for every rule *except* `eager-materialization`
— a known gap, not an oversight. Per the working notes, negatives are the
harder, more valuable half of a fixture corpus: anyone can make a rule fire,
and the hard part is not firing on the eleven things that look similar. The
four `eager-materialization` negatives are hand-written, not harvested, so
they're still subject to the textbook-bias hazard the notes describe —
real code is aliased and half-refactored in ways these aren't.

`redundant-iteration` and `untested-boundaries` are registered as rule types
(see below) and have fixtures, but no `.scm` query — they're the two
original Phase 0 AST analyzers (`ForLoopAnalyzer`, `IfAnalyzer`), not yet
ported to tree-sitter. `eager-materialization` went the other direction and
is now the most complete rule here: two patterns, four positive and four
negative fixtures, verified by running the query per fixture rather than by
inspection. Two things it cost that are worth not re-learning:

- **An unknown predicate is silently ignored, not rejected.** The rule
  shipped with `#any_of?` (underscore) instead of `#any-of?`. py-tree-sitter
  files an unrecognised predicate as a "general predicate" and never
  evaluates it, so the function-name filter simply never ran and the rule
  fired on `sorted([x for x in data])` — see
  `fixtures/no-flag/non-reducer/`. Nothing surfaces the typo:
  `Query.pattern_settings(0)` returns `{}`. Same trap applies to `#eq?` and
  `#match?`.
- **Capturing a child that can repeat multiplies matches.** A capture inside
  an unanchored repeatable child (`(for_in_clause right: (_) @_iterable)`)
  binds once per occurrence, so `max([x for row in grid for x in row])`
  reported one call site as two matches. Counter-intuitively the
  multiplicity comes from the *capture*, not the pattern — remove
  `@_iterable` and tree-sitter collapses the identical capture sets back to
  one. The fix is the sibling anchor `body: (_) .`, which pins it to the
  first clause. `fixtures/flag/nested-comprehension/` guards this.

An alternation also can't carry shared children — `[(a) (b)] body: (_)` is
an `Impossible pattern` error at query-compile time, not a silent
non-match — so `rule.scm` repeats the subtree in each branch. Reusing the
same capture name across branches is fine, since only one branch binds.

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

1. Create `<rule-name>/` with `fixtures/flag/source.py` and
   `fixtures/no-flag/source.py` — or, if the rule has more than one shape per
   side, `fixtures/{flag,no-flag}/<variant>/source.py` as
   `eager-materialization` does. One match site per file either way. Only
   `eager-materialization` has negatives so far; write them anyway, since
   articulating what the rule does *not* catch is the design work.
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
syntax — `eager-materialization` was in this state until its query was
written) and treats either as zero matches with a printed warning, rather
than crashing the whole run. Convenient while porting, but note the failure
mode: a rule whose query is malformed reports zero, which is also what a
correct rule reports on clean code. Worth distinguishing once there's real
output rather than a counter.

## Driver: `detect.py`

For each rule type, walks `fixtures/flag/` and `fixtures/no-flag/`, runs
`rule.scm` against every file via tree-sitter, and builds a `Finding` per
match (see `findings.py`). Counters in `shared_state.py`'s
`violations_tracker` are now *derived* — `len(findings)` — rather than being
the only thing captured. For rules with a registered `special_hdlr` the
counter still comes from the AST pass instead, but findings are collected
either way, so `busy-wait` no longer discards its query results. Renamed
from `detect_ts.py`.

```
python3 detect.py                      # counters, as before
python3 detect.py --out findings.jsonl # one JSON record per site
```

`violations_tracker` is a shared dataclass instance — this is why
`shared_state.py` exists as its own module: something both
`astanalyzers.py` and `detect.py` import.

## `findings.py`

Turns query matches into records. A count can't say *which* site fired, so a
false positive in a harvested corpus surfaces only as a number being one too
high and has to be bisected by hand; and a count can't be joined to a tier-3
measurement. One record per site, written as JSON Lines, never aggregated at
capture time — a mean can always be re-derived from rows, but rows can't be
recovered from a mean.

Each record carries the rule id, the repo-relative path, a 1-based
character-column region, the snippet, a fingerprint, the enclosing context,
the raw capture text, and per-rule `inferences`.

### Grain is a site; scope is a grouping

**Analysis reports one violation per site.** Per-file, per-function and
per-check-in are *groupings* over those rows, not different analyses — so
none of them is an architecture decision, and adding one is a `GROUP BY`
rather than a new code path. Per-file is the current default, because
`detect.py` already walks files.

**No sums.** Reporting happens at the scope level of the group, never as a
total. A tier-3 coefficient is cost per *execution* of a shape, while static
analysis finds *sites*, so adding coefficients across sites silently assumes
each one runs exactly once — wrong by orders of magnitude. A per-file joule
figure would be a count wearing a joule costume, and would be the most
quotable and least defensible number the tool could emit.

The one grouping worth planning for is **per check-in** (findings on changed
lines only). Every static-analysis tool developers tolerate converged there,
and the reason is noise: any real codebase has hundreds of pre-existing
findings, nobody clears them, and the tool gets muted. It needs no new
analysis — the file walker plus a line filter.

### `enclosing_function` and `enclosing_loop_depth`

The two group keys, and they must be read **together**: `None` /0 (module
level, runs once at import) is a different fact from `tally`/0 (runs once per
call).

`enclosing_loop_depth` counts iterating ancestors and is the **only frequency
signal available statically**. Absolute execution counts are invisible to
tree-sitter, but loop *nesting* is right there in the tree. It yields an
**ordering**, never a count, and must not be presented as one — but ordering
is the difference between 40 findings a developer reads and 40 they ignore.

Two things that make the number mean what it says:

- **A `def`/`lambda` is an execution-count barrier, not just a scope.** A loop
  wrapped around a `def` runs the *definition*; how often the body runs is
  decided by callers, which is a call-graph fact tree-sitter cannot see.
  Counting through the barrier would report depth 1 for a site that may never
  execute.
- **Comprehensions are counted at the comprehension node, not its
  `for_in_clause`.** A comprehension's body is a *sibling* of its clause, not
  a descendant, so a parent walk from the body never passes through
  `for_in_clause` — counting that instead reports depth 0 for
  `[sum([x for x in row]) for row in grid]`, where the inner site plainly runs
  once per row. Arriving at a comprehension *from* a `for_in_clause` is
  skipped, since that's the iterable expression and it's evaluated once.

Because depth stops at the barrier it is only comparable **within** a
function: a depth-0 site in a hot handler outranks a depth-2 site in startup
code. Ranking functions against each other needs an execution count this
cannot supply — that's the seam where an optional profile join would go, not
somewhere to add more static cleverness.

**The two claims stay separate.** Per `working-notes.md`, a rule asserts both
"this code has shape X" (certain, if the query is right) and "shape X costs
energy" (a tier-3 claim). So there is no single `confidence` field. There is
`impact_confidence`, only ever about the second claim, derived from whether
the trip count is knowable from the source — the one part of the cost claim
static analysis can partially settle, and the dominant false-positive source
per the notes.

`eager-materialization`'s inferences, each a fact about the match rather than
a guess:

| field | derived from | why it matters |
|---|---|---|
| `reducer` | `@_func` | which single-pass consumer |
| `short_circuits` | `@_func` ∈ {any, all} | the shape wastes the early exit *as well as* the allocation — a different cost mechanism, so the rig should expect a different ratio |
| `materialised` | `@_built` node type / `@_ctor` | list vs set vs tuple |
| `spelling` | `pattern_index` | comprehension-arg vs ctor-wrapper; two shapes that may not cost the same |
| `iterable_kind` | `@_iterable` node type | `call` / `identifier` / `list` |
| `trip_count`, `trip_count_n` | `@_iterable` | `literal` for `range(1_000_000)` or a literal sequence, `unknown` for `range(n)` or a bare name |
| `removal_preserves_semantics` | reducer + materialised | `False` only for `sum({...})`, where `set`'s dedup changes the answer |

Rules absent from `INFERENCE_HANDLERS` still produce findings, just with
captures and no inferences — the honest default for a rule nobody has
characterised yet.

Two helpers worth knowing about before writing a third rule's handler:

- `char_column()` converts tree-sitter's **byte** columns to character
  columns, and `node_region()` shifts to 1-based. Both exist in exactly one
  place on purpose: an off-by-one in a location never raises, it just points
  one character left, and the byte/char gap only opens on non-ASCII — so it
  passes every hand-written fixture here and would fail on harvested code.
  Verified against `total_café = sum([...])`, where the byte column is 15 and
  the character column is 14.
- `fingerprint()` is `sha256(rule_id, path, whitespace-normalised snippet)`
  and deliberately **excludes the line number**, so editing anything above a
  site doesn't rename it. Not needed to join tier 1 to tier 3 — that join is
  on `rule_id` — but required to compare the same site against a measurement
  taken at a different commit.

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
working venv exists at the repo root (`.venv`) if you need one in a hurry;
otherwise `pip install tree-sitter tree-sitter-python` into whatever
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
