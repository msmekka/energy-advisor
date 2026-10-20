#!/usr/bin/env python3
"""Direct /sys/class/powercap/intel-rapl* reader.

Not pyRAPL: its DeviceAPIFactory only builds PkgAPI/DramAPI, and
_get_socket_directory_names filters top-level zones to ones whose name
contains "package" — so a sibling "psys" zone is skipped, and there's no
CoreAPI/UncoreAPI at all. Walking sysfs ourselves picks up whatever domains
a given rig actually has (dram, psys, core, uncore, package-0, ...).

Shared by pin_baseline.sh (idle baseline capture), validate_shelly.py
(cross-check against the Shelly plug), and benchmark children, which bracket
their own hot loop with start()/stop() — one sysfs walk, not three copies of
it.
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
    found = []
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
            # Trial read at discovery, outside any measured window. A directory
            # listing only proves energy_uj EXISTS; it is commonly 0400
            # (PLATYPUS / CVE-2020-8694), so an unprivileged reader discovers
            # the domain happily and then fails on the first read INSIDE a
            # window. Failing here costs one startup instead of a campaign.
            #
            # Raise rather than skip the domain: a silently dropped zone
            # produces rows covering fewer domains than their siblings, with
            # nothing in the output looking wrong.
            try:
                read_uj(path)
            except OSError as exc:
                try:
                    mode = oct(os.stat(os.path.join(path, "energy_uj")).st_mode & 0o777)
                except OSError:
                    mode = "unknown"
                raise type(exc)(
                    f"{real}/energy_uj is not readable as uid {os.geteuid()} "
                    f"(mode {mode}): {exc}. RAPL counters are commonly "
                    f"root-only; run pin_baseline.sh, which relaxes them for "
                    f"the session and restores them with --restore."
                ) from exc
            max_range = None
            max_range_path = os.path.join(path, "max_energy_range_uj")
            if os.path.exists(max_range_path):
                with open(max_range_path) as f:
                    max_range = int(f.read().strip())
            # Record the REALPATH, not the path this walk happened to
            # arrive by. /sys/class/powercap exposes each zone twice -- flat
            # (intel-rapl:0:0) and nested (intel-rapl/intel-rapl:0/...) -- and
            # which one is reached first depends on os.listdir order.
            # Deduplication already keys on realpath, so the domain SET is
            # correct either way, but recording the arrival path left the
            # stored path varying between invocations and made the sort below
            # order on something non-canonical -- which is what that sort
            # exists to prevent.
            found.append((real, name, max_range))
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

    # Sort by CANONICAL path before assigning keys, not after. listdir order
    # isn't guaranteed, and the duplicate-name suffix below depends on order —
    # so sorting only the iteration order would still let `core` and `core-2`
    # swap which socket they point at between invocations on a multi-socket
    # box. Path order also keeps the subzone hierarchy visible, since
    # intel-rapl:0 sorts before intel-rapl:0:0.
    #
    # The order matters for measurement, not just for reading the output:
    # start() and stop() walk this dict in the same order, so each domain's
    # read lands at the same offset inside both brackets and the offset
    # cancels in the delta.
    domains = {}
    for path, name, max_range in sorted(found):
        key = name
        n = 1
        while key in domains:
            n += 1
            key = f"{name}-{n}"
        domains[key] = {"path": path, "max_range_uj": max_range}

    return domains


def read_uj(path):
    with open(os.path.join(path, "energy_uj")) as f:
        return int(f.read().strip())


def start(domains):
    """Open a measurement window: read every counter, then the clock.

    Returns an opaque mark to hand to stop(). No module-level state, so two
    brackets can be open at once and windows can nest.

    This does no sysfs walking — one open/read/close per domain and nothing
    else. Discovery must happen before the window, or a benchmark loop re-walks
    sysfs inside every measured region.

    The read ORDER here has to match stop()'s exactly. Reading ~5 sysfs files
    takes real time, and whichever of {counters, clock} is read second carries
    that overhead inside its own interval. Counters-then-clock at both ends
    puts the energy window at [T0, T1] and the clock window at [T0+d, T1+d]:
    different intervals, identical length, so d cancels in the subtraction.
    Reversing the order at one end only would leave 2d of read overhead in the
    duration but not in the energy, biasing avg power in a fixed direction.
    """
    if not domains:
        raise RuntimeError(f"no RAPL domains found under {RAPL_ROOT}")

    uj = {k: read_uj(v["path"]) for k, v in domains.items()}
    return {"uj": uj, "monotonic": time.monotonic()}


def stop(domains, mark):
    """Close the window opened by `mark`; return raw per-domain deltas.

    Counters then clock, matching start(). Pass the same `domains` dict that
    opened the window — a different dict means a different read order, and the
    offsets stop cancelling.

    No total is computed. Whether to sum package + dram, and whether psys
    belongs in that sum or double-counts the package, is an aggregator's
    judgment call — revisable only while the per-domain numbers still exist.
    Read errors propagate for the same reason: a zero delta is
    indistinguishable from a genuinely idle window, so the runner records a
    failed row rather than a measurement that reads as real.
    """
    end = {k: read_uj(v["path"]) for k, v in domains.items()}
    elapsed = time.monotonic() - mark["monotonic"]

    energy_uj = {}
    for k, v in domains.items():
        delta = end[k] - mark["uj"][k]
        if delta < 0 and v["max_range_uj"]:
            # Single wrap only, deliberately. max_energy_range_uj is
            # ~262,143 J (not 262 J — the digits mislead; ÷ 2^32-1 gives the
            # standard 61.03 µJ unit), so the wrap period is ~4.9 h at 15 W.
            # A second wrap inside one window is unreachable at any rate this
            # rig can produce, while one wrap is likely enough across a full
            # campaign to be worth correcting.
            delta += v["max_range_uj"]
        energy_uj[k] = delta

    return {
        "duration_s": elapsed,
        "energy_uj": energy_uj,
        "avg_power_w": {k: (uj / 1e6) / elapsed for k, uj in energy_uj.items()},
    }


def sample(seconds, domains):
    """Sample every RAPL domain for `seconds`, wall-clock via monotonic clock.

    Returns {"duration_s", "energy_uj": {domain: uj}, "avg_power_w": {domain: w}}.
    32-bit counter wraparound is corrected per-domain via max_energy_range_uj.

    A thin wrapper over start()/stop() rather than a second copy of the
    bracket: an idle window is just a window whose workload is a sleep. It's
    the only caller shape that predates the pair, which makes it the pair's
    regression test — pin_baseline.sh's baseline capture runs through here.
    """
    mark = start(domains)
    time.sleep(seconds)
    return stop(domains, mark)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    record = sample(args.seconds, discover_domains())
    print(json.dumps(record, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(record, f, indent=2)


if __name__ == "__main__":
    main()
