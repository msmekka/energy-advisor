#!/usr/bin/env python3
"""flag / any_list -- short_circuits: allocation PLUS a lost early exit.

any() stops at the first truthy element, but the list is built in full before
any() sees element zero. So the flag arm pays for n elements while the no-flag
arm pays for HIT_AT * n of them. That is the mechanism behind the
`short_circuits` inference, and it is why this pair is read against sum_list
rather than on its own: sum_list isolates the allocation, this adds the
forgone early exit.

The predicate's truth distribution is load-bearing, not incidental. Data is
built falsy for the first HIT_AT of its length and truthy after, so the early
exit has something to bite on at a known, fixed point. A predicate that is
never satisfied would make this pair a duplicate of sum_list under a different
reducer; one satisfied at element zero would measure call overhead. HIT_AT
belongs in the campaign manifest alongside N, R and warmup.
"""

N = 50_000
HIT_AT = 0.01


def build(n):
    falsy = int(n * HIT_AT)
    return [0] * falsy + [1] * (n - falsy)


def work(data):
    return any([x > 0 for x in data])


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else N
    print(work(build(n)))
