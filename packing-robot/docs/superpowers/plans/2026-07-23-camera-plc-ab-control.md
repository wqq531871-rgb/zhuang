# Camera Vision and PLC A/B Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive conveyor boxes from camera data and export PLC-ready rotation state and A/B pickup-point fields.

**Architecture:** Add a focused camera/PLC data module that validates camera JSON and derives PLC controls. Extend `RobotAction` with camera binding and semantic A/B fields, then connect those fields to the existing PySide6 controls, export path, animation origin and PyVista annotations.

**Tech Stack:** Python 3, PySide6, PyVista, pytest, JSON.

## Global Constraints

- A is `x_min_y_min`; B is `x_max_y_min`, independent of box orientation.
- `rotation_state = 1` means no rotation; `rotation_state = 2` means rotate 90°.
- `pickup_point_code = 1` means A; `pickup_point_code = 2` means B.
- Missing camera data permits offline preview but produces `ready = false`.
- Camera orientation accepts only 0 or 90.
- Existing `seq` ordering and `x_min_y_min` pallet placement remain unchanged.

---

### Task 1: Camera and PLC domain model

**Files:**
- Create: `packing_ui/integration.py`
- Create: `tests/test_integration.py`

**Interfaces:**
- Produces: `CameraBoxData`, `parse_camera_payload(data)`, `plc_control(camera_orientation, target_orientation)`.
- `CameraBoxData` contains `box_id`, optional `x/y/z`, `orientation_deg`, `timestamp`, and optional `confidence`.

- [ ] Write tests proving valid single-object/list parsing, invalid orientation rejection, and A/B/state mapping for all four 0°/90° combinations.
- [ ] Run `python -m pytest tests/test_integration.py -q` and confirm failure because the module does not exist.
- [ ] Implement immutable data classes, validation and control derivation.
- [ ] Run `python -m pytest tests/test_integration.py -q` and confirm all tests pass.

### Task 2: Extend robot actions and JSON output

**Files:**
- Modify: `packing_ui/data.py`
- Modify: `tests/test_data.py`

**Interfaces:**
- Consumes: `CameraBoxData | None` and `plc_control`.
- Produces: `build_action(..., camera_data=None)` and exported `camera`/`plc` objects.

- [ ] Add failing tests for camera orientation overriding manual orientation, camera metadata export, `rotation_state`, A/B fields and `ready`.
- [ ] Run the focused tests and confirm the new assertions fail.
- [ ] Add optional camera data and PLC fields to `RobotAction`; preserve old callers with defaults.
- [ ] Update `build_action` and `action_to_dict`; keep existing geometric corner calculations for safe animation while exposing the confirmed semantic A/B controls.
- [ ] Run `python -m pytest tests/test_data.py tests/test_integration.py -q`.

### Task 3: Camera-driven animation origin and A/B geometry

**Files:**
- Modify: `packing_ui/animation.py`
- Modify: `packing_ui/scene.py`
- Modify: `tests/test_animation.py`
- Modify: `tests/test_scene_geometry.py`

**Interfaces:**
- Consumes: action camera coordinates and semantic `pickup_point`.
- Produces: camera-aware `conveyor_box_origin` and `pickup_marker_positions`.

- [ ] Add failing tests showing camera X/Y/Z replace the nominal conveyor origin and A/B marker positions resolve to the two defined top corners.
- [ ] Run focused animation/geometry tests and verify failure.
- [ ] Implement camera-aware origin with nominal fallback, plus A/B marker helpers and scene labels.
- [ ] Run the focused tests and verify pass.

### Task 4: PySide6 camera input and PLC display

**Files:**
- Modify: `packing_ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `parse_camera_payload`, per-item camera map, extended actions.
- Produces: `receive_camera_data(payload)`, “导入相机 JSON” action, camera status fields and PLC-ready display.

- [ ] Add UI smoke tests for data binding by box ID, status labels, selected row synchronization and invalid payload handling without replacing valid data.
- [ ] Run `python -m pytest tests/test_ui_smoke.py -q` and confirm failure.
- [ ] Add the camera import button, status panel, in-memory map and action rebuild integration.
- [ ] Show camera coordinates, A/B point, point code, rotation state and readiness in the right panel and list rows.
- [ ] Run the UI smoke tests and confirm pass.

### Task 5: PLC command export and documentation

**Files:**
- Modify: `packing_ui/main_window.py`
- Modify: `data_act/导出动作JSON字段说明.md`
- Modify: `README.md`
- Modify: `tests/test_ui_smoke.py`

**Interfaces:**
- Produces: top-level `plc_commands` in exported JSON, one command per action with `ready`, state, point/code, pickup Z and placement values.

- [ ] Add a pure payload-builder test so export content is testable without a file dialog.
- [ ] Extract `build_export_payload()` and use it from `export_actions()`.
- [ ] Document camera input, PLC fields, A/B definitions and offline-not-ready behavior.
- [ ] Run `python -m pytest -q`, `python -m compileall -q main.py packing_ui tests`, then launch the desktop renderer and inspect a fresh screenshot.
