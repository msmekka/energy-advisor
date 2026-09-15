import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor
import ast
import os
from astanalyzers import ForLoopAnalyzer, IfAnalyzer, BusyWaitAnalyzer
from shared_state import violations_tracker



DIRTY_SRC_PATH = "fixtures/flag/"
CLEAN_SRC_PATH = "fixtures/no-flag/"
RULES_FILENAME = "rule.scm"
PY = Language(tspython.language())


def detect_busy_wait(source):
    bw_analyzer = BusyWaitAnalyzer()
    ast_tree = ast.parse(source)
    bw_analyzer.visit(ast_tree)

def update_ts_counters(rule_type, pattern_count):
    counter_name = rule_types[rule_type]["counter"]
    setattr(
        violations_tracker,
        counter_name,
        getattr(violations_tracker, counter_name) + pattern_count,
    )
#Consider classes for the rule types
rule_types = {
    "polling-loop" : 
        {"special_hdlr" : None, "counter" : "polling_loop"},
    "busy-wait" : 
        {"special_hdlr" : detect_busy_wait, "counter" : "busy_wait"},
    }

def get_ts_match_counts(ts_parser, source, rule):
    ts_tree = ts_parser.parse(source)
    print(rule)
    query = Query(PY, open(rule).read())
    ts_cursor = QueryCursor(query)
    matches = ts_cursor.matches(ts_tree.root_node)
    print(matches)
    return matches, len(matches)    

def update_ast_counters(source):
    ast_tree = ast.parse(source)
    if_detector = IfAnalyzer()
    for_detector = ForLoopAnalyzer()
    if_detector.visit(ast_tree)
    for_detector.visit(ast_tree)

def main():
    ts_parser = Parser(PY)
    ts_match_count = 0

    # Walk through rules/flags/fixtures
    for rule_type in rule_types:
        rule_type_path = "./" + rule_type + "/"
        src_path = rule_type_path + DIRTY_SRC_PATH
        rule = rule_type_path + RULES_FILENAME

        for directory, _, filenames in os.walk(src_path):
            print(src_path)
            for filename in filenames:
                filepath = os.path.join(directory, filename)
                print(filepath)
                with open(filepath, "rb") as f:
                    source = f.read()

                matches, ts_match_count = get_ts_match_counts(ts_parser, source, rule)

                # some rules need extra processing
                if rule_types[rule_type]["special_hdlr"] != None:
                    rule_types[rule_type]["special_hdlr"](source)

                update_ts_counters(rule_type, ts_match_count)
                update_ast_counters(source)

              
    
    print(violations_tracker)

if __name__ == "__main__":
    main()