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

## Deploying

`npm run build` copies the app plus only the `.js`/`.wasm` files it actually
imports (skipping `canvas`, `.node` binaries, source packages, etc.) into
`dist/`, laid out so `mwast.js`'s existing `./node_modules/...` import paths
resolve unmodified. Upload `dist/`'s contents as-is to any static host —
it's fully self-contained and needs no server-side logic, just HTTPS (ES
modules require a real origin, not `file://`).

```bash
npm run build
```

## Usage

- Choose a source file with the file picker (`.py`, `.js`/`.mjs`/`.cjs`/`.jsx`, `.ts`, `.tsx`, `.go`, `.rs`). The language dropdown updates to match, but you can change it to force a different grammar.
- Click a `▸` branch to expand/collapse it.
- Click any node (branch or leaf) to highlight its byte range in the source pane.
- Files over 1MB are rejected (see `MAX_FILE_BYTES` in `mwast.js`) — each byte can become a DOM node, so large files can bog down the tab.

## Project layout

```
index.html            the page shell
mwast.js              loads the grammars, parses the target file, and builds the tree UI
scripts/build-dist.sh the static-hosting bundle builder (npm run build)
```

## Notes

- Adding another language means adding its `tree-sitter-*` grammar package, then adding an entry to `WASM_BY_LANGUAGE` (and `LANGUAGE_BY_EXT`, and an `<option>`) in `mwast.js`/`index.html` — and a `copy_vendor_file` line for its `.wasm` in `scripts/build-dist.sh`.
- No Python dependencies (`python3 -m http.server` is stdlib-only) — `npm install` is the only setup step.
- The selected source file is read in the browser and is not uploaded anywhere.
