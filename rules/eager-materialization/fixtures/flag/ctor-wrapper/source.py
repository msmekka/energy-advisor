# flag: the generator is already lazy, then list() forces it. Same shape as
# sum([...]) in a different spelling -- which is why rule.scm needs a second
# pattern rather than a wider first one, and why findings carry a `spelling`
# inference: the two may not cost the same.
#
# Grammar note: a sole bare generator argument replaces the argument_list
# instead of nesting inside it, so list()'s `arguments:` field here is a
# generator_expression directly.
total = sum(list(x * x for x in read_values()))
