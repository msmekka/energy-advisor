//Limits for source code loading
// 8MB per wasm module, 32-bit wasm instance = 4GB of RAM max
// js single string limit is 512MB or 1GB

const dotPalette = ["#E4002B", "#FFD200", "#EC38BC", "#29ABE2", "#7ED321", "#FF7A00"];
const background = "#0B0B0B";
function maxDepth(cursor, depth = 0) {
    let m = 0;
    let done = false;

    while (!done) {
        if (cursor.currentDepth > m) m = cursor.currentDepth;
        if (cursor.gotoFirstChild()) continue;
        while (!cursor.gotoNextSibling()) {
            if (!cursor.gotoParent())
                return m;
        }
    }
}

function nodeWalk(tree) {
    console.log("Node Walk\n");
    let node = tree.rootNode;
    let done = false;
    let visited = new Set();
    let i = 0;
    while (!done) {
        const nn = node.nextSibling;
        const fc = node.firstChild;
        const alreadyVisited = visited.has(node.id);

        if (!alreadyVisited) {
            visited.add(node.id);
            if (node.childCount > 0 && node.isNamed === true) {
                printNodeChildren(i++, node);
            }
        }
        
        if (!fc || alreadyVisited) {
            if (nn) node = nn;
            else node = node.parent;
        }
        else node = fc;
        
        if (node.id === tree.rootNode.id)
            done = true;
    }
}



function cursorWalk(cursor) {
    let visited = new Set();
    let done = false;
    let topid = cursor.currentNode.id;
    let md = 0;

    while (!done) {
        const alreadyVisited = visited.has(cursor.currentNode.id);
        if (!alreadyVisited) {
            if (cursor.currentDepth > md) md = cursor.currentDepth;
            visited.add(cursor.currentNode.id);
            if (cursor.currentNode.childCount > 0) printNodeChildren(cursor.currentDepth, cursor.currentNode);
        }

        if (!alreadyVisited)
            if (cursor.gotoFirstChild()) continue;
        if (cursor.gotoNextSibling()) continue;
        
        cursor.gotoParent();
            
        if (cursor.currentNode.id === topid)
            done = true;
    }
    return md;
}


function printNodeChildren(depth, node){
    console.log("printNodeChildren for", node.id,":", "at depth: ", depth);
    for (const child of node.children) {
        console.log(".   ", child.type)
    } 
}