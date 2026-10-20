#!/usr/bin/env python3
"""Read a rows JSONL and report the decoupling quotient. Read-only.

    python3 -s -m etdc.rig.decouple etdc/rig/runs/*.jsonl
    python3 -s -m etdc.rig.decouple runs/sweep.jsonl --json summary.json

    energy_ratio = E_flag / E_no-flag
    time_ratio   = T_flag / T_no-flag
    decoupling   = energy_ratio / time_ratio     # ~1.0 => a speed rule in a green hat

Rows are the artifact; this is a view over them. It opens nothing but the
files named, writes nothing unless asked for --json, and computes no number
that cannot be recomputed from the rows by someone who disagrees with the
choices here. The two choices worth disagreeing with are named constants at
the top: which domains count, and what counts as a calibrated window.

Reported raw AND idle-subtracted, side by side, because the subtraction
trades bias for noise -- P_idle's own uncertainty propagates into every
subtracted figure -- and the only honest way to present that trade is to show
both and let the gap be visible.

Three things it will not do, each because the alternative manufactures a
plausible-looking number:

  * clamp a negative E_active. That means the idle baseline is stale or the
    window was below the floor. Clamping to zero would hide exactly the
    condition that invalidates the row.
  * pool rows from different interpreters. PEP 709 inlined comprehensions but
    not generator expressions, so the asymmetry this rule rests on moved in a
    released minor version. Two versions are two experiments.
  * drop a failed row silently. Failures are counted and named; a reader who
    cannot see them cannot tell a clean campaign from a filtered one.
"""
import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys

# CPU-side total. core/uncore are subzones of package-0, so adding them to
# package-0 double-counts; psys is excluded because it measures BELOW
# package-0 + dram on rc-mw01, which is incoherent for a platform umbrella.
# Every domain is still written to every row -- a domain can be dropped from a
# sum later, but cannot be recovered if it was never captured -- so this is an
# analysis-time policy and changing it requires no re-measurement.
ENERGY_DOMAINS = ("package-0", "dram")

# Relative error is roughly (RAPL refresh period / window length), and a ratio
# of ratios compounds it. The same sum_list pair read 1.21 at a 71 ms window
# and 1.083 at ~1 s; the 1.21 was an artifact of the window, not a finding.
WINDOW_FLOOR_S = 1.0

# ...and the warning fires below this FRACTION of the floor, not below the
# floor itself. R is chosen to land the window near 1 s, so roughly half of a
# healthy sweep's windows sit a percent or two under it. Warning on those
# means warning on nearly every row, which trains the reader to skip the one
# note that mattered. The condition worth catching is the 71 ms window -- 0.07
# of the floor -- not the 0.99 s one.
WINDOW_WARN_FRACTION = 0.9

MEASURED_ARMS = ("flag", "no-flag")


def parse_stamp(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        return None


def load(paths):
    """Read every row, remembering which file and line each came from.

    A bad line is itself reported rather than skipped: a JSONL truncated by a
    killed sweep is a normal thing to find, and "107 rows, 1 unreadable" is
    actionable where "107 rows" is not.
    """
    rows, bad = [], []
    for path in paths:
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    bad.append(f"{path}:{lineno}: {exc}")
                    continue
                row["_src"] = f"{os.path.basename(path)}:{lineno}"
                rows.append(row)
    return rows, bad


def idle_power(idle_rows):
    """P_idle per domain from each idle window, with its timestamp.

    Returns a time-ordered list, not a mean. P_idle is a function of time --
    that is the whole reason the idle arm is in the rotation rather than
    captured once at pin time -- so each measured row is subtracted against
    the idle window nearest it, and a baseline that drifted mid-sweep shows up
    as a changing subtrahend instead of being averaged away.
    """
    samples = []
    for row in idle_rows:
        if row.get("status") != "ok" or not row.get("avg_power_w"):
            continue
        samples.append({
            "at": parse_stamp(row.get("started_at")),
            "power_w": row["avg_power_w"],
            "src": row.get("_src"),
        })
    samples.sort(key=lambda s: (s["at"] is None, s["at"]))
    return samples


def nearest_idle(samples, at):
    """The idle window closest in time to `at`, or None if there are none."""
    if not samples:
        return None
    if at is None:
        return samples[len(samples) // 2]
    dated = [s for s in samples if s["at"] is not None]
    if not dated:
        return samples[0]
    return min(dated, key=lambda s: abs((s["at"] - at).total_seconds()))


def energy_uj(row, domains):
    """Summed energy over the policy domains, plus which of them read zero.

    A domain reading exactly zero is reported rather than tolerated. `uncore`
    reads 0 on rc-mw01 by design, but a zero from `package-0` or `dram` means
    a counter is not advancing, and summing it in would quietly shrink the
    denominator of every ratio built from this row.
    """
    e = row.get("energy_uj") or {}
    total, dead, missing = 0.0, [], []
    for d in domains:
        if d not in e:
            missing.append(d)
            continue
        if e[d] == 0:
            dead.append(d)
        total += e[d]
    return total, dead, missing


def active_uj(row, domains, idle):
    """E_active = E_measured - P_idle * duration, per domain, then summed.

    Per domain and not on the total, because P_idle is per domain and the
    domains idle at different power. Subtracting matters rather than merely
    tidying: the idle term rides along with duration, so leaving it in pulls
    energy_ratio toward time_ratio -- toward a decoupling of 1.0. It biases
    the result toward finding nothing.

    Returns (uj, negatives). A negative is returned as-is and named. It means
    the measured window drew less than the floor being subtracted from it,
    i.e. the baseline is stale or the window was too short to be meaningful --
    a condition to surface, never to clamp.
    """
    e = row.get("energy_uj") or {}
    duration = row.get("duration_s")
    if idle is None or duration is None:
        return None, []
    total, negatives = 0.0, []
    for d in domains:
        if d not in e or d not in idle["power_w"]:
            return None, []
        active = e[d] - idle["power_w"][d] * duration * 1e6
        if active < 0:
            negatives.append(d)
        total += active
    return total, negatives


def runtime_key(row):
    """What must match for two rows to be comparable at all."""
    rt = row.get("runtime") or {}
    return (rt.get("version"), rt.get("implementation"),
            rt.get("free_threaded"), rt.get("executable"))


def make_ratio(flag, noflag, domains, idle_samples, window_floor):
    """One ratio from one adjacent flag/no-flag couple.

    Everything is per repetition. R may legitimately differ between arms --
    any_list's no-flag arm is ~57x faster, so a shared R would give the flag
    arm a ~57 s window -- and dividing by R is what makes that free: harness
    overhead enters as E/R = w + h regardless of R.
    """
    notes = []
    out = {
        "n": flag.get("n"),
        "seq": [flag.get("seq"), noflag.get("seq")],
        "src": [flag.get("_src"), noflag.get("_src")],
    }

    if runtime_key(flag) != runtime_key(noflag):
        notes.append("runtime mismatch between arms")
        out["notes"] = notes
        out["usable"] = False
        return out

    rf, rn = flag.get("r") or 0, noflag.get("r") or 0
    tf, tn = flag.get("duration_s"), noflag.get("duration_s")
    if not rf or not rn or not tf or not tn:
        notes.append("missing r or duration_s")
        out.update(notes=notes, usable=False)
        return out

    warn_below = window_floor * WINDOW_WARN_FRACTION
    for row, arm in ((flag, "flag"), (noflag, "no-flag")):
        if row["duration_s"] < warn_below:
            notes.append(f"{arm} window {row['duration_s']:.3f}s is under "
                         f"{warn_below:.2f}s ({window_floor:.1f}s floor) "
                         f"-- uncalibrated")

    out["time_ratio"] = (tf / rf) / (tn / rn)
    out["duration_s"] = [tf, tn]

    ef, dead_f, miss_f = energy_uj(flag, domains)
    en, dead_n, miss_n = energy_uj(noflag, domains)
    for label, dead, miss in (("flag", dead_f, miss_f), ("no-flag", dead_n, miss_n)):
        if dead:
            notes.append(f"{label}: domain(s) read zero: {', '.join(dead)}")
        if miss:
            notes.append(f"{label}: domain(s) absent from the row: {', '.join(miss)}")

    if en > 0 and ef > 0:
        out["energy_ratio_raw"] = (ef / rf) / (en / rn)
        out["decoupling_raw"] = out["energy_ratio_raw"] / out["time_ratio"]
    else:
        notes.append("no usable raw energy (a policy domain summed to zero)")

    # Each arm against the idle window nearest IT, not nearest the couple.
    # The two arms are adjacent, so this is nearly always the same window --
    # but when a sweep crosses an idle sample it is the correct thing to do,
    # and it costs nothing.
    idle_f = nearest_idle(idle_samples, parse_stamp(flag.get("started_at")))
    idle_n = nearest_idle(idle_samples, parse_stamp(noflag.get("started_at")))
    af, neg_f = active_uj(flag, domains, idle_f)
    an, neg_n = active_uj(noflag, domains, idle_n)
    if neg_f or neg_n:
        where = ", ".join(sorted(set(neg_f) | set(neg_n)))
        notes.append(f"negative E_active in {where} -- stale idle baseline or "
                     f"a window below the floor; NOT clamped")
    elif af is None or an is None:
        notes.append("no idle window available, or a domain missing from it")
    elif an > 0 and af > 0:
        out["energy_ratio_sub"] = (af / rf) / (an / rn)
        out["decoupling_sub"] = out["energy_ratio_sub"] / out["time_ratio"]
        out["idle_src"] = [idle_f.get("src"), idle_n.get("src")]
    else:
        notes.append("no usable subtracted energy")

    out["usable"] = "decoupling_raw" in out
    if notes:
        out["notes"] = notes
    return out


def couple(rows):
    """Pair adjacent flag/no-flag rows in sequence order.

    Adjacency is the point of interleaving: two windows minutes apart differ
    by drift as well as by shape, and a ratio cannot tell those apart. So this
    never reaches past an intervening row of the same arm -- an unmatched flag
    is dropped from the couples and counted, rather than paired with whatever
    no-flag turns up later.
    """
    couples, unmatched = [], 0
    pending = None
    for row in sorted(rows, key=lambda r: (r.get("seq") is None, r.get("seq"))):
        arm = row.get("arm")
        if arm == "flag":
            if pending is not None:
                unmatched += 1
            pending = row
        elif arm == "no-flag":
            if pending is None:
                unmatched += 1
            else:
                couples.append((pending, row))
                pending = None
    if pending is not None:
        unmatched += 1
    return couples, unmatched


def stats(values):
    """mean, stdev and SEM. SEM is the one that answers 'is this 1.0?'."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    mean = statistics.fmean(vals)
    stdev = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return {
        "n": len(vals),
        "mean": mean,
        "stdev": stdev,
        "sem": stdev / math.sqrt(len(vals)) if len(vals) > 1 else 0.0,
    }


def summarise(rows, domains=ENERGY_DOMAINS, window_floor=WINDOW_FLOOR_S):
    idle_rows = [r for r in rows if r.get("arm") == "idle"]
    measured = [r for r in rows if r.get("arm") in MEASURED_ARMS]
    problems = [r for r in rows if r.get("status") != "ok"]
    idle_samples = idle_power(idle_rows)

    ok = [r for r in measured if r.get("status") == "ok"]
    groups = {}
    for row in ok:
        groups.setdefault((row.get("pair"), row.get("n")), []).append(row)

    points, notes = [], []
    for (pair, n), group in sorted(
            groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0)):
        scope = f"{pair} N={n:,}" if isinstance(n, int) else f"{pair} N={n}"

        def note(text, seq=None):
            # kind is the text with its numbers removed, so instances of one
            # problem group together; scope keeps the pair and N OUT of that
            # stripping, because "6 negatives" and "6 negatives at N=200k and
            # N=600k" are different amounts of information and the second is
            # the one that says where to look.
            notes.append({
                "kind": re.sub(r"[\d][\d,.]*", "#", text),
                "scope": scope,
                "seq": seq,
                "detail": text,
            })

        couples, unmatched = couple(group)
        if unmatched:
            note(f"{unmatched} row(s) had no adjacent partner")
        ratios = [make_ratio(f, nf, domains, idle_samples, window_floor)
                  for f, nf in couples]
        for r in ratios:
            for text in r.get("notes", ()):
                note(text, seq=r["seq"])
        point = {
            "pair": pair,
            "n": n,
            "r": sorted({c[0].get("r") for c in couples} |
                        {c[1].get("r") for c in couples}),
            "couples": len(couples),
            "time_ratio": stats([r.get("time_ratio") for r in ratios]),
            "energy_ratio_raw": stats([r.get("energy_ratio_raw") for r in ratios]),
            "decoupling_raw": stats([r.get("decoupling_raw") for r in ratios]),
            "energy_ratio_sub": stats([r.get("energy_ratio_sub") for r in ratios]),
            "decoupling_sub": stats([r.get("decoupling_sub") for r in ratios]),
            "ratios": ratios,
        }
        points.append(point)

    return {
        "domains": list(domains),
        "window_floor_s": window_floor,
        "rows": len(rows),
        "measured_rows": len(measured),
        "idle_rows": len(idle_rows),
        "idle_usable": len(idle_samples),
        "problem_rows": [
            {"src": r.get("_src"), "status": r.get("status"),
             "arm": r.get("arm"), "n": r.get("n"),
             "error": r.get("error")}
            for r in problems
        ],
        # Per-domain stats AND every sample's own value. A mean over a
        # baseline that drifted mid-sweep is a number no row was subtracted
        # against -- the nearest-in-time logic deliberately never forms it --
        # so the spread has to stay visible here too.
        "idle_power_w": {
            d: stats([s["power_w"].get(d) for s in idle_samples])
            for d in domains
        } if idle_samples else {},
        "idle_samples": [
            {"at": s["at"].isoformat() if s["at"] else None,
             "src": s["src"],
             "power_w": {d: s["power_w"].get(d) for d in domains}}
            for s in idle_samples
        ],
        "points": points,
        "notes": notes,
    }


def fmt(s, places=3):
    if not s:
        return "—".rjust(15)
    return f"{s['mean']:.{places}f} ±{s['sem']:.{places}f}".rjust(15)


def report(summary, verbose=False):
    out = []
    d = ", ".join(summary["domains"])
    out.append(f"domains: {d}    window floor: {summary['window_floor_s']:.1f}s")
    out.append(f"rows: {summary['rows']}  measured: {summary['measured_rows']}  "
               f"idle: {summary['idle_rows']} ({summary['idle_usable']} usable)  "
               f"problem: {len(summary['problem_rows'])}")

    if summary["idle_power_w"]:
        parts, drifted = [], []
        for d, st in summary["idle_power_w"].items():
            if not st:
                continue
            vals = [s["power_w"].get(d) for s in summary["idle_samples"]
                    if s["power_w"].get(d) is not None]
            lo, hi = (min(vals), max(vals)) if vals else (None, None)
            # A mean is only a fair summary of a baseline that held still.
            # Report the range instead when it did not, and say so: every row
            # was subtracted against its NEAREST idle window, so a wide range
            # means different rows used materially different floors.
            if lo is not None and st["mean"] and (hi - lo) > 0.1 * st["mean"]:
                parts.append(f"{d} {lo:.3f}-{hi:.3f}")
                drifted.append(d)
            else:
                parts.append(f"{d} {st['mean']:.3f}")
        out.append(f"P_idle (W, {len(summary['idle_samples'])} window(s)): "
                   + "  ".join(parts))
        if drifted:
            out.append(f"  ! baseline moved during the sweep in "
                       f"{', '.join(drifted)} — rows used their nearest "
                       f"window, not this range")

    out.append("")
    head = (f"{'pair':<14}{'N':>9}{'R':>6}{'pairs':>7}"
            f"{'time_ratio':>16}{'energy raw':>16}{'DECOUP raw':>16}"
            f"{'energy sub':>16}{'DECOUP sub':>16}")
    out.append(head)
    out.append("-" * len(head))
    for p in summary["points"]:
        r = ",".join(str(x) for x in p["r"] if x is not None)
        out.append(
            f"{str(p['pair']):<14}{p['n'] or 0:>9,}{r:>6}{p['couples']:>7}"
            f"{fmt(p['time_ratio'])}{fmt(p['energy_ratio_raw'])}"
            f"{fmt(p['decoupling_raw'])}{fmt(p['energy_ratio_sub'])}"
            f"{fmt(p['decoupling_sub'])}")
    out.append("")
    out.append("mean ±SEM. A decoupling whose SEM does not reach 1.0 is the "
               "finding; ~1.0 is a speed rule in a green hat.")

    if summary["problem_rows"]:
        out.append("")
        out.append(f"{len(summary['problem_rows'])} problem row(s) — kept, not dropped:")
        for p in summary["problem_rows"][:10 if not verbose else None]:
            out.append(f"  {p['src']}  {p['status']}  arm={p['arm']} n={p['n']}  "
                       f"{(p.get('error') or '')[:90]}")
        if not verbose and len(summary["problem_rows"]) > 10:
            out.append(f"  ... {len(summary['problem_rows']) - 10} more (--verbose)")

    if summary["notes"]:
        out.append("")
        if verbose:
            out.append(f"{len(summary['notes'])} note(s):")
            for note in summary["notes"]:
                seq = f" seq={note['seq']}" if note["seq"] else ""
                out.append(f"  {note['scope']}{seq}: {note['detail']}")
        else:
            # Grouped by (kind, scope): one line per problem per measurement
            # point. Collapsing across scopes too would say "6 negatives"
            # without saying at which N, and the N is the actionable half.
            groups = {}
            for note in summary["notes"]:
                groups.setdefault((note["kind"], note["scope"]), []).append(note)
            out.append(f"{len(summary['notes'])} note(s), "
                       f"{len(groups)} distinct (kind, point):")
            for (kind, scope), inst in sorted(
                    groups.items(), key=lambda kv: (-len(kv[1]), kv[0][1])):
                out.append(f"  {len(inst):>4}x  {scope}: {inst[0]['detail']}")
            out.append("  (--verbose for every instance)")

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rows", nargs="+", help="one or more rows JSONL files")
    parser.add_argument("--domains", default=",".join(ENERGY_DOMAINS),
                        help="comma-separated domains to sum")
    parser.add_argument("--window-floor", type=float, default=WINDOW_FLOOR_S)
    parser.add_argument("--json", default=None,
                        help="write the full summary here, for the chart")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    rows, bad = load(args.rows)
    if bad:
        sys.stderr.write(f"{len(bad)} unreadable line(s):\n")
        for b in bad:
            sys.stderr.write(f"  {b}\n")
    if not rows:
        sys.stderr.write("no rows\n")
        return 2

    domains = tuple(d.strip() for d in args.domains.split(",") if d.strip())
    summary = summarise(rows, domains, args.window_floor)
    print(report(summary, args.verbose))

    if args.json:
        with open(args.json, "w") as f:
            json.dump(summary, f, indent=1, sort_keys=True)
            f.write("\n")
        sys.stderr.write(f"\nsummary -> {args.json}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
