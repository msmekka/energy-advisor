; rules/eager-materialization/rule.scm
; A reducer that consumes its input exactly once, fed a fully-materialised
; collection instead of a generator. The whole sequence is built in memory
; first, then thrown away one element at a time.
;
; Two spellings of the same waste, so two patterns. Both capture @_func and
; @_iterable for the finding message; neither is a type constraint.

; Shape 1: sum([... for ...]) / sum({... for ...})
;
; The alternation can't carry shared children — `[(a) (b)] body: (_)` is an
; "Impossible pattern" error, not a match failure — so each branch repeats
; the subtree. Only one branch ever binds, so @_iterable is unambiguous.
;
; `body: (_) .` anchors to the FIRST for_in_clause. Without the anchor,
; a nested comprehension (`[x for row in grid for x in row]`) binds
; @_iterable twice and yields two matches for one call site, which
; double-counts in detect.py's len(matches).
((call
    function: (identifier) @_func
    arguments: (argument_list
        [(list_comprehension body: (_) . (for_in_clause right: (_) @_iterable)) @_built
         (set_comprehension  body: (_) . (for_in_clause right: (_) @_iterable)) @_built]))
@eager_materialization

(#any-of? @_func "sum" "any" "all" "max" "min"))

; dictionary_comprehension is deliberately excluded: sum({k: v for ...})
; reduces over the keys, which is a different shape and usually a bug rather
; than a waste. The set branch carries a caveat for the message, not the
; query: set() deduplicates, so sum({...}) -> sum(... for ...) changes the
; answer. Safe to rewrite under any/all/max/min, a question under sum.

; Shape 2: sum(list(... for ...)) — a constructor call wrapping a generator.
;
; Grammar surprise: a sole bare generator argument REPLACES the argument_list
; rather than nesting inside it, so the inner call's `arguments:` is a
; generator_expression directly. The second branch covers the belt-and-braces
; spelling sum(list([... for ...])).
((call
    function: (identifier) @_func
    arguments: (argument_list
        (call function: (identifier) @_ctor
              arguments: [(generator_expression body: (_) . (for_in_clause right: (_) @_iterable))
                          (argument_list (list_comprehension body: (_) . (for_in_clause right: (_) @_iterable)))])))
@eager_materialization

(#any-of? @_func "sum" "any" "all" "max" "min")
(#any-of? @_ctor "list" "set" "tuple"))
