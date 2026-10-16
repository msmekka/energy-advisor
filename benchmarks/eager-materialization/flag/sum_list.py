#!/usr/bin/env python3
"""flag / sum_list -- baseline pair: allocation and nothing else.

Tier-3 counterpart of rules/eager-materialization/fixtures/flag/
list-comprehension. sum() consumes its input exactly once, so the list is
built in full and then discarded an element at a time. sum() cannot
short-circuit, so this pair's only difference is the allocation and the
memory traffic it causes -- which is why it is the baseline every other pair
is read against.

Comparisons this pair serves:
  vs no-flag/sum_list   -- the pair itself: energy_ratio / time_ratio
  vs any_list           -- short_circuits: adds a lost early exit on top
  vs sum_list_ctor      -- spelling: same waste, different syntax
"""

N = 50_000


def build(n):
    return list(range(n))


def work(data):
    return sum([x * x for x in data])


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
