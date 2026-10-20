#!/usr/bin/env python3
"""Draw ratio(N) from a decouple.py summary. Writes SVG and a Markdown table.

    python3 -s -m etdc.rig.decouple runs/sweep.jsonl --json summary.json
    python3 -s -m etdc.rig.chart summary.json --svg ratio-n.svg --table ratio-n.md

Hand-rolled SVG, no dependency, for one reason: the report is committed, and
the test that it still matches the rows beside it is regenerating it and
finding an empty `git diff`. matplotlib's SVG carries embedded font subsets and
generated element ids that churn between runs, so a regenerated chart would
diff even when the numbers did not -- which destroys the only cheap check
available. Nothing here is non-deterministic: no timestamp, no id counter, no
dict iteration order that isn't sorted, and every number formatted to a fixed
number of places.

Colors are emitted as resolved hex PRESENTATION ATTRIBUTES, with the embedded
stylesheet carrying only the dark-mode override. CSS beats a presentation
attribute in the cascade, so a themed renderer gets both modes while a renderer
that ignores CSS entirely still draws a correct light-mode chart. Driving the
marks from CSS custom properties instead reads tidier and is a trap: librsvg
does not resolve them, so the whole chart renders as empty black -- verified,
not assumed -- and this SVG has to survive GitHub, a terminal-side viewer and
whatever converts it for a slide.

Form is EMPHASIS, not two categorical series. The finding is "energy
distinguishes these programs and wall-clock does not", so energy carries the
accent hue and time is de-emphasis gray -- one point, one color. Painting both
in categorical hues would say "here are two equally interesting series", which
is the most common way a chart misses its own point.

Two panels, raw and idle-subtracted, on a SHARED y-axis. Side by side because
the subtraction trades bias for noise and the gap between the panels is the
honest way to show that trade; shared y because a reader comparing two panels
drawn to different scales is being misled.

Palette is the reference instance's slot 1 (blue) against de-emphasis gray.
Validated in both modes: CVD separation dE 15.9 (protan), normal-vision 17.8
light / 17.0 dark, contrast >= 3:1 on both surfaces. The one reported FAIL is
the chroma floor on the gray -- "reads gray", which is what a de-emphasis
series is FOR, and that check is scoped to categorical palettes. Recorded here
rather than silenced.
"""
import argparse
import json
import math
import sys

# Light / dark pairs. Both modes are selected, not flipped: the dark steps are
# the reference palette's own dark column, stepped for the dark surface.
INK = {
    "surface": ("#fcfcfb", "#1a1a19"),
    "primary": ("#0b0b0b", "#ffffff"),
    "secondary": ("#52514e", "#c3c2b7"),
    "muted": ("#898781", "#898781"),
    "grid": ("#e1e0d9", "#2c2c2a"),
    "axis": ("#c3c2b7", "#383835"),
    "accent": ("#2a78d6", "#3987e5"),
}
# The de-emphasis series. Same value in both modes, >= 3:1 on both surfaces,
# so it carries no themed class.
CONTEXT = "#898781"

# Mark specs: 2px lines, markers >= 8px across (r >= 4) with a 2px surface ring
# so they stay legible where they cross a line, hairline solid grid one step
# off the surface. Never dashed -- a dashed rule reads as "projection".
LINE_W = 2
MARKER_R = 4
RING_W = 2
HAIRLINE = 1

PANELS = (
    ("raw", "energy_ratio_raw"),
    ("idle-subtracted", "energy_ratio_sub"),
)


def paint(role, prop="fill"):
    """A themable paint: light hex inline, class for the dark override."""
    return '{0}="{1}" class="{2}-{3}"'.format(prop, INK[role][0], prop[0], role)


def marker(role):
    """Fill + 2px surface ring on one element, with ONE class attribute.

    Composing two paint() calls here emits `class` twice, which is invalid XML
    and makes the whole document unparseable -- a failure that only shows up in
    a strict renderer, not in a browser.
    """
    ring = INK["surface"][0]
    if role in INK:
        return 'fill="{0}" stroke="{1}" class="f-{2} s-surface"'.format(
            INK[role][0], ring, role)
    return 'fill="{0}" stroke="{1}" class="s-surface"'.format(role, ring)


def ink(role, cls, prop="fill"):
    """Same, for an element that also carries a type class (text sizes)."""
    return '{0}="{1}" class="{2} {3}-{4}"'.format(
        prop, INK[role][0], cls, prop[0], role)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def nice_n(n):
    """50000 -> 50k. The axis reads as trip counts, not as digits."""
    if n >= 1_000_000 and n % 1_000_000 == 0:
        return "{0}M".format(n // 1_000_000)
    if n >= 1000 and n % 1000 == 0:
        return "{0}k".format(n // 1000)
    return "{0:,}".format(n)


def collect(summary, pair=None):
    """Points for one pair, in N order.

    A point missing a series is kept rather than dropped: a panel that cannot
    be drawn has to say so, and that requires knowing the N it could not draw.
    """
    points = [p for p in summary.get("points", [])
              if pair is None or p.get("pair") == pair]
    points = [p for p in points if isinstance(p.get("n"), int)]
    points.sort(key=lambda p: p["n"])
    return points


def series_of(points, key):
    """[(n, mean, sem)] for the points that actually carry `key`."""
    out = []
    for p in points:
        st = p.get(key)
        if st and st.get("mean") is not None:
            out.append((p["n"], st["mean"], st.get("sem") or 0.0))
    return out


def y_domain(all_series):
    """A shared y range covering every drawn series AND parity at 1.0.

    1.0 is always in frame because the whole question is which side of it a
    series sits on. A chart that cropped parity out of view would let a ratio
    of 1.4 and a ratio of 1.04 look alike.
    """
    vals = [1.0]
    for s in all_series:
        for _, mean, sem in s:
            vals += [mean - sem, mean + sem]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        lo, hi = lo - 0.05, hi + 0.05
    pad = (hi - lo) * 0.14
    return lo - pad, hi + pad


def ticks_for(lo, hi, target=6):
    """Round y ticks at a 1/2/5 step, so labels read 1.0, 1.1, 1.2..."""
    span = hi - lo
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 0.01
    step = mag
    for mult in (1, 2, 2.5, 5, 10):
        step = mag * mult
        if step >= raw:
            break
    first = math.ceil(lo / step) * step
    out, v = [], first
    while v <= hi + step * 1e-6:
        out.append(round(v, 10))
        v += step
    return out, step


def svg(summary, pair, title, subtitle):
    points = collect(summary, pair)
    if not points:
        raise SystemExit("no points with an integer N in the summary")

    time_s = series_of(points, "time_ratio")
    panel_series = [{"label": label, "energy": series_of(points, key)}
                    for label, key in PANELS]

    drawn = [time_s] + [ps["energy"] for ps in panel_series if ps["energy"]]
    ylo, yhi = y_domain(drawn)
    yticks, _ = ticks_for(ylo, yhi)

    ns = [p["n"] for p in points]
    xlo, xhi = math.log10(min(ns)), math.log10(max(ns))
    if xhi - xlo < 1e-9:
        xlo, xhi = xlo - 0.2, xhi + 0.2

    # Geometry. The container includes the x-axis band and the legend, so
    # nothing needs a nested scroll to be read.
    W, H = 900, 460
    # pad_r has to hold the right-hand direct label, not just the plot: the
    # last marker sits 16px inside the panel and its value label runs ~36px
    # past that. Sized at 18 it cropped "1.330" to "1.33" -- a clipped number
    # is worse than no label, and only shows up on render.
    pad_l, pad_r, pad_t, pad_b = 54, 50, 104, 74
    gutter = 40
    plot_w = (W - pad_l - pad_r - gutter) / 2
    plot_h = H - pad_t - pad_b

    def px(n, panel):
        x0 = pad_l + panel * (plot_w + gutter)
        frac = (math.log10(n) - xlo) / (xhi - xlo) if xhi > xlo else 0.5
        # Inset so a marker at either end is not clipped by the panel edge.
        return x0 + 16 + frac * (plot_w - 32)

    def py(v):
        frac = (v - ylo) / (yhi - ylo)
        return pad_t + plot_h - frac * plot_h

    o = []
    a = o.append
    a('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {0} {1}" '
      'width="{0}" height="{1}" font-family="system-ui, -apple-system, '
      '&quot;Segoe UI&quot;, sans-serif" role="img">'.format(W, H))

    # Dark overrides only. The light values are already on every element as
    # presentation attributes, so this block adds a mode rather than supplying
    # the colors -- which is what keeps the chart correct in a renderer with
    # no CSS support. Declared under both the media query and the data-theme
    # scope so an OS setting and a viewer's toggle both work, toggle winning.
    def dark_rules(prefix, indent):
        rows = []
        for role, (_, dark) in sorted(INK.items()):
            rows.append("{0}{1}.f-{2} {{ fill: {3}; }}".format(
                indent, prefix, role, dark))
            rows.append("{0}{1}.s-{2} {{ stroke: {3}; }}".format(
                indent, prefix, role, dark))
        return "\n".join(rows)

    a("<style>\n"
      "  .ax { font-size: 11px; }\n"
      "  .pl { font-size: 12.5px; font-weight: 600; }\n"
      "  .ti { font-size: 17px; font-weight: 600; }\n"
      "  .su { font-size: 12.5px; }\n"
      "  .lg { font-size: 12px; }\n"
      "  .dl { font-size: 11.5px; font-weight: 600; }\n"
      "  @media (prefers-color-scheme: dark) {\n"
      + dark_rules(":root:not([data-theme=\"light\"]) ", "    ") + "\n"
      "  }\n"
      + dark_rules(':root[data-theme="dark"] ', "  ") + "\n"
      "</style>")

    a('<rect width="{0}" height="{1}" {2}/>'.format(W, H, paint("surface")))
    a('<text {0} x="{1}" y="30">{2}</text>'.format(
        ink("primary", "ti"), pad_l, esc(title)))
    a('<text {0} x="{1}" y="50">{2}</text>'.format(
        ink("secondary", "su"), pad_l, esc(subtitle)))

    # Legend above the plots. Always present at two series; identity is the
    # colored line-key beside the text, never the text's own color.
    lx = pad_l
    for role, name in (("accent", "energy per repetition"),
                       (None, "elapsed time per repetition")):
        sk = paint(role, "stroke") if role else 'stroke="{0}"'.format(CONTEXT)
        a('<line x1="{0}" y1="70" x2="{1}" y2="70" {2} stroke-width="{3}" '
          'stroke-linecap="round"/>'.format(lx, lx + 18, sk, LINE_W))
        a('<circle cx="{0}" cy="70" r="{1}" {2} stroke-width="{3}"/>'.format(
            lx + 9, MARKER_R, marker(role or CONTEXT), RING_W))
        a('<text {0} x="{1}" y="74">{2}</text>'.format(
            ink("secondary", "lg"), lx + 26, esc(name)))
        lx += 30 + 7.4 * len(name)

    for panel, ps in enumerate(panel_series):
        x0 = pad_l + panel * (plot_w + gutter)

        a('<text {0} x="{1}" y="{2}">{3}</text>'.format(
            ink("secondary", "pl"), x0, pad_t - 12, esc(ps["label"])))

        # Grid: hairline, solid, one step off the surface.
        for t in yticks:
            y = py(t)
            a('<line x1="{0}" y1="{1:.1f}" x2="{2}" y2="{1:.1f}" {3} '
              'stroke-width="{4}"/>'.format(
                  x0, y, x0 + plot_w, paint("grid", "stroke"), HAIRLINE))
            if panel == 0:
                a('<text {0} x="{1}" y="{2:.1f}" text-anchor="end">'
                  '{3:.2f}</text>'.format(
                      ink("muted", "ax"), x0 - 9, y + 4, t))

        # Parity. Solid, in the axis ink, one step stronger than the grid, and
        # labeled -- it is the line the whole chart is about, so it is named
        # rather than left for the reader to infer from the y-axis.
        yp = py(1.0)
        a('<line x1="{0}" y1="{1:.1f}" x2="{2}" y2="{1:.1f}" {3} '
          'stroke-width="{4}"/>'.format(
              x0, yp, x0 + plot_w, paint("axis", "stroke"), LINE_W))
        # Annotated at the LEFT end. At the right it lands on top of the time
        # series' own end-label, because a time ratio near parity IS this
        # line -- which is exactly the case the chart exists to show, so the
        # collision is the normal case rather than an edge one.
        # One word, at whichever END has more room. A fixed side cannot work:
        # the series approach parity exactly where the finding is, so the
        # crowded end is data-dependent -- left-anchoring was clear on a
        # ladder whose ratios all sat high, and landed on top of the 50k
        # energy marker once a real ladder dipped toward parity there.
        # Clearance is measured in pixels against every series drawn at that
        # end, so the choice is deterministic rather than a guess.
        def clearance(idx):
            vals = [d[idx][1] for d in (time_s, ps["energy"]) if d]
            return min((abs(py(v) - yp) for v in vals), default=1e9)

        if clearance(0) >= clearance(-1):
            a('<text {0} x="{1}" y="{2:.1f}">parity</text>'.format(
                ink("muted", "ax"), x0 + 4, yp - 8))
        else:
            a('<text {0} x="{1}" y="{2:.1f}" text-anchor="end">parity</text>'
              .format(ink("muted", "ax"), x0 + plot_w - 4, yp - 8))

        # X axis.
        a('<line x1="{0}" y1="{1}" x2="{2}" y2="{1}" {3} stroke-width="{4}"/>'
          .format(x0, pad_t + plot_h, x0 + plot_w,
                  paint("axis", "stroke"), HAIRLINE))
        for n in ns:
            a('<text {0} x="{1:.1f}" y="{2}" text-anchor="middle">{3}</text>'
              .format(ink("muted", "ax"), px(n, panel),
                      pad_t + plot_h + 18, esc(nice_n(n))))
        a('<text {0} x="{1:.1f}" y="{2}" text-anchor="middle">'
          'trip count N (log scale)</text>'.format(
              ink("muted", "ax"), x0 + plot_w / 2, pad_t + plot_h + 40))

        if not ps["energy"]:
            # An undrawable panel says why. Leaving it blank would read as
            # "no difference" rather than "not measured".
            a('<text {0} x="{1:.1f}" y="{2:.1f}" text-anchor="middle">'
              'no usable {3} energy</text>'.format(
                  ink("secondary", "su"), x0 + plot_w / 2,
                  pad_t + plot_h / 2, esc(ps["label"])))
            a('<text {0} x="{1:.1f}" y="{2:.1f}" text-anchor="middle">'
              '(no idle window to subtract, or a negative E_active)</text>'
              .format(ink("muted", "ax"), x0 + plot_w / 2,
                      pad_t + plot_h / 2 + 18))
            continue

        for name, data, role in (("elapsed time", time_s, None),
                                 ("energy", ps["energy"], "accent")):
            if not data:
                continue
            sk = paint(role, "stroke") if role else 'stroke="{0}"'.format(CONTEXT)
            mk = marker(role or CONTEXT)

            # Error bars first, so the markers ring over them.
            for n, mean, sem in data:
                if sem <= 0:
                    continue
                x = px(n, panel)
                a('<line x1="{0:.1f}" y1="{1:.1f}" x2="{0:.1f}" y2="{2:.1f}" '
                  '{3} stroke-width="1.5" stroke-linecap="round" '
                  'opacity="0.75"/>'.format(
                      x, py(mean - sem), py(mean + sem), sk))
                for yy in (mean - sem, mean + sem):
                    a('<line x1="{0:.1f}" y1="{1:.1f}" x2="{2:.1f}" '
                      'y2="{1:.1f}" {3} stroke-width="1.5" opacity="0.75"/>'
                      .format(x - 4, py(yy), x + 4, sk))

            pts = " ".join("{0:.1f},{1:.1f}".format(px(n, panel), py(m))
                           for n, m, _ in data)
            a('<polyline points="{0}" fill="none" {1} stroke-width="{2}" '
              'stroke-linejoin="round" stroke-linecap="round"/>'.format(
                  pts, sk, LINE_W))

            for n, mean, sem in data:
                a('<circle cx="{0:.1f}" cy="{1:.1f}" r="{2}" {3} '
                  'stroke-width="{4}"><title>{5} at N={6:,}: {7:.3f} '
                  '±{8:.3f} (SEM)</title></circle>'.format(
                      px(n, panel), py(mean), MARKER_R, mk, RING_W,
                      esc(name), n, mean, sem))

            # One direct label per series, at the right-hand end only. A value
            # on every point is noise; the axis and tooltips carry the rest.
            n, mean, _ = data[-1]
            dl = (ink(role, "dl") if role
                  else 'class="dl" fill="{0}"'.format(CONTEXT))
            a('<text {0} x="{1:.1f}" y="{2:.1f}">{3:.3f}</text>'.format(
                dl, px(n, panel) + 9, py(mean) + 4, mean))

    a("</svg>")
    return "\n".join(o)


def table(summary, pair):
    """The table view. Not optional -- it is how the values stay available to
    a reader the chart does not serve: a screen reader, a muted recording, a
    terminal, and anyone who wants the raw column the chart de-emphasises."""
    points = collect(summary, pair)
    dom = " + ".join(summary.get("domains", []))
    rows = [
        "Energy domains: `{0}`. Ratios are per repetition (E/R and T/R), so R "
        "may differ between arms. Uncertainty is ±SEM over the "
        "adjacent-pair ratios.".format(dom),
        "",
        "| N | R | pairs | time ratio | energy ratio (raw) | decoupling (raw) "
        "| energy ratio (idle-subtracted) | decoupling (idle-subtracted) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def cell(st):
        if not st or st.get("mean") is None:
            return "—"
        return "{0:.3f} ±{1:.3f}".format(st["mean"], st.get("sem") or 0.0)

    for p in points:
        r = ",".join(str(x) for x in p.get("r", []) if x is not None)
        rows.append(
            "| {0:,} | {1} | {2} | {3} | {4} | {5} | {6} | {7} |".format(
                p["n"], r, p.get("couples", 0),
                cell(p.get("time_ratio")),
                cell(p.get("energy_ratio_raw")),
                cell(p.get("decoupling_raw")),
                cell(p.get("energy_ratio_sub")),
                cell(p.get("decoupling_sub"))))
    return "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("summary", help="JSON written by decouple.py --json")
    parser.add_argument("--pair", default=None,
                        help="which pair to draw; default the only one present")
    parser.add_argument("--title", default=None)
    parser.add_argument("--subtitle", default=None)
    parser.add_argument("--svg", default=None, help="write the chart here")
    parser.add_argument("--table", default=None,
                        help="write the Markdown table here")
    args = parser.parse_args()

    with open(args.summary) as f:
        summary = json.load(f)

    pairs = sorted({p.get("pair") for p in summary.get("points", [])})
    pair = args.pair
    if pair is None:
        if len(pairs) != 1:
            parser.error("summary holds {0} pairs ({1}); name one with --pair"
                         .format(len(pairs), pairs))
        pair = pairs[0]

    title = args.title or "{0}: energy separates what wall-clock cannot".format(pair)
    subtitle = args.subtitle or (
        "flag arm / no-flag arm, per repetition, at each trip count. "
        "Above parity means the flagged shape costs more.")

    doc = svg(summary, pair, title, subtitle)
    if args.svg:
        with open(args.svg, "w") as f:
            f.write(doc + "\n")
        sys.stderr.write("chart -> {0}\n".format(args.svg))
    elif not args.table:
        print(doc)

    if args.table:
        with open(args.table, "w") as f:
            f.write(table(summary, pair))
        sys.stderr.write("table -> {0}\n".format(args.table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
