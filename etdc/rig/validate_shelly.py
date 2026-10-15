#!/usr/bin/env python3
"""Cross-check RAPL domain power against the Shelly plug's measured wall
power, sampled over the same window.

    python3 validate_shelly.py --seconds 30 [--host <ip>] [--out path]

Shelly is validation-tier only (see energy-aware-code-analysis-plan.md) —
this script exists to sanity-check that RAPL's numbers are physically
plausible against true wall draw, never to replace RAPL as the primary
measurement path.

Each RAPL domain's average power is reported as coverage_ratio: domain_power
/ shelly_power. Every ratio must be < 1.0 — a domain can never draw more
power than the whole machine pulls from the wall. A ratio >= 1.0 means the
measurement is broken (misaligned windows, wrong assumptions), not a real
finding — treat that run as invalid, don't write it down as a result.

Sampling isn't perfectly simultaneous: the Shelly reads are HTTP round trips
(tens to a few hundred ms) bracketing the RAPL reads (near-instant file
reads). That skew is a small fraction of a 20-30s window and fine for a
sanity check; don't use this for short snippets where that skew matters.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # shelly_check

import rapl  # noqa: E402
import shelly_check  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--host", default=None, help="Shelly host (default: <device id>.local)")
    parser.add_argument("--switch-id", type=int, default=0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    host = args.host or shelly_check.default_host()
    domains = rapl.discover_domains()
    if not domains:
        raise SystemExit(f"no RAPL domains found under {rapl.RAPL_ROOT}")

    rapl_start = {k: rapl.read_uj(v["path"]) for k, v in domains.items()}
    shelly_start = shelly_check.switch_status(host, args.switch_id)
    t0 = time.monotonic()

    time.sleep(args.seconds)

    elapsed = time.monotonic() - t0
    rapl_end = {k: rapl.read_uj(v["path"]) for k, v in domains.items()}
    shelly_end = shelly_check.switch_status(host, args.switch_id)

    rapl_energy_uj = {}
    for k, v in domains.items():
        delta = rapl_end[k] - rapl_start[k]
        if delta < 0 and v["max_range_uj"]:  # 32-bit counter wraparound
            delta += v["max_range_uj"]
        rapl_energy_uj[k] = delta
    rapl_avg_power_w = {k: (uj / 1e6) / elapsed for k, uj in rapl_energy_uj.items()}

    shelly_wh_delta = shelly_end["aenergy"]["total"] - shelly_start["aenergy"]["total"]
    if shelly_wh_delta < 0:
        raise SystemExit(
            "Shelly aenergy.total went backwards — counters were reset "
            "during the sample window, discard this run"
        )
    shelly_energy_j = shelly_wh_delta * 3600.0
    shelly_avg_power_w = shelly_energy_j / elapsed

    coverage_ratio = {
        k: (w / shelly_avg_power_w if shelly_avg_power_w else float("nan"))
        for k, w in rapl_avg_power_w.items()
    }

    warnings = [
        f"domain '{k}' reports {ratio:.2f}x Shelly's wall power — physically "
        "impossible, treat this run as invalid (clock skew / misaligned windows)"
        for k, ratio in coverage_ratio.items()
        if ratio >= 1.0
    ]

    record = {
        "elapsed_s": elapsed,
        "shelly_avg_power_w": shelly_avg_power_w,
        "rapl_avg_power_w": rapl_avg_power_w,
        "coverage_ratio": coverage_ratio,
        "warnings": warnings,
    }

    print(json.dumps(record, indent=2))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(record, f, indent=2)
        print(f"written to {out_path}")


if __name__ == "__main__":
    main()
