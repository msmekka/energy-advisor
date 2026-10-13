# flag, and a regression guard for the counter: this comprehension has two
# for_in_clauses, so an unanchored `(for_in_clause right: (_) @_iterable)`
# binds twice and reports ONE call site as TWO matches. rule.scm anchors with
# `body: (_) .` to pin @_iterable to the first clause.
#
# Expected contribution to eager_materialization: exactly 1, not 2.
largest = max([cell for row in grid for cell in row])
