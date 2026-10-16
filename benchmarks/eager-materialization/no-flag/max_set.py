#!/usr/bin/env python3
"""no-flag / max_set -- the shape absent.

Identical to no-flag/max_list by design; see flag/max_set.py for why the two
legs must share control code, and no-flag/sum_list.py for why it is a copy.
"""

N = 50_000


def build(n):
    return list(range(n))


def work(data):
    return max(x * 3 for x in data)


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
