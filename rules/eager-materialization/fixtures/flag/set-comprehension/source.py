# flag: the set is built in full before any() looks at the first element, and
# any() would otherwise stop at the first truthy one.
#
# Note for the finding, not the query: under any/all/max/min the set's
# deduplication cannot change the answer, but under sum() it can. So the
# shape's presence is certain either way, while what its absence would even
# mean depends on the reducer -- hence the removal_preserves_semantics
# inference rather than a blanket claim.
ok = any({is_valid(row) for row in fetch_rows()})
