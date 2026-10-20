# Show run — five-pair campaign with screen recording

Cut and paste, top to bottom. `[LOCAL]` = your Mac. `[RIG]` = inside the ssh
session. Expected output is given so you can tell immediately if something is
off; anything that deviates, stop rather than continuing.

Rig: `sixoneone@192.168.4.44` (`rc-mw01`). Key auth, no password.
`sudo` on the rig **does** prompt for a password.

---

## 0 — Pre-flight [LOCAL], before recording

```sh
tput cols
```

**Must be ≥ 120.** The decouple table is 117 characters; at 80 it wraps and the
one frame that matters becomes unreadable. Resize now — it cannot be fixed in
post. Bump the font size while you are here.

```sh
cd ~/recurse/F126/energy_advisor
git log --oneline -1          # expect 1d3873d or later
git status --short            # expect only the preso/*.png untracked
```

---

## 1 — Sync and pin [RIG], NOT recorded (~11 min)

```sh
ssh -t sixoneone@192.168.4.44
```

```sh
cd ~/energy-advisor
etdc/rig/sync.sh
```

Expect a fast-forward to `1d3873d` or later, and **no** warning about
untracked files. Sync **once, here only** — never between sweeps, or rows from
before and after are not comparable.

```sh
cd etdc/rig
sudo ./pin_baseline.sh --dry-run
sudo ./pin_baseline.sh
```

~11 min: a 600 s thermal soak, then a 30 s idle baseline. RAPL permissions are
relaxed and verified in the first second, so a permissions failure appears
immediately rather than ten minutes in.

### Verify the pin took

```sh
./pin_baseline.sh --status
cat /sys/devices/system/cpu/online
```

Expect `0-1` — **not** `0-3`. SMT off means `cpu2`/`cpu3` are gone and the
child pins to core 1.

```sh
cd ~/energy-advisor
python3 -c "from etdc.rig import rapl; print(sorted(rapl.discover_domains()))"
```

Expect `['core', 'dram', 'package-0', 'psys', 'uncore']`.

---

## 2 — START RECORDING [LOCAL screen capture]

Record **your Mac's terminal**, not the rig's console. The rig only streams
text, so the encoder never touches core 0. Recording at the rig's own console
would put the video encoder alongside the runner on a two-core machine and
corrupt the measurement — wrong rows, not just a bad video.

### Clip A — the ladder is calibrated, not arbitrary

```sh
python3 -s -m etdc.rig.sweep --dry-run
```

Expect `R: calibrated per (arm, N) to 1.15s` and a seed + probe R per N.
If it prints a bare `R=` column, the sync did not take — stop.

### Clip B — one sweep running (~2.5 min)

```sh
python3 -s -m etdc.rig.sweep --rule eager-materialization --pair sum_list \
    --out etdc/rig/runs/$(date -u +%Y%m%dT%H%M%SZ)-sum_list.jsonl
```

Watch the per-arm calibration lines, e.g. `N=   50,000  flag  R=449
(probe 0.109s)`. Ends with `115 rows in ~137s`.

**Hands off the machine while it runs.** The runner shares core 0 with the OS.

---

## 3 — STOP RECORDING, then the remaining four pairs

Nothing below needs to be on camera.

```sh
for pair in sum_list_ctor max_list max_set any_list; do
  echo "=== $pair ==="
  python3 -s -m etdc.rig.sweep --rule eager-materialization --pair "$pair" \
      --out "etdc/rig/runs/$(date -u +%Y%m%dT%H%M%SZ)-$pair.jsonl"
done
```

~10 min for the four. `any_list` is last deliberately: its no-flag arm is ~57×
faster, so its probe window is very short and the R it extrapolates may be
noisy. Watch its calibration lines. It cannot fail silently — window length is
on every row and the floor check catches it — but if its windows come back
off-target, say so rather than promoting it.

---

## 4 — Restore the rig [RIG]

```sh
cd etdc/rig
sudo ./pin_baseline.sh --restore
./pin_baseline.sh --status
exit
```

Expect `powersave`, SMT `on`, turbo on, `energy_uj` back to `0400`.
Do not leave the rig pinned overnight — `thermald`, `ModemManager` and `fwupd`
stay stopped the whole time it is.

---

## 5 — Pull and promote [LOCAL]

```sh
cd ~/recurse/F126/energy_advisor
scp 'sixoneone@192.168.4.44:~/energy-advisor/etdc/rig/runs/2026*-*.jsonl' etdc/rig/runs/
ls -l etdc/rig/runs/
```

```sh
for f in etdc/rig/runs/2026*-*.jsonl; do
  echo "=== $f ==="
  python3 -s -m etdc.rig.decouple "$f"
done
```

```sh
for f in etdc/rig/runs/2026*-*.jsonl; do
  python3 -s -m etdc.rig.report "$f" --out results/
done
```

Each pair lands in its own `results/<date>-<sha>-<pair>/`. A pair that fails a
check **will not promote** and exits non-zero — that is information, not a
problem. Send me the check list rather than reaching for `--anyway`.

---

## 6 — Re-shootable clips [LOCAL], no rig needed, any time

These run against committed rows, so take as many attempts as you like.

### Clip C — the money shot

```sh
python3 -s -m etdc.rig.decouple results/2026-10-20-6fc254c-sum_list/rows.jsonl
```

Hold on the `N=50,000` row longer than feels natural:

```
sum_list   50,000  404,449  10   0.900 ±0.004  ...  1.115 ±0.006
```

Time ratio **0.900** — the wasteful shape is 10% *faster* on the clock.
Decoupling **1.115** — energy says it is not cheaper at all. That is the
finding, and it is the first fifteen seconds.

### Clip D — the credibility shot

```sh
python3 -s -m etdc.rig.report results/2026-10-20-6fc254c-sum_list/rows.jsonl \
    --out /tmp/showrun-demo
```

Ten mechanical checks printing `pass`. Boring on purpose: it is what separates
this from a benchmark someone ran once.

---

## If something goes wrong

| symptom | meaning |
|---|---|
| `refusing to measure: the tree has uncommitted changes` | something was written inside the repo. Find it with `git status --porcelain`; do not reach for `--allow-dirty`. |
| `PermissionError ... energy_uj ... mode 0o400` | the pin is not active, or `--restore` already ran. Re-pin. |
| `taskset: failed to set affinity: Invalid argument` | SMT is still on, or the pin did not take. Check `cat /sys/devices/system/cpu/online` is `0-1`. |
| dry-run prints a bare `R=` column | the rig is on pre-calibration code. Re-run `etdc/rig/sync.sh`. |
| `refusing to promote: ... already holds the '<pair>' campaign` | a forced `--name` collided. Pick a different one. |
| windows under the floor in decouple notes | a probe mis-sized R. Expected candidate: `any_list`. |
