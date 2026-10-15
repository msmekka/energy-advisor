# no-flag: the shape is absent. Nothing is materialised -- the generator is
# consumed lazily. Byte-for-byte the flag/list-comprehension fixture minus the
# brackets, which is what makes the pair usable as a control on the rig: the
# two differ in exactly the thing the rule names and nothing else.
total = sum(x * x for x in range(1_000_000))
