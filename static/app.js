/* CD_LAB Phase 1 frontend.
 * - Boots Monaco editor (C/C++).
 * - POSTs /api/analyze on click, renders AST + parse errors.
 * - Diagnostic rendering is stubbed for Phase 3.
 */

const SAMPLE = `// ai-ub-detection — sample snippet
#include <stdio.h>

int main(void) {
    int *p = 0;       // null pointer
    int x;            // uninitialized
    *p = x + 1;       // both null deref and uninit-use (Phase 3 will flag these)
    return 0;
}
`;

let editor = null;
let llvmEditor = null;

// ---------------------------------------------------------------------------
// Tier-1 UX helpers: persistence + active-tab restore + empty states + counts
// ---------------------------------------------------------------------------
const LS = {
    source: 'cdlab.source',
    language: 'cdlab.language',
    activeTab: 'cdlab.activeTab',
};

let _persistTimer = null;
function persistSourceDebounced(value) {
    clearTimeout(_persistTimer);
    _persistTimer = setTimeout(() => {
        try { localStorage.setItem(LS.source, value); } catch (e) { /* quota */ }
    }, 500);
}

function activateTab(name) {
    document.querySelectorAll('.tab').forEach(t =>
        t.classList.toggle('active', t.dataset.tab === name)
    );
    document.querySelectorAll('.tab-panel').forEach(p =>
        p.classList.toggle('active', p.id === `tab-${name}`)
    );
}

function updateSeverityPills(counts) {
    const set = (id, n) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (n > 0) { el.textContent = n; el.hidden = false; }
        else { el.textContent = ''; el.hidden = true; }
    };
    set('pill-err',  counts.error   || 0);
    set('pill-warn', counts.warning || 0);
    set('pill-info', counts.info    || 0);
}

function renderEmptyStates() {
    const diagUl = document.getElementById('diagnostics-list');
    if (diagUl && !diagUl.children.length) {
        diagUl.innerHTML = '<li class="empty-state">Run Analyze (Ctrl+↵) to see diagnostics.</li>';
    }
    const ast = document.getElementById('ast-json');
    if (ast && !ast.textContent.trim()) {
        ast.textContent = '// Run Analyze to populate the AST.';
    }
    const errs = document.getElementById('errors-list');
    if (errs && !errs.children.length) {
        errs.innerHTML = '<li class="empty-state">No parse errors yet — Run Analyze.</li>';
    }
    const cfgCanvas = document.getElementById('cfg-canvas');
    if (cfgCanvas && !cfgCanvas.children.length) {
        cfgCanvas.innerHTML = '<div class="empty-state cfg-empty">Run Analyze to render the control-flow graph.</div>';
    }
}

function bindKeyboardShortcut() {
    window.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            analyze();
        }
    });
}

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
            activateTab(name);
            try { localStorage.setItem(LS.activeTab, name); } catch (e) { /* quota */ }
        });
    });
    // Restore last-active tab if saved (falls back to whatever's marked
    // active in the HTML — currently the Diagnostics tab).
    try {
        const saved = localStorage.getItem(LS.activeTab);
        if (saved && document.querySelector(`.tab[data-tab="${saved}"]`)) {
            activateTab(saved);
        }
    } catch (e) { /* localStorage unavailable */ }
}

async function loadSamples() {
    try {
        const res = await fetch('/api/samples');
        if (!res.ok) return;
        const samples = await res.json();
        const sel = document.getElementById('samples-select');
        if (!sel) return;
        
        sel.innerHTML = '<option value="">-- Load Sample --</option>';
        samples.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.name;
            opt.textContent = s.name;
            sel.appendChild(opt);
        });
        
        sel.onchange = () => {
            const chosen = samples.find(s => s.name === sel.value);
            if (chosen && editor) {
                editor.setValue(chosen.content);
                const isC = chosen.name.endsWith('.c');
                document.getElementById('language').value = isC ? 'c' : 'cpp';
                monaco.editor.setModelLanguage(editor.getModel(), isC ? 'c' : 'cpp');
                analyze();
            }
        };
    } catch (e) {
        console.error('Failed to load samples:', e);
    }
}

function initMonaco() {
    require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
    require(['vs/editor/editor.main'], () => {
        // Restore saved source + language; fall back to defaults.
        let savedSource = null, savedLang = null;
        try {
            savedSource = localStorage.getItem(LS.source);
            savedLang   = localStorage.getItem(LS.language);
        } catch (e) { /* localStorage unavailable */ }
        const initialSource = savedSource ?? SAMPLE;
        const initialLang   = (savedLang === 'c' || savedLang === 'cpp') ? savedLang : 'cpp';
        document.getElementById('language').value = initialLang;

        editor = monaco.editor.create(document.getElementById('editor'), {
            value: initialSource,
            language: initialLang,
            theme: 'vs-dark',
            automaticLayout: true,
            fontSize: 13,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
        });
        editor.onDidChangeModelContent(() => persistSourceDebounced(editor.getValue()));
        window.CDLABEditor = {
            revealLine(line) {
                editor.revealLineInCenter(line);
                editor.setPosition({ lineNumber: line, column: 1 });
                editor.focus();
            },
        };
        // Second Monaco instance for the LLVM IR viewer (read-only).
        // Monaco doesn't ship an `llvm` grammar out of the box, so we use
        // `plaintext` with monospaced styling — readable, no extra deps.
        llvmEditor = monaco.editor.create(document.getElementById('llvm-editor'), {
            value: '; LLVM IR will appear here after Analyze.\n',
            language: 'plaintext',
            theme: 'vs-dark',
            readOnly: true,
            automaticLayout: true,
            fontSize: 12,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'off',
        });
        document.getElementById('language').addEventListener('change', e => {
            const lang = e.target.value === 'c' ? 'c' : 'cpp';
            monaco.editor.setModelLanguage(editor.getModel(), lang);
            try { localStorage.setItem(LS.language, lang); } catch (err) { /* quota */ }
        });
        loadSamples();
    });
}

function renderLLVMMetrics(metrics) {
    const bar = document.getElementById('llvm-metrics-bar');
    if (!bar) return;
    if (!metrics) {
        bar.hidden = true;
        bar.innerHTML = '';
        return;
    }
    bar.hidden = false;
    const cell = (label, value) =>
        `<span class="metric"><span class="metric-label">${label}</span><span class="metric-value">${value}</span></span>`;
    bar.innerHTML = [
        cell('Functions', metrics.functions),
        cell('Basic Blocks', metrics.basic_blocks),
        cell('Instructions', metrics.instructions),
        cell('Memory Ops', metrics.memory_ops),
        cell('Arithmetic Ops', metrics.arithmetic_ops),
    ].join('');
}

function renderLLVMIR(payload) {
    const status = document.getElementById('llvm-status');
    const container = document.getElementById('llvm-editor');
    if (!payload) {
        if (llvmEditor) llvmEditor.setValue('; (no IR returned)\n');
        if (status) status.textContent = '';
        renderLLVMMetrics(null);
        return;
    }
    renderLLVMMetrics(payload.metrics || null);
    if (payload.ok && payload.ir) {
        // Make sure the editor is visible (we may have replaced it with the
        // error <div> on a previous failure — restore the canvas first).
        if (!llvmEditor && window.monaco) {
            container.innerHTML = '';
            llvmEditor = monaco.editor.create(container, {
                value: payload.ir,
                language: 'plaintext',
                theme: 'vs-dark',
                readOnly: true,
                automaticLayout: true,
                fontSize: 12,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                wordWrap: 'off',
            });
        } else {
            llvmEditor.setValue(payload.ir);
        }
        const lineCount = payload.ir.split('\n').length;
        if (status) status.textContent = `${lineCount} lines`;
    } else {
        if (llvmEditor) { llvmEditor.dispose(); llvmEditor = null; }
        container.innerHTML = `<div class="llvm-error">${escapeHtml(payload.error || 'IR generation failed.')}</div>`;
        if (status) status.textContent = 'unavailable';
    }
}

function renderASTReasoning(d) {
    // AST-level decision chain: why the detector flagged this code. Distinct
    // from `renderLLVMEvidence` (which shows the downstream IR artefact).
    // Empty/null array → render nothing so the card stays compact.
    if (!d.reasoning || !d.reasoning.length) return '';
    const items = d.reasoning.map(s => `<li>${escapeHtml(s)}</li>`).join('');
    return `
        <details class="ast-reasoning" open>
            <summary><strong>AST Reasoning</strong> <span class="muted">(${d.reasoning.length} steps)</span></summary>
            <ul class="reasoning-list">${items}</ul>
        </details>
    `;
}

function renderLLVMEvidence(d) {
    // Collapsible <details> block of IR instructions backing the diagnostic.
    // Empty/null arrays render nothing — the previous LLVM Evidence panel
    // simply vanishes when no IR is available (e.g. clang missing).
    // Each row carries its 1-based IR line (llvm_evidence_lines, aligned by
    // index) as a data attribute so it can scroll the IR viewer on click.
    if (!d.llvm_evidence || !d.llvm_evidence.length) return '';
    const irLines = d.llvm_evidence_lines || [];
    const rows = d.llvm_evidence.map((s, i) => {
        const irLine = irLines[i];
        if (irLine) {
            return `<div class="evidence-line jump" data-ir-line="${irLine}" `
                 + `title="Jump to line ${irLine} in the LLVM IR tab">${escapeHtml(s)}</div>`;
        }
        return `<div class="evidence-line">${escapeHtml(s)}</div>`;
    }).join('');
    return `
        <details class="llvm-evidence" open>
            <summary><strong>Compiler Evidence (LLVM IR)</strong> <span class="muted">(${d.llvm_evidence.length} instr)</span></summary>
            <div class="codeblock evidence-code">${rows}</div>
        </details>
    `;
}

function jumpToIRLine(line) {
    // Switch to the LLVM IR tab and scroll its viewer to `line`, flashing a
    // whole-line highlight. The tab switch may un-hide the editor for the
    // first time, so defer the reveal until layout settles (rAF) — otherwise
    // Monaco computes scroll position against a 0-height container.
    const tab = document.querySelector('.tab[data-tab="llvm"]');
    if (tab) tab.click();
    if (!llvmEditor || !window.monaco) return;
    requestAnimationFrame(() => {
        llvmEditor.layout();
        llvmEditor.revealLineInCenter(line);
        llvmEditor.setPosition({ lineNumber: line, column: 1 });
        _irEvidenceDeco = llvmEditor.deltaDecorations(_irEvidenceDeco, [{
            range: new monaco.Range(line, 1, line, 1),
            options: { isWholeLine: true, className: 'ir-evidence-highlight' },
        }]);
    });
}
let _irEvidenceDeco = [];

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderDiagnostics(diagnostics) {
    const ul = document.getElementById('diagnostics-list');
    ul.innerHTML = '';

    // Tally severities for the tab pills.
    const counts = { error: 0, warning: 0, info: 0 };

    if (window.monaco && editor) {
        const markers = diagnostics.map(d => {
            let severity = monaco.MarkerSeverity.Info;
            if (d.severity === 'error') severity = monaco.MarkerSeverity.Error;
            else if (d.severity === 'warning') severity = monaco.MarkerSeverity.Warning;
            if (d.severity in counts) counts[d.severity]++;

            return {
                startLineNumber: d.range.line,
                startColumn: d.range.column,
                endLineNumber: d.range.end_line,
                endColumn: d.range.end_column,
                message: d.message,
                severity: severity
            };
        });
        monaco.editor.setModelMarkers(editor.getModel(), 'owner', markers);
    } else {
        for (const d of diagnostics) {
            if (d.severity in counts) counts[d.severity]++;
        }
    }
    updateSeverityPills(counts);

    if (!diagnostics.length) {
        ul.innerHTML = '<li class="empty-state">No diagnostics. Code is healthy.</li>';
        return;
    }

    for (const d of diagnostics) {
        const li = document.createElement('li');
        li.className = `diag-item diag-${d.severity}`;
        li.innerHTML = `
            <div class="diag-header">
                <span class="diag-badge badge-${d.severity}">${d.severity}</span>
                <span class="category-badge">${d.category}</span>
                <span class="muted font-mono">Line ${d.range.line}</span>
            </div>
            <div class="diag-message">${d.message}</div>
            ${renderASTReasoning(d)}
            ${renderLLVMEvidence(d)}
            <div class="explain-container" id="explain-${d.id}">
                <button class="btn btn-sm btn-explain" id="btn-${d.id}">Explain & Suggest Fix</button>
            </div>
        `;
        
        const focusHandler = () => {
            // Visually mark the clicked diagnostic as the active selection.
            document.querySelectorAll('#diagnostics-list .diag-item').forEach(item =>
                item.classList.remove('active')
            );
            li.classList.add('active');

            if (editor) {
                editor.revealLineInCenter(d.range.line);
                editor.setSelection({
                    startLineNumber: d.range.line,
                    startColumn: d.range.column,
                    endLineNumber: d.range.end_line,
                    endColumn: d.range.end_column
                });
                editor.focus();
            }
            if (d.cfg_node_id && window.CFGView) {
                const parts = d.cfg_node_id.split('#');
                if (parts.length > 0) {
                    const funcName = parts[0];
                    window.CFGView.focusFunction(funcName);
                    window.CFGView.highlightNode(d.cfg_node_id);
                    document.querySelector('.tab[data-tab="cfg"]').click();
                }
            }
        };
        
        li.querySelector('.diag-header').addEventListener('click', focusHandler);
        li.querySelector('.diag-message').addEventListener('click', focusHandler);

        // Click-to-jump: each evidence row scrolls the IR viewer to its
        // instruction. stopPropagation so it doesn't also trigger the card's
        // source-focus handler.
        li.querySelectorAll('.evidence-line.jump').forEach(row => {
            row.addEventListener('click', evt => {
                evt.stopPropagation();
                const line = parseInt(row.dataset.irLine, 10);
                if (line) jumpToIRLine(line);
            });
        });
        
        const btn = li.querySelector(`#btn-${d.id}`);
        btn.addEventListener('click', async (evt) => {
            evt.stopPropagation();
            const explainDiv = li.querySelector(`#explain-${d.id}`);
            explainDiv.innerHTML = `
                <div class="llm-spinner">
                    <div class="spinner-icon"></div>
                    <span>Consulting LLM Expert...</span>
                </div>
            `;
            
            try {
                const res = await fetch('/api/explain', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        diagnostic: d,
                        code: editor.getValue(),
                        context_lines: 3
                    })
                });
                
                if (!res.ok) {
                    throw new Error(`HTTP error ${res.status}`);
                }
                
                const data = await res.json();
                if (data.ok) {
                    explainDiv.innerHTML = `
                        <div class="llm-explanation">
                            <strong>AI Explanation:</strong>
                            <p>${data.explanation}</p>
                        </div>
                        ${data.fix_suggestion ? `
                        <div class="llm-fix">
                            <strong>Suggested Fix:</strong>
                            <pre class="codeblock fix-code">${escapeHtml(data.fix_suggestion)}</pre>
                        </div>
                        ` : ''}
                    `;
                } else {
                    explainDiv.innerHTML = `
                        <div class="llm-error">
                            <p><strong>LLM Offline:</strong> ${data.error || 'Failed to generate explanation.'}</p>
                        </div>
                    `;
                }
            } catch (err) {
                explainDiv.innerHTML = `
                    <div class="llm-error">
                        <p><strong>Error:</strong> ${err.message}</p>
                    </div>
                `;
            }
        });
        
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
        renderLLVMIR(data.llvm_ir);
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
renderEmptyStates();
bindKeyboardShortcut();
document.getElementById('analyze-btn').addEventListener('click', analyze);
