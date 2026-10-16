# etdc/rig — tier 3, the measurement rig

The scripts that run on the dedicated Linux measurement box (`rc-mw01`, an old
Lenovo with Intel RAPL), not on a dev machine. See
[energy-aware-code-analysis-plan.md](../../energy-aware-code-analysis-plan.md),
section "d) Calibration rig and methodology", for why this tier exists; this
file covers how to operate it.

**The rig is an instrument for validating rules, not for improving programs.**
It measures a `flag` arm against a `no-flag` control and reports a decoupling
quotient — a quality score for the detector. The second arm is a control, not
a recommended rewrite.

RAPL is the primary measurement path. The Shelly plug is validation-tier only:
it sanity-checks RAPL against true wall power and never replaces it.

![One measurement session on the rig](session.svg)

A second drawing, [parent-child.svg](parent-child.svg), shows the structure of
a single run — what the parent does, what the child does, and what the measured
window contains. Both depict the design as intended; they are not a progress
tracker.

---

## Runbook

### Once, to set the rig up

```sh
git clone <repo-url> ~/energy-advisor      # as the campaign user, NOT root
cd ~/energy-advisor
python3 -VV                                # must be 3.12+; 3.14.4 as of writing
```

**Which branch the rig tracks.** `main` by default, which is what a fresh
clone gives you. Checking out a feature branch to measure work in flight is
legitimate — often it is the whole point of having a rig — but a campaign you
intend to *promote* should cite a sha reachable from `main`, or the published
result references code that may be rebased away or never merged. `sync.sh`
fast-forwards whatever branch is checked out; it does not pick one for you.

The checkout must be owned by the user who will run campaigns. `sudo` is for
`pin_baseline.sh` and nothing else — a root `git pull` leaves root-owned files
in a tree the campaign user has to write to.

The Python version is not a detail. CPython 3.12 inlined list/set/dict
comprehensions (PEP 709) but **not** generator expressions, which is the exact
asymmetry the eager-materialization rule rests on. Rows from two versions are
not poolable, and the manifest pins an exact version.

### Every session

```sh
cd ~/energy-advisor
etdc/rig/sync.sh                           # 1. fast-forward; prints the HEAD sha

cd etdc/rig
sudo ./pin_baseline.sh --dry-run           # 2. preview; changes nothing
sudo ./pin_baseline.sh                     # 3. pin + relax + soak + baseline

# 4. run the campaign (unprivileged) — see "Running a measurement" below

sudo ./pin_baseline.sh --restore           # 5. put the machine back
```

Step 2 is worth doing every time on a rig you have not pinned recently. It
prints the pre-change `energy_uj` modes and exercises every path without
touching anything.

Step 3 takes **about eleven minutes** — a 600 s thermal soak then a 30 s idle
baseline. It fails fast if it is going to fail: RAPL permissions are relaxed
and verified in the first second, before the soak, specifically so you do not
wait ten minutes to find out the campaign user cannot read the counters.

### Checking state at any point

```sh
./pin_baseline.sh --status                 # no root needed
```

Run it **as the campaign user**: besides reporting what is pinned and the
current-vs-original RAPL modes, it tells you whether *that user* can read the
counters, which is the question that decides whether a campaign will start.

### Running a measurement

The campaign runner does not exist yet. One run at a time does:

```sh
cd ~/energy-advisor                        # must be the repo root
PYTHONHASHSEED=0 taskset -c 3 python3 -s -m etdc.rig.harness \
    benchmarks/eager-materialization/flag/sum_list.py \
    --n 200000 --r 500 --warmup 2 --out /tmp/run.json
```

Three things in that line matter:

- **`python3 -m` from the repo root.** `-m` puts the working directory on
  `sys.path`, which is how `etdc.rig.harness` resolves with no `pip install`
  and no `PYTHONPATH`. Running `python3 etdc/rig/harness.py` will not work.
- **`PYTHONHASHSEED=0`.** Set construction and membership go through `hash()`,
  and the `max_set` pair exists to measure exactly that path. An unpinned seed
  injects variance into the arm under test.
- **`taskset`** needs no root. Pinning affinity on your own process is
  unprivileged, which is part of why the campaign needs no `sudo` at all.

A fixture also runs on its own, which is useful for a sanity check:

```sh
python3 benchmarks/eager-materialization/flag/sum_list.py 200000
```

### Off-rig, after a campaign

Validate the rows, then promote a campaign worth citing into
`results/<date>-<short-sha>/`. Raw rows in `runs/` are scratch and gitignored;
a promoted campaign carries its rows verbatim alongside the manifest, the rig
provenance, the coefficients and the report. None of this is built yet.

---

## When something goes wrong

| symptom | what it means |
|---|---|
| `pin_baseline.sh` exits part-way | It already rolled itself back. The trap is armed for the whole pinning sequence and disarmed only once the baseline is captured, so the rig is never left half-pinned. |
| `energy_uj is not readable as uid N` | The counters are back at 0400 — usually a reboot, since sysfs modes do not survive one. Re-run `pin_baseline.sh`. |
| `--restore` says "nothing to restore" | No state file. Either it was already restored, or the machine rebooted, which restores everything by itself. |
| campaign refuses to start | Dirty working tree. The sha on each row has to identify the code that produced it; `git status` and commit or revert. |
| `sync.sh` reports divergence | The rig has commits of its own, which should never happen. Inspect with `git log --oneline @{u}..HEAD`; do not resolve it automatically. |

**A reboot is a full restore.** Sysfs modes, cpufreq, SMT and stopped services
are all session state and none of it survives. If the rig is in an unknown
state and you cannot be bothered, reboot it.

---

## What is in here

### `rapl.py`

Reads `/sys/class/powercap/intel-rapl*` directly — not `pyRAPL`, whose
`DeviceAPIFactory` only builds `PkgAPI`/`DramAPI` and filters zones by name, so
it silently misses `psys`/`core`/`uncore` (all of which this rig exposes).

- `discover_domains(root=…)` — walks sysfs, sorts by path **before** assigning
  keys so both the order and the name→path mapping are reproducible, and
  trial-reads each `energy_uj` so an unreadable counter fails here rather than
  inside a measured window.
- `start(domains)` / `stop(domains, mark)` — brackets a workload. Both read
  counters then the clock, in that order, so the sysfs read overhead lands in
  both intervals and cancels in the subtraction. Returns raw per-domain deltas
  and computes no total.
- `sample(seconds, domains)` — an idle window is a window whose workload is a
  sleep, so this is three lines over the pair.

```sh
python3 rapl.py --seconds 30 --out baseline.json
```

### `harness.py`

The child half of a run: one fixture, one measured window, one JSON row. The
window holds the R loop and nothing else — fixture load, domain discovery,
`build(n)`, warmup and `gc.collect()` all happen above it and are separately
timed. Bracketing the whole process instead would put ~20–30 ms of interpreter
startup inside the measurement.

Every row carries the interpreter it ran on. A failure is a row too, with the
error and a traceback and **no `energy_uj` key at all** — a zero delta is
indistinguishable from a genuinely idle window, so nothing is ever substituted.

### `pin_baseline.sh`

```sh
sudo ./pin_baseline.sh              # pin, relax, soak, capture baseline
sudo ./pin_baseline.sh --dry-run    # preview; no root needed, changes nothing
sudo ./pin_baseline.sh --restore    # undo everything, restart stopped services
     ./pin_baseline.sh --status     # what is pinned right now; no root needed
```

Stops noisy services (power/thermal daemons first — `thermald` and friends
actively rewrite cpufreq policy and will contend with the writes below),
relaxes the RAPL counters, disables turbo and SMT, locks governor and
min/max frequency to base clock per core, soaks, then captures an idle
baseline through `rapl.py`.

Every original value is snapshotted — `/var/tmp/energy-advisor-pin.state`, plus
`.services` and `.rapl` sidecars — so `--restore` puts back what was actually
there rather than a guessed default. Reads and writes to cpufreq sysfs both
retry on transient `EBUSY`: offlining an SMT sibling triggers a kernel-side
policy rebuild on its still-online partner, and anything landing mid-rebuild
fails the same way a write would. On `rc-mw01` that teardown has been observed
to take much longer than a couple of seconds, so a persistent warning does not
necessarily mean something is broken — check `cat .../cpuN/online` first.

**On relaxing the counters.** `energy_uj` is commonly 0400 because of PLATYPUS
(CVE-2020-8694): energy readings leak information about other processes' work.
That needs a hostile local user, which a single-user dedicated rig does not
have. Relaxing to 0444 for the session is what keeps ~1200 invocations of
code-under-development from running as root for zero measurement benefit, and
`--restore` bounds it to the session. An ACL scoped to one user would be
tighter, but sysfs does not carry POSIX ACLs.

### `sync.sh`

```sh
./sync.sh            # fast-forward, report what moved
./sync.sh --check    # report only, change nothing
```

The rig is a pull-only consumer: it never commits, never pushes, never merges.
Refuses to run as root, refuses a dirty tree, refuses a detached HEAD, and
fast-forwards only. It also reports whether anything under `etdc/` or
`benchmarks/` changed — that is, whether rows collected before the sync are
still comparable with rows collected after it.

Git rather than rsync because every row carries the commit sha, which keeps
"which code produced this row?" answerable months later. That is the one
question a calibration rig must always be able to answer.

### `shelly_check.py` and `validate_shelly.py`

```sh
python3 shelly_check.py status                        # one-shot Switch.GetStatus
python3 shelly_check.py sample --seconds 30 --out out.json
python3 validate_shelly.py --seconds 30 [--host <ip>]
```

Gen2+ RPC (`/rpc/<Method>?params`). The default host comes from
`shelly-device-info.json`'s `id` as `<id>.local` — if mDNS is flaky, or
`avahi-daemon` has been stopped by a live `pin_baseline.sh` run, pass `--host`
with an IP instead. `sample` diffs `aenergy.total` rather than calling
`Switch.ResetCounters`, so it does not disturb anything else reading it.

`validate_shelly.py` samples RAPL and Shelly over the same window and reports
each RAPL domain's average power as `coverage_ratio` (domain / Shelly total).
Any ratio ≥ 1.0 means the measurement itself is broken — a domain cannot draw
more than the whole machine pulls from the wall.

A wall plug cannot bracket a one-second window, so the Shelly never measures a
fixture. It validates the rig, over long steady-state windows.

### Output directories

- `measurements/` — idle baselines, written by `pin_baseline.sh` as root.
- `runs/` — campaign rows, written by the unprivileged runner, created and
  chowned by `pin_baseline.sh`.

Separate producers, separate owners, which is why they are separate trees: the
runner never needs write access to a root-owned directory. Both are gitignored.

---

## Legacy

`../../rules/measure.py` and the top-level `requirements.txt` (`pyRAPL`,
`pandas`, `pymongo`) predate `rapl.py` and are superseded by it. `measure.py`
is also incomplete as written (`snippet_f.seek()` with no offset). Kept for
reference; not wired into anything above.
