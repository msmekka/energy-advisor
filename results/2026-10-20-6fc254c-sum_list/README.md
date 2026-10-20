# 2026-10-20-6fc254c-sum_list — the calibrated ratio(N) campaign

Hand-written note. `report.md` beside it is **generated** and regenerating it
must leave an empty `git diff`, so standing context lives here instead.

**This is the campaign to cite.** All ten promotion checks pass; it was
promoted without `--anyway`. It supersedes
[`../2026-10-20-95ce499-sum_list/`](../2026-10-20-95ce499-sum_list/README.md), which is kept
because it is the run that found the calibration defect.

## What differs from the first campaign

Same rig, same pin session, same pair, same ladder, same 10 ratio pairs per
point, 37 minutes apart. The only change is that R is now calibrated per
`(arm, N)` by a probe rather than derived from a fixed `R·N` constant, so every
window lands near 1.15 s instead of drifting from 0.73 s to 1.10 s across the
ladder.

| N | decoupling, uncalibrated | decoupling, calibrated | shift | old window |
|---:|---:|---:|---:|---:|
| 50,000 | 1.132 ±0.011 | 1.115 ±0.006 | **−0.017** | 0.732 s |
| 100,000 | 1.122 ±0.004 | 1.109 ±0.007 | −0.013 | 0.936 s |
| 200,000 | 1.096 ±0.007 | 1.107 ±0.005 | +0.011 | 0.989 s |
| 400,000 | 1.094 ±0.006 | 1.086 ±0.004 | −0.008 | 1.042 s |
| 800,000 | 1.067 ±0.003 | 1.066 ±0.003 | **−0.001** | 1.100 s |

**The shift is ordered by how uncalibrated each point was.** N = 800,000,
whose window was already 1.100 s, is unchanged to the third decimal.
N = 50,000, whose window was 0.732 s, moved most — and moved *down*.

That is the window-floor effect behaving exactly as the design predicted:
short windows inflate the quotient. It is the same effect that retired the
R = 5 reading of 1.21 in favour of 1.083 at R = 72 on 2026-10-16, now seen
across a whole ladder rather than at a single point. The ladder's spread
tightened from 0.065 to 0.049 because the inflated end came down to meet the
rest.

So calibration fixed a **precision** problem and changed nothing structural.
Both campaigns agree on every qualitative claim.

## What replicated

- **Time ratio at N = 50,000: 0.901 → 0.900.** The flagged shape is ~10%
  *faster* on the clock, while energy says it is not cheaper at all
  (1.004 ±0.006 — parity). Wall-clock does not merely miss this cost, it
  points the other way.
- **Decoupling distinguishable from parity at every N**, weakest point
  1.066 ±0.003, ~22 SEM above 1.0.
- **The quotient declines with N** (slope −0.041 ±0.008 per decade, against
  −0.052 ±0.007 uncalibrated) — still the opposite of what harness dilution
  would produce, because the time ratio climbs with N while the energy ratio
  stays flatter.

## Known caveats

- The idle-drift note still fires: `package-0` ranged 0.426–0.639 W, narrower
  than the first campaign's 0.42–0.83 W. Each row is subtracted against its
  nearest idle window, so this is reported rather than averaged away. The
  first idle window of a sweep is taken *before* any child has run and so is
  not a floor "between runs"; on the first campaign, excluding it moved one
  point by 0.005.
- One pair, one rule. `sum_list` isolates allocation only. The other four
  pairs — `sum_list_ctor`, `any_list`, `max_list`, `max_set` — are what
  separate *spelling*, *short-circuiting* and *materialised* as mechanisms,
  and none has been measured on the rig yet.
