# AST Explorer

A browser-based tool for exploring the syntax tree of a source file, side by side with its source. Built on [`web-tree-sitter`](https://github.com/tree-sitter/tree-sitter/tree/master/lib/binding_web) with grammars for Python, JavaScript, TypeScript, Go, and Rust.

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

- Choose a source file with the file picker (`.py`, `.js`/`.mjs`/`.cjs`/`.jsx`, `.ts`, `.tsx`, `.go`, `.rs`). The language dropdown updates to match, but you can change it to force a different grammar.
- Click a `▸` branch to expand/collapse it.
- Click any node (branch or leaf) to highlight its byte range in the source pane.
- Files over 1MB are rejected (see `MAX_FILE_BYTES` in `mwast.js`) — each byte can become a DOM node, so large files can bog down the tab.

## Project layout

```
index.html            the page shell
mwast.js              loads the grammars, parses the target file, and builds the tree UI
```

## Notes

- Adding another language means adding its `tree-sitter-*` grammar package, then adding an entry to `WASM_BY_LANGUAGE` (and `LANGUAGE_BY_EXT`, and an `<option>`) in `mwast.js`/`index.html`.
- No Python dependencies (`python3 -m http.server` is stdlib-only) — `npm install` is the only setup step.
- The selected source file is read in the browser and is not uploaded anywhere.
