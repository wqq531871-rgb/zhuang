# Per-Box Orientation and Green Corner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align pickup/place geometry to the screenshot's green `x_max_y_max` point and edit conveyor orientation independently for each box.

**Architecture:** Keep corner geometry in the pure data layer and store per-box UI orientation in `PackingMainWindow` keyed by plan and item. Rebuild actions from that map while preserving the selected playback step.

**Tech Stack:** Python, PySide6, PyVista, pytest.

## Global Constraints

- Placement box and cup corners are `x_max_y_max`.
- Each box independently stores 0° or 90° conveyor orientation.
- Existing global conveyor Z remains shared.

---

### Task 1: Green corner geometry

**Files:**
- Modify: `tests/test_data.py`
- Modify: `packing_ui/data.py`

**Interfaces:**
- Consumes: `build_action(item, conveyor_orientation_deg, conveyor_z)`
- Produces: `RobotAction` with corrected pickup/place corners and `suction_place`

- [ ] Change data assertions so no rotation uses `x_max_y_max`, 0→90 uses `x_max_y_min`, and 90→0 uses `x_min_y_max`.
- [ ] Assert placement corners are `x_max_y_max` and suction center is derived from the matching box/cup corners.
- [ ] Run `python -m pytest tests/test_data.py -q` and confirm the old implementation fails.
- [ ] Update `pickup_corner()` and `build_action()` with the new corner geometry.
- [ ] Run `python -m pytest tests/test_data.py -q` and confirm it passes.

### Task 2: Per-box UI orientation

**Files:**
- Modify: `tests/test_ui_smoke.py`
- Modify: `packing_ui/main_window.py`

**Interfaces:**
- Consumes: current pallet and selected box row
- Produces: `_orientation_by_item[(source_key, item_id)] -> int`

- [ ] Add a UI test selecting the second box, changing it to 90°, and asserting all other actions remain 0°.
- [ ] Add assertions that switching rows synchronizes the combo and preserves each value.
- [ ] Run the focused UI test and confirm failure because the current combo changes all actions.
- [ ] Store orientations by plan/item, synchronize the combo with selection, and rebuild while preserving the row.
- [ ] Display the per-box orientation in the list and export a per-item orientation map.
- [ ] Run `python -m pytest tests/test_ui_smoke.py -q` and confirm it passes.

### Task 3: Regression and visual verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: sample JSON and the real PyVista scene
- Produces: verified READY, PICK_ATTACH, and PLACE_DESCEND behavior

- [ ] Document green-corner and per-box editing semantics.
- [ ] Run `python -m pytest -q` and `python -m compileall -q main.py packing_ui tests`.
- [ ] Render a selected box at 90° and visually inspect conveyor location and aligned green corner geometry.
