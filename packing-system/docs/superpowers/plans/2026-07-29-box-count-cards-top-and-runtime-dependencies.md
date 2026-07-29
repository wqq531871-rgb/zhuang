# Box Count Cards Top Placement and Runtime Dependencies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the regular/irregular box cards to the top of the right metric grid and install the missing runtime packages for database, 3D, and solver support.

**Architecture:** Reorder the existing card list in `realtime_dashboard_v2.py` without changing statistics or lifecycle code. Install only packages proven missing from `D:\Python\python.exe`, then verify their imports and the integrated V3 UI.

**Tech Stack:** Python 3.11, PyQt5, unittest, pip

## Global Constraints

- The two count cards must be the first metric row under the current-pallet hero.
- Do not duplicate cards or statistics.
- Use `D:\Python\python.exe` for dependency installation and verification.
- Do not downgrade existing NumPy, Pandas, or PyQt5 packages.

---

### Task 1: Move the cards

**Files:**
- Modify: `packing-system/ui/realtime_dashboard_v2.py`
- Test: `packing-system/ui/tests/test_box_count_cards_unittest.py`

**Interfaces:**
- Consumes: existing `card_regular_boxes`, `card_irregular_boxes`, `card_fill`, and `card_mpm`.
- Produces: the same cards in a new grid order.

- [ ] **Step 1: Add a failing layout assertion**

Show the offscreen window, process Qt events, and assert both count cards have a smaller `y()` coordinate than `card_fill` and `card_mpm`, while the regular and irregular cards share the same `y()` coordinate.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH='E:\research_code\zhuang-main\packing-system\ui'
$env:QT_QPA_PLATFORM='offscreen'
D:\Python\python.exe -m unittest ui.tests.test_box_count_cards_unittest -v
```

Expected: failure because the count cards currently appear below the other metrics.

- [ ] **Step 3: Reorder the existing grid**

Place the two count cards first in the enumerated `cards` list, followed by the existing paired metrics, and place `card_cg` in the final left cell.

- [ ] **Step 4: Verify GREEN**

Run the same unittest command and expect all tests to pass.

### Task 2: Install and verify missing dependencies

**Files:**
- No source-file changes.

**Interfaces:**
- Consumes: `D:\Python\python.exe -m pip`.
- Produces: importable `pyqtgraph`, `OpenGL`, `pymysql`, and `ortools`.

- [ ] **Step 1: Preview dependency resolution**

Run:

```powershell
D:\Python\python.exe -m pip install --dry-run pyqtgraph==0.13.7 PyOpenGL==3.1.7 PyMySQL==1.0.2 ortools==9.8.3296 protobuf==4.25.3
```

Review the resolver output and confirm it does not downgrade NumPy, Pandas, or PyQt5.

- [ ] **Step 2: Install the packages**

Run the same command without `--dry-run`.

- [ ] **Step 3: Verify imports**

Import all four packages plus `pyqtgraph.opengl`, print installed versions, and confirm the dashboard's `HAS_GL` flag is true.

### Task 3: Final regression verification

**Files:**
- Test: `packing-system/ui/tests/test_box_counts_unittest.py`
- Test: `packing-system/ui/tests/test_box_count_cards_unittest.py`

**Interfaces:**
- Consumes: the completed layout and installed runtime.
- Produces: verified UI startup and dependency support.

- [ ] **Step 1: Run unittest discovery**

Run all `*unittest.py` files under `ui/tests`.

- [ ] **Step 2: Compile the affected modules**

Compile `dashboard_state.py`, `realtime_dashboard_v2.py`, and `realtime_dashboard_v3_clean.py`.

- [ ] **Step 3: Run a V3 offscreen smoke check**

Create `IndustrialPackingWorkbenchClean`, process Qt events, assert the card positions, confirm `HAS_GL`, and close the window.
