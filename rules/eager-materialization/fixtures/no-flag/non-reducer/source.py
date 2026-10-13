# no-flag: sorted() cannot start until it holds every element, so the list is
# not surplus -- it is the input the callee requires. This rule's shape is
# about single-pass reducers specifically, which is why @_func is constrained
# by #any-of? rather than matching any identifier.
#
# This is the false positive the original rule produced: #any_of? (underscore)
# is not a predicate tree-sitter knows, and an unknown predicate is silently
# ignored rather than rejected, so the function-name filter never ran at all.
ranked = sorted([score(x) for x in candidates])
