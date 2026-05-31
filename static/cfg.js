/* Cytoscape-based CFG renderer for CD_LAB.
 * Exposes window.CFGView with:
 *   .render(cfgs)            — replace contents with multi-function dropdown
 *   .focusFunction(name)     — switch the displayed function
 *   .clear()                 — wipe the canvas
 */
(() => {
    let cy = null;
    let currentCFGs = [];

    let dagreRegistered = false;
    function ensureDagre() {
        if (dagreRegistered) return;
        if (typeof window.cytoscape === 'function' && window.cytoscapeDagre) {
            window.cytoscape.use(window.cytoscapeDagre);
            dagreRegistered = true;
        }
    }

    function showBanner(message) {
        const container = document.getElementById('cfg-canvas');
        if (!container) return;
        if (cy) { try { cy.destroy(); } catch (e) {} cy = null; }
        container.innerHTML = `<div style="padding:20px;color:#ff6b6b;font-size:13px;font-family:'JetBrains Mono',monospace;">${message}</div>`;
    }

    function nodeStyle() {
        return [
            {
                selector: 'node',
                style: {
                    'background-color': '#1d2230',
                    'border-color': '#7c5cff',
                    'border-width': 1,
                    'label': 'data(label)',
                    'color': '#e4e6ed',
                    'font-size': 10,
                    'font-family': 'JetBrains Mono, Consolas, monospace',
                    'text-wrap': 'wrap',
                    'text-max-width': 220,
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'padding': '8px',
                    'shape': 'round-rectangle',
                    'width': 'label',
                    'height': 'label',
                },
            },
            { selector: 'node[kind = "entry"]',       style: { 'background-color': '#143d2a', 'border-color': '#54d28a' } },
            { selector: 'node[kind = "exit"]',        style: { 'background-color': '#3a1f1f', 'border-color': '#ff6b6b' } },
            { selector: 'node[kind = "cond"]',        style: { 'background-color': '#2b2440', 'border-color': '#f7c948', 'shape': 'diamond' } },
            { selector: 'node[kind = "loop_header"]', style: { 'background-color': '#1f2a40', 'border-color': '#4cc2ff' } },
            { selector: 'node[kind = "return"]',      style: { 'background-color': '#2a1f33', 'border-color': '#ff6b6b' } },
            { selector: 'node[kind = "break"]',       style: { 'background-color': '#33291f', 'border-color': '#f7c948' } },
            { selector: 'node[kind = "continue"]',    style: { 'background-color': '#1f3326', 'border-color': '#54d28a' } },
            { selector: 'node.highlight',             style: { 'border-color': '#ff3b30', 'border-width': 3, 'background-color': '#4a1515' } },
            {
                selector: 'edge',
                style: {
                    'width': 1.5,
                    'line-color': '#4a5269',
                    'target-arrow-color': '#4a5269',
                    'target-arrow-shape': 'triangle',
                    'curve-style': 'bezier',
                    'label': 'data(label)',
                    'font-size': 9,
                    'color': '#8a91a3',
                    'text-background-color': '#0f1117',
                    'text-background-opacity': 1,
                    'text-background-padding': 2,
                },
            },
            { selector: 'edge[label = "T"]',       style: { 'line-color': '#54d28a', 'target-arrow-color': '#54d28a' } },
            { selector: 'edge[label = "F"]',       style: { 'line-color': '#ff6b6b', 'target-arrow-color': '#ff6b6b' } },
            { selector: 'edge[label = "back"]',    style: { 'line-color': '#4cc2ff', 'target-arrow-color': '#4cc2ff', 'line-style': 'dashed' } },
            { selector: 'edge[label = "break"]',   style: { 'line-color': '#f7c948', 'target-arrow-color': '#f7c948' } },
            { selector: 'edge[label = "continue"]',style: { 'line-color': '#7c5cff', 'target-arrow-color': '#7c5cff' } },
        ];
    }

    function buildElements(cfg) {
        const elements = [];
        for (const n of cfg.nodes) {
            const stmtPreview = (n.statements || [])
                .map(s => s.text)
                .join('\n')
                .slice(0, 160);
            const lines = n.start_line && n.end_line
                ? (n.start_line === n.end_line ? `L${n.start_line}` : `L${n.start_line}-${n.end_line}`)
                : '';
            const lbl = stmtPreview
                ? `${n.label}${lines ? ' [' + lines + ']' : ''}\n${stmtPreview}`
                : `${n.label}${lines ? ' [' + lines + ']' : ''}`;
            elements.push({ data: { id: n.id, label: lbl, kind: n.kind, line: n.start_line || null } });
        }
        for (const e of cfg.edges) {
            elements.push({ data: { source: e.source, target: e.target, label: e.label || '' } });
        }
        return elements;
    }

    function renderFunction(cfg) {
        if (typeof window.cytoscape !== 'function') {
            showBanner('Cytoscape failed to load from CDN. Check your network / adblocker, then reload.');
            return;
        }
        ensureDagre();
        const container = document.getElementById('cfg-canvas');
        if (!container) return;
        container.innerHTML = '';
        if (cy) { try { cy.destroy(); } catch (e) { /* noop */ } cy = null; }
        const layout = dagreRegistered
            ? { name: 'dagre', rankDir: 'TB', nodeSep: 30, rankSep: 50, edgeSep: 10 }
            : { name: 'breadthfirst', directed: true, padding: 10 };
        cy = window.cytoscape({
            container,
            elements: buildElements(cfg),
            style: nodeStyle(),
            layout,
            wheelSensitivity: 0.2,
        });
        cy.on('tap', 'node', evt => {
            const line = evt.target.data('line');
            if (line && window.CDLABEditor) window.CDLABEditor.revealLine(line);
        });
    }

    function populateDropdown(cfgs) {
        const sel = document.getElementById('cfg-function');
        sel.innerHTML = '';
        for (const c of cfgs) {
            const opt = document.createElement('option');
            opt.value = c.function;
            opt.textContent = c.function;
            sel.appendChild(opt);
        }
        sel.onchange = () => {
            const fn = cfgs.find(c => c.function === sel.value);
            if (fn) renderFunction(fn);
        };
    }

    window.CFGView = {
        render(cfgs) {
            currentCFGs = cfgs || [];
            populateDropdown(currentCFGs);
            if (currentCFGs.length > 0) {
                renderFunction(currentCFGs[0]);
            } else {
                if (cy) { try { cy.destroy(); } catch (e) {} cy = null; }
            }
        },
        focusFunction(name) {
            const fn = currentCFGs.find(c => c.function === name);
            if (fn) {
                document.getElementById('cfg-function').value = name;
                renderFunction(fn);
            }
        },
        clear() {
            currentCFGs = [];
            const sel = document.getElementById('cfg-function');
            if (sel) sel.innerHTML = '';
            if (cy) { try { cy.destroy(); } catch (e) {} cy = null; }
        },
        fit() {
            if (cy) cy.fit(undefined, 20);
        },
        highlightNode(nodeId) {
            if (!cy) return;
            cy.nodes().removeClass('highlight');
            if (nodeId) {
                const node = cy.$id(nodeId);
                if (node.length > 0) {
                    node.addClass('highlight');
                    cy.center(node);
                }
            }
        }
    };


    document.addEventListener('DOMContentLoaded', () => {
        const btn = document.getElementById('cfg-fit');
        if (btn) btn.addEventListener('click', () => window.CFGView.fit());
    });
})();
