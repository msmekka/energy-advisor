# Energy-Aware Code Analysis — Recurse Project Plan

*Revised September 2026 (updated 2026-09-18 with measurement-rig findings: RAPL domain hierarchy, wall-power-over-battery decision). Supersedes the earlier "IDE Extension for Efficiency & Bias Coding Feedback" outline.*

*What changed: the project is now energy-focused and CLI-first, built on a three-tier architecture that separates cheap continuous static detection from expensive offline measurement. Track A (efficiency/energy) is the active work. Track B (bias) is retained below but deferred to Impossible Day–style exploration.*

---

## a) Where the idea stands after review

The original outline was sound as a learning project. Three findings from working through the measurement side forced a restructure rather than an edit.

### 1. Live energy measurement in the editor is not achievable — for three independent reasons

**Access.** pyRAPL, CodeCarbon's RAPL path, and everything else in that family read Intel's counters through `/sys/class/powercap/`. That interface does not exist inside a VM: hypervisors don't virtualize the RAPL MSRs, and the semantics would be incoherent if they did (what does package energy mean when you own 4 of 96 vCPUs?). WSL2, devcontainers on macOS, Codespaces, and every cloud instance that isn't `.metal` are all excluded. Since CVE-2020-8694, `energy_uj` is also root-readable only on most distributions.

**Resolution.** The RAPL energy counter updates on roughly a 1 ms interval with tens of microjoules of resolution. A snippet that runs in microseconds sits below that noise floor. The counter is also package-wide and non-attributable — the language server, the browser, and the editor itself are all in the number — and DVFS, turbo, and thermal state mean the same snippet measures differently at minute 1 and minute 30 of a session. A trustworthy per-snippet figure requires warmup, repetition, and statistical treatment. That is a benchmark run, not something that happens while you type.

**Coverage.** RAPL sees package and, on server parts, DRAM. It does not see disks, NICs, fans, PSU conversion losses, or cooling. On a typical node the CPU package is roughly half of system power, and considerably less on GPU- or storage-heavy machines. This was true before virtualization entered the picture.

**Consequence:** the honest design is *a static rule backed by a coefficient measured offline on a documented rig*, never a live joule counter. This is a constraint to state in the README, not one to engineer around.

### 2. Wall time is a stronger proxy for energy than the green-coding literature implies

Race-to-idle means that for single-threaded CPU-bound code on fixed hardware, the fastest version is very nearly always the lowest-energy version. A tool whose rules mostly fire where a profiler would already say "slow" is a profiler with a greener label.

The project earns its framing only where energy and wall time **decouple**:

- memory traffic versus compute (DRAM energy per byte is high and often hidden by prefetching, so it costs energy without costing time)
- thread and process count versus parallel efficiency (more cores at low utilization is worse energy at similar wall time)
- polling and timer wakeups that keep the package out of deep C-states (cheap in CPU time, expensive in energy)
- I/O patterns that hold devices and links active
- numeric precision and SIMD width
- GPU offload decisions

**This list should drive the rule set**, in preference to the classic complexity anti-patterns, which are already well served by existing linters and profilers.

*Python caveat worth stating up front:* in pure CPython the interpreter dominates and most of this decoupling vanishes — energy tracks time closely. Where it survives in Python: numpy/pandas memory traffic and dtype choices, asyncio versus threads versus polling, sleep and poll intervals, multiprocessing worker counts, and I/O batching. Python remains the right first target for the AST learning goals; just don't expect it to be the domain that best demonstrates energy ≠ speed.

### 3. There are two consumers, not one

Alongside the human in an editor, there is a code-generating agent that could take energy feedback as a signal during generation. That changes the design centre of gravity:

- the **output format is the product interface**, not an afterthought behind a squiggle
- findings need stable rule IDs, machine-readable locations, explicit confidence, and explicit provenance
- a CLI with a documented contract serves both consumers; an editor extension serves only one

This is the main argument for CLI-first, ahead of any editor integration.

---

## b) Architecture: three tiers, with provenance carried through

| Tier | Mechanism | Runs | Available in VMs/containers | Gives you |
|---|---|---|---|---|
| **1 — Candidates** | Tree-sitter static analysis | Continuously, milliseconds | Yes, always | Pattern *shape* and location. No magnitude. |
| **2 — Confirmation** | Deterministic counting (Cachegrind, allocation and syscall counts) | On demand, per selection/function/test | Yes — it's a simulator, not a hardware counter | Reproducible instruction and cache-miss counts. Same number every run. |
| **3 — Calibration** | RAPL / wall-meter measurement on a documented rig | Offline, occasionally, by you | No — bare metal only | Ratio coefficients per pattern class, shipped as data. |

Two rules that follow from this table:

1. **Never blend tiers silently.** Every finding carries the tier it came from. "Measured on rig X" and "estimated from coefficient table v3" are different claims and the output schema must distinguish them.
2. **Cachegrind is the VM-immune tier.** It's a simulator, so it runs identically inside a container, and its determinism matters more than its accuracy for a tool that must not flicker between runs. (Note: Valgrind does not support Apple Silicon — a Linux container works fine, precisely because nothing physical is being measured.)

### Report ratios, not joules

Surface *"pattern B costs 4.2× pattern A on rig X"* rather than an absolute joule figure. Ratios are far more stable across hardware than magnitudes, they're what a developer or an agent can act on, and they sidestep every argument about whether the absolute number is right. Keep raw joules in the measurement logs for the write-up; don't put them in the tool's output.

---

## c) Rule set

Prioritised by the decoupling criterion above. "Decoupled" means the rule catches something a wall-clock profiler would not already flag.

| # | Pattern | Tree-sitter detectability | Decoupled from time | Notes |
|---|---|---|---|---|
| 1 | `while True:` containing `sleep(<small literal>)` — polling | High | **Yes** | Defeats deep C-states. One of the clearest energy-first rules. |
| 2 | Busy-wait: `while cond:` with no sleep, I/O, or yield in body | High | **Yes** | |
| 3 | Short-interval timers — `threading.Timer(0.01, …)`, `schedule.every(1).seconds` | High (literal-driven) | **Yes** | High precision; the interval is right there in the source. |
| 4 | Worker count from `cpu_count()` for I/O-bound work; large literal `max_workers` | Medium | **Yes** | Over-parallelisation costs energy at flat wall time. |
| 5 | `.iterrows()`, `.apply(axis=1)`, `.append` in a loop on DataFrames | High (name-based) | **Yes** | Nobody writes those names by accident — precision is high in practice. |
| 6 | Materialising a list where a generator suffices — `sum([...])`, `list(...)` immediately consumed | High | **Yes** | DRAM traffic and allocator pressure. |
| 7 | Explicit `dtype=np.float64` where float32 would serve | Medium (literal) | **Yes** | Memory bandwidth and SIMD width. |
| 8 | Unbatched I/O in a loop (N+1): `requests.get`, `cursor.execute`, `session.query` inside `For` | Medium (name list; defeated by aliasing) | Partly | Device stays active, wakeups accumulate. |
| 9 | Loop-invariant computation inside a loop body | Medium–high (needs def-use analysis) | No — tracks time | Most instructive rule to implement. |
| 10 | Nested loop with linear membership test (`x in list` inside a loop) | High shape, no trip counts | No | Keep for coverage; acknowledge it's a speed rule. |
| 11 | String concatenation accumulating in a loop | High shape, no types | No | Quadratic for `str`, harmless for `int`. Cannot tell which. |

### What tree-sitter structurally cannot see

Worth writing into the README, because these are the limits of the whole tier-1 approach, not gaps to close with more effort:

- **Types.** `x += y` in a loop is quadratic for `str`, fine for `int`, something else again for a numpy array. Mitigable with annotations, literal inference, or a type layer (jedi, pyright output) — never fully closed in Python.
- **Trip counts.** `for i in range(n)` — is `n` 3 or 3 million? Nested loops over tiny collections are free, and will be flagged identically. **This is the dominant false-positive source.**
- **Hot-path frequency.** A quadratic loop in startup code run once, versus in a request handler at 10k rps. This probably matters more to real energy than every pattern in the table combined, and it is invisible statically.
- **Library internals.** `df.merge(...)` is one call node; all the energy is inside C.
- **Aliasing and dynamic dispatch.** `f = requests.get; f(url)` defeats name-based rules routinely.
- **Memory traffic.** The thing you most want to know is a runtime property. This is exactly what tier 2 is for.

**Summary:** tier 1 gives good recall, mediocre precision, and no magnitude. That is not a flaw in the implementation — it's the shape of the technique, and stating it plainly is part of the deliverable.

---

## d) Calibration rig and methodology

### Hardware

The old Lenovo is the right rig, not the development machine. Target-machine representativeness matters here even though it doesn't for static analysis: coefficients meant to describe code shipping to Xeon or EPYC servers should not be derived on Apple Silicon, whose efficiency cores, unified memory, and performance-per-watt curve are genuinely atypical. Ratios shift, particularly the memory-traffic-versus-compute ones that matter most.

Setup checklist:

1. Linux on the Lenovo, then `ls /sys/class/powercap/` — non-empty means RAPL is live. Any Intel from Sandy Bridge (2011) forward qualifies; most ThinkPads from 2012 on are fine.
2. Check which domains exist. Client chips typically expose `package`, `core`, and `uncore/gfx`. **The `dram` domain is usually server-only** — a real limitation, since memory-traffic coefficients are the most interesting case. Plan to infer memory cost from tier-2 cache-miss counts rather than measure it directly. **Our rig exposes dram. We can get measurements directly**
3. Pin the machine down. Disable turbo (`intel_pstate/no_turbo`), fix the governor with `cpupower frequency-set`, `taskset` to one core, disable the SMT sibling, stop background services, and let it thermally soak before the first sample. **Reproducibility depends far more on this than on the choice of meter** — skipping it produces variance that averaging will not fix.

**Rig details, 2026-10-16** — the record this section calls for. `rc-mw01`: 4 logical CPUs / 2 physical cores, so SMT-off leaves `cpu0` and `cpu1` online and nothing else; the measured child pins to core 1 while the runner shares core 0 with the OS. Base clock locked at 2,600,000 kHz, turbo off, governor `performance`. Kernel 7.0.0-38-generic, x86_64, CPython 3.14.4 (GCC 15.2.0). Five RAPL domains: `package-0`, `core`, `uncore`, `dram`, `psys`. `energy_uj` ships at 0400 and is relaxed to 0444 for the session by `pin_baseline.sh`, restored on `--restore`, which is what keeps the measurement campaign entirely unprivileged. Idle baseline after a 600 s soak: package-0 0.420 W, dram 0.656 W, core 0.019 W, psys 0.319 W, and `uncore` **exactly zero** — a dead counter on this part, not a quiet one, which matters because a zero delta is otherwise indistinguishable from an idle window.

**Domain hierarchy, confirmed empirically on this rig:** `core` and `uncore` are children of `package-0` (sysfs subzones), not separate rails — never sum them on top of package-0. `dram` is a genuinely separate physical rail (memory controller/DIMMs) and adds to, rather than replaces, the package total. `psys` — meant to be the platform-wide umbrella covering package + dram + more — measured *lower* than package-0 + dram combined here, which is physically incoherent for an umbrella metric. **Decision: CPU-side total = sum of package domains + dram; `psys` excluded, and its inconsistency is not being root-caused.** `psys` is seemingly unreliable on this rig, and chasing why is a rabbit hole with no payoff for the project's goals — an explicit call to drop it rather than debug it. Write this choice down next to the rig details (CPU model, kernel, governor, date) whenever coefficients get recorded — it's a rig-specific finding, not a general RAPL fact.

### Whole-system reference: wall power, not battery discharge

Two paths were tried for a whole-system number to validate RAPL's package+dram total against (RAPL only ever sees a slice of the machine — see "Coverage" in section a).

**Battery discharge (`power_now`/`energy_now`) — tried, set aside.** `power_now` is an instantaneous rate; `energy_now` is a level (µWh remaining) and the more stable of the two to sample. Worked out on this rig: `energy_now` ticks in ~10,000 µWh (10 mWh = 36 J) steps roughly every 9.5 s, giving an idle draw of ~3.8 W (36 J ÷ 9.5 s) — plausible, but **the granularity and accuracy this path can deliver on this system don't get us where we need to be**: the counter's own step size dominates short-window deltas for the same reason Shelly's `aenergy.total` does (see below), only with a coarser tick, so it can't resolve anything finer than a fairly coarse, long-window average. It's also in tension with `pin_baseline.sh`'s 600 s soak: that wants the rig parked in a stable pinned state on mains, not drained down while measuring. **Decision: use wall power (the Shelly plug) as the whole-system reference instead of battery discharge.**

**Smart plug (Shelly, wall power) — the reference path.** Local HTTP API, no cloud round-trip, no Kill-A-Watt hand-reading. Built as `shelly_check.py` (RPC client) plus `validate_shelly.py` (samples RAPL and Shelly concurrently over the same window) and `validate_baseline.py` (cross-checks a saved `pin_baseline.sh` idle baseline against Shelly, sampled fresh, and flags it stale past 1 hr — the comparison is only meaningful while the rig is still in the same pinned/idle state). Two constraints came out of building these: sampling is ~1 Hz, so short windows are dominated by `aenergy.total`'s own quantization (a 30 s window can read a 0 W or a wildly inflated delta) — fixed in practice by using 300 s+ windows so real accumulated energy swamps the counter step, cross-checked against the instantaneous `apower` field and flagged if the two diverge by more than 2×. And because this rig is a laptop, not a dedicated desktop/NUC, wall draw only means "system load" if it stays plugged in with the battery already topped off — otherwise the charger's own draw contaminates the reading. That long-standing laptop caveat is mitigated this way, not eliminated.

A clean validated 300 s run on this rig: Shelly ≈4.3 W wall draw at idle, RAPL package+dram covering 7–15% of that — sensible, since CPU package/DRAM is only a slice of total system power (PSU conversion loss, disk, fans, screen aren't seen by RAPL at all).

### Methodology

- **Measure idle and subtract it.** The attributable figure is marginal energy over baseline, not total draw. This is also what makes a laptop measurement partially transferable to a server despite the enormous difference in fixed power.
- **`avg_power_w` is an energy-delta average, not an instantaneous reading** — compute it as (energy delta over the window) ÷ (elapsed time) for both RAPL and Shelly, and only compare against Shelly's instantaneous `apower` loosely, since it isn't the same quantity.
- **Batch to clear the sampling floor.** Loop the snippet until the run exceeds the meter's resolution by a comfortable margin, then divide.
- **Version the coefficient file and record the rig in it** — CPU model, kernel, governor settings, Python version, date. Python version matters more than it looks: 3.11's specialising interpreter moved per-operation costs meaningfully, and free-threading moves them again.
- **Don't try to build the table.** Build the harness that would build it, and populate it for three to five patterns on one machine. A defensible general table would have to vary microarchitecture, core count, governor, memory configuration, platform idle power, workload size, thermal state, and interpreter version — thousands of runs, stale in eighteen months. That's ongoing research infrastructure, which is why no good public table exists. The absence is itself a finding worth writing up.

### First measured result — 2026-10-16

First measurement on real hardware. `eager-materialization`, the `sum_list`
pair: `sum([x * x for x in data])` against `sum(x * x for x in data)`, which
differ by two characters. N = 200,000, R = 72 (≈1 s window), six interleaved
flag/no-flag pairs, ratio computed per adjacent pair. Raw — idle subtraction is
designed but not yet implemented.

| | mean | stdev |
|---|---|---|
| time ratio | 1.017 | 0.038 |
| energy ratio (`package-0` + `dram`) | 1.101 | 0.035 |
| **decoupling** | **1.083** | **0.012** |

SEM on the decoupling quotient is ≈0.005, putting it roughly 16 standard errors
above 1.0. The time ratio is **not** distinguishable from 1.0 — individual pairs
land on both sides of parity (0.981 to 1.068).

**So: wall-clock cannot tell these two programs apart. Energy says one costs
about 10% more.** That is the project's thesis in its cleanest form. Not "a
difference a profiler might dismiss as small" — a difference a profiler cannot
see at all.

Three methodological findings came with it, each arguably worth more than the
number:

1. **The window floor is real, and short windows inflate.** The same pair at
   R = 5 — a 71 ms window — gave a decoupling of 1.21. At R = 72 it gives 1.083.
   Too few repetitions let cold-iteration effects occupy a large fraction of the
   measured region. The 1.21 is retired. Anything below roughly a 1 s window
   should be treated as uncalibrated.
2. **The decoupling quotient is better-conditioned than either ratio it is built
   from** — stdev 0.012 against 0.038 and 0.035. Time and energy noise are
   strongly correlated (a slow run is also a high-energy run), so the ratio of
   ratios cancels the common mode. The unit chosen for conceptual reasons turns
   out to be the statistically sharper one too.
3. **Campaigns are far cheaper than assumed.** At that variance, 6–10 repetitions
   per point give a usable standard error. Five pairs × five values of N × 10
   repetitions × 2 arms is ~500 runs — well under half an hour of rig time. The
   earlier working estimate of ~1200 runs over several hours predated knowing the
   variance.

Still open: idle subtraction, the `trip_count` sweep that turns this into
`ratio(N)`, and the other four pairs. Also worth re-confirming at R = 72 is the
domain split seen in the first (retired) R = 5 run, where `core` tracked the time
ratio while `package − core` roughly doubled and `dram` rose ~44% — i.e. compute
unchanged, memory path loaded. If that holds at a proper window it is direct
evidence the instrument tracks the *claimed mechanism* rather than merely
producing a number, which is the strongest thing a result here can do.

### Open: joules → CO2e

Turning a measured or estimated joule figure into a CO2e figure needs a grid carbon-intensity coefficient (gCO2/kWh), which is region- and time-dependent. Region is unresolved on purpose — it's plausibly private information, and defaulting to an estimate has to be a visible, explicit choice, not a silent one. Per the never-blend-tiers-silently rule in section b), if this lands later it must be its own separately labelled tier (e.g. "estimated CO2e assuming region R, coefficient source S, dated") — never folded into the ratio numbers the tool otherwise reports.

---

## e) Phases

### Phase 0 — Foundations *(in progress)*

- ✅ Custom AST explorer using tree-sitter compiled to WASM
- ✅ `If` and `For` analyzers walking the tree
- Choose the output contract before writing more rules (see Phase 1)

*Note: the WASM tree-sitter choice already delivers what the old outline listed as a Phase 4 stretch goal. It runs in a TypeScript host with no Python bridge, and grammars for other languages are drop-in — the language-agnostic goal is now an incremental step rather than a rewrite.*

### Phase 1 — CLI analyzer

- `analyze <path>` plus `--selection <range>`, `--function <name>`, `--test <id>` to match the three snippet granularities.
- Implement rules 1–6 from the table. Start with the energy-first ones; the classic speed rules can wait.
- **Output: JSON Lines and SARIF.** SARIF is worth the small extra effort — it's the standard static-analysis interchange format, so GitHub code scanning and VS Code consume it without you writing an integration. That makes editor support nearly free later, and gives agents a documented contract rather than a bespoke one.
- Every finding carries: stable rule ID, location, tier, confidence, and (once Phase 3 lands) a ratio estimate with the coefficient-table version it came from.
- No coefficients yet — report shape and confidence only, and say so in the output.

### Phase 2 — Measurement harness

- ✅ Lenovo online, powercap verified
- ✅ Pinning script written, including idle baseline capture (`pin_baseline.sh`)
- ✅ RAPL vs Shelly wall-power cross-validation (`validate_shelly.py`, `validate_baseline.py`) — see "Whole-system reference: wall power, not battery discharge" above for the coverage-ratio sanity check and the quantization-noise fix
- ✅ `start`/`stop` counter bracketing (`rapl.py`), so a workload can be measured rather than only a window sampled
- ✅ Per-run harness (`harness.py`): one fixture, one measured window, one JSON row, interpreter recorded on every row, failures recorded as rows
- ✅ Benchmark corpus (`benchmarks/`): five flag/no-flag pairs plus a documented contract
- ✅ Whole path validated on hardware 2026-10-16 — pin, relax, verify-as-campaign-user, measure unprivileged, restore
- Campaign runner (interleaving, manifest, provenance, JSONL append) — not built; a throwaway loop produced the first result
- Idle subtraction — decided (analysis-time, per domain, never clamped) but not implemented
- Validate the harness against something known before trusting it — a `sleep` loop versus a spin loop should show a large, predictable difference.

### Phase 3 — Coefficients

- Before/after pairs for three to five patterns, across two or three input sizes. Measured variance (see "First measured result") puts this at ~500 runs and under half an hour of rig time, not the multi-hour campaign originally assumed.
- Emit ratios with confidence intervals into the coefficient file, tagged with the rig description.
- Wire the CLI to read it. Findings now carry magnitude, clearly labelled as estimated from that table.

### Phase 4 — Agent surface

- Expose the analyzer to code-generating agents: an MCP server wrapping `analyze`, or a documented stdin/stdout JSON contract.
- Design question worth thinking about explicitly: what does an agent do differently given this signal? "Rewrite and re-check" is a tighter loop than anything available to a human, and it's the most novel part of the project.

### Phase 5 — Stretch, in rough priority order

- Tier-2 confirmation pass with Cachegrind, wired to the same output schema.
- Second language grammar, to prove the tree-sitter language-agnostic claim.
- Editor integration via the SARIF output already produced in Phase 1.
- Cross-rig validation: do the ratios hold on a second machine?

---

## f) Validation and the research question

The most interesting output here may not be the tool. It's the answer to: **what fraction of energy-relevant patterns are statically detectable, and at what precision?**

That's measurable and finishable within a batch:

- Build a small labelled corpus — snippets with known pattern membership, drawn from real code where possible.
- Run the rules; report per-rule recall and false-positive rate.
- Keep a running false-positive log while dogfooding on your own code. Fastest way to learn where a heuristic is too blunt, and the raw material for the write-up.
- Sanity-check measured ratios against a second rig or against published figures where any exist.

Track A's validation is the measurement step — every number is one you generated and can explain. That remains the most defensible part of the project.

---

## g) Track B — Bias Advisor *(retained, deferred)*

Not the active focus. Kept here because the ideas are still good and worth returning to on Impossible Day–style days, where an open-ended, likely-to-fail exploration is the point.

The scoping insight stands: pick one concrete, checkable proxy rather than "detect bias" broadly — e.g. conditional branches with no corresponding test case (a proxy for confirmation-bias-driven under-testing), or repeated use of the same algorithm choice across a file when a more suitable one is already imported elsewhere (a proxy for anchoring). Bias is a decision-over-time phenomenon, so the more interesting version reads `git log`/`git diff` rather than the current snapshot.

Validation is weak by nature — there's no ground truth for "was this actually bias." Treat outputs as prompts for reflection and sanity-check against your own past commits. Set the expectation that this stays heuristic/nudge-quality rather than confidently detecting anything.

---

## References

### Measurement tooling

- EnergiBridge — cross-platform energy measurement (macOS, Windows, Linux). https://github.com/tdurieux/EnergiBridge · paper: https://arxiv.org/html/2312.13897v1
- pyEnergiBridge — Python wrapper. https://github.com/luiscruz/pyEnergiBridge
- JoularJX — per-method energy attribution for the JVM; the closest existing thing to snippet-level attribution, and its attribution model is worth studying or critiquing. https://github.com/joular/joularjx · docs: https://joular.github.io/joularjx/ref/how_it_works.html
- pyJoules — PowerAPI's Python library for code-snippet energy capture. https://github.com/powerapi-ng/pyJoules
- Scaphandre — energy metrology agent. https://github.com/hubblo-org/scaphandre
- Kepler — container/pod-level power estimation for Kubernetes. https://github.com/sustainable-computing-io/kepler
- Green Metrics Tool — Green Coding Solutions. https://docs.green-coding.io/ · https://github.com/green-coding-solutions

### Datasets and coefficients

- Teads — Estimating AWS EC2 instance power consumption. https://medium.com/teads-engineering/estimating-aws-ec2-instances-power-consumption-c9745e347959
- Teads — Building an AWS EC2 carbon emissions dataset. https://engineering.teads.com/2021/09/23/building-an-aws-ec2-carbon-emissions-dataset-2/
- Cloud Carbon Coefficients (derived from SPECpower results). https://github.com/cloud-carbon-footprint/cloud-carbon-coefficients · https://github.com/cloud-carbon-footprint/ccf-coefficients
- Boavizta environmental footprint data. https://github.com/Boavizta/environmental-footprint-data · https://boavizta.org/en/tools
- GitHub Green Software Directory. https://github.com/github/GreenSoftwareDirectory

### Background and prior claims

- Pereira, R. et al. "Energy Efficiency across Programming Languages." SLE 2017. https://greenlab.di.uminho.pt/wp-content/uploads/2017/09/paperSLE.pdf — read specifically *for* its methodological problems; most "language X is greener" claims trace back here.
- "Ranking Programming Languages by Energy Efficiency." https://haslab.github.io/SAFER/scp21.pdf
- "Ground-Truthing AI Energy Consumption: Validating CodeCarbon Against External Measurements." arXiv:2509.22092. https://arxiv.org/abs/2509.22092 — CodeCarbon underestimates real consumption by roughly 20%, since it can't see PSU, cooling, or peripheral draw.
- Green Software Foundation — Software Carbon Intensity (SCI). https://greensoftware.foundation/standards/sci/
- Green Software Foundation — Awesome Green Software. https://github.com/Green-Software-Foundation/awesome-green-software
- "Green Coding is a Matter of Code Quality" (ecoCode/SonarQube). https://greensoftware.foundation/articles/green-coding-is-a-matter-of-code-quality/

### Comparable tools

- oaklean — energy visualisation for JS/TS. https://oaklean.io
- Green Coder — VS Code Marketplace. https://marketplace.visualstudio.com/items?itemName=UnelmaPlatforms.green-coder
- GreenCode — VS Code Marketplace. https://marketplace.visualstudio.com/items?itemName=GreenCode.greencode

### Implementation

- Tree-sitter. https://tree-sitter.github.io/tree-sitter/
- Valgrind / Cachegrind manual. https://valgrind.org/docs/manual/cg-manual.html
- SARIF — community hub and tooling. https://sarifweb.azurewebsites.net/ · OASIS standard v2.1.0: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
- VS Code Language Server Extension Guide. https://code.visualstudio.com/api/language-extensions/language-server-extension-guide

### Track B (deferred)

- Chattopadhyay, S. et al. "A Tale from the Trenches: Cognitive Biases and Software Development." ICSE 2020. https://web.engr.oregonstate.edu/~sarmaa/wp-content/uploads/2020/08/icse20-chattopadhyay.pdf
- "Cognitive Biases in Software Engineering: A Systematic Mapping Study." arXiv:1707.03869. https://arxiv.org/pdf/1707.03869
- "Automatic Bias Detection in Source Code Review." arXiv:2504.18449. https://arxiv.org/html/2504.18449
- "Towards Debiasing Code Review Support." CHASE 2025 / arXiv:2407.01407. https://arxiv.org/abs/2407.01407
