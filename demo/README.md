# Demo

This directory holds the project's submission demo — a short, scripted
walkthrough of CD_LAB analyzing both a buggy and a clean program.

## What submitters provide

Per the submission brief, the demo is delivered as **either** a video
**or** screenshots showing **both a working case and a failure case**.

CD_LAB ships:

- A screenshot tour (this file + `screenshots/`)
- A scripted walkthrough you can re-record in ~3 minutes (below)

A video file (e.g. `demo.mp4`) can be added at the repository root and
linked from the [README.md](../README.md) "What it does" section.

---

## Scripted walkthrough (~3 min)

### 0. Boot

```bash
./build.sh    # one-time
./run.sh
```

Open <http://localhost:8000/>.

### 1. Working case — null deref + div by zero

Paste this in the editor (or pick `null_deref_01.c` from the **Load Sample** dropdown):

```c
#include <stddef.h>
int main(void) {
    int *p = NULL;
    *p = 42;             // null dereference
    int a = 10;
    int b = a / 0;       // div by zero
    return b;
}
```

Hit **Ctrl + Enter**. Expect:

- **Source pane:** red squiggles on lines 4 and 6.
- **Diagnostics tab title:** pills show `2 errors`.
- **Diagnostics list:**
  - `[error] null_deref @ Line 4` — "Dereference of null pointer 'p'"
  - `[error] div_zero @ Line 6` — "Division by literal zero"
- Click the **null_deref** card → editor reveals/selects line 4,
  side panel highlights the active diagnostic, **LLVM Evidence** block
  shows:
  ```
  store ptr null, ptr %2
  %3 = load ptr, ptr %2
  store i32 42, ptr %3
  ```
- Click **Explain & Suggest Fix** → Groq returns a 1-paragraph
  explanation + a code-snippet fix.
- Switch to **LLVM IR** tab → metrics bar shows e.g.
  `Functions: 1 · Basic Blocks: 1 · Instructions: ~12 · Memory Ops: 6 · Arithmetic Ops: 1`.
- Switch to **CFG** tab → control-flow graph with a single function
  named `main`. ENTRY (green) → statements → return → EXIT (red).
- Switch to **AST** tab → libclang AST tree.

Screenshot: `screenshots/01-overview.png`

### 2. Failure case 1 — code that doesn't compile

Edit the editor to introduce a syntax error:

```c
int main(void) {
    int x = ;       // missing RHS
    return x
}                   // missing semicolon
```

Hit **Ctrl + Enter**. Expect:

- **Diagnostics tab** empty (no clean AST to analyze).
- **Parse errors tab** has at least 2 entries from libclang.
- **LLVM IR tab** shows a clang error block — but the rest of the UI
  is alive.

Screenshot: `screenshots/02-parse-errors.png`

### 3. Failure case 2 — clang missing (graceful degradation)

Either rename your `clang.exe` temporarily or unset `CLANG_PATH` in
`.env` and restart the server.

Re-paste the original buggy code from step 1. Expect:

- **Diagnostics still appear** with severity, category, and message.
- **LLVM Evidence** blocks disappear (graceful — no IR available).
- **LLVM IR tab** shows the install hint:
  > clang not found on PATH. Install LLVM (https://github.com/llvm/llvm-project/releases) and ensure `clang` / `clang++` are on PATH, or set CLANG_PATH in .env.
- AST + CFG still render normally.

This is the main "system handles missing dependency" demo and the
single most important failure-mode screenshot.

Screenshot: `screenshots/03-clang-missing.png`

### 4. Evaluation harness

In a second terminal:

```bash
./evaluate.sh
```

Expect a markdown table showing:

- 7-row per-category report for CD_LAB
- Aggregate comparison: cdlab vs. gcc -fanalyzer vs. clang --analyze
- cppcheck row only if installed

Screenshot: `screenshots/04-evaluation.png`

---

## Capturing the screenshots

We use Windows's built-in **Snipping Tool** (`Win + Shift + S`) at
1920×1080 zoom level 100%. Save under `screenshots/` with the names
listed above. The browser is Chrome 148 with DevTools closed and the
default font size.

Suggested screen captures:

1. `01-overview.png` — full window with 2 diagnostics + LLVM Evidence expanded
2. `02-parse-errors.png` — Parse errors tab active, errors visible
3. `03-clang-missing.png` — Diagnostics still working, LLVM IR tab
   showing the install hint
4. `04-evaluation.png` — terminal output of `./evaluate.sh`

For a video, [OBS Studio](https://obsproject.com/) at 30 fps records
the same flow in 2–3 minutes. Drop it at the repo root as `demo.mp4`
and link it from [README.md](../README.md).

---

## Why this demo design

- **Working case + 2 failure cases** exceeds the submission brief's
  "working + failure case" requirement.
- **Both failure cases are realistic:** one is user error (bad code),
  one is environment (missing dependency). Together they show CD_LAB
  is robust to both.
- **The evaluation screenshot proves the metrics are real** — they
  come from the same code the reviewer can run.
