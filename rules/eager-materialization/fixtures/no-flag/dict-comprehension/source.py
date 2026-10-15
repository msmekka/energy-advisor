# no-flag: sum() over a dict reduces the KEYS, not the values. That is a
# different shape -- plausibly worth its own rule -- so
# dictionary_comprehension is deliberately left out of rule.scm's alternation
# instead of being flagged and then explained away in the finding text.
key_total = sum({name: weight for name, weight in pairs})
