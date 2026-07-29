# Regular and Irregular Box Counts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show regular and irregular box counts in the right-side summary area of the packing UI.

**Architecture:** Add a pure counting function to `ui/dashboard_state.py`, keeping dimension classification independent of Qt. Reuse the function from `realtime_dashboard_v2.py` to populate two existing-style metric cards during result load and reset them during clear.

**Tech Stack:** Python 3, PyQt5, pytest

## Global Constraints

- Use original dimensions before raw or effective dimensions.
- Compare corresponding length, width, and height axes without rotation.
- Treat integer ratios within `1e-6` as exact.
- Count malformed or non-positive dimensions as irregular.

---

### Task 1: Box classification

**Files:**
- Modify: `packing-system/ui/dashboard_state.py`
- Test: `packing-system/ui/tests/test_dashboard_state.py`

**Interfaces:**
- Produces: `regular_irregular_box_counts(pallets) -> tuple[int, int]`

- [ ] **Step 1: Write failing tests**

Add tests with hand-checked fixtures covering an integer-multiple pair plus an isolated specification, original-dimension precedence, invalid dimensions, and aggregation across pallets.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest ui/tests/test_dashboard_state.py -q`

Expected: collection fails because `regular_irregular_box_counts` does not exist.

- [ ] **Step 3: Implement the pure function**

Extract valid dimensions using the required field priority, group valid specifications, compare every distinct specification pair on all three axes, and return the total counts. Add invalid items directly to the irregular count.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest ui/tests/test_dashboard_state.py -q`

Expected: all tests pass.

### Task 2: UI cards and lifecycle

**Files:**
- Modify: `packing-system/ui/realtime_dashboard_v2.py`
- Test: `packing-system/tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `regular_irregular_box_counts(pallets) -> tuple[int, int]`
- Produces: `card_regular_boxes` and `card_irregular_boxes` metric cards.

- [ ] **Step 1: Write a failing UI smoke test**

Instantiate the workbench offscreen and assert both cards exist, then provide controlled pallet data and verify the displayed values after `populate_after_load()` or the focused refresh helper runs.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_ui_smoke.py -q`

Expected: failure because the new card attributes are absent.

- [ ] **Step 3: Implement the UI integration**

Import the pure function, append the two cards to the right summary grid, populate them after result load, and reset them in `clear_current_views()`.

- [ ] **Step 4: Verify GREEN and regression suite**

Run: `python -m pytest ui/tests/test_dashboard_state.py tests/test_ui_smoke.py -q`

Expected: all tests pass.

- [ ] **Step 5: Compile check**

Run: `python -m py_compile ui/dashboard_state.py ui/realtime_dashboard_v2.py`

Expected: exit code 0.
