"""Findings: what a rule match tells us, beyond the fact that it matched.

A counter answers "how many". It cannot answer "which site", "how confident",
or "which of the two shapes" -- and those are the questions both triage and the
tier-3 rig need. This module turns tree-sitter matches into Finding records.

Two things are deliberately kept apart, per working-notes.md's "the two claims":

  1. This code has shape X.  Certain, if the query is right. Not a confidence.
  2. Shape X costs energy.   A tier-3 claim this file does NOT make.

So there is no single `confidence` field. There is `impact_confidence`, which
is only ever about claim 2, and it is derived from one thing: whether the trip
count is knowable from the source. Unknown trip counts are the dominant
false-positive source for every rule here, and they are the one part of claim 2
that static analysis can partially settle.
"""

import hashlib
from dataclasses import dataclass, field, asdict


# --- locations ---------------------------------------------------------------
#
# tree-sitter gives 0-based rows and BYTE columns. Everything downstream
# (editors, SARIF, humans reading a traceback) is 1-based with CHARACTER
# columns. Converting in exactly one place is the whole point of this helper:
# an off-by-one here never raises, it just silently points one character to the
# left, and the byte/char distinction only diverges on non-ASCII -- which means
# it passes every hand-written fixture and fails on harvested code.


def char_column(line_bytes, byte_col):
    """Byte offset -> 1-based character column within one line."""
    return len(line_bytes[:byte_col].decode("utf-8", errors="replace")) + 1


def node_region(node, source_lines):
    """1-based, character-column region. end is exclusive, as in tree-sitter."""
    (sr, sc), (er, ec) = node.start_point, node.end_point
    return {
        "start_line": sr + 1,
        "start_col": char_column(source_lines[sr], sc),
        "end_line": er + 1,
        "end_col": char_column(source_lines[er], ec),
    }


# --- enclosing context ------------------------------------------------------
#
# Analysis reports one violation per site. File-level, function-level and
# per-check-in views are groupings over those rows, not different analyses, and
# none of them sum anything: a coefficient is cost per EXECUTION of a shape,
# while static analysis finds SITES, so adding coefficients across sites
# silently assumes each one runs exactly once. These two fields are the group
# keys that make those views possible.

# Nodes that repeat what they contain.
#
# Comprehensions are counted via the COMPREHENSION node, not its for_in_clause:
# the body of a comprehension is a *sibling* of the clause, not a descendant,
# so a parent walk from the body never passes through for_in_clause at all.
# Counting for_in_clause instead silently reports depth 0 for
# `[sum([x for x in row]) for row in grid]`, where the inner site plainly runs
# once per row.
#
# A site's own comprehension is a descendant of the anchor, not an ancestor,
# so it never counts itself.
ITERATING = {
    "for_statement",
    "while_statement",
    "list_comprehension",
    "set_comprehension",
    "dictionary_comprehension",
    "generator_expression",
}

# Arriving at a comprehension FROM a for_in_clause means the site sits in that
# clause's iterable expression, which is evaluated once rather than per
# iteration -- so that step must not count. Exactly right for the first clause;
# for a second clause (`for a in xs for b in f(a)`) the iterable really is
# re-evaluated, so this under-counts there. Accepted: this field is an ordering
# signal, and under-counting a rare shape beats over-counting a common one.
NOT_ITERATED_WITHIN = {"for_in_clause"}

# A `def` or `lambda` is an EXECUTION-COUNT barrier, not merely a scope. A loop
# wrapped around a `def` runs the definition, not the body -- how often the
# body runs is decided by callers, which is a call-graph fact tree-sitter
# cannot see. Counting through it would report depth 1 for a site that may
# never execute at all.
EXECUTION_BARRIERS = {"function_definition", "lambda"}


def _qualname(node):
    """Dotted name for a function_definition, qualified by enclosing
    classes/functions so that grouping on it doesn't collide every `run`."""
    parts = []
    name = node.child_by_field_name("name")
    parts.append(name.text.decode() if name is not None else "<anonymous>")
    cur = node.parent
    while cur is not None:
        if cur.type in ("class_definition", "function_definition"):
            n = cur.child_by_field_name("name")
            parts.append(n.text.decode() if n is not None else f"<{cur.type}>")
        cur = cur.parent
    return ".".join(reversed(parts))


def enclosing_context(node):
    """(enclosing_function, loop_depth) for a site.

    `loop_depth` counts iterating ancestors up to the nearest execution
    barrier. It is the only frequency signal available statically -- absolute
    counts are invisible, but nesting is right there in the tree -- so it gives
    an ORDERING, never a count, and must never be presented as one.

    Because it stops at the barrier, the depth is only comparable WITHIN a
    function: a depth-0 site in a hot handler outranks a depth-2 site in
    startup code. Ranking functions against each other needs an execution
    count this cannot supply. `enclosing_function` is None for module level,
    which is a different fact from depth 0 inside a function (once at import
    vs. once per call), so the two fields have to be read together.
    """
    depth = 0
    function = None
    child, cur = node, node.parent
    while cur is not None:
        if cur.type in EXECUTION_BARRIERS:
            function = _qualname(cur) if cur.type == "function_definition" else "<lambda>"
            break
        if cur.type in ITERATING and child.type not in NOT_ITERATED_WITHIN:
            depth += 1
        child, cur = cur, cur.parent
    return function, depth


def fingerprint(rule_id, path, snippet):
    """Stable identity for a finding, for joining the same site across commits.

    Deliberately excludes the line number: editing anything above a site must
    not rename it, or nothing can be compared to a measurement taken last week.
    Whitespace is normalised so reformatting doesn't either.
    """
    norm = " ".join(snippet.split())
    return hashlib.sha256(f"{rule_id}\0{path}\0{norm}".encode()).hexdigest()[:16]


# --- the record --------------------------------------------------------------


@dataclass
class Finding:
    rule_id: str
    path: str
    pattern_index: int  # which pattern in rule.scm fired; shapes differ in cost
    region: dict
    snippet: str
    fingerprint: str
    enclosing_function: str = None  # None == module level; read WITH loop_depth
    enclosing_loop_depth: int = 0  # within-function ordering signal, not a count
    captures: dict = field(default_factory=dict)  # raw capture text, as matched
    inferences: dict = field(default_factory=dict)  # see infer_* below

    def as_dict(self):
        return asdict(self)


def anchor_node(captures):
    """The node a finding points AT, picked from a match's captures.

    Convention here: `@_name` captures are payload (message text, inferences),
    unprefixed ones are candidate anchors. Where a rule has several unprefixed
    captures -- polling-loop has both @polling_loop and @interval -- the widest
    span wins, since that's the one worth highlighting. Renaming @interval to
    @_interval would make that explicit rather than width-dependent.
    """
    candidates = [n for name, nodes in captures.items() if not name.startswith("_") for n in nodes]
    if not candidates:
        candidates = [n for nodes in captures.values() for n in nodes]
    if not candidates:
        return None
    return max(candidates, key=lambda n: n.end_byte - n.start_byte)


def _text(captures, name):
    nodes = captures.get(name) or []
    return nodes[0] if nodes else None


# --- per-rule inferences -----------------------------------------------------


def _trip_count(node):
    """Classify how many iterations the source commits to, if it says at all.

    Returns ("literal", n) when the source pins it down, ("unknown", None)
    otherwise. tree-sitter cannot resolve `range(n)` or a bare name, and
    pretending otherwise is how a rule corpus fills up with noise.
    """
    if node is None:
        return "unknown", None
    if node.type in ("list", "set", "tuple"):
        return "literal", len(node.named_children)
    if node.type == "call":
        fn = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if fn is not None and fn.text == b"range" and args is not None:
            nums = [c for c in args.named_children if c.type == "integer"]
            if len(nums) == 1 and len(args.named_children) == 1:
                return "literal", int(nums[0].text.decode().replace("_", ""))
    return "unknown", None


# Thresholds for turning a trip count into a confidence about the COST claim.
# Arbitrary, and deliberately in one named place so they can be replaced by
# measured numbers once the rig has produced any.
SMALL_TRIP_COUNT = 1_000

SHORT_CIRCUITING = {"any", "all"}


def infer_eager_materialization(captures, pattern_index):
    func = _text(captures, "_func")
    iterable = _text(captures, "_iterable")
    built = _text(captures, "_built")  # pattern 0: the comprehension node
    ctor = _text(captures, "_ctor")  # pattern 1: list/set/tuple call

    reducer = func.text.decode() if func is not None else None
    kind, n = _trip_count(iterable)

    if built is not None:
        materialised = {"list_comprehension": "list", "set_comprehension": "set"}.get(built.type)
    elif ctor is not None:
        materialised = ctor.text.decode()
    else:
        materialised = None

    # Short-circuiting reducers waste two things, not one: the allocation AND
    # the early exit they can no longer take. Non-short-circuiting ones waste
    # only the allocation. Different cost mechanism, so the rig should expect
    # a different ratio -- this is a hypothesis for tier 3, not a verdict.
    short_circuits = reducer in SHORT_CIRCUITING

    # Removing a set does not preserve the answer under sum(): set()
    # deduplicates. Under any/all/max/min duplicates are irrelevant.
    removal_preserves_semantics = not (materialised == "set" and reducer == "sum")

    if kind == "literal":
        impact_confidence = "high" if n >= SMALL_TRIP_COUNT else "low"
    else:
        impact_confidence = "medium"

    return {
        "reducer": reducer,
        "materialised": materialised,
        "spelling": "comprehension_arg" if pattern_index == 0 else "ctor_wrapper",
        "iterable_kind": iterable.type if iterable is not None else None,
        "trip_count": kind,
        "trip_count_n": n,
        "short_circuits": short_circuits,
        "removal_preserves_semantics": removal_preserves_semantics,
        "impact_confidence": impact_confidence,
    }


# Rules absent from this map still produce Findings -- just with no inferences
# beyond their captures. That's the honest default for a rule nobody has
# thought about yet, and it keeps adding a rule a one-file change.
INFERENCE_HANDLERS = {
    "eager-materialization": infer_eager_materialization,
}


def build_finding(rule_id, path, pattern_index, captures, source_lines):
    anchor = anchor_node(captures)
    if anchor is None:
        return None
    snippet = anchor.text.decode("utf-8", errors="replace")
    function, loop_depth = enclosing_context(anchor)
    handler = INFERENCE_HANDLERS.get(rule_id)
    return Finding(
        rule_id=rule_id,
        path=path,
        pattern_index=pattern_index,
        region=node_region(anchor, source_lines),
        snippet=snippet,
        fingerprint=fingerprint(rule_id, path, snippet),
        enclosing_function=function,
        enclosing_loop_depth=loop_depth,
        captures={
            name: nodes[0].text.decode("utf-8", errors="replace")
            for name, nodes in captures.items()
            if nodes
        },
        inferences=handler(captures, pattern_index) if handler else {},
    )
