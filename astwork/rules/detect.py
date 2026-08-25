import ast
from  datetime import date, datetime

#src = "for x in range(1,10): print(x)"


#print(ast.dump(ast.parse(src)))

class IfAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.num_constants = 0
        self.if_count = 0
        self.else_count = 0
        self.magic_number_violations = 0
        self.untested_boundary_violation = 0

    def get_constant(self): 
        return self.num_constants


    def visit_Constant(self, node):
            #print("Visited a constant")
            #return super().visit_Constant(node)
            self.num_constants += 1
            self.generic_visit(node)

    def visit_If(self, node):
        self.if_count += 1
        if not node.orelse:
            #if not (any(isinstance(child, ast.Return) for child in ast.walk(node))):
            self.untested_boundary_violation += 1
        else:
            self.else_count += 1
        

        if node.test:
            if isinstance(node.test, ast.Compare):
                if node.test.comparators:
                    if isinstance(node.test.comparators[0], ast.Constant) and isinstance(node.test.comparators[0].value, int): 
                        self.magic_number_violations += 1
        self.generic_visit(node)


class RedundantIterationDetector(ast.NodeVisitor):
    def __init__(self):
        self.current_loop_vars = []

    def visit_For(self, node):
        # 1. Identify the loop induction variable target (e.g., 'i')
        if isinstance(node.target, ast.Name):
            self.current_loop_vars.append(node.target.id)
        
        # 2. Analyze the statements inside the loop body
        for body_node in node.body:
            # We track all variable names used in this specific line
            used_variables = [
                n.id for n in ast.walk(body_node) 
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            ]
            
            # 3. Check for redundancy: does the statement ignore the loop variable?
            # (Simplification: excludes assignments to the loop variable itself)
            if self.current_loop_vars and not any(var in used_variables for var in self.current_loop_vars):
                if not isinstance(body_node, (ast.Pass, ast.Break, ast.Continue)):
                    print(f"[REDUNDANCY WARNING] Line {body_node.lineno}: "
                          f"Statement does not depend on loop variable '{self.current_loop_vars[-1]}'. "
                          f"It executes redundantly on every iteration.")
                #TODO: Implement some measurement and indicate impact here and at scale.

        self.generic_visit(node)

        # Context cleanup for nested loops
        if isinstance(node.target, ast.Name):
            self.current_loop_vars.pop()
            

# --- Test Case ---
source_code = """
for i in range(100):
    x = 10 * 5          # Redundant (Invariant computation)
    y = array[i] + 2    # Valid (Changes with 'i')
    for j in range(1,10):
        print("Another redundant iteration")
    print("Looping...") # Redundant iteration output
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


#tree = ast.parse(source_code)
#detector = RedundantIterationDetector()
#detector.visit(tree)

targetfilepath = Path("./ageism_test_code.py")
if targetfilepath.exists(): 
    with open(targetfilepath, "r", encoding = "utf-8") as f:
        source = f.read()
        tree = ast.parse(source)
        #print(ast.dump(tree))
        ridetector = RedundantIterationDetector()
        ridetector.visit(tree)
        ifdetector = IfAnalyzer()
        ifdetector.visit(tree)
        print(f"Bias score: untested boundary violations: {ifdetector.untested_boundary_violation}, magic number violations: {ifdetector.magic_number_violations}")
        print(f"unbalanced score: {ifdetector.if_count - ifdetector.else_count}")
        f.close()

