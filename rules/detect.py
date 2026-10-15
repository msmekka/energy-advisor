import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor, QueryError
import argparse
import ast
import json
import os
from astanalyzers import ForLoopAnalyzer, IfAnalyzer, BusyWaitAnalyzer
from findings import build_finding
from shared_state import violations_tracker



def detect_busy_wait(source):
    bw_analyzer = BusyWaitAnalyzer()
    ast_tree = ast.parse(source)
    bw_analyzer.visit(ast_tree)


DIRTY_SRC_PATH = "fixtures/flag/"
CLEAN_SRC_PATH = "fixtures/no-flag/"
RULES_FILENAME = "rule.scm"
PY = Language(tspython.language())
#Consider classes for the rule types
#TODO: Since the name and counters are identical we can get rid of counter
rule_types = {
    "polling-loop" :
        {"special_hdlr" : None, "counter" : "polling_loop"},
    "busy-wait" :
        {"special_hdlr" : detect_busy_wait, "counter" : "busy_wait"},
    "redundant-iteration" :
        {"special_hdlr": None, "counter" : "redundant_iterations"},
    "untested-boundaries" :
        {"special_hdlr" : None, "counter" : "untested_boundaries"},
    "eager-materialization" :
        {"special_hdlr" : None, "counter" : "eager_materialization"}
    }


def update_ts_counters(rule_type, pattern_count):
    counter_name = rule_types[rule_type]["counter"]
    try:
        setattr(
            violations_tracker,
            counter_name,
            getattr(violations_tracker, counter_name) + pattern_count,
        )
    except AttributeError:
        print(f"Counter not found for ruletype {rule_type}")



def collect_ts_findings(rule_type, ts_cursor, node, path, source):
    """Turn query matches into Finding records.

    This replaces the old get_ts_match_counts, which returned len(matches).
    A count cannot say WHICH site fired, so a false positive in a harvested
    corpus shows up only as a number being one too high, and has to be found
    by hand. It also cannot be joined to a tier-3 measurement. The count is
    still available -- it's len() of what this returns -- but it is now a
    derived view of the findings rather than the only thing captured.
    """
    source_lines = source.split(b"\n")
    findings = []
    for pattern_index, captures in ts_cursor.matches(node):
        finding = build_finding(rule_type, path, pattern_index, captures, source_lines)
        if finding is not None:
            findings.append(finding)
    return findings


def update_ast_counters(source):
    ast_tree = ast.parse(source)
    if_detector = IfAnalyzer()
    for_detector = ForLoopAnalyzer()
    if_detector.visit(ast_tree)
    for_detector.visit(ast_tree)


def run_detection_rules(rule_type, rule_type_path, ts_parser):
    #2passes. One for positive test one for negative test
    dirty_src_path = rule_type_path + DIRTY_SRC_PATH
    clean_src_path = rule_type_path + CLEAN_SRC_PATH
    paths_list = [dirty_src_path, clean_src_path]
    rule = rule_type_path + RULES_FILENAME
    all_findings = []

    for path in paths_list:
        for directory, _, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(directory, filename)
                with open(filepath, "rb") as f:
                    source = f.read()

                try:
                    ts_tree = ts_parser.parse(source)
                    query = Query(PY, open(rule).read())
                    ts_cursor = QueryCursor(query)
                    findings = collect_ts_findings(
                        rule_type,
                        ts_cursor,
                        ts_tree.root_node,
                        os.path.normpath(filepath),
                        source,
                    )
                    all_findings.extend(findings)

                    # Rules with a special_hdlr have additional processing that is
                    # authoritative for this counter (it can express things the
                    # .scm query can't, like "no sleep call anywhere in body").
                    # Only one of {special_hdlr, findings} should increment
                    # the counter, or every fixture double-counts.
                    if rule_types[rule_type]["special_hdlr"] != None:
                        rule_types[rule_type]["special_hdlr"](source)
                    else:
                        update_ts_counters(rule_type, len(findings))

                    #Special case to detect standard profiler violators
                    #TODO: Delete later
                    update_ast_counters(source)

                except FileNotFoundError:
                    print(f"File not found {rule}")
                except QueryError:
                    print(f"Invalid query, skipping {rule}")
        print(f"{rule}: {violations_tracker}")

    return all_findings



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=None,
        help="write findings as JSON Lines (one record per site) to this path",
    )
    args = parser.parse_args()

    ts_parser = Parser(PY)
    all_findings = []

    # Walk through rules/flags/fixtures
    for rule_type in rule_types:
        rule_type_path = "./" + rule_type + "/"
        all_findings.extend(run_detection_rules(rule_type, rule_type_path, ts_parser))
    #TODO: verify counters after rule verfifcation

    if args.out:
        # JSON Lines, append-only shaped: one record per site, never an
        # aggregate. A mean can always be re-derived from rows; rows cannot be
        # recovered from a mean.
        with open(args.out, "w") as f:
            for finding in all_findings:
                f.write(json.dumps(finding.as_dict()) + "\n")
        print(f"\nwrote {len(all_findings)} findings to {args.out}")


if __name__ == "__main__":
    main()
