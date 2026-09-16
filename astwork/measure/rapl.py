#!/usr/bin/env python3
"""Direct /sys/class/powercap/intel-rapl* reader.

Not pyRAPL: its DeviceAPIFactory only builds PkgAPI/DramAPI, and
_get_socket_directory_names filters top-level zones to ones whose name
contains "package" — so a sibling "psys" zone is skipped, and there's no
CoreAPI/UncoreAPI at all. Walking sysfs ourselves picks up whatever domains
a given rig actually has (dram, psys, core, uncore, package-0, ...).

Shared by pin_baseline.sh (idle baseline capture) and validate_shelly.py
(cross-check against the Shelly plug) — one sysfs walk, not two copies of it.
"""
import argparse
import json
import os
import time

RAPL_ROOT = "/sys/class/powercap"


def discover_domains(root=RAPL_ROOT):
    # /sys/class/powercap/intel-rapl:N is a symlink into /sys/devices/..., so
    # this needs to follow symlinks to find anything at all — but a blanket
    # os.walk(root, followlinks=True) hangs forever: every /sys device
    # directory carries a "subsystem" symlink back to its class directory,
    # and os.walk has no cycle detection once followlinks is on. Restricting
    # recursion to intel-rapl*-named children avoids the subsystem/driver/
    # power/uevent cycle, but naming alone doesn't rule out a symlink loop
    # among the RAPL zones themselves — so also track realpath()s already
    # visited and refuse to re-enter one.
    domains = {}
    seen = set()

    def visit(path):
        real = os.path.realpath(path)
        if real in seen:
            return
        seen.add(real)
        try:
            entries = os.listdir(path)
        except OSError:
            return
        if "energy_uj" in entries and "name" in entries:
            with open(os.path.join(path, "name")) as f:
                name = f.read().strip()
            max_range = None
            max_range_path = os.path.join(path, "max_energy_range_uj")
            if os.path.exists(max_range_path):
                with open(max_range_path) as f:
                    max_range = int(f.read().strip())
            key = name
            n = 1
            while key in domains:
                n += 1
                key = f"{name}-{n}"
            domains[key] = {"path": path, "max_range_uj": max_range}
        for entry in entries:
            if entry.startswith("intel-rapl"):
                child = os.path.join(path, entry)
                if os.path.isdir(child):  # follows the symlink for the type check
                    visit(child)

    if os.path.isdir(root):
        for entry in os.listdir(root):
            if entry.startswith("intel-rapl"):
                child = os.path.join(root, entry)
                if os.path.isdir(child):
                    visit(child)

    return domains


def read_uj(path):
    with open(os.path.join(path, "energy_uj")) as f:
        return int(f.read().strip())


def sample(seconds, domains=None):
    """Sample every RAPL domain for `seconds`, wall-clock via monotonic clock.

    Returns {"duration_s", "energy_uj": {domain: uj}, "avg_power_w": {domain: w}}.
    32-bit counter wraparound is corrected per-domain via max_energy_range_uj.
    """
    domains = domains or discover_domains()
    if not domains:
        raise RuntimeError(f"no RAPL domains found under {RAPL_ROOT}")

    start = {k: read_uj(v["path"]) for k, v in domains.items()}
    t0 = time.monotonic()
    time.sleep(seconds)
    elapsed = time.monotonic() - t0
    end = {k: read_uj(v["path"]) for k, v in domains.items()}

    energy_uj = {}
    for k, v in domains.items():
        delta = end[k] - start[k]
        if delta < 0 and v["max_range_uj"]:
            delta += v["max_range_uj"]
        energy_uj[k] = delta

    return {
        "duration_s": elapsed,
        "energy_uj": energy_uj,
        "avg_power_w": {k: (uj / 1e6) / elapsed for k, uj in energy_uj.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    record = sample(args.seconds)
    print(json.dumps(record, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(record, f, indent=2)


if __name__ == "__main__":
    main()
