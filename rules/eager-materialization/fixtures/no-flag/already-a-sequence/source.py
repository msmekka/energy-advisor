# no-flag: no comprehension, so nothing is built that was not already there.
# .values() is a lazy view and the literal is three elements that exist in the
# source. Guards against widening the rule to "sum() of any bracketed thing",
# which would fire on both of these.
subtotal = sum(weights.values())
small = sum([1, 2, 3])
