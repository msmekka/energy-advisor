# flag: sum() consumes its input exactly once, so the list is built in memory
# in full and then discarded one element at a time. The arithmetic is
# identical with or without the brackets -- what the brackets add is
# allocation and memory traffic, which is why this shape is a decoupling
# candidate rather than just a slow one.
total = sum([x * x for x in range(1_000_000)])
