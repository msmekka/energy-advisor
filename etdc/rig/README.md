# measure/

Tier-3 offline calibration harness — the scripts that run on the dedicated
Linux measurement rig (`rc-mw01`, an old Lenovo with Intel RAPL), not on a
dev machine. See
[energy-aware-code-analysis-plan.md](../../energy-aware-code-analysis-plan.md)
section "d) Calibration rig and methodology" for the why; this file covers
what's actually in this directory and how the pieces fit together.

RAPL is the primary measurement path. The Shelly plug is validation-tier
only — it exists to sanity-check RAPL against true wall power, never to
replace it.

## Current pipeline

```
pin_baseline.sh   # pin turbo/governor/SMT/services, capture idle baseline
  └─ rapl.py      # shared RAPL sysfs reader (also used standalone)

shelly/
  shelly_check.py         # Shelly RPC client: `status` / `sample` subcommands
  validate_shelly.py      # RAPL vs Shelly wall power, sampled concurrently
    ├─ ../rapl.py
    └─ shelly_check.py
  shelly-device-info.json # source of truth for the default host (<id>.local)
  shelly-methods.json     # raw Shelly.ListMethods dump, for reference
  measurements/            # gitignored output dir
```

Everything here is stdlib-only Python (`urllib`, `argparse`, `json`) — no
`pip install` needed to run `rapl.py`, `shelly_check.py`, or
`validate_shelly.py`. `pin_baseline.sh` just shells out to plain `python3`.

### `pin_baseline.sh`

Pins the rig for reproducible measurement, then captures an idle RAPL
baseline to subtract from future snippet measurements.

```
sudo ./pin_baseline.sh              # pin, soak, capture baseline
sudo ./pin_baseline.sh --dry-run    # preview only, no root required, changes nothing
sudo ./pin_baseline.sh --restore    # undo pinning, restart stopped services
```

What it does, in order: stop known noisy services (see `NOISY_SERVICES` —
power/thermal daemons like `thermald`/`tlp`/`power-profiles-daemon` are
stopped *first*, since they actively rewrite cpufreq policy and will contend
with the writes below if left running), disable turbo, disable SMT, lock
governor + min/max frequency to base clock per core, soak
(`SOAK_SECONDS`, default 600s), then sample idle RAPL power for
`SAMPLE_SECONDS` (default 30s) via `rapl.py`.

Every original value it changes is snapshotted to
`/var/tmp/energy-advisor-pin.state` (and `.services`) so `--restore` can put
the machine back the way it was. Reads and writes to cpufreq sysfs files
both retry with backoff on transient `EBUSY` — offlining an SMT sibling
triggers a kernel-side policy rebuild on its still-online partner, and a
read/write that lands mid-rebuild fails exactly like a write would; on
`rc-mw01` this teardown has been observed to take much longer than a couple
of seconds, so a persistent warning here doesn't necessarily mean anything
is broken — check `cat .../cpuN/online` to confirm before assuming a
reboot is needed.

### `rapl.py`

Reads `/sys/class/powercap/intel-rapl*` directly — not `pyRAPL`, which only
knows `PKG`/`DRAM` and would silently miss `psys`/`core`/`uncore` (all of
which this rig exposes). Exports `discover_domains()`, `read_uj()`, and
`sample(seconds)`; also runnable standalone:

```
python3 rapl.py --seconds 30 --out baseline.json
```

Domain discovery walks `/sys/class/powercap` with `followlinks=True` —
`/sys/class/*` entries are symlinks into `/sys/devices/...`, and
`os.walk`'s default `followlinks=False` would silently find zero domains.

### `shelly/shelly_check.py`

```
python3 shelly_check.py status                       # one-shot Switch.GetStatus dump
python3 shelly_check.py sample --seconds 30 --out out.json
```

Talks to the plug's Gen2+ RPC API (`/rpc/<Method>?params`). Default host is
derived from `shelly-device-info.json`'s `id` field as `<id>.local` — if
mDNS resolution is flaky (or `avahi-daemon` has been stopped by a live
`pin_baseline.sh` run), pass `--host <ip>` explicitly instead. `sample`
diffs `aenergy.total` before/after rather than calling
`Switch.ResetCounters`, so it doesn't disturb anything else reading that
counter.

### `shelly/validate_shelly.py`

Samples RAPL and Shelly concurrently over the same window and reports each
RAPL domain's average power as `coverage_ratio` (domain / Shelly total). Any
ratio ≥ 1.0 means the measurement itself is broken (clock skew, misaligned
windows) — a domain can never legitimately draw more than the whole machine
pulls from the wall.

```
python3 shelly/validate_shelly.py --seconds 30 [--host <ip>]
```

Must run on the rig itself — it imports `rapl`, which only finds anything
on a real Linux box with RAPL. It lives in `shelly/` next to
`shelly_check.py` (same-directory import) and reaches `../rapl.py` via an
explicit `sys.path` insert for the parent directory.

## Legacy — not part of the current pipeline

`measure.py` and the top-level `requirements.txt` (`pyRAPL`, `pandas`,
`pymongo`) predate `rapl.py` and are superseded by it — `measure.py` is
also incomplete/broken as written (e.g. `snippet_f.seek()` called with no
offset). Kept for reference; not wired into anything above.
