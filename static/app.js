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
let llvmEditor = null;

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
            monaco.editor.setModelLanguage(editor.getModel(), e.target.value === 'c' ? 'c' : 'cpp');
        });
        loadSamples();
    });
}

function renderLLVMIR(payload) {
    const status = document.getElementById('llvm-status');
    const container = document.getElementById('llvm-editor');
    if (!payload) {
        if (llvmEditor) llvmEditor.setValue('; (no IR returned)\n');
        if (status) status.textContent = '';
        return;
    }
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
    
    if (window.monaco && editor) {
        const markers = diagnostics.map(d => {
            let severity = monaco.MarkerSeverity.Info;
            if (d.severity === 'error') severity = monaco.MarkerSeverity.Error;
            else if (d.severity === 'warning') severity = monaco.MarkerSeverity.Warning;
            
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
    }
    
    if (!diagnostics.length) {
        ul.innerHTML = '<li class="muted">No diagnostics. Code is healthy!</li>';
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
            <div class="explain-container" id="explain-${d.id}">
                <button class="btn btn-sm btn-explain" id="btn-${d.id}">Explain & Suggest Fix</button>
            </div>
        `;
        
        const focusHandler = () => {
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
document.getElementById('analyze-btn').addEventListener('click', analyze);
