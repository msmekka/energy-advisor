#!/usr/bin/env python3
"""no-flag / sum_list -- the shape absent.

Byte-for-byte flag/sum_list minus the brackets. Nothing is materialised; the
generator is consumed lazily. Same build, same arithmetic, same result.

Deliberately duplicated rather than shared with no-flag/sum_list_ctor, whose
work() is identical: a pair is a filename, and each pair is measured at its
own frozen R. Sharing one file across two pairs would couple them.
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
