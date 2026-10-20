# 2026-10-20-95ce499-sum_list — the first ratio(N) campaign

> **Superseded for citation by [`../2026-10-20-6fc254c-sum_list/`](../2026-10-20-6fc254c-sum_list/README.md)**,
> the calibrated re-run on the same pin session 37 minutes later, which passes
> every promotion check. This campaign is kept because it is the run that found
> the defect, and because it is the control that shows calibration changed
> precision and nothing structural.

Hand-written note. `report.md` beside it is **generated** and regenerating it
must leave an empty `git diff`, so standing context lives here instead.

## This campaign tracks the pre-calibration design

R was chosen from a fixed `R·N` constant — `WINDOW_WORK = 72 × 200,000` — on
the assumption that cost per element is roughly constant across N, so holding
`R·N` would hold the window near 1 s.

**This campaign is what disproved that assumption.** Per-element cost rose
with N as the working set outgrew cache:

| N | R | window (flag arm) | ns/element |
|---:|---:|---:|---:|
| 50,000 | 288 | 0.732 s | 50.84 |
| 100,000 | 144 | 0.936 s | 64.98 |
| 200,000 | 72 | 0.989 s | 68.68 |
| 400,000 | 36 | 1.042 s | 72.38 |
| 800,000 | 18 | 1.100 s | 76.40 |

The constant was calibrated at N = 200,000 and nails it. It undershoots at the
small end, putting 26 windows under the 1 s floor at N = 50,000 and 100,000 —
the failed promotion check recorded in `report.md`. The ladder's most
interesting point is therefore also its least calibrated one.

## What replaced it

`sweep.py` now probes each `(arm, N)` and scales R to a target window, per arm
as well as per N. Campaigns from that design carry `r_policy: "calibrated"` and
`target_window_s` in each row's sweep header; this campaign's rows carry
neither, which is how the two are told apart without reference to dates.

Against the per-element costs measured here, calibration would have run
N = 50,000 at R ≈ 453 for a 1.15 s window instead of 0.732 s.

## Why it is kept despite the failed check

The result does not depend on the defect. Decoupling is distinguishable from
parity at every N, including the four points whose windows cleared the floor,
and the N = 200,000 anchor reproduced the 2026-10-16 measurement (1.096 here
against 1.083 then). The uncalibrated points are the *small*-N ones, and the
window-floor concern is about precision, not bias — a short window widens the
error bar, it does not invent a direction.

It is also the run that found the problem, which is most of why it is worth
keeping. Re-measuring under calibration should move the 50,000 and 100,000
points; if it moves the four calibrated points too, something else is wrong and
this archive is the comparison that would show it.

## Reproducing the old behaviour

```sh
python3 -s -m etdc.rig.sweep --no-calibrate --window-work 14400000 ...
```

`--no-calibrate` exists for exactly this: comparing a re-run against this
archive without the calibration change as a confound.
