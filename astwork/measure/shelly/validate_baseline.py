#!/usr/bin/env python3
"""Cross-check a saved idle_baseline_*.json (from pin_baseline.sh) against
the Shelly plug's wall power, measured now.

    python3 validate_baseline.py [--baseline path] [--seconds N] [--host ip] [--out path]

Unlike validate_shelly.py, this does NOT resample RAPL — it reuses the
avg_power_w already recorded in a baseline file and only samples Shelly live.
That means the two readings are NOT from the same window: the baseline was
captured whenever pin_baseline.sh last ran, and the Shelly sample happens
now. This is only a meaningful cross-check if the machine is still sitting
in the same idle/pinned state the baseline was captured in — if anything
has run on the box since (or turbo/governor/SMT pinning was restored), this
comparison is meaningless and will be flagged as stale.

Same coverage_ratio convention as validate_shelly.py: domain_power /
shelly_power, every ratio must be < 1.0.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # shelly_check

import shelly_check  # noqa: E402

DEFAULT_BASELINE_DIR = Path(__file__).resolve().parent.parent / "measurements"
STALE_WARN_S = 3600  # baseline older than this vs. now is probably not "still idle"
QUANTIZATION_WARN_RATIO = 2.0  # aenergy-vs-apower divergence beyond this is flagged


def latest_baseline(baseline_dir=DEFAULT_BASELINE_DIR):
    candidates = sorted(Path(baseline_dir).glob("idle_baseline_*.json"))
    if not candidates:
        raise SystemExit(f"no idle_baseline_*.json files found under {baseline_dir}")
    return candidates[-1]  # filenames are timestamp-sorted (YYYYmmddTHHMMSS)


def baseline_timestamp(baseline_path):
    """Pull the YYYYmmddTHHMMSS suffix back out of idle_baseline_<ts>.json so
    the validation output can be named to match, instead of stamping its own
    (different) capture time."""
    prefix = "idle_baseline_"
    stem = baseline_path.stem
    return stem[len(prefix):] if stem.startswith(prefix) else stem


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", default=None, help="idle_baseline_*.json path (default: newest in measurements/)")
    parser.add_argument("--seconds", type=float, default=None, help="Shelly sample window (default: baseline's duration_s)")
    parser.add_argument("--host", default=None, help="Shelly host (default: <device id>.local)")
    parser.add_argument("--switch-id", type=int, default=0)
    parser.add_argument("--out", default=None, help="default: <baseline dir>/baseline_validate_<baseline's timestamp>.json")
    args = parser.parse_args()

    baseline_path = Path(args.baseline) if args.baseline else latest_baseline()
    out_path = Path(args.out) if args.out else baseline_path.parent / f"baseline_validate_{baseline_timestamp(baseline_path)}.json"
    with open(baseline_path) as f:
        baseline = json.load(f)

    seconds = args.seconds if args.seconds is not None else baseline["duration_s"]
    host = args.host or shelly_check.default_host()

    baseline_age_s = time.time() - baseline_path.stat().st_mtime
    print(
        f"using baseline: {baseline_path} (captured {baseline_age_s / 60:.1f} min ago) "
        f"-- Ctrl-C now if that's the wrong file",
        file=sys.stderr,
    )

    shelly_start = shelly_check.switch_status(host, args.switch_id)
    t0 = time.monotonic()
    time.sleep(seconds)
    elapsed = time.monotonic() - t0
    shelly_end = shelly_check.switch_status(host, args.switch_id)

    shelly_wh_delta = shelly_end["aenergy"]["total"] - shelly_start["aenergy"]["total"]
    if shelly_wh_delta < 0:
        raise SystemExit(
            "Shelly aenergy.total went backwards — counters were reset "
            "during the sample window, discard this run"
        )
    shelly_avg_power_w = (shelly_wh_delta * 3600.0) / elapsed
    apower_w_start = shelly_start.get("apower")
    apower_w_end = shelly_end.get("apower")

    coverage_ratio = {
        k: (w / shelly_avg_power_w if shelly_avg_power_w else float("nan"))
        for k, w in baseline["avg_power_w"].items()
    }

    warnings = []
    if not shelly_avg_power_w:
        # aenergy.total is a cumulative counter that may only tick on its own
        # internal interval — a short window can read 0 delta even at real
        # non-zero power. apower is instantaneous and doesn't have that lag,
        # so surface it here rather than silently emitting NaN ratios.
        warnings.append(
            f"Shelly aenergy delta was 0 over {elapsed:.1f}s (instantaneous apower: "
            f"{apower_w_start}W -> {apower_w_end}W) — coverage_ratio is undefined, "
            "treat this run as invalid; try a longer --seconds"
        )
    else:
        warnings.extend(
            f"domain '{k}' reports {ratio:.2f}x Shelly's wall power — physically "
            "impossible, treat this run as invalid"
            for k, ratio in coverage_ratio.items()
            if ratio >= 1.0
        )
        # aenergy.total has its own internal step size (quantization). Over a
        # short window at low power, the true delta can be smaller than that
        # step, so the reported delta — and everything derived from it — is
        # mostly rounding noise. apower is instantaneous and isn't subject to
        # that, so use it as an independent cross-check: if the two disagree
        # by a lot, the energy-derived average isn't trustworthy even though
        # it passed the >= 1.0 impossibility check above.
        if apower_w_start is not None and apower_w_end is not None:
            apower_avg = (apower_w_start + apower_w_end) / 2
            if apower_avg > 0:
                divergence = shelly_avg_power_w / apower_avg
                if divergence > QUANTIZATION_WARN_RATIO or divergence < 1 / QUANTIZATION_WARN_RATIO:
                    warnings.append(
                        f"aenergy-derived avg power ({shelly_avg_power_w:.1f}W) diverges "
                        f"{divergence:.1f}x from instantaneous apower ({apower_w_start}W -> "
                        f"{apower_w_end}W) — the {elapsed:.0f}s window is likely too short "
                        "relative to the meter's own energy-counter resolution at this power "
                        "level; treat this run as invalid and try a much longer --seconds "
                        "(300s+)"
                    )
    if baseline_age_s > STALE_WARN_S:
        warnings.append(
            f"baseline is {baseline_age_s / 60:.0f} min old — this comparison assumes "
            "the machine is still in the same idle/pinned state it was captured in; "
            "re-run pin_baseline.sh if that's no longer true"
        )

    record = {
        "baseline_path": str(baseline_path),
        "baseline_age_s": baseline_age_s,
        "elapsed_s": elapsed,
        "shelly_avg_power_w": shelly_avg_power_w,
        "apower_w_start": apower_w_start,
        "apower_w_end": apower_w_end,
        "baseline_avg_power_w": baseline["avg_power_w"],
        "coverage_ratio": coverage_ratio,
        "warnings": warnings,
    }

    print(json.dumps(record, indent=2))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(record, f, indent=2)
    print(f"written to {out_path}")


if __name__ == "__main__":
    main()
