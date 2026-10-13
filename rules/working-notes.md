# Working Notes — Energy-Aware Code Analysis

*Companion to [the project plan](./energy-aware-code-analysis-plan.md). The plan is the structured version; this is "what next and what not to forget."*

Last updated: 2026-09-01

---

## Starting a fresh session

Attach this file and the plan doc. Short version to paste:

> Recurse project: a CLI tool that surfaces energy insights to developers (and code-generating agents) during coding, via static analysis. Tree-sitter queries over Python, Python engine, ratios rather than absolute joules. Currently porting hand-written If/For analyzers to tree-sitter queries, then building the rule metadata schema and the first real rule. Measurement rig (two old laptops, RAPL + smart plug) is being revived in parallel. See attached notes for decisions already settled.

---

## Next actions

### Static analysis (active)

- [ ] **Decide per analyzer: query or visitor — before writing any code.** The If/For analyzers are probably shape rules, so they want to be `.scm` queries, not tree-sitter visitors. Visitor → visitor → query is two migrations where one will do.
- [ ] **Port the If/For analyzers to tree-sitter.** Keep the `ast` versions running alongside temporarily; diff the flagged line numbers over the same files. Agreement means the port is correct. Delete the `ast` version once they match.
- [ ] **Pin `tree-sitter` and `tree-sitter-python` to exact versions** before starting.
- [ ] **Add a query-tester pane to the JS explorer** — paste a query, see matched nodes highlighted in the tree already being rendered. Turns rule authoring from half-hours into minutes.
- [ ] **Design the rule metadata schema** (id, name, severity, tier, decoupled, portable, config, message template).
- [ ] **Write rule ENERGY001 — polling loop.** `while True:` containing `sleep(<small literal>)`. Exercises the whole path: node matching, body traversal, call resolution, literal extraction.
- [ ] **Read the ICSME 2026 energy-smell taxonomy** (link below) before finalising the rule set.

### Hardware (parallel, unblocks Phase 2)

- [ ] Lazarus treatment on both laptops. **Record CPU model and generation before wiping** — if they differ, cross-rig validation gets much more interesting.
- [ ] Smart plug ordered.
- [ ] Once Linux is on: `ls /sys/class/powercap/` to confirm RAPL, and check which domains exist.

---

## Decisions already made — don't relitigate

| Decision | Why |
|---|---|
| **CLI-first, not IDE extension** | Two consumers: humans *and* code-generating agents. A CLI with a documented contract serves both. |
| **Python engine, JS explorer stays a dev tool** | Exercises Python; the Phase 2 harness is Python anyway. The explorer is browser-shaped and already works. |
| **Tree-sitter primary, `ast`/`symtable` as escape hatch** | Tree-sitter ports across languages and has the query language. `ast` only earns its place for scope-dependent rules. |
| **Report ratios, not joules** | Ratios are stable across hardware; absolutes aren't. Keep raw joules in the logs. |
| **Three tiers with explicit provenance** | Static candidates / deterministic confirmation / offline calibration. Never blend silently. |
| **Rules biased toward energy-time decoupling** | Otherwise it's a profiler with a greener label. |
| **Track B (bias) parked** | Revisit on Impossible Day. |

---

## Key concepts

**SARIF** — Static Analysis Results Interchange Format. OASIS-standardised JSON: rules declared once, results referencing them by ID, plus a `properties` bag for tool-specific data (tier, ratio, confidence). GitHub code scanning and VS Code consume it directly. *Verbose for a small tool — design your own clean JSON as primary, add SARIF as an export.*

**`.scm` / tree-sitter queries** — `.scm` is Scheme's extension, borrowed because the syntax uses S-expressions. **Not Scheme**, can't be executed. Search "tree-sitter query syntax," never "scm."

**Fixtures corpus** — small source files where the answer is known. `flag/` should trigger; `no-flag/` should not. **The `no-flag/` directory is where the value is** — anyone can make a rule fire; the hard part is not firing on the eleven things that look similar.

**Tiers** — 1: tree-sitter static (continuous, everywhere, shape only). 2: Cachegrind deterministic counting (on demand, VM-safe because it's a simulator). 3: RAPL/wall-meter calibration (offline, bare metal, produces ratio coefficients).

**Decoupled** — the rule catches something a wall-clock profiler wouldn't already flag. Race-to-idle means fastest usually *is* lowest-energy, so undecoupled rules are speed rules in a green hat.

---

## Validation strategy

### The two claims — don't conflate them

A rule asserts two separate things:

1. **This code has shape X.** Local, mechanical, judgeable from the snippet alone.
2. **Shape X costs energy.** A tier-3 coefficient claim, validated once per rule class on the rig.

**Fixtures only validate #1.** That collapses most of the labelling difficulty — you're not asking "does this waste energy," you're asking "is this a polling loop."

### Local decidability is a design criterion, not just a testing convenience

If you can't tell from fifteen lines whether the rule fired correctly, **neither can a developer reading the finding in their editor**. A finding requiring whole-program analysis to evaluate is a bad finding even when technically correct. So a rule that's hard to build fixtures for should be narrowed until it's locally decidable, or dropped. Labelling difficulty is a quality signal.

### Harvesting real code

The rule does localization; you do judgment. You still read code — fifteen lines at sites the rule already found, not whole trees.

- **Start with `site-packages`** — tens of thousands of files of real production Python already on disk. `python -c "import site; print('\n'.join(site.getsitepackages()))"`. Add the stdlib as a conservative contrast set. This will probably saturate the first few rules.
- **Match repo domain to rule** when cloning. Polling → daemons, bots, monitoring agents, scrapers. `iterrows` → data science scripts. N+1 → ORM-heavy Django/SQLAlchemy. Ten well-chosen repos beat a hundred popular ones; popularity correlates with quality, which is the opposite of what you want.
- **Seed with code search**, not cloning: GitHub code search takes literal strings (`"while True:" "time.sleep(0.0" language:Python`); [grep.app](https://grep.app) needs no login.
- **Build a `harvest` mode** that dumps each hit as a triage record with a few lines of context.
- **Extract minimal snippets** (5–15 lines), not whole files. A 400-line fixture tells you nothing when it starts failing in six weeks.
- **Timebox one hour per rule.** ~30–50 sites, most judged in seconds.

### Triage with three buckets

`flag/`, `no-flag/`, and **`unsure/`**. Don't force a call. A rule generating many unsures has an undefined boundary — that's a finding, cheaply obtained. Report the exclusion rate alongside precision.

**The asymmetry that saves you:** negatives are the cheap judgment ("that's obviously fine" — ten seconds), and negatives are what you need most, since `flag/` fixtures you can write yourself.

### AI-generated fixtures

Fine for volume, not for the cases that define the rule. Write the first 3–5 yourself, especially the negatives — articulating what you're *not* catching is the design work.

Two hazards: **the closed loop** (AI writes fixtures *and* helps write queries → the test agrees with the rule because both came from the same notion of the pattern), and **textbook bias** (generated Python is too clean; real code is aliased, half-refactored, weird). Both are fixed by harvesting negatives from real repos.

**Tag fixture provenance** — `hand/`, `generated/`, `harvested/` subdirectories. Then report precision per source. "94% on generated, 71% on harvested" is far more interesting than a blended number, and the gap is itself worth writing about.

---

## Gotchas — the things that cost a day

### Tree-sitter / Python

- **py-tree-sitter's API has churned hard.** `QueryCursor` only appeared around 0.25. Most tutorials target older versions and fail confusingly. Read docs for *your pinned version*.
- `parser.parse()` takes **bytes** — just `open(path, "rb")`, nothing exotic.
- **Offsets are bytes, not characters.** Fine on ASCII; breaks on an em-dash in a comment. Slice `source_bytes[node.start_byte:node.end_byte].decode("utf-8")`, or use `node.text.decode("utf-8")`.
- **`start_point` columns are also byte columns**, but SARIF expects character columns. Convert once in the location helper: `len(line[:byte_col].decode("utf-8"))`.
- **`named_children` vs `children`** — tree-sitter keeps punctuation and keywords as anonymous nodes. Python's `ast` has no equivalent.
- Node types are **snake_case strings** from the grammar (`while_statement`), not CamelCase classes.
- **`generic_visit` footgun**: define `visit_X`, forget to call `generic_visit`, traversal silently stops.
- **Prefer field names** (`condition:`, `body:`) over positional matching — positional queries break when the grammar adds a node.
- **Write queries against 3–4 variants**, not one. A query written against a single example overfits immediately.
- **Serving the explorer:** WASM won't load over `file://`. `python -m http.server 8000`. `.wasm` MIME is correct on modern Python.

### What tree-sitter structurally cannot do

Limits of the technique, not gaps to close. Put them in the README.

- **Types.** `x += y` in a loop: quadratic for `str`, fine for `int`. Unknowable.
- **Trip counts.** `range(n)` — 3 or 3 million? **Dominant false-positive source.**
- **Hot-path frequency.** Startup code vs a handler at 10k rps. Probably matters more to real energy than every pattern in the rule table combined, and it's invisible.
- **Library internals.** `df.merge(...)` is one node with all the energy inside C.
- **Aliasing.** `f = requests.get; f(url)` defeats name-based rules.
- **Scope/name resolution.** Needs `symtable`. The only reason `ast` stays in the picture.

### Measurement

- **`dram` RAPL domain is usually server-only.** Client chips give package/core/uncore. Memory-traffic coefficients will have to come from tier-2 cache-miss counts.
- **Pin frequency, disable turbo, `taskset` one core, SMT sibling off, background services stopped, thermal soak.** Matters far more than the meter — skipping it produces variance averaging won't fix.
- **Measure idle and subtract it.** The attributable number is marginal energy over baseline.
- **Wall meters sample ~1 Hz** — loop the snippet to 20–30s and divide.
- **A laptop with a working battery is a bad wall-meter subject** (charging masks load). A dead battery is an asset.
- **Free first try:** on battery, sample `/sys/class/power_supply/BAT0/power_now` — whole-system µW, no purchase.
- Since CVE-2020-8694, `energy_uj` is root-only on most distros.

### Misc

- **Relative markdown links don't resolve in issues, PRs, or comments** — only files in the repo tree. Those need full URLs.
- Relative links beat absolute because they follow the branch you're viewing; `blob/main/...` pins to `main` forever.

---

## The field — what to search, where to publish

**Umbrella:** *green software engineering* / *sustainable software engineering*.

**The exact niche has a name: "energy smells"** (also *energy code smells*, *green code smells*). That's your rule table, and it's the highest-yield search term.

- **["Watts This Smell: A Comprehensive Taxonomy of Software Energy Smells"](https://tusharma.in/preprints/ICSME2026_EnergySmell.pdf)** (ICSME 2026) — read before finalising the rule set.

**Adjacent terms:** static energy estimation · software energy profiling · green refactoring · energy debugging.

**Don't skip the mobile literature** — Android energy research is the mature precedent, a decade ahead because battery made it urgent. Search **"no-sleep bugs"** and **wakelock misuse**: a no-sleep bug is the polling-loop rule in a different setting, and the detection techniques, false-positive problems, and developer-UX questions are all worked over there.

**Venues:** [GREENS](https://greensworkshop.github.io/) (ICSE workshop, most on-target) · [ICT4S](https://conf.researchr.org/track/ict4s-2026/ict4s-2026-workshops) · HotCarbon · MSR (the harvesting methodology) · ICSME · EMSE.

**Search hygiene:** "software sustainability" also means *maintainability of research software* and will pollute results. Use "green software" or "software energy."

**Possible gap to claim:** most of this literature doesn't separate "saves energy" from "is just faster," and detectability precision is usually reported against curated examples rather than harvested real code. Confirm against the taxonomy paper.

---

## Open questions

- **What does an agent do differently given this signal?** "Generate, check, rewrite, re-check" is a tighter loop than a human can run. Probably the most novel part — decide deliberately rather than discovering late.
- Do the ratios hold across both laptops?
- Mark each rule `portable: true/false` as written. Query-based rules port to a new grammar free; `symtable`-dependent ones don't.
- Does the comprehension-vs-loop speed claim (avoided `.append` attribute lookup) actually hold? Good first sanity check for the rig — tests the claim and the harness at once.

---

## Parked, but not wasted

The **"could have been a comprehension"** For analyzer is a speed rule. Keep it as `decoupled: false`.

**But reuse its guts.** It detects "a loop accumulating into a list," one step from the energy-relevant sibling: materializing a list where a generator would do — `sum([x for x in y])` vs `sum(x for x in y)`. Same shape, different recommendation, and that one is DRAM traffic rather than interpreter overhead.
