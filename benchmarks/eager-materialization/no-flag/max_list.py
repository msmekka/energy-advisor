#!/usr/bin/env python3
"""no-flag / max_list -- the shape absent.

Shared control code with no-flag/max_set: the materialised comparison varies
only the flag arm's container, so both legs must measure against identical
no-flag code. Copied rather than imported, per the note in no-flag/sum_list.py.
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
