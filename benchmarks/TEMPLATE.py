#!/usr/bin/env python3
"""TEMPLATE — how to write a tier-3 benchmark fixture.

Copy this file to benchmarks/<rule-name>/flag/<pair>.py, write its twin at
benchmarks/<rule-name>/no-flag/<pair>.py, and change nothing but the shape.

A fixture serves two callers and must satisfy both:

  standalone   python3 benchmarks/TEMPLATE.py 50000
               The __main__ guard below makes it runnable, so a fixture can be
               smoke-tested, profiled or read end-to-end on its own.

  harness      loaded by path via importlib.util.spec_from_file_location under
               a module name that is NOT "__main__", so the guard stays inert.
               The harness takes `build` and `work` by attribute and owns the
               RAPL window:

                   data = build(n)        # outside the window
                   gc.collect()
                   mark = rapl.start(domains)
                   for _ in range(r): work(data)
                   record = rapl.stop(domains, mark)

The contract, and why each clause is there:

1. Expose BOTH `build(n)` and `work(data)`, always. A shape needing no input
   gets a `build` that returns None. The harness must never branch on which
   functions a fixture happens to define -- identical harness code across arms
   is the whole reason the harness is shared.

2. `build` must return a RE-ITERABLE -- list or tuple, never a generator or
   any other one-shot iterator. `work` is called R times against the same
   object. A generator would be exhausted after the first call and every
   remaining iteration would measure near-nothing.

3. `work` must be pure and idempotent: it must not mutate `data`, and call
   number R must do the same work as call number 1. Return the result rather
   than discarding it.

4. Only the shape may differ between the flag and no-flag arms. Same `build`,
   same data, same predicate, same constants. Anything else that differs is
   something you are measuring by accident.

5. Module level holds definitions and constants ONLY -- no work, no I/O, and
   no argparse. Module-level `parse_args()` would, under the harness, parse
   the HARNESS's argv. Anything expensive at module scope lands in the
   fixture-load time the harness records as `import_s`, where it shows up as
   an outlier rather than as unexplained measurement variance.

6. N below is a smoke-test default so the standalone run is instant. The N
   used for measurement comes from the campaign manifest and is swept -- it is
   the x-axis, never a duration knob. Use R for duration.
"""

# Smoke-test default only. Measurement N comes from the manifest.
N = 50_000


def build(n):
    """Construct the input. Runs outside the measured window.

    Returns a re-iterable (see clause 2).
    """
    return list(range(n))


def work(data):
    """The shape under test. Called R times inside the measured window.

    Everything on this line that is not the shape must be identical in the
    twin arm. Here the shape is the brackets: the list is built in full and
    then consumed one element at a time.
    """
    return sum([x * x for x in data])
    # no-flag twin:   return sum(x * x for x in data)


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
