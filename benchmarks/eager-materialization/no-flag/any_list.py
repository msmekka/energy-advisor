#!/usr/bin/env python3
"""no-flag / any_list -- the shape absent, early exit intact.

Same data, same predicate, same result. The generator is evaluated only as far
as any() needs it, so this arm stops at the first truthy element -- roughly
HIT_AT of the way in -- and never allocates.
"""

N = 50_000
HIT_AT = 0.01


def build(n):
    falsy = int(n * HIT_AT)
    return [0] * falsy + [1] * (n - falsy)


def work(data):
    return any(x > 0 for x in data)


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
