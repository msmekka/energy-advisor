#!/usr/bin/env python3
"""Sweep one benchmark pair across trip counts. The parent half of a run.

    taskset -c 0 python3 -s -m etdc.rig.sweep \
        --rule eager-materialization --pair sum_list \
        --out etdc/rig/runs/$(date -u +%Y%m%dT%H%M%SZ)-sum_list.jsonl

Not the campaign runner. This drives ONE pair over the N ladder to produce
`ratio(N)`, which is the chart the report is built around. The real runner
adds a manifest, the remaining pairs, the null arm and rig provenance; none of
that is needed to answer "does the decoupling hold as N grows?", and the
answer to that is what makes a result readable as mechanism rather than as a
single number.

What this file owns, and the child does not:

  ordering     Arms are interleaved (flag, no-flag, flag, ...), never blocked
               in time, so a ratio is formed from two windows that are
               adjacent rather than hours apart. Drift between reps cancels
               inside each ratio instead of landing entirely on whichever arm
               ran first.
  R selection  The window floor is ~1 s and N is the x-axis, so R has to
               absorb N (see WINDOW_WORK).
  the idle arm Measured here, in the gap between children, because the floor
               worth subtracting is the floor under campaign conditions.
  provenance   seq, started_at, git SHA and dirtiness -- facts about the run,
               which only the thing doing the running knows.

Rows are appended one line at a time and flushed, so a sweep killed halfway
leaves every row it already measured. Nothing is aggregated here: the JSONL is
the artifact, and decouple.py is a reader over it.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

from etdc.rig import rapl

# R=72 held a ~1 s window at N=200,000 on rc-mw01 (2026-10-16), so a window is
# set by the product R*N -- element-iterations, not repetitions. Deriving R
# from one measured constant keeps the window near-constant across the ladder,
# which matters because relative error is roughly (RAPL refresh period /
# window) and a ratio of ratios compounds it.
#
# The alternative is to probe each (arm, N) and scale, which is more robust and
# more moving parts. It earns its cost on a pair whose arms differ wildly in
# speed -- any_list's no-flag arm is ~57x faster -- but not on a pair whose
# arms are within a couple of percent on time. Per-arm R is legitimate when
# needed: ratios are formed from E/R, and harness overhead enters as
# E/R = w + h regardless of R.
#
# This constant is specific to rc-mw01. It is now only a SEED for the probe
# below, not the thing that sets R.
#
# Why it stopped being enough (measured 2026-10-20, results/2026-10-20-95ce499):
# R*N assumes cost per element is constant across N. It is not. Per-element
# cost rose from 50.8 ns at N=50,000 to 76.4 ns at N=800,000 as the working
# set outgrew cache -- the very memory effect this rule is about. Calibrated
# at 200,000 the constant nails that point (0.989 s) and undershoots badly at
# the ends: 0.732 s at 50,000, under the 1.0 s floor. The most interesting
# point on that ladder was also the uncalibrated one.
WINDOW_WORK = 72 * 200_000

# What a calibrated window aims for. Slightly above the 1.0 s floor rather than
# at it: R is an integer and the window jitters, so targeting the floor exactly
# puts about half the windows under it.
TARGET_WINDOW_S = 1.15

# The probe runs at this fraction of the seed R -- long enough to measure a
# per-repetition cost, short enough to be nearly free. Ten probes (five N, two
# arms) cost a couple of seconds against a sweep of ~2 minutes.
PROBE_FRACTION = 0.15

# Weighted toward large N deliberately. Interpreter dispatch overhead is
# roughly constant per iteration, so its share shrinks as N grows, while the
# memory traffic this rule is about scales with N. At small N you are
# measuring the interpreter; the ladder is what separates the two, because an
# artifact of dispatch and a real memory effect have different slopes.
#
# 200,000 is on the ladder on purpose: it is the point already measured at
# decoupling 1.083, so the sweep re-measures a known value. If it does not
# come back, the sweep is wrong and the rest of the ladder is not evidence.
DEFAULT_LADDER = (50_000, 100_000, 200_000, 400_000, 800_000)

# One idle window per this many child runs, plus one before the first run.
# ~5% of sweep time. Cheap because it is the difference between reporting raw
# ratios and reporting idle-subtracted ones: the idle term rides along with
# duration, so leaving it in drags energy_ratio toward time_ratio -- toward a
# decoupling of 1.0, i.e. toward understating whatever is actually there.
IDLE_EVERY = 20

# The child is pinned here, the parent on the other core. rc-mw01 has 2 cores
# once SMT is off (4 logical CPUs, siblings (0,2) and (1,3), leaving cpu0 and
# cpu1 online), so there is no third core and the parent shares core 0 with
# the OS. An unpinned child is not a cheaper measurement, it is an
# uncalibrated one, so this is not optional even in a throwaway.
CHILD_CPU = 1
PARENT_CPU = 0


def utc_now():
    """An ISO-8601 UTC stamp, which rows otherwise have no way to carry.

    Not decoration. P_idle is a function of time, so subtracting an idle
    window from a measured one requires knowing which idle window was nearest
    -- and without a stamp, nothing can tell whether a baseline predates the
    rows it is being subtracted from.
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def git_provenance(repo_root):
    """The SHA on every row, and whether the tree was dirty when it was taken.

    This is the one question a calibration rig must always be able to answer:
    which code produced this row? Sync to the rig is git, pull-only and
    --ff-only, precisely so the answer is a SHA rather than a guess about what
    rsync copied when.
    """
    def git(*args):
        return subprocess.run(
            ("git", "-C", repo_root) + args,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    try:
        sha = git("rev-parse", "HEAD")
        dirty = bool(git("status", "--porcelain"))
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return {"git_sha": None, "git_dirty": None, "git_error": str(exc)}
    return {"git_sha": sha, "git_dirty": dirty}


def r_for(n, window_work):
    """Repetitions needed to hold the target window at this trip count."""
    return max(1, round(window_work / n))


def child_env():
    """A minimal, reproducible environment for the child.

    PYTHONHASHSEED is pinned because set construction and membership go
    through hash(), so an unpinned seed injects variance into exactly the arm
    whose allocator path is under test in the set-materialising pairs. The
    child records what actually arrived, so a campaign can be audited rather
    than trusted -- pinning it here and recording it there are two halves of
    one check.

    Passing a trimmed env rather than os.environ keeps a stray PYTHONPATH,
    PYTHONOPTIMIZE or PYTHONDONTWRITEBYTECODE in the operator's shell from
    becoming an invisible treatment.
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TZ")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONHASHSEED"] = "0"
    return env


def run_child(python, repo_root, fixture, n, r, warmup, rapl_root, timeout,
               pin=True):
    """Spawn one harness run and return its row.

    The child measures itself; bracketing this subprocess call would put
    ~20-30 ms of interpreter startup inside the window. So the parent reads
    the child's JSON off stdout and never times it.

    A failed child is still a row -- the harness catches its own exceptions
    and reports them as `status: failed`. What this has to handle is the case
    the child cannot report on: it died without producing parseable JSON.
    """
    cmd = ["taskset", "-c", str(CHILD_CPU)] if pin else []
    cmd += [
        python, "-s", "-m", "etdc.rig.harness", fixture,
        "--n", str(n), "--r", str(r), "--warmup", str(warmup),
    ]
    if rapl_root is not None:
        cmd += ["--rapl-root", rapl_root]

    try:
        proc = subprocess.run(
            cmd, cwd=repo_root, env=child_env(),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "fixture": os.path.relpath(fixture, repo_root),
            "n": n, "r": r, "warmup": warmup,
            "error": f"child exceeded {timeout}s",
        }

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        # Deliberately keeps the child's stderr: a row saying only "unparseable"
        # is a row nobody can act on.
        return {
            "status": "unparseable",
            "fixture": os.path.relpath(fixture, repo_root),
            "n": n, "r": r, "warmup": warmup,
            "error": f"{type(exc).__name__}: {exc}",
            "returncode": proc.returncode,
            "stdout_head": proc.stdout[:400],
            "stderr_tail": proc.stderr[-800:],
        }


def measure_idle(domains, seconds):
    """One idle window, measured by the parent between children.

    A fourth arm, not a pin-time capture. Two reasons it belongs in the
    rotation: it makes P_idle a function of time instead of a constant taken
    hours earlier, and an idle window taken BETWEEN runs is the floor under
    campaign conditions, which is what is actually being subtracted. The
    pin-time baseline stays as the drift reference, not as the subtrahend.

    Shaped like a child row -- same status/arm/duration_s/energy_uj keys -- so
    a reader can group by `arm` without special-casing where the row came from.
    """
    try:
        record = rapl.sample(seconds, domains)
    except OSError as exc:
        return {"status": "failed", "arm": "idle", "pair": None,
                "error": f"{type(exc).__name__}: {exc}"}
    row = {"status": "ok", "arm": "idle", "pair": None, "r": 1}
    row.update(record)
    return row


def calibrate(run, n, window_work, target):
    """Measure this (arm, N)'s per-repetition cost, then pick R from it.

    Returns (r, probe_row). `run` is a callable taking R, so this does not
    need to know how a child is spawned.

    Per ARM as well as per N. The arms of a pair can differ enormously --
    any_list's no-flag arm is ~57x faster, so one shared R would give the flag
    arm a ~57 s window and cost hours for one pair. Nothing is lost by letting
    them differ: ratios are formed from E/R and T/R, and harness overhead
    enters as E/R = w + h regardless of R.

    A failed probe falls back to the seed constant rather than aborting. A
    campaign with one badly-sized window is worth more than no campaign, and
    the window length is recorded on every row, so decouple.py flags it.
    """
    r_probe = max(1, round(r_for(n, window_work) * PROBE_FRACTION))
    row = run(r_probe)
    row["probe"] = True

    duration = row.get("duration_s")
    if row.get("status") != "ok" or not duration or duration <= 0:
        row["r_source"] = "seed (probe failed)"
        return r_for(n, window_work), row

    per_rep = duration / r_probe
    row["r_source"] = "probe"
    row["probe_per_rep_s"] = per_rep
    return max(1, round(target / per_rep)), row


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule", default="eager-materialization")
    parser.add_argument("--pair", default="sum_list")
    parser.add_argument("--ladder", default=",".join(str(n) for n in DEFAULT_LADDER),
                        help="comma-separated trip counts")
    parser.add_argument("--reps", type=int, default=10,
                        help="flag/no-flag ratio pairs per trip count")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--window-work", type=int, default=WINDOW_WORK,
                        help="seed R*N product for the calibration probe; "
                             "with --no-calibrate, it sets R outright")
    parser.add_argument("--target-window", type=float, default=TARGET_WINDOW_S,
                        help="window length each arm is calibrated to")
    parser.add_argument("--no-calibrate", action="store_true",
                        help="derive R from --window-work alone, the pre-"
                             "2026-10-21 behaviour; reproduces older campaigns")
    parser.add_argument("--idle-every", type=int, default=IDLE_EVERY)
    parser.add_argument("--idle-seconds", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="per-child wall-clock limit")
    parser.add_argument("--python", default=sys.executable,
                        help="interpreter for the child; recorded on every row")
    parser.add_argument("--rapl-root", default=None,
                        help="override for off-rig testing against a fake tree")
    parser.add_argument("--no-pin", action="store_true",
                        help="skip taskset/affinity -- off-rig plumbing tests "
                             "only; stamps pinned=false on every row")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="measure anyway with uncommitted changes present")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the rotation and the R ladder, measure nothing")
    parser.add_argument("--out", default=None,
                        help="JSONL to append to; omitted prints rows to stdout")
    args = parser.parse_args()

    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    ladder = [int(x) for x in args.ladder.split(",") if x.strip()]
    if not ladder:
        parser.error("--ladder is empty")
    if args.reps < 1:
        parser.error("--reps must be at least 1")

    fixtures = {
        arm: os.path.join(repo_root, "benchmarks", args.rule, arm, args.pair + ".py")
        for arm in ("flag", "no-flag")
    }
    for arm, path in fixtures.items():
        if not os.path.exists(path):
            parser.error(f"no {arm} fixture at {path}")

    children = len(ladder) * args.reps * 2

    if args.dry_run:
        mode = ("fixed R*N (--no-calibrate)" if args.no_calibrate
                else f"calibrated per (arm, N) to {args.target_window:.2f}s")
        print(f"pair={args.rule}/{args.pair}  reps={args.reps}  R: {mode}")
        for n in ladder:
            seed = r_for(n, args.window_work)
            if args.no_calibrate:
                print(f"  N={n:>9,}  R={seed:>5}")
            else:
                print(f"  N={n:>9,}  seed R={seed:>5}  "
                      f"probe R={max(1, round(seed * PROBE_FRACTION)):>4}  "
                      f"(final R measured at run time)")
        # An idle window fires BEFORE a child when the counter is due, so the
        # last block never gets a trailing one -- hence children // every, not
        # one more. The old estimate said 6 where 5 were written.
        idles = 1 + (children - 1) // max(1, args.idle_every)
        probes = 0 if args.no_calibrate else len(ladder) * 2
        print(f"{children} child runs + {probes} probes + {idles} idle windows")
        return 0

    prov = git_provenance(repo_root)
    if prov.get("git_dirty") and not args.allow_dirty:
        sys.stderr.write(
            "refusing to measure: the tree has uncommitted changes, so no SHA "
            "identifies the code that produced these rows. Commit, or pass "
            "--allow-dirty to accept rows stamped git_dirty=true.\n")
        return 2

    # Pin the parent here rather than trusting the operator's taskset. The
    # child gets core 1 explicitly; if the parent were left free to land on
    # the same core, it would contend with the thing being measured.
    #
    # --no-pin exists because taskset and sched_setaffinity are both
    # Linux-only, so the plumbing cannot be exercised at all on a dev Mac.
    # It is a loud flag and not a fallback: pinning failing on a rig must stay
    # an error, because a row that silently lost its pin reads exactly like a
    # measured one.
    if not args.no_pin:
        try:
            os.sched_setaffinity(0, {PARENT_CPU})
        except (AttributeError, OSError) as exc:
            sys.stderr.write(
                f"cannot pin parent to cpu{PARENT_CPU}: {exc}. Pass --no-pin "
                f"only for an off-rig plumbing test.\n")
            return 2

    # Discovered once, in the parent, for the idle arm only. The child does
    # its own discovery -- it must, since its window must contain no sysfs
    # walk -- and the two are expected to agree. A disagreement is worth
    # seeing, which is why both are recorded.
    rapl_root = args.rapl_root if args.rapl_root is not None else rapl.RAPL_ROOT
    try:
        domains = rapl.discover_domains(root=rapl_root)
    except OSError as exc:
        sys.stderr.write(f"RAPL discovery failed: {exc}\n")
        return 2

    sweep = {
        "sweep_id": utc_now(),
        "rule_id": args.rule,
        "pair": args.pair,
        "reps": args.reps,
        "warmup": args.warmup,
        "window_work": args.window_work,
        # How R was chosen, recorded so a campaign is readable years later.
        # Absence of this key means a campaign from before calibration
        # existed, when R came from the fixed R*N constant alone.
        "r_policy": "fixed" if args.no_calibrate else "calibrated",
        "target_window_s": None if args.no_calibrate else args.target_window,
        "ladder": ladder,
        "expected_python": args.python,
        "pinned": not args.no_pin,
        # Keys only, not paths. The child records its own full domain paths
        # on every row, so the parent's contribution is the SET it discovered
        # -- which is what a disagreement would show up in. Carrying the paths
        # too would repeat ~400 bytes of absolute path on every row to say
        # something already said.
        "parent_domains": sorted(domains),
        **prov,
    }

    out = open(args.out, "a", buffering=1) if args.out else None
    seq = 0
    since_idle = args.idle_every  # forces an idle window before the first run

    def emit(row):
        nonlocal seq
        row = {"seq": seq, "started_at": utc_now(), "sweep": sweep, **row}
        seq += 1
        line = json.dumps(row)
        if out:
            out.write(line + "\n")
        else:
            print(line)

    def child(arm, n, r):
        return run_child(args.python, repo_root, fixtures[arm], n, r,
                         args.warmup, args.rapl_root, args.timeout,
                         pin=not args.no_pin)

    t0 = time.monotonic()
    try:
        for n in ladder:
            # Calibrate both arms before measuring either, so the whole block
            # for this N runs at its settled R and no ratio is ever formed
            # from one calibrated and one seeded window.
            r_by_arm = {}
            for arm in ("flag", "no-flag"):
                if args.no_calibrate:
                    r_by_arm[arm] = r_for(n, args.window_work)
                    continue
                r, probe_row = calibrate(
                    lambda rr, a=arm: child(a, n, rr),
                    n, args.window_work, args.target_window)
                r_by_arm[arm] = r
                emit(probe_row)
                sys.stderr.write(
                    f"  N={n:>9,} {arm:>8}  R={r:<6} "
                    f"(probe {probe_row.get('duration_s', 0):.3f}s)\n")

            for _ in range(args.reps):
                for arm in ("flag", "no-flag"):
                    if since_idle >= args.idle_every:
                        emit(measure_idle(domains, args.idle_seconds))
                        since_idle = 0
                    emit(child(arm, n, r_by_arm[arm]))
                    since_idle += 1
    except KeyboardInterrupt:
        sys.stderr.write(f"\ninterrupted after {seq} rows\n")
    finally:
        if out:
            out.close()

    sys.stderr.write(f"{seq} rows in {time.monotonic() - t0:.1f}s"
                     + (f" -> {args.out}\n" if args.out else "\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
