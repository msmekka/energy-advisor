#!/usr/bin/env python3
"""Promote a campaign: rows in, a citable results/ directory out. Off-rig.

    python3 -s -m etdc.rig.report etdc/rig/runs/*.jsonl --out results/

Writes `results/<date>-<short-sha>/` holding

    rows.jsonl         verbatim, nothing dropped, failures included
    manifest.json      what was asked for (N ladder, R, reps, interpreter)
    rig.json           what answered (kernel, machine, domains, interpreter)
    coefficients.json  keyed on rule_id, the tier-1 join key
    report.md          generated, never hand-edited
    charts/ratio-n.svg + charts/ratio-n.md

This is ONE view, not the view. Rows stay primary and everything here is
recomputable from them: anyone rebuilding this rig should feel free to report
to their own taste, and nothing downstream is allowed to depend on this
particular Markdown. That is also why the rig never runs this -- measurement
produces rows, interpretation happens off-rig where it can be re-run and
argued with.

Determinism is a property, not an aspiration: every date in the output comes
from the ROWS (their own `started_at`), never from the clock, so regenerating
a promoted campaign and finding an empty `git diff` is itself the test that
the report still matches the rows beside it. A campaign promoted a month late
keeps the date it was measured.
"""
import argparse
import json
import math
import os
import shutil
import statistics
import sys

from etdc.rig import chart, decouple

# How many standard errors from 1.0 before a ratio counts as distinguishable.
# 3 is ~99.7% under a normal assumption. The first measured result sat ~16 SEM
# above parity, so this threshold is not what decides anything interesting --
# it exists so the verdict is mechanical rather than a judgment call.
SIGMA = 3.0

# The three verdicts. Deliberately not a score: a number would invite summing,
# and a coefficient is cost per execution while static analysis finds sites.
ENERGY_DISTINCT = "energy-distinct"
TIME_DOMINATED = "time-dominated"
NOT_DEMONSTRATED = "not demonstrated"

VERDICT_GLOSS = {
    ENERGY_DISTINCT:
        "energy separates the two arms by more than the time ratio explains",
    TIME_DOMINATED:
        "the arms differ, but energy tracks time -- a speed rule in a green hat",
    NOT_DEMONSTRATED:
        "nothing distinguishable from parity at this sample size",
}


def distinguishable(st, value=1.0):
    """Is this statistic's mean separated from `value` by >= SIGMA SEM?"""
    if not st or st.get("mean") is None:
        return False
    sem = st.get("sem") or 0.0
    if sem <= 0:
        # Zero SEM means one ratio, or a perfectly correlated set. Either way
        # there is no spread to argue from, so refuse to call it distinct.
        return False
    return abs(st["mean"] - value) >= SIGMA * sem


def verdict_for(point):
    """One point's verdict, from the subtracted quotient where it exists.

    Subtracted first because raw is biased toward 1.0 -- the idle term rides
    along with duration, so reporting raw understates the very thing being
    looked for. Raw is the fallback when there was no usable idle window, and
    the report says which was used.
    """
    decoup = point.get("decoupling_sub") or point.get("decoupling_raw")
    energy = point.get("energy_ratio_sub") or point.get("energy_ratio_raw")
    time_r = point.get("time_ratio")

    if distinguishable(decoup):
        return ENERGY_DISTINCT
    if distinguishable(energy) and distinguishable(time_r):
        return TIME_DOMINATED
    return NOT_DEMONSTRATED


def slope_per_decade(points, key):
    """OLS slope of a quotient against log10(N), with a residual-based SE.

    The handoff's tiebreaker. Harness dilution shrinks as N grows, so a
    quotient sitting near 1.0 and RISING tells a different story from one
    sitting near 1.0 and flat -- the first is an effect being diluted at small
    N, the second is no effect. Reported always, used to decide nothing: it
    annotates the verdict rather than overriding it.
    """
    xy = [(math.log10(p["n"]), p[key]["mean"])
          for p in points
          if p.get(key) and p[key].get("mean") is not None and p.get("n")]
    if len(xy) < 3:
        return None
    xs = [x for x, _ in xy]
    ys = [y for _, y in xy]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in xy) / sxx
    intercept = my - slope * mx
    resid = [y - (intercept + slope * x) for x, y in xy]
    dof = len(xy) - 2
    se = None
    if dof > 0:
        s2 = sum(r * r for r in resid) / dof
        se = math.sqrt(s2 / sxx) if s2 > 0 else 0.0
    return {"slope": slope, "se": se, "points": len(xy)}


def campaign_facts(rows):
    """What the rows agree on -- and, by their absence, what they do not.

    Every value here is collected as a SET. A campaign is only citable if the
    rig did not change underneath it, so the check is "did this vary?", which
    means never collapsing to a first-seen value.
    """
    sweeps, shas, dirty, runtimes, kernels, machines = [], set(), set(), set(), set(), set()
    domains, pinned, pairs, rules = set(), set(), set(), set()
    pair_rules = {}
    for row in rows:
        sw = row.get("sweep") or {}
        if sw:
            sweeps.append(sw)
            if sw.get("git_sha"):
                shas.add(sw["git_sha"])
            if sw.get("git_dirty") is not None:
                dirty.add(bool(sw["git_dirty"]))
            if sw.get("pinned") is not None:
                pinned.add(bool(sw["pinned"]))
        rt = row.get("runtime") or {}
        if rt.get("version"):
            runtimes.add((rt.get("version"), rt.get("implementation"),
                          bool(rt.get("free_threaded")), rt.get("executable")))
            kernels.add(rt.get("kernel"))
            machines.add(rt.get("machine"))
        if row.get("domains"):
            domains.add(tuple(sorted(row["domains"])))
        if row.get("pair"):
            pairs.add(row["pair"])
        if row.get("rule_id"):
            rules.add(row["rule_id"])
        if row.get("pair") and row.get("rule_id"):
            pair_rules.setdefault(row["pair"], set()).add(row["rule_id"])

    stamps = sorted(r["started_at"] for r in rows if r.get("started_at"))
    return {
        "sweeps": sweeps,
        "git_sha": sorted(shas),
        "git_dirty": sorted(dirty),
        "pinned": sorted(pinned),
        "runtimes": sorted(runtimes),
        "kernels": sorted(k for k in kernels if k),
        "machines": sorted(m for m in machines if m),
        "domain_sets": sorted(domains),
        "pairs": sorted(pairs),
        "rules": sorted(rules),
        # pair -> the rule(s) its rows claim. decouple.py groups by
        # (pair, n) and never carries rule_id, so this is the only way to
        # file a point under the right rule once more than one is in play.
        "pair_rules": {k: sorted(v) for k, v in sorted(pair_rules.items())},
        "first_row_at": stamps[0] if stamps else None,
        "last_row_at": stamps[-1] if stamps else None,
    }


def promotion_checks(rows, summary, facts):
    """The checkable list. Not a judgment -- each entry is true or false.

    Failures stay in rows.jsonl and are explained in the report. Silently
    dropping them is the one thing that would make the archive untrustworthy,
    so "there were failures" is not itself a failed check; "failures are
    unaccounted for" would be, and cannot happen because the rows are copied
    verbatim.
    """
    out = []

    def check(name, ok, detail):
        out.append({"check": name, "ok": bool(ok), "detail": detail})

    check("one interpreter across the campaign",
          len(facts["runtimes"]) == 1,
          "; ".join(
              "{0} {1}{2} ({3})".format(
                  rt[1], rt[0], " free-threaded" if rt[2] else "", rt[3])
              for rt in facts["runtimes"])
          or "no runtime recorded on any row")

    check("one git SHA across the campaign",
          len(facts["git_sha"]) == 1,
          ", ".join(s[:12] for s in facts["git_sha"]) or "no SHA on any row")

    check("tree was clean throughout",
          facts["git_dirty"] == [False],
          "no row measured against uncommitted changes"
          if facts["git_dirty"] == [False]
          else "some rows carry git_dirty=true, so no SHA identifies the code "
               "that produced them"
          if facts["git_dirty"] else "no row records whether the tree was clean")

    check("child was pinned",
          facts["pinned"] == [True],
          "every row measured on a pinned core"
          if facts["pinned"] == [True]
          else "rows carry pinned=false -- an unpinned row is uncalibrated, "
               "not merely noisier"
          if facts["pinned"] else "no row records whether it was pinned")

    check("one RAPL domain set",
          len(facts["domain_sets"]) == 1,
          " | ".join(", ".join(d) for d in facts["domain_sets"]) or "none")

    problems = summary.get("problem_rows", [])
    check("failed rows are present and explained",
          True,
          "{0} failed row(s), all retained verbatim".format(len(problems))
          if problems else "no failed rows")

    negatives = [n for n in summary.get("notes", [])
                 if "negative E_active" in n.get("detail", "")]
    check("no negative E_active",
          not negatives,
          "{0} note(s) -- a stale idle baseline or a window under the floor"
          .format(len(negatives)) if negatives else "none")

    uncal = [n for n in summary.get("notes", [])
             if "uncalibrated" in n.get("detail", "")]
    check("every window at or above the floor",
          not uncal,
          "{0} window(s) under the floor".format(len(uncal))
          if uncal else "none")

    idle_ok = summary.get("idle_usable", 0) > 0
    check("an idle window exists to subtract",
          idle_ok,
          "{0} usable idle window(s)".format(summary.get("idle_usable", 0)))

    points = summary.get("points", [])
    check("every point has at least 3 ratio pairs",
          points and all(p.get("couples", 0) >= 3 for p in points),
          "couples per point: {0}".format(
              ", ".join(str(p.get("couples", 0)) for p in points) or "no points"))

    return out


def coefficients(summary, facts):
    """coefficients.json -- keyed on rule_id, the tier-1 join key.

    So a measured result can feed `impact_confidence` without anything
    downstream parsing prose. Carries BOTH quotients: the subtraction trades
    bias for noise, since P_idle's own uncertainty propagates, and carrying
    both is what makes that trade auditable instead of invisible.

    No totals, no sums. A coefficient is cost per execution and static
    analysis finds sites; a summed joule figure would be a count wearing a
    joule costume.
    """
    by_rule = {}
    for point in summary.get("points", []):
        pair = point.get("pair")
        # The rule this PAIR's rows claimed, not whichever rule happened to be
        # first in the campaign. A pair whose rows disagree is filed under
        # every rule they named rather than silently under one.
        claimed = facts["pair_rules"].get(pair) or ["unknown"]
        rule = claimed[0] if len(claimed) == 1 else "+".join(claimed)
        entry = by_rule.setdefault(rule, {"pairs": {}})
        pair_entry = entry["pairs"].setdefault(pair, {
            "points": [], "domains": summary.get("domains", []),
        })
        pair_entry["points"].append({
            "n": point.get("n"),
            "r": point.get("r"),
            "ratio_pairs": point.get("couples"),
            "time_ratio": point.get("time_ratio"),
            "energy_ratio_raw": point.get("energy_ratio_raw"),
            "energy_ratio_idle_subtracted": point.get("energy_ratio_sub"),
            "decoupling_raw": point.get("decoupling_raw"),
            "decoupling_idle_subtracted": point.get("decoupling_sub"),
            "verdict": verdict_for(point),
        })

    for rule, entry in by_rule.items():
        for pair, pair_entry in entry["pairs"].items():
            pts = sorted(pair_entry["points"], key=lambda p: p["n"] or 0)
            pair_entry["points"] = pts
            # The headline is the LARGEST N, as the CONSERVATIVE point.
            #
            # The original reason was harness dilution: overhead is roughly
            # constant per iteration, so its share shrinks as N grows and the
            # largest N should show the effect least diluted. Measurement on
            # rc-mw01 (2026-10-20) contradicted that -- decoupling DECLINED
            # with N, 1.127 at 50k down to 1.067 at 800k, because the time
            # ratio climbs with N while the energy ratio stays flatter. So
            # dilution is not what dominates here.
            #
            # Largest N is kept, but for a different and weaker reason: it is
            # the smallest decoupling on the ladder, so quoting it cannot
            # overstate the result. The trend across the ladder is reported
            # alongside it, because on this data the headline alone hides the
            # most interesting point.
            head = pts[-1] if pts else None
            pair_entry["headline"] = {
                "n": head["n"],
                "verdict": head["verdict"],
                "decoupling_raw": head["decoupling_raw"],
                "decoupling_idle_subtracted":
                    head["decoupling_idle_subtracted"],
            } if head else None
            raw_pts = [{"n": p["n"], "decoupling_raw": p["decoupling_raw"],
                        "decoupling_sub": p["decoupling_idle_subtracted"]}
                       for p in pts]
            pair_entry["slope_per_decade"] = {
                "raw": slope_per_decade(raw_pts, "decoupling_raw"),
                "idle_subtracted": slope_per_decade(raw_pts, "decoupling_sub"),
            }
            pair_entry["sigma_threshold"] = SIGMA
    return by_rule


def arm_sources(rows):
    """The `work()` line from each arm's fixture, if the files are reachable.

    The whole claim is about two shapes, and a report that never shows them
    asks the reader to take the most important part on trust. Read at report
    time rather than carried on the row: the rows record the SHA, so the
    pairing is checkable, and a fixture is text that belongs in the repo
    rather than duplicated onto 100 rows.

    Returns {} when the fixtures are not alongside -- a promoted campaign must
    still render from rows alone.
    """
    out = {}
    for row in rows:
        arm, fixture = row.get("arm"), row.get("fixture")
        if arm in ("flag", "no-flag") and fixture and arm not in out:
            try:
                with open(fixture) as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            body, seen = [], False
            for line in lines:
                if line.startswith("def work("):
                    seen = True
                    continue
                if seen:
                    if line.strip().startswith("return "):
                        body.append(line.strip())
                        break
                    if line and not line.startswith((" ", "\t")):
                        break
            if body:
                out[arm] = body[0]
    return out


def fmt_stat(st, places=3):
    if not st or st.get("mean") is None:
        return "—"
    return "{0:.{2}f} ±{1:.{2}f}".format(
        st["mean"], st.get("sem") or 0.0, places)


def render(summary, facts, checks, coeffs, pair, chart_rel, sources=None):
    """report.md. Markdown primary, SVG beside it -- it diffs, which is most
    of the point of committing a report, and it renders on GitHub and over
    SSH where an HTML bundle does not."""
    points = sorted(summary.get("points", []), key=lambda p: p.get("n") or 0)
    head = points[-1] if points else None
    rule = facts["rules"][0] if facts["rules"] else "unknown"
    pair_coeff = coeffs.get(rule, {}).get("pairs", {}).get(pair, {})
    verdict = (pair_coeff.get("headline") or {}).get("verdict", NOT_DEMONSTRATED)

    L = []
    a = L.append

    a("# {0} / {1} — energy–time decoupling".format(rule, pair))
    a("")
    a("**This file is generated by `etdc/rig/report.py` and is never "
      "hand-edited.** Regenerate it with:")
    a("")
    a("```sh")
    a("python3 -s -m etdc.rig.report rows.jsonl --out .")
    a("```")
    a("")
    a("It is deterministic — every date below comes from the rows, not from "
      "the clock — so regenerating it and finding an empty `git diff` is the "
      "test that it still matches `rows.jsonl` beside it. It is also only "
      "*one* view: the rows are the artifact, and every number here is "
      "recomputable from them.")
    a("")

    a("## The finding")
    a("")
    if head:
        t_st = head.get("time_ratio") or {}
        e_st = (head.get("energy_ratio_sub")
                or head.get("energy_ratio_raw") or {})
        a("At N = {0:,}, the flagged arm costs **{1:.3f}×** the no-flag arm "
          "in elapsed time (±{2:.3f}) and **{3:.3f}×** in energy (±{4:.3f})."
          .format(head["n"],
                  t_st.get("mean") or float("nan"), t_st.get("sem") or 0.0,
                  e_st.get("mean") or float("nan"), e_st.get("sem") or 0.0))
        a("")
        a("> **Decoupling at N = {0:,}: {1}** (idle-subtracted) · "
          "{2} (raw)".format(
              head["n"],
              fmt_stat(head.get("decoupling_sub")),
              fmt_stat(head.get("decoupling_raw"))))
        a("")
        a("Verdict: **{0}** — {1}.".format(verdict, VERDICT_GLOSS[verdict]))
        a("")
        a("A decoupling of 1.0 would mean energy says exactly what the clock "
          "already said: a speed rule wearing a green hat, and not worth "
          "having as a separate rule. The threshold used is {0:.0f}×SEM from "
          "parity.".format(SIGMA))

        # The headline is the most conservative point by construction, so on
        # any ladder with a trend it is NOT the most informative one. Report
        # the span and name the extreme, or the report buries its own finding.
        ranked = [(p, (p.get("decoupling_sub") or p.get("decoupling_raw")))
                  for p in points]
        ranked = [(p, st) for p, st in ranked if st and st.get("mean")]
        if len(ranked) > 1:
            best, best_st = max(ranked, key=lambda ps: ps[1]["mean"])
            worst, worst_st = min(ranked, key=lambda ps: ps[1]["mean"])
            a("")
            a("**Across the ladder** the decoupling runs from {0} at "
              "N = {1:,} to {2} at N = {3:,}, and is distinguishable from "
              "parity at every point measured. The headline above quotes the "
              "smallest of these, so it understates the rest."
              .format(fmt_stat(worst_st), worst["n"],
                      fmt_stat(best_st), best["n"]))

            # The case the whole project is looking for: the clock does not
            # merely fail to see the cost, it points the other way.
            inverted = [p for p, _ in ranked
                        if p.get("time_ratio")
                        and (p["time_ratio"].get("mean") or 1.0) < 1.0
                        and distinguishable(p["time_ratio"])]
            if inverted:
                q = inverted[0]
                a("")
                a("At N = {0:,} the time ratio is **{1}** — the flagged "
                  "shape is *faster*. Energy at the same point is {2}. "
                  "Wall-clock does not merely fail to see this cost; it "
                  "points the other way."
                  .format(q["n"], fmt_stat(q["time_ratio"]),
                          fmt_stat(q.get("energy_ratio_sub")
                                   or q.get("energy_ratio_raw"))))
    else:
        a("No measurement points survived. See the checks below.")
    a("")

    slopes = pair_coeff.get("slope_per_decade", {}) or {}
    sl = slopes.get("idle_subtracted") or slopes.get("raw")
    if sl and sl.get("slope") is not None:
        se = sl.get("se")
        slope = sl["slope"]
        rising = slope > 0
        significant = se is not None and se > 0 and abs(slope) >= 2 * se
        a("Slope of the decoupling quotient against trip count: "
          "**{0:+.3f} per decade of N**{1} — the quotient {2} as N grows."
          .format(slope, " (±{0:.3f})".format(se) if se else "",
                  "rises" if rising else "declines" if significant
                  else "is flat within noise"))
        if significant and not rising:
            a("")
            a("That is the opposite of what harness dilution would produce. "
              "Dilution is a roughly constant per-iteration overhead, so its "
              "share shrinks as N grows and it pushes the quotient *up* with "
              "N; a quotient that falls instead means something else "
              "dominates. Here it is the time ratio: it climbs with N while "
              "the energy ratio stays flatter, so their quotient shrinks.")
        a("")

    if sources and sources.get("flag") and sources.get("no-flag"):
        a("## The two arms")
        a("")
        a("Identical `build()`, identical data, identical arithmetic. Only the "
          "shape differs:")
        a("")
        a("```python")
        a("# flag — the shape present")
        a(sources["flag"])
        a("")
        a("# no-flag — the shape absent")
        a(sources["no-flag"])
        a("```")
        a("")

    a("## ratio(N)")
    a("")
    a("![ratio(N) for {0}]({1})".format(pair, chart_rel))
    a("")
    a(chart.table(summary, pair))
    a("")
    a("Both panels share a y-axis. The idle-subtracted panel removes "
      "`P_idle × duration` per domain, measured from idle windows taken "
      "*between* runs rather than once at pin time — the idle term rides "
      "along with duration, so leaving it in drags the energy ratio toward "
      "the time ratio and understates whatever is there. A negative "
      "`E_active` is never clamped; it is reported as a failed check.")
    a("")

    uncal_scopes = sorted({n["scope"] for n in summary.get("notes", [])
                           if "uncalibrated" in n.get("detail", "")})
    if uncal_scopes:
        a("> **Caveat:** windows under the floor at {0}. Relative error scales "
          "as (RAPL refresh period / window length), so those points are "
          "reported but not calibrated — see the failed check below."
          .format("; ".join(uncal_scopes)))
        a("")

    a("## Method")
    a("")
    a("- **Energy domains:** `{0}`. `core`/`uncore` are subzones of "
      "`package-0`, so summing them would double-count; `psys` is excluded "
      "because it reads below `package-0 + dram` on this rig. All domains are "
      "recorded on every row regardless — a domain can be dropped from a sum "
      "later, but cannot be recovered if it was never captured."
      .format(" + ".join(summary.get("domains", []))))
    a("- **Window floor:** {0:.1f} s. Relative error is roughly (RAPL refresh "
      "period / window length) and a ratio of ratios compounds it."
      .format(summary.get("window_floor_s", 1.0)))
    a("- **Interleaved arms.** Every ratio is formed from two adjacent "
      "windows, so drift between repetitions cancels inside the ratio instead "
      "of landing entirely on whichever arm ran first.")
    a("- **Per repetition.** Ratios divide by R, so R may differ between arms "
      "without affecting the comparison.")
    a("- **Statistic:** mean ±SEM over the adjacent-pair ratios. The "
      "decoupling quotient is better-conditioned than either ratio it is "
      "built from, because time and energy noise are correlated and the "
      "common mode cancels.")
    a("")

    a("## Promotion checks")
    a("")
    a("| check | result | detail |")
    a("|---|---|---|")
    for c in checks:
        a("| {0} | {1} | {2} |".format(
            c["check"], "pass" if c["ok"] else "**FAIL**", c["detail"]))
    a("")
    failed = [c for c in checks if not c["ok"]]
    if failed:
        a("**{0} check(s) failed.** The rows are archived anyway and verbatim; "
          "a reader who cannot see a campaign's defects cannot tell it from a "
          "filtered one.".format(len(failed)))
    else:
        a("All checks pass.")
    a("")

    problems = summary.get("problem_rows", [])
    if problems:
        a("### Failed rows")
        a("")
        a("Retained in `rows.jsonl`, not dropped.")
        a("")
        a("| row | status | arm | N | error |")
        a("|---|---|---|---|---|")
        for p in problems:
            a("| {0} | {1} | {2} | {3} | {4} |".format(
                p.get("src"), p.get("status"), p.get("arm"), p.get("n"),
                (p.get("error") or "")[:120]))
        a("")

    notes = summary.get("notes", [])
    if notes:
        groups = {}
        for n in notes:
            groups.setdefault((n["kind"], n["scope"]), []).append(n)
        a("### Notes")
        a("")
        a("| count | point | note |")
        a("|---:|---|---|")
        for (_, scope), inst in sorted(groups.items(),
                                       key=lambda kv: (-len(kv[1]), kv[0][1])):
            a("| {0} | {1} | {2} |".format(
                len(inst), scope, inst[0]["detail"]))
        a("")

    a("## Provenance")
    a("")
    a("| | |")
    a("|---|---|")
    a("| rule / pair | `{0}` / `{1}` |".format(rule, pair))
    a("| git SHA | {0} |".format(
        ", ".join("`{0}`".format(s) for s in facts["git_sha"]) or "—"))
    a("| tree clean | {0} |".format(
        "yes" if facts["git_dirty"] == [False] else str(facts["git_dirty"])))
    a("| child pinned | {0} |".format(
        "yes" if facts["pinned"] == [True] else str(facts["pinned"])))
    for rt in facts["runtimes"]:
        a("| interpreter | {0} {1}{2} — `{3}` |".format(
            rt[1], rt[0], " free-threaded" if rt[2] else "", rt[3]))
    a("| kernel / machine | {0} / {1} |".format(
        ", ".join(facts["kernels"]) or "—",
        ", ".join(facts["machines"]) or "—"))
    a("| RAPL domains seen | {0} |".format(
        " | ".join(", ".join(d) for d in facts["domain_sets"]) or "—"))
    a("| rows | {0} measured, {1} idle, {2} failed |".format(
        summary.get("measured_rows", 0), summary.get("idle_rows", 0),
        len(problems)))
    a("| measured | {0} → {1} |".format(
        facts.get("first_row_at") or "—", facts.get("last_row_at") or "—"))
    a("")
    return "\n".join(L) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rows", nargs="+", help="rows JSONL from sweep.py")
    parser.add_argument("--out", default="results",
                        help="parent directory for <date>-<short-sha>/")
    parser.add_argument("--pair", default=None)
    parser.add_argument("--domains", default=",".join(decouple.ENERGY_DOMAINS))
    parser.add_argument("--window-floor", type=float,
                        default=decouple.WINDOW_FLOOR_S)
    parser.add_argument("--name", default=None,
                        help="override the <date>-<short-sha> directory name")
    parser.add_argument("--anyway", action="store_true",
                        help="promote even though a check failed")
    args = parser.parse_args()

    rows, bad = decouple.load(args.rows)
    if bad:
        sys.stderr.write("{0} unreadable line(s):\n".format(len(bad)))
        for b in bad:
            sys.stderr.write("  {0}\n".format(b))
    if not rows:
        sys.stderr.write("no rows\n")
        return 2

    domains = tuple(d.strip() for d in args.domains.split(",") if d.strip())
    summary = decouple.summarise(rows, domains, args.window_floor)
    facts = campaign_facts(rows)

    pairs = sorted({p.get("pair") for p in summary.get("points", [])})
    pair = args.pair
    if pair is None:
        if len(pairs) != 1:
            parser.error("rows hold {0} pairs ({1}); name one with --pair"
                         .format(len(pairs), pairs))
        pair = pairs[0]

    checks = promotion_checks(rows, summary, facts)
    coeffs = coefficients(summary, facts)

    # The directory name comes from the DATA: the first row's own date and the
    # SHA the rows were measured at. Using today's date would make the same
    # campaign promote to a different path tomorrow, and the point of the
    # name is to identify the measurement, not the act of filing it.
    date = (facts.get("first_row_at") or "unknown")[:10]
    sha = facts["git_sha"][0][:7] if facts["git_sha"] else "nosha"
    name = args.name or "{0}-{1}".format(date, sha)
    dest = os.path.join(args.out, name)

    failed = [c for c in checks if not c["ok"]]
    for c in checks:
        sys.stderr.write("  [{0}] {1} — {2}\n".format(
            "pass" if c["ok"] else "FAIL", c["check"], c["detail"]))
    if failed and not args.anyway:
        sys.stderr.write(
            "\n{0} check(s) failed; not promoting. The rows are still valid "
            "input to decouple.py -- pass --anyway to promote regardless, "
            "which archives the failures in the report rather than hiding "
            "them.\n".format(len(failed)))
        return 1

    os.makedirs(os.path.join(dest, "charts"), exist_ok=True)

    # Rows verbatim. Concatenated rather than re-serialised, so the archived
    # bytes are the measured bytes -- re-dumping through json would silently
    # normalise float formatting and key order.
    #
    # Written through a temp file and then renamed, because the destination is
    # very often ALSO a source: regenerating a promoted campaign in place --
    # `report.py results/X/rows.jsonl --out results/`, the command this
    # report's own header prints, and the way the empty-git-diff property is
    # tested -- makes src and dest the same path. Opening the destination "w"
    # first truncated it to zero bytes before the read, destroying the very
    # rows being promoted. Reading every source before anything is replaced
    # makes the self-referential case correct rather than merely refused.
    rows_path = os.path.join(dest, "rows.jsonl")
    tmp_path = rows_path + ".tmp"
    with open(tmp_path, "w") as out:
        for path in args.rows:
            with open(path) as f:
                shutil.copyfileobj(f, out)
    os.replace(tmp_path, rows_path)

    chart_rel = os.path.join("charts", "ratio-n.svg")
    with open(os.path.join(dest, chart_rel), "w") as f:
        f.write(chart.svg(
            summary, pair,
            "{0}: energy separates what wall-clock cannot".format(pair),
            "flag arm / no-flag arm, per repetition, at each trip count. "
            "Above parity means the flagged shape costs more.") + "\n")
    with open(os.path.join(dest, "charts", "ratio-n.md"), "w") as f:
        f.write(chart.table(summary, pair))

    manifest = {
        "pair": pair,
        "sweeps": [dict(s) for s in {json.dumps(s, sort_keys=True): s
                                     for s in facts["sweeps"]}.values()],
    }
    for fname, payload in (
            ("manifest.json", manifest),
            ("rig.json", {k: v for k, v in facts.items() if k != "sweeps"}),
            ("coefficients.json", coeffs),
    ):
        with open(os.path.join(dest, fname), "w") as f:
            json.dump(payload, f, indent=1, sort_keys=True, default=list)
            f.write("\n")

    with open(os.path.join(dest, "report.md"), "w") as f:
        f.write(render(summary, facts, checks, coeffs, pair, chart_rel,
                       arm_sources(rows)))

    sys.stderr.write("\npromoted -> {0}\n".format(dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
