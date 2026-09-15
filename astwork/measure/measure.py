

import pyRAPL
import black
from pathlib import Path
from datetime import datetime
import textwrap
from io import StringIO

RAPL_OUT = "./measurements"
source_code = """
for i in range(100):
    x = 10 * 5          # Redundant (Invariant computation)
    y = array[i] + 2    # Valid (Changes with 'i')
    for j in range(1,10):
        print("Another redundant iteration")
    print("Looping...") # Redundant iteration output
"""

class SnippetMeasure():
    def __init__(self):
        pyRAPL.setup()


    def create_snippet(snippet: str) -> None:
        now = datetime.now()
        snippet_fn = RAPL_OUT + "/snippet-" + now
        output_fn = RAPL_OUT + "/output" + now
        black.format_str(snippet)
        with open(snippet_fn, "a+", "utf-8") as snippet_f:
            snippet_f.seek()
            snippet_f.write("import pyRAPL")
            snippet_f.write("pyRAPL.setup()")
            snippet_f.write("report = pyRAPL.outputs.DataFrameOutput()")
            snippet_f.write("with pyRAPL.Measurement('bar', output=report):")
            snippet_f.writeLines(textwrap.indent(snippet, "    "))
            snippet_f.write("report.data.head()")
            snippet_f.close()
        return snippet_f

def main():
    measurer = SnippetMeasure()
    measurer.create_snippet(source_code)
    
if __name__ == "__main__":
    main()