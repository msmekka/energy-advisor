#!/usr/bin/env python3
"""flag / max_set -- the set leg of the `materialised` comparison.

Tier-3 counterpart of rules/eager-materialization/fixtures/flag/
set-comprehension. One character different from flag/max_list -- `{` for `[` --
so the difference between the two pairs' decoupling quotients is the allocator
path and the hashing, which is the mechanism argument the `materialised`
inference rests on.

`x * 3` over range(n) is injective, so the set holds n distinct elements and
deduplication is inert: the no-flag arm returns the same value, and this pair
is a valid control for this data even though sum({...}) would not be. That is
a property of the data build() produces, not of the shape -- changing build()
to emit duplicates would silently turn the set arm into an O(1)-space
benchmark and make the comparison meaningless.
"""

N = 50_000


def build(n):
    return list(range(n))


def work(data):
    return max({x * 3 for x in data})


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
