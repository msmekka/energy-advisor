#!/usr/bin/env python3
"""flag / max_list -- the list leg of the `materialised` comparison.

max() consumes its input once and cannot short-circuit, so this pair isolates
allocation exactly as sum_list does. It exists as a separate pair because the
list-vs-set comparison has to hold the reducer constant, and sum() cannot be
used for it: set() deduplicates, and under sum() that changes the answer
(findings.py sets removal_preserves_semantics False for precisely that
combination). max() is indifferent to duplicates, so the set leg stays a
legitimate control.

Read against flag/max_set, which differs from this file in one character.
"""

N = 50_000


def build(n):
    return list(range(n))


def work(data):
    return max([x * 3 for x in data])


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
