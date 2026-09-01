# IDE Extension for Efficiency & Bias Coding Feedback — Review & Learning-Project Outline

*Revised framing: This was the original plan. We are now using [the energy-aware code analysis plan][#./energy-aware-code-analysis-plan.md] plan

## a) Review of the idea

**As a learning project, this is a strong pick.** It touches several distinct, transferable skills at once: static analysis / AST parsing, IDE extension APIs, empirical performance measurement, and (for the bias track) applying recent, still-unsettled research to a working tool. Treating efficiency and bias as two separate modules — which you've now clarified is the intent — is the right call technically, since they need almost entirely different techniques and have no natural shared signal. Building them as two independent tracks that happen to ship in the same extension is more tractable than one merged feature.

**The efficiency module's core learning value is in the measurement, not the linting.** Flagging "this loop is O(n²)" is a solved, well-trodden static-analysis problem. The genuinely interesting and educational part is instrumenting real energy/time/memory measurement yourself (e.g., with CodeCarbon or simple wall-clock/RAPL-based profiling) and building your own before/after dataset — that's where you actually learn how energy measurement works, versus just re-implementing a rule engine. Be aware going in that write-time static analysis cannot itself measure energy or emissions: consumption depends on runtime, hardware, input scale, and grid carbon intensity, none of which exist yet at the moment you're typing. The Pereira et al. benchmark that most "language X is more efficient" claims trace back to measured whole-program runs, not snippets (Pereira et al., SLE 2017). CodeCarbon itself is known to underestimate real consumption by roughly 20% since it can't see PSU, cooling, or peripheral draw (arXiv 2509.22092). None of this blocks the project — it just means the honest design is "static rule, backed by an offline measurement you ran yourself," not a live carbon counter in the editor.

**The bias module is the more open-ended, research-y half — good for learning, harder to get "right."** Even scoped to cognitive/decision bias (not algorithmic fairness), the detection techniques are recent and still experimental: eye-tracking and interaction-log approaches show up in the literature (arXiv 2504.18449), but pure static-analysis signals for cognitive bias are thin. That's fine for a learning project — it means you're genuinely exploring, not implementing a known recipe — but set the expectation that this module will likely stay heuristic/nudge-quality (e.g., "you've reused this same pattern 4 times without checking alternatives," or "this function has no test for the branch it just added") rather than confidently "detecting bias."

**Practical suggestion given the two goals ("can I build it" / "how do these things work"):** start with the smallest possible end-to-end slice of each track before adding any architectural sophistication (LSP servers, multi-language support, Rust). A single-file, single-language, rule-of-two extension that actually runs in VS Code teaches you the IDE integration; a hand-built benchmark of 5–10 code pairs teaches you real energy measurement. Both are more valuable early wins than a "proper" cross-editor architecture you don't finish.

## b) Project outline

Structured as two independent tracks that share only the extension shell. Each track is phased from "smallest thing that works" to "more capable," so you can stop at whichever phase satisfies the "can I build it / how does it work" goal.

### Phase 0 — Shared setup
- Pick one language to target first (recommend Python or JS/TS — both have simple ASTs to work with and you'll be able to reuse the parser for both tracks).
- Scaffold a single VS Code extension (TypeScript, using `yo code` / the official Extension Generator) with two independent diagnostic providers registered in it — one per track. No LSP server yet; VS Code's built-in Diagnostics API is enough for a single-editor learning build.

### Track A — Efficiency Advisor
1. **Smallest slice**: hand-write 5–10 rules as direct AST pattern matches (e.g., using Python's built-in `ast` module, or `@typescript-eslint/parser` for JS/TS) for well-known inefficiencies — nested loops that could be a set/dict lookup, string concatenation in a loop, repeated recomputation of a loop-invariant value, N+1-style repeated calls. Surface as VS Code Diagnostics (squiggle + hover message). This alone proves out the "IDE extension that reads code and gives feedback" mechanic.
2. **Real measurement layer**: for each rule, write the "before" and "after" version of the pattern and actually measure them yourself — `timeit`/wall-clock for speed, CodeCarbon (Python) for energy/CO2 estimates on your own machine. Store the results in a small JSON/YAML file the extension reads from, and show the measured numbers (yours, not invented) in the hover message. This is the step that teaches you how energy profiling actually works, and it's the most defensible part of the project since every number is one you generated and can explain.
3. **Optional stretch**: reproduce a slice of the Pereira et al. methodology (Computer Language Benchmark Game–style fixed problems, run across a couple of language implementations) to compare against published numbers — good check on whether your own measurements are sane.
4. **Optional stretch**: rebuild the analysis core in Rust with Tree-sitter and expose it as an LSP server, to get the cross-editor + "how does an LSP actually work" learning goal. Ruff and Biome are the reference implementations worth reading for this.

### Track B — Bias Advisor
1. **Smallest slice**: pick one concrete, checkable cognitive-bias proxy rather than "detect bias" broadly — e.g., flag functions with conditional branches that have no corresponding test case (a proxy for confirmation-bias-driven under-testing), or flag repeated use of the same algorithm/library choice across a file when a more suitable one is already imported elsewhere in the project (a proxy for anchoring on the first solution). These are concrete, implementable AST/heuristic checks, unlike "bias" in the abstract.
2. **Add history context**: bias is a decision-over-time phenomenon, so the more interesting version of this track reads `git log`/`git diff` for a file (via `simple-git` or shelling out to `git`) rather than just the current snapshot — e.g., "you've made this same fix 3 times in the last 10 commits without addressing the root cause."
3. **Optional stretch**: read the automatic-bias-detection literature (arXiv 2504.18449) for ideas beyond static heuristics, and consider an LLM-based pass that explains *why* a flagged pattern might reflect a bias, clearly labeled as a generated hypothesis, not a finding.

### Validation (both tracks)
- For Track A, the validation *is* the measurement step — you have real numbers to check.
- For Track B, validation is weaker by nature (there's no ground truth for "was this actually bias"); treat outputs as prompts for reflection, and sanity-check rules against your own past commits to see if they flag things you'd agree with in hindsight.
- Keep a running log of false positives you notice while dogfooding it on your own code — the fastest way to learn where a heuristic is too blunt.

### Suggested language choices
- **Extension shell: TypeScript** — required by the VS Code Extension API, and keeps Phase 0–1 fast to get running.
- **Track A analysis, phase 1–2: Python** (via its own `ast` module) or **TypeScript** (via `@typescript-eslint/parser`) — match whichever language you're targeting first; Python also gives you direct access to CodeCarbon for the measurement step without a language bridge.
- **Track A, stretch phase 4: Rust** with Tree-sitter, if you want the LSP/performance learning track — this is a legitimately different, harder project phase, worth treating as its own milestone.
- **Track B**: TypeScript/Python is fine throughout; the interesting part is heuristic design, not raw performance, so there's little reason to reach for Rust here.

---

## References

- Pereira, R. et al. "Energy Efficiency across Programming Languages: How Do Energy, Time, and Memory Relate?" SLE 2017. https://greenlab.di.uminho.pt/wp-content/uploads/2017/09/paperSLE.pdf
- "Ranking Programming Languages by Energy Efficiency." https://haslab.github.io/SAFER/scp21.pdf
- Green Software Foundation — Software Carbon Intensity (SCI) standard. https://greensoftware.foundation/standards/sci/
- Green Software Foundation — Carbon Aware SDK (GitHub). https://github.com/Green-Software-Foundation/carbon-aware-sdk
- Green Software Foundation — Awesome Green Software (tool list). https://github.com/Green-Software-Foundation/awesome-green-software
- "Ground-Truthing AI Energy Consumption: Validating CodeCarbon Against External Measurements." arXiv:2509.22092. https://arxiv.org/abs/2509.22092
- "Automatic Bias Detection in Source Code Review." arXiv:2504.18449. https://arxiv.org/html/2504.18449
- Chattopadhyay, S. et al. "A Tale from the Trenches: Cognitive Biases and Software Development." ICSE 2020. https://web.engr.oregonstate.edu/~sarmaa/wp-content/uploads/2020/08/icse20-chattopadhyay.pdf
- "Cognitive Biases in Software Engineering: A Systematic Mapping Study." arXiv:1707.03869. https://arxiv.org/pdf/1707.03869
- "Towards Debiasing Code Review Support." CHASE 2025 / arXiv:2407.01407. https://arxiv.org/abs/2407.01407
- Green Coder — VS Code Marketplace. https://marketplace.visualstudio.com/items?itemName=UnelmaPlatforms.green-coder
- GreenCode — VS Code Marketplace. https://marketplace.visualstudio.com/items?itemName=GreenCode.greencode
- "Green Coding is a Matter of Code Quality" (ecoCode/SonarQube). Green Software Foundation. https://greensoftware.foundation/articles/green-coding-is-a-matter-of-code-quality/
- oaklean — energy visualization for JS/TS. https://oaklean.io
- VS Code Language Server Extension Guide. https://code.visualstudio.com/api/language-extensions/language-server-extension-guide
- Tree-sitter (parser generator) overview. https://en.wikipedia.org/wiki/Tree-sitter_(parser_generator)
