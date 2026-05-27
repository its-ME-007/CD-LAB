/* CD_LAB Phase 1 frontend.
 * - Boots Monaco editor (C/C++).
 * - POSTs /api/analyze on click, renders AST + parse errors.
 * - Diagnostic rendering is stubbed for Phase 3.
 */

const SAMPLE = `// CD_LAB sample — Phase 1 smoke test
#include <stdio.h>

int main(void) {
    int *p = 0;       // null pointer
    int x;            // uninitialized
    *p = x + 1;       // both null deref and uninit-use (Phase 3 will flag these)
    return 0;
}
`;

let editor = null;

function setHealth(ok, info) {
    const dot = document.getElementById('health-dot');
    const text = document.getElementById('health-text');
    dot.className = 'dot ' + (ok ? 'dot-ok' : 'dot-bad');
    text.textContent = ok ? `libclang: ${info || 'loaded'}` : `libclang error: ${info || 'unknown'}`;
}

async function checkHealth() {
    try {
        const res = await fetch('/health');
        const data = await res.json();
        setHealth(data.libclang_loaded, data.libclang_path);
    } catch (e) {
        setHealth(false, e.message);
    }
}

function initTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const name = tab.dataset.tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.tab-panel').forEach(p =>
                p.classList.toggle('active', p.id === `tab-${name}`)
            );
        });
    });
}

function initMonaco() {
    require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
    require(['vs/editor/editor.main'], () => {
        editor = monaco.editor.create(document.getElementById('editor'), {
            value: SAMPLE,
            language: 'cpp',
            theme: 'vs-dark',
            automaticLayout: true,
            fontSize: 13,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
        });
        window.CDLABEditor = {
            revealLine(line) {
                editor.revealLineInCenter(line);
                editor.setPosition({ lineNumber: line, column: 1 });
                editor.focus();
            },
        };
        document.getElementById('language').addEventListener('change', e => {
            monaco.editor.setModelLanguage(editor.getModel(), e.target.value === 'c' ? 'c' : 'cpp');
        });
    });
}

function renderDiagnostics(diagnostics) {
    const ul = document.getElementById('diagnostics-list');
    ul.innerHTML = '';
    if (!diagnostics.length) {
        ul.innerHTML = '<li class="muted">No diagnostics. (Detectors land in Phase 3.)</li>';
        return;
    }
    for (const d of diagnostics) {
        const li = document.createElement('li');
        li.className = `diag-${d.severity}`;
        li.innerHTML = `<strong>[${d.category}]</strong> line ${d.range.line}: ${d.message}`;
        ul.appendChild(li);
    }
}

function renderParseErrors(errors) {
    const ul = document.getElementById('errors-list');
    ul.innerHTML = '';
    if (!errors.length) {
        ul.innerHTML = '<li class="muted">No parse errors.</li>';
        return;
    }
    for (const e of errors) {
        const li = document.createElement('li');
        li.textContent = e;
        ul.appendChild(li);
    }
}

function renderAST(ast) {
    const pre = document.getElementById('ast-json');
    pre.textContent = ast ? JSON.stringify(ast, null, 2) : '(no AST)';
}

async function analyze() {
    if (!editor) return;
    const btn = document.getElementById('analyze-btn');
    btn.disabled = true;
    btn.textContent = 'Analyzing...';
    const elapsed = document.getElementById('elapsed');
    elapsed.textContent = '';

    const body = JSON.stringify({
        code: editor.getValue(),
        language: document.getElementById('language').value,
    });

    try {
        // Phase 1: AST + parse errors. Phase 2 adds CFG via /api/cfg in parallel.
        const [analyzeRes, cfgRes] = await Promise.all([
            fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }),
            fetch('/api/cfg',     { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }),
        ]);
        if (!analyzeRes.ok) throw new Error(`/api/analyze HTTP ${analyzeRes.status}: ${await analyzeRes.text()}`);
        if (!cfgRes.ok)     throw new Error(`/api/cfg HTTP ${cfgRes.status}: ${await cfgRes.text()}`);

        const data = await analyzeRes.json();
        const cfgData = await cfgRes.json();

        renderDiagnostics(data.diagnostics || []);
        renderParseErrors(data.parse_errors || []);
        renderAST(data.ast);
        if (window.CFGView) {
            try {
                window.CFGView.render(cfgData.cfgs || []);
            } catch (e) {
                console.error('CFG render failed:', e);
            }
        }
        elapsed.textContent = `analyze ${data.elapsed_ms} ms · cfg ${cfgData.elapsed_ms} ms`;
    } catch (e) {
        renderParseErrors([`request failed: ${e.message}`]);
        document.querySelector('.tab[data-tab="errors"]').click();
    } finally {
        btn.disabled = false;
        btn.textContent = 'Analyze';
    }
}

initTabs();
initMonaco();
checkHealth();
document.getElementById('analyze-btn').addEventListener('click', analyze);
