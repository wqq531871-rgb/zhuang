# Seq, Negative-Y Conveyor, and Min-Corner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make UI execution follow `seq`, move the conveyor to the negative-Y side of the `(0,0,0)` pallet origin, and align placement at `x_min_y_min`.

**Architecture:** Update the pure JSON normalization and action-building rules first, then move both trajectory start and PyVista conveyor geometry using matching negative-Y bounds. Keep legacy JSON loadable by using array order only when `seq` is absent.

**Tech Stack:** Python, PySide6, PyVista, pytest.

## Global Constraints

- `seq` is the only named sequence field.
- Conveyor Y bounds are `-1800` to `-350` mm.
- Placement corners are `x_min_y_min`.

---

### Task 1: Seq-only ordering

**Files:** `tests/test_data.py`, `packing_ui/data.py`

- [ ] Add a failing test where `seq` conflicts with both legacy fields and must win.
- [ ] Add a failing test that missing `seq` preserves array order even when legacy fields conflict.
- [ ] Change `_sequence_key` and parsed `sequence_source` to use only `seq` or `array`.
- [ ] Run `python -m pytest tests/test_data.py -q`.

### Task 2: Minimum-corner actions

**Files:** `tests/test_data.py`, `packing_ui/data.py`, `tests/test_animation.py`

- [ ] Change expected pickup mappings and fixed placement corners to `x_min_y_min` semantics.
- [ ] Change suction center expectations to `(x+300,y+400)` at 0° and `(x+400,y+300)` at 90°.
- [ ] Update `pickup_corner` and `build_action`, then run data and animation tests.

### Task 3: Negative-Y conveyor

**Files:** `tests/test_animation.py`, `tests/test_scene_geometry.py`, `packing_ui/animation.py`, `packing_ui/scene.py`

- [ ] Change tests to require conveyor and ready box entirely below Y=0.
- [ ] Set conveyor bounds to `-1800..-350` and center the box within those bounds.
- [ ] Update the default camera focal region to include both negative-Y conveyor and positive-Y pallet.
- [ ] Run the full suite and render READY plus PLACE_DESCEND frames.

### Task 4: Documentation

**Files:** `README.md`, `data_act/导出动作JSON字段说明.md`

- [ ] Replace legacy ordering precedence with `seq` plus array compatibility.
- [ ] Update conveyor side, pickup mapping, placement corners, and suction-center formulas.
- [ ] Compile all Python modules and verify the final test suite.
