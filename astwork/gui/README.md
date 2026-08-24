# AST Explorer

A browser-based tool for exploring the syntax tree of a Python file, side by side with its source. Built on [`web-tree-sitter`](https://github.com/tree-sitter/tree-sitter/tree/master/lib/binding_web) and the `tree-sitter-python` grammar.

Left pane shows the source; right pane shows a collapsible tree of every AST node (à la [astexplorer.net](https://astexplorer.net)). Click any node to highlight the source range it covers.

## Setup

```bash
npm install
```

## Run

This needs to be served over HTTP — it won't work opened directly as a `file://` URL, since ES modules and `fetch()` are both blocked there.

```bash
python3 -m http.server 8000
```

Then open **http://localhost:8000/index.html**.

## Usage

- Choose a Python source file with the file picker.
- Click a `▸` branch to expand/collapse it.
- Click any node (branch or leaf) to highlight its byte range in the source pane.

## Project layout

```
index.html            the page shell (mwastexplorer.html is the scratch space)
mwast.js              parses the target file and builds the tree UI
```

## Notes

- Python only, for now — parsing another language just means swapping the grammar package and updating the `Language.load(...)` path in `mwast.js`.
- No Python dependencies (`python3 -m http.server` is stdlib-only) — `npm install` is the only setup step.
- The selected source file is read in the browser and is not uploaded anywhere.
