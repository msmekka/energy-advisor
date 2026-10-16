#!/usr/bin/env python3
"""no-flag / sum_list_ctor -- the shape absent.

Identical to no-flag/sum_list by design: the spelling check varies only the
flag arm, so both pairs must share the same control code. See the note in
no-flag/sum_list.py on why this is a copy and not a shared import.
"""

N = 50_000


def build(n):
    return list(range(n))


def work(data):
    return sum(x * x for x in data)


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
