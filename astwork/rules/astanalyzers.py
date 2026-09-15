import ast
from  datetime import date, datetime
from pathlib import Path
from shared_state import violations_tracker
        

def is_no_op_while(node):
    return (
        isinstance(node, ast.While)
        and len(node.body) == 1
        and isinstance(node.body[0], (ast.Pass, ast.Continue))
    )

class BusyWaitAnalyzer(ast.NodeVisitor):
    def visit_While(self, node):
        if is_no_op_while(node):
            violations_tracker.busy_wait += 1

        self.generic_visit(node)

class IfAnalyzer(ast.NodeVisitor):
        
    def visit_Constant(self, node):
            #print("Visited a constant")
            #return super().visit_Constant(node)
            self.generic_visit(node)

    def visit_If(self, node):
        if not node.orelse:
            #if not (any(isinstance(child, ast.Return) for child in ast.walk(node))):
            violations_tracker.untested_boundaries += 1
       

        if node.test:
            if isinstance(node.test, ast.Compare):
                if node.test.comparators:
                    if isinstance(node.test.comparators[0], ast.Constant) and isinstance(node.test.comparators[0].value, int): 
                        violations_tracker.magic_numbers += 1
        self.generic_visit(node)


class ForLoopAnalyzer(ast.NodeVisitor):
    ''' Checks for redundtant iteration and should have used comprehension'''
    def __init__(self):
        self.current_loop_vars = []

    def visit_For(self, node):
        # 1. Identify the loop induction variable target (e.g., 'i')
        if isinstance(node.target, ast.Name):
            self.current_loop_vars.append(node.target.id)

        #Identify if there is a nested loop over a collection
        # if isinstance(node.iter, ast.List):
        #     for body_node in node.body()
        

        
        # 2. Analyze the statements inside the loop body
        for body_node in node.body:
            if not isinstance(body_node, ast.Expr):
                # We track all variable names used in this specific line
                used_variables = [
                    n.id for n in ast.walk(body_node) 
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                ]
            # elif isinstance(body_node, ast.Expr):
            #     print(body_node)
            #     for subnode in ast.walk(body_node):
            #         if isinstance(subnode.value, ast.Call) and isinstance(subnode.func, ast.Attribute):
            #             print(subnode.func.attr)
            # else:
            #     print("I fell out")
            # 3. Check for redundancy: does the statement ignore the loop variable?
            # (Simplification: excludes assignments to the loop variable itself)
                if self.current_loop_vars and not any(var in used_variables for var in self.current_loop_vars):
                    if not isinstance(body_node, (ast.Pass, ast.Break, ast.Continue)):
                        violations_tracker.redundant_iterations += 1
                    #TODO: Implement some measurement and indicate impact here and at scale.

        self.generic_visit(node)

        # Context cleanup for nested loops
        if isinstance(node.target, ast.Name):
            self.current_loop_vars.pop()

    
            

def main():
    # --- Test Case ---
    source_code = """
    for i in range(100):
        x = 10 * 5          # Redundant (Invariant computation)
        y = array[i] + 2    # Valid (Changes with 'i')
        for j in range(1,10):
            print("Another redundant iteration")
        print("Looping...") # Redundant iteration output
    """

    source_code_for = """
    somelist =[1,2,3,4,5,6]
    newlist = []
    for somenum in somelist:
        if somenum >= 10:
            newlist.append(somenum)
    """
    #array = [x for x in range(1,101)]
    #before = datetime.now()
    #for i in range(100):
    #    x = 10 * 5          # Redundant (Invariant computation)
    #    y = array[i] + 2    # Valid (Changes with 'i')
    #    for j in range(1,10):
    #        z = y + 5
    #    print("Looping...") # Redundant iteration output
    #after = datetime.now()
    #print(f"Execution: {after - before}")
    ############################################

    violations_tracker = violations("snippet")

    tree = ast.parse(source_code)
    #print(ast.dump(tree))
    detector = ForLoopAnalyzer()
    detector.visit(tree, violations_tracker)
    print(violations_tracker)

    # targetfilepath = Path("./src/ageism_test_code.py")
    # if targetfilepath.exists(): 
    #     with open(targetfilepath, "r", encoding = "utf-8") as f:
    #         source = f.read()
    #         tree = ast.parse(source)
    #         #print(ast.dump(tree))
    #         ridetector = RedundantIterationDetector()
    #         ridetector.visit(tree)
    #         ifdetector = IfAnalyzer()
    #         ifdetector.visit(tree)
    #         print(f"Bias score: untested boundary violations: {violations_tracker.untested_boundaries}, magic number violations: {violations_tracker.magic_numbers}")
    #         print(f"unbalanced score: {violations_tracker.if_count - violations_tracker.else_count}")
    #         f.close()

if __name__ == "__main__":
    main()
