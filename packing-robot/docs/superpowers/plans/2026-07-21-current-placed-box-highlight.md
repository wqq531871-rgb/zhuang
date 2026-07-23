# Current Placed Box Highlight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Highlight only the most recently placed box in orange and restore it to its normal type color only when the next box reaches the pallet.

**Architecture:** Add a pure phase-to-color function in `packing_ui.scene` and apply its result to the reused active-box actor on every rendered frame. Existing target actors continue to provide solid normal-color history and translucent future positions.

**Tech Stack:** Python, PyVista, pytest.

## Global Constraints

- Orange applies at `PLACE_DESCEND` 100%, `RELEASE`, and `RETRACT`.
- The latest placed box remains orange while the next box is picked and transferred; older placed boxes remain opaque in their original type color.
- Future targets remain translucent.

---

### Task 1: Active box phase color

**Files:**
- Modify: `tests/test_scene_geometry.py`
- Modify: `packing_ui/scene.py`

**Interfaces:**
- Consumes: `box_type: str`, `phase: str`, `fraction: float`
- Produces: `active_box_color(...) -> tuple[float, float, float]`

- [ ] Add assertions that transfer and incomplete descent use `_type_color`, while completed descent, release, and retract use `CURRENT_PLACED_COLOR`.
- [ ] Run `python -m pytest tests/test_scene_geometry.py -q` and confirm the missing function causes failure.
- [ ] Implement `CURRENT_PLACED_COLOR` and `active_box_color`.
- [ ] Update `PackingScene.show_frame` to set the active actor color every frame.
- [ ] Run the focused test and full test suite.
- [ ] Render consecutive placement frames and verify only the latest placed box is orange.
