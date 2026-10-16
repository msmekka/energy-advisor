#!/usr/bin/env python3
"""Measure one fixture, once. The child half of a benchmark run.

Run from the repo root so `python -m` puts it on sys.path; no pip install:

    taskset -c 3 python3 -s -m etdc.rig.harness \
        benchmarks/eager-materialization/flag/sum_list.py \
        --n 200000 --r 500 --warmup 2 --out run.json

One process, one fixture, one measured window, one JSON object out. The
campaign runner spawns this once per run and appends the object to its JSONL,
adding the rig provenance only the parent knows (host, CPU, kernel, governor,
turbo, SMT). Everything this file reports is something only the child can
speak for -- above all the interpreter, which IS the thing being measured.

Why the bracket lives here and not in the parent: wrapping the whole exec
would put ~20-30 ms of interpreter startup inside the window. Why it lives
here and not in each fixture: the window has to be the same bytecode for
every arm, or the control isn't a control.

The window contains the R loop and nothing else. Fixture load, domain
discovery, build() and warmup all happen before it.
"""
import argparse
import gc
import importlib.util
import json
import os
import platform
import sys
import sysconfig
import time
import traceback

from etdc.rig import rapl

# Not "__main__": a fixture is runnable on its own and carries an
# `if __name__ == "__main__"` block. Loading it under any other name keeps
# that block inert, so the workload does not run once, unmeasured, here.
FIXTURE_MODULE_NAME = "etdc_fixture"

# repr() of the work() result is recorded so analysis can confirm the two arms
# of a pair computed the same value on the same data. Truncated because a
# fixture may legitimately reduce to something large.
RESULT_REPR_LIMIT = 120


def runtime_info():
    """Everything about this interpreter that can change a measurement.

    Not background provenance -- a treatment variable. CPython 3.12 inlined
    list/set/dict comprehensions (PEP 709) but NOT generator expressions, so
    the exact asymmetry the eager-materialization rule rests on moved in a
    released minor version. 3.11's specializing interpreter and 3.14's
    tail-calling interpreter both shift dispatch cost, which dominates at
    small N. Rows from two versions are not poolable, and a free-threaded
    build is a different runtime altogether rather than a flag.

    hash_randomization matters specifically for the set-materialising pairs:
    set construction and membership go through hash(), so an unpinned seed
    injects variance into the arm whose allocator path is under test. The
    runner is expected to pin PYTHONHASHSEED; this records what actually
    arrived so a campaign can be audited rather than trusted.
    """
    return {
        "executable": sys.executable,
        "version": platform.python_version(),
        "version_full": sys.version,
        "implementation": sys.implementation.name,
        "implementation_version": ".".join(
            str(p) for p in sys.implementation.version[:3]
        ),
        "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "hash_seed": os.environ.get("PYTHONHASHSEED"),
        "hash_randomization": bool(sys.flags.hash_randomization),
        "xoptions": {k: v for k, v in sys._xoptions.items()},
        "optimize": sys.flags.optimize,
        "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
        "pycache_prefix": sys.pycache_prefix,
        # The child's own view of the machine. The runner's rig provenance is
        # authoritative; these are here so a hand-run row is self-contained,
        # and because a disagreement between the two means something is wrong.
        "kernel": platform.release(),
        "machine": platform.machine(),
    }


def identify(fixture_path):
    """Derive rule_id / arm / pair from benchmarks/<rule>/<arm>/<pair>.py.

    rule_id is the tier-1 join key, so it is worth carrying on every row even
    though the runner also knows it. Returns Nones rather than raising for a
    fixture kept outside that layout -- an unrecognised path is a reason to
    label a row poorly, not to lose a measurement.
    """
    parts = os.path.normpath(os.path.abspath(fixture_path)).split(os.sep)
    pair = os.path.splitext(parts[-1])[0] if parts else None
    arm = parts[-2] if len(parts) >= 2 and parts[-2] in ("flag", "no-flag") else None
    rule_id = parts[-3] if arm and len(parts) >= 3 else None
    return rule_id, arm, pair


def load_fixture(path):
    """Load a fixture by explicit path, adding nothing to sys.path.

    `python fixture.py` would put the fixture's own directory at sys.path[0],
    letting a stray sibling file shadow a stdlib module in one arm and not the
    other. Loading from a spec avoids that entirely.
    """
    spec = importlib.util.spec_from_file_location(FIXTURE_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load fixture: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[FIXTURE_MODULE_NAME] = mod
    spec.loader.exec_module(mod)

    for name in ("build", "work"):
        if not callable(getattr(mod, name, None)):
            raise AttributeError(
                f"fixture {path} must define a callable {name}(); see "
                f"benchmarks/TEMPLATE.py for the contract"
            )
    return mod


def measure(domains, work, data, r):
    """The measured window. Keep this function boring and short.

    `work` and `data` arrive as locals so the loop compiles to LOAD_FAST, and
    the loop body is one call and one store -- identical in both arms. The
    result of the last iteration is kept for the cross-arm equality check; the
    harness does not compare results per iteration, which would put work
    inside the window.
    """
    mark = rapl.start(domains)
    for _ in range(r):
        result = work(data)
    record = rapl.stop(domains, mark)
    return record, result


def run(args):
    t = time.perf_counter
    row = {
        "status": "ok",
        "fixture": os.path.relpath(args.fixture),
        "n": args.n,
        "r": args.r,
        "warmup": args.warmup,
        "runtime": runtime_info(),
    }

    t0 = t()
    mod = load_fixture(args.fixture)
    row["import_s"] = t() - t0

    rule_id, arm, pair = identify(args.fixture)
    row.update(rule_id=rule_id, arm=arm, pair=pair)

    n = args.n if args.n is not None else getattr(mod, "N")
    row["n"] = n

    # Discovery is a sysfs walk; doing it here means the window contains one
    # open/read/close per domain and no directory traversal at all.
    domains = rapl.discover_domains(root=args.rapl_root)
    row["domains"] = {k: v["path"] for k, v in domains.items()}

    t0 = t()
    data = mod.build(n)
    row["build_s"] = t() - t0

    # Warmup is outside the window and recorded, so cold-start cost is a
    # declared parameter instead of an accident that lands on whichever arm
    # allocates more.
    t0 = t()
    for _ in range(args.warmup):
        mod.work(data)
    row["warmup_s"] = t() - t0

    # GC stays ENABLED inside the window: the collection cost of materialising
    # really is part of the shape under test. Collect first so garbage left by
    # build() and warmup is not swept up inside the measured region by luck.
    gc.collect()
    row["gc_enabled"] = gc.isenabled()

    record, result = measure(domains, mod.work, data, args.r)

    row.update(record)
    row["result_repr"] = repr(result)[:RESULT_REPR_LIMIT]
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="path to a benchmark fixture")
    parser.add_argument("--n", type=int, default=None,
                        help="trip count; defaults to the fixture's own N")
    parser.add_argument("--r", type=int, default=1,
                        help="repetitions inside the measured window")
    parser.add_argument("--warmup", type=int, default=1,
                        help="unmeasured iterations before the window")
    parser.add_argument("--rapl-root", default=rapl.RAPL_ROOT,
                        help="override for off-rig testing against a fake tree")
    parser.add_argument("--out", default=None,
                        help="write the row here; omitted prints to stdout")
    args = parser.parse_args()

    if args.r < 1:
        parser.error("--r must be at least 1")
    if args.warmup < 0:
        parser.error("--warmup cannot be negative")

    # A failure is a row, not a silent gap: the runner needs to know WHICH run
    # failed and why, and a campaign of ~1200 runs cannot afford to lose that
    # to a traceback on stderr. Nothing is ever substituted for a missing
    # measurement -- a failed row carries no energy_uj at all, because a zero
    # delta is indistinguishable from a genuinely idle window.
    try:
        row = run(args)
        status = 0
    except Exception as exc:
        row = {
            "status": "failed",
            "fixture": os.path.relpath(args.fixture),
            "n": args.n,
            "r": args.r,
            "warmup": args.warmup,
            "runtime": runtime_info(),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=6),
        }
        status = 1

    if args.out:
        # One line, so a run file concatenates straight into the campaign JSONL.
        with open(args.out, "w") as f:
            f.write(json.dumps(row) + "\n")
    else:
        print(json.dumps(row, indent=2))

    return status


if __name__ == "__main__":
    sys.exit(main())
