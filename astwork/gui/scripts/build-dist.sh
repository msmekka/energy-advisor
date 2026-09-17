#!/usr/bin/env bash
# Assembles dist/ — the minimal set of files needed to serve the AST explorer
# as static files. Copies only the .js/.wasm this app actually imports, laid
# out under node_modules/<pkg>/... so mwast.js's import paths work unmodified.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d node_modules ]; then
    echo "node_modules not found — run 'npm install' first" >&2
    exit 1
fi

rm -rf dist
mkdir -p dist

cp index.html mwast.js dist/

copy_vendor_file() {
    local rel="$1"
    mkdir -p "dist/$(dirname "$rel")"
    cp "$rel" "dist/$rel"
}

copy_vendor_file node_modules/web-tree-sitter/web-tree-sitter.js
copy_vendor_file node_modules/web-tree-sitter/web-tree-sitter.wasm
copy_vendor_file node_modules/tree-sitter-python/tree-sitter-python.wasm
copy_vendor_file node_modules/tree-sitter-javascript/tree-sitter-javascript.wasm
copy_vendor_file node_modules/tree-sitter-typescript/tree-sitter-typescript.wasm
copy_vendor_file node_modules/tree-sitter-typescript/tree-sitter-tsx.wasm
copy_vendor_file node_modules/tree-sitter-go/tree-sitter-go.wasm
copy_vendor_file node_modules/tree-sitter-rust/tree-sitter-rust.wasm

echo "dist/ built:"
du -sh dist
find dist -type f | sort
