import { Parser, Language } from "./node_modules/web-tree-sitter/web-tree-sitter.js";
window.addEventListener("error", (e) => console.error("uncaught error:", e.error));
window.addEventListener("unhandledrejection", (e) => console.error("unhandled rejection:", e.reason));
//Global
let src = "";
let tree;
let cursor;
const sourceElement = document.getElementById("source");
const treeElement = document.getElementById("tree");
const fileInput = document.getElementById("file-input");
const fileName = document.getElementById("file-name");
const languageSelect = document.getElementById("language-select");

// Keys match the <option value> list in #language-select.
const WASM_BY_LANGUAGE = {
    py: "./node_modules/tree-sitter-python/tree-sitter-python.wasm",
    js: "./node_modules/tree-sitter-javascript/tree-sitter-javascript.wasm",
    ts: "./node_modules/tree-sitter-typescript/tree-sitter-typescript.wasm",
    tsx: "./node_modules/tree-sitter-typescript/tree-sitter-tsx.wasm",
    go: "./node_modules/tree-sitter-go/tree-sitter-go.wasm",
    rs: "./node_modules/tree-sitter-rust/tree-sitter-rust.wasm",
};
const LANGUAGE_BY_EXT = {
    py: "py",
    js: "js", mjs: "js", cjs: "js", jsx: "js",
    ts: "ts",
    tsx: "tsx",
    go: "go",
    rs: "rs",
};
const MAX_FILE_BYTES = 1_000_000; // 1MB — each byte can become a DOM node, so keep this small.
let languages;

function extOf(filename) {
    return filename.slice(filename.lastIndexOf(".") + 1).toLowerCase();
}

/**
 * Initialize Parser and load every supported grammar. These are wasm
 * objects that will not be garbage collected by js. Anything created here
 * will need it's own garbage collection
 *
 * @returns {Parser}
 */
async function initParser() {
    await Parser.init();
    const parser = new Parser();

    languages = new Map();
    for (const [lang, wasmPath] of Object.entries(WASM_BY_LANGUAGE)) {
        languages.set(lang, await Language.load(wasmPath));
    }
    parser.setLanguage(languages.get(languageSelect.value));

    return parser;
}


/**
 * Highlight source code that occurs between start and end (indices)
 * 
 * @param {number} start - Byte offset where the highlight begins
 * @param {number} end - Byte offset where highlight ends
 */
function highlightSource(start, end) {
    sourceElement.textContent = "";
    sourceElement.append(document.createTextNode(src.slice(0, start)));
    const mark = document.createElement("mark");
    mark.textContent = src.slice(start, end);
    sourceElement.appendChild(mark);
    sourceElement.append(document.createTextNode(src.slice(end)));
    mark.scrollIntoView({ block: "center" });
}

/**
 * Generates HTML for the current AST node to be displayed in a code explorer
 * 
 * @param {TreeCursor} cursor positioned at a node in an AST
 * @returns {string} HTML parts 
 */
function labelForCursor(cursor) {
    const cn = cursor.currentNode;
    const nt_typelabel= cn.isNamed ? "type" : "anon";
    const cn_field = cn.currentFieldName;
    let parts = [];

    if (cn_field) parts.push(`<span class="field">${cn_field}</span>`);
    parts.push(`<span class="${nt_typelabel}">${cn.type}</span>`);
    if (cn.childCount === 0 && cn.isNamed) {
        const text = cn.text.length < 40 ? cn.text : cn.text.slice(0,40) + "..."
        parts.push(` <span class="text">${JSON.stringify(text)}</span>`);
    }
    return parts.join("");
}

/**
 * Build the AST starting from the root node of the tree.
 * 
 * @param {TreeCursor} cursor - Cursor positioned at the current node of the tree
 * @param {HTMLElement} topEl - parent element of the HTML tree being built
 */
function buildAST(cursor, topEl) {
    const cn = cursor.currentNode;
    const innerHTML = labelForCursor(cursor);
    const hasChildren = cursor.gotoFirstChild();

    if (!hasChildren) {
        const el = document.createElement("div");
        el.className = "leaf";
        el.innerHTML = innerHTML;
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            highlightSource(cn.startIndex, cn.endIndex);
        });
        topEl.appendChild(el);
        return;
    }

    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.innerHTML = innerHTML;
    summary.addEventListener('click', (e) => {
        e.stopPropagation();
        highlightSource(cn.startIndex, cn.endIndex);
    });
    details.appendChild(summary);

    do {
        buildAST(cursor, details);
    } while(cursor.gotoNextSibling());
    cursor.gotoParent();

    topEl.appendChild(details);
}

/**
 * 
 * @param {*} parser 
 * @returns 
 */
function renderAST(parser) {
    tree?.delete();
    treeElement.replaceChildren();
    sourceElement.textContent = src;

    tree = parser.parse(src);
    cursor = tree?.walk();
    if (cursor === null || cursor === undefined) return;

    buildAST(cursor, treeElement);
    treeElement.querySelector("details")?.setAttribute("open", "");
}

/**
 * 
 */
const parser = await initParser().catch(err => console.error(err));
if (parser) {
    fileInput.addEventListener("change", async () => {
        const [file] = fileInput.files;
        if (!file) return;

        if (file.size > MAX_FILE_BYTES) {
            fileInput.value = "";
            fileName.textContent = `"${file.name}" is ${(file.size / 1e6).toFixed(1)}MB, over the ${MAX_FILE_BYTES / 1e6}MB limit`;
            return;
        }

        const guessed = LANGUAGE_BY_EXT[extOf(file.name)];
        if (guessed) languageSelect.value = guessed;

        src = await file.text();
        fileName.textContent = file.name;
        parser.setLanguage(languages.get(languageSelect.value));
        renderAST(parser);
    });

    languageSelect.addEventListener("change", () => {
        if (!src) return;
        parser.setLanguage(languages.get(languageSelect.value));
        renderAST(parser);
    });
}


