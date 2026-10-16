#!/usr/bin/env python3
"""flag / sum_list_ctor -- spelling check. A TEMPORARY pair.

Tier-3 counterpart of rules/eager-materialization/fixtures/flag/ctor-wrapper.
The generator is already lazy, then list() forces it: the same waste as
sum_list in a different spelling, which is why rule.scm carries a second
pattern and findings carry a `spelling` inference.

This pair exists to be checked ONCE against sum_list. If the two decoupling
quotients agree, `spelling` collapses as an inference and this pair is
retired -- it is not a standing member of the matrix. Its no-flag arm is
identical to no-flag/sum_list, which is the point: the arms differ only in
how the flag side spells the materialisation.
"""

N = 50_000


def build(n):
    return list(range(n))


def work(data):
    return sum(list(x * x for x in data))


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
