# Height-Aware Egress and Forced WCS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delay only locally obstructive upper boxes and guarantee a support-safe execution/WCS bundle when configurable path gates reject a pallet.

**Architecture:** Add a pure local-egress geometry predicate, then convert its conflicts into lower-tier-to-upper-tier scheduling edges. Keep normal full-gate planning first; on `ExecutionSequenceError`, rebuild only support and egress edges, produce the same centered/annotated report, and derive execution JSON, WCS cases, and WCS map from that one report.

**Tech Stack:** Python 3.8, dataclasses, existing geometry helpers, PyYAML, pytest.

---

### Task 1: Configuration Contract

**Files:**
- Modify: `packing-system/src/config/execution_sequence_config.py`
- Modify: `packing-system/src/execution/sequence_planner.py`
- Modify: `packing-system/run_packing.py`
- Modify: `packing-system/run_execution_planning.py`
- Modify: `packing-system/config/packing_config.yaml`
- Test: `packing-system/tests/test_config.py`
- Test: `packing-system/tests/test_execution_sequence.py`

- [ ] **Step 1: Write failing configuration tests**

Add assertions that `force_publish_on_gate_failure` is loaded, rejects non-boolean values, and is passed into `ExecutionSequenceConfig`:

```python
settings = ExecutionSequenceSettings.from_dict({
    "force_publish_on_gate_failure": True,
})
assert settings.force_publish_on_gate_failure is True
with pytest.raises(ValueError, match="force_publish_on_gate_failure"):
    ExecutionSequenceSettings(force_publish_on_gate_failure="true")
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -B -m pytest tests/test_config.py tests/test_execution_sequence.py -q`

Expected: FAIL because the field is not defined or propagated.

- [ ] **Step 3: Add and propagate the boolean setting**

Add the field with a safe code default of `False`, include it in boolean validation, and set the repository delivery YAML to `true`:

```python
force_publish_on_gate_failure: bool = False
```

Pass `settings.force_publish_on_gate_failure` at both CLI construction sites. Preserve all current locally calibrated approach and suction values in `packing_config.yaml`.

- [ ] **Step 4: Run the focused tests**

Run: `python -B -m pytest tests/test_config.py tests/test_execution_sequence.py -q`

Expected: PASS for configuration tests; planner behavior remains unchanged in this task.

### Task 2: Pure Height-Aware Egress Geometry

**Files:**
- Modify: `packing-system/src/execution/approach_geometry.py`
- Test: `packing-system/tests/test_execution_sequence.py`

- [ ] **Step 1: Write failing geometry tests**

Cover all required branches:

```python
assert local_egress_blocked(
    corridor_rect=(100, 200, 100, 200),
    lower_top=100,
    upper_rect=(0, 95, 0, 95),
    upper_z_min=100,
    upper_z_max=220,
    offset_x=35,
    offset_y=35,
    xy_clearance=5,
    height_tolerance=2,
)
assert not local_egress_blocked(
    corridor_rect=(100, 200, 100, 200),
    lower_top=100,
    upper_rect=(0, 95, 0, 95),
    upper_z_min=100,
    upper_z_max=102,
    offset_x=35,
    offset_y=35,
    xy_clearance=5,
    height_tolerance=2,
)
assert not local_egress_blocked(
    corridor_rect=(100, 200, 100, 200),
    lower_top=100,
    upper_rect=(-500, -400, -500, -400),
    upper_z_min=100,
    upper_z_max=220,
    offset_x=35,
    offset_y=35,
    xy_clearance=5,
    height_tolerance=2,
)
```

Add a case where the upper rectangle is outside the local expanded rectangle but intersects the `+X/+Y` directional exit sweep.

- [ ] **Step 2: Run the new geometry tests and verify failure**

Run: `python -B -m pytest tests/test_execution_sequence.py -q -k "local_egress"`

Expected: FAIL because `local_egress_blocked` does not exist.

- [ ] **Step 3: Implement the pure predicate**

Implement and export:

```python
def local_egress_blocked(
    corridor_rect,
    lower_top,
    upper_rect,
    upper_z_min,
    upper_z_max,
    offset_x,
    offset_y,
    xy_clearance,
    height_tolerance,
    tolerance=1e-6,
):
    if upper_z_max <= lower_top + height_tolerance + tolerance:
        return False
    local_hit = _strict_axis_overlap(
        corridor_rect[0], corridor_rect[1],
        upper_rect[0], upper_rect[1], xy_clearance, tolerance,
    ) and _strict_axis_overlap(
        corridor_rect[2], corridor_rect[3],
        upper_rect[2], upper_rect[3], xy_clearance, tolerance,
    )
    path = MovingRectPath(
        corridor_rect, offset_x, offset_y, lower_top, upper_z_max
    )
    return local_hit or moving_path_blocked(
        path, upper_rect, upper_z_min, upper_z_max,
        xy_clearance, tolerance,
    )
```

Validate every numeric input through the module's existing finite/non-negative helpers.

- [ ] **Step 4: Run geometry tests**

Run: `python -B -m pytest tests/test_execution_sequence.py -q -k "local_egress or approach_geometry"`

Expected: PASS.

### Task 3: Add Local Egress Dependencies to the Directed Wave

**Files:**
- Modify: `packing-system/src/execution/sequence_planner.py`
- Test: `packing-system/tests/test_execution_sequence.py`

- [ ] **Step 1: Replace the obsolete early-upper expectation with failing behavior tests**

Change the five-box fixture expectation to:

```python
assert _ids(ordered) == [
    "origin_base",
    "y_base",
    "x_base",
    "diagonal_base",
    "origin_upper",
]
```

Add tests proving that equal top heights do not delay the upper box, a distant upper box is unaffected, and a directional-sweep conflict adds a lower-before-upper edge.

- [ ] **Step 2: Run the ordering tests and verify failure**

Run: `python -B -m pytest tests/test_execution_sequence.py -q -k "egress or public_planner_uses_one_directed_wave"`

Expected: FAIL with the current `origin_upper` second.

- [ ] **Step 3: Build egress edges**

Add `_add_height_egress_edges(items, config, edges, indegree, supports, pallet_dims, deadline)`:

```python
tiers = _support_tiers(supports, deadline)
for upper_idx, upper_supports in enumerate(supports):
    if not upper_supports:
        continue
    for lower_idx in range(len(items)):
        if tiers[lower_idx] >= tiers[upper_idx]:
            continue
        lower_rect = _suction_rect(
            items[lower_idx], 0.0, config.require_suction_pose
        ) or _rect(items[lower_idx])
        _x, _y, lower_z, _l, _w, lower_h = geometry[lower_idx]
        _ux, _uy, upper_z, _ul, _uw, upper_h = geometry[upper_idx]
        if local_egress_blocked(
            lower_rect,
            lower_z + lower_h,
            _rect(items[upper_idx]),
            upper_z,
            upper_z + upper_h,
            config.approach_offset_x_mm,
            config.approach_offset_y_mm,
            config.side_neighbor_clearance_mm,
            config.side_height_tolerance_mm,
            config.coordinate_tolerance_mm,
        ):
            _add_edge(edges, indegree, lower_idx, upper_idx)
```

Use the lower box's suction rectangle, falling back to its box rectangle only when suction pose is optional. Invoke this helper after support edges and before clearance/approach edges. Rebuild the same edge during centered final validation.

- [ ] **Step 4: Run execution-sequence tests**

Run: `python -B -m pytest tests/test_execution_sequence.py -q`

Expected: PASS, including the new pallet-1 order and equal-height exception.

- [ ] **Step 5: Commit the height-aware scheduler**

```bash
git add packing-system/src/execution/approach_geometry.py packing-system/src/execution/sequence_planner.py packing-system/tests/test_execution_sequence.py
git commit -m "feat(execution): add height-aware egress dependencies"
```

### Task 4: Support-Safe Forced Fallback

**Files:**
- Modify: `packing-system/src/execution/sequence_planner.py`
- Test: `packing-system/tests/test_execution_sequence.py`

- [ ] **Step 1: Write failing forced-fallback tests**

Create a fixture whose support and approach edges form a cycle. Verify:

```python
with pytest.raises(ExecutionSequenceError, match="cyclic"):
    plan_execution_report(report, ExecutionSequenceConfig(
        force_publish_on_gate_failure=False,
    ))

forced = plan_execution_report(report, ExecutionSequenceConfig(
    force_publish_on_gate_failure=True,
))
assert sorted(item["seq"] for item in forced_items) == list(
    range(1, len(forced_items) + 1)
)
assert support_seq < upper_seq
assert all("stack_height_before" in item for item in forced_items)
```

Also assert that duplicate IDs and out-of-bounds geometry still raise with the switch enabled.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -B -m pytest tests/test_execution_sequence.py -q -k "force_publish"`

Expected: FAIL because `plan_execution_report` still propagates the gate error.

- [ ] **Step 3: Extract shared finalization and implement per-pallet fallback**

Extract ordering output work into `_finalize_ordered_items`: deep-copy items, remove obsolete sequence fields, assign `seq`, center, refresh robot depth, optionally run complete final replay, and annotate `stack_height_before`.

Implement `_force_sequence_pallet_items` with a fresh deadline, support edges, height-egress edges, `preserve_open_direction=False`, and no clearance/approach/final path replay. Revalidate centered bounds and the retained dependency order.

In `plan_execution_report`, catch each pallet's `ExecutionSequenceError`; if the flag is true, log the pallet ID and original error at warning level, then call the forced planner. Do not catch failures from the forced planner.

- [ ] **Step 4: Run fallback and complete planner tests**

Run: `python -B -m pytest tests/test_execution_sequence.py -q`

Expected: PASS.

### Task 5: Derive All Artifacts from One Execution Report

**Files:**
- Modify: `packing-system/src/execution/wcs_export.py`
- Modify: `packing-system/src/execution/publisher.py`
- Modify: `packing-system/run_execution_planning.py`
- Test: `packing-system/tests/test_execution_sequence.py`
- Test: `packing-system/tests/test_main.py`

- [ ] **Step 1: Write a failing no-replanning test**

Monkeypatch `plan_execution_report` with a call counter, publish a bundle, and assert it is called once. Compare every pallet's execution `seq` against WCS case cartons and WCS map items.

- [ ] **Step 2: Run focused publication tests and verify failure**

Run: `python -B -m pytest tests/test_execution_sequence.py tests/test_main.py -q -k "publish or replanning or forced"`

Expected: FAIL because WCS export replans the original report.

- [ ] **Step 3: Add an execution-report exporter**

Add:

```python
def execution_report_to_plan_result(execution_report, include_failed=True):
    base_result = report_to_plan_result(
        deepcopy(execution_report), include_failed=include_failed
    )
    cases = deepcopy(base_result.cases)
    for case in cases:
        pallet = base_result.plan_by_unique_id[case["box_unique_id"]]
        layers, total_height = _layers_in_execution_order(
            list(pallet.get("packed_items") or [])
        )
        case["layers"] = layers
        case["total_height"] = total_height
    plan_by_unique_id = deepcopy(base_result.plan_by_unique_id)
    for pallet in plan_by_unique_id.values():
        for item in pallet.get("packed_items") or []:
            item.pop(STACK_HEIGHT_BEFORE_FIELD, None)
    return WcsPlanResult(cases=cases, plan_by_unique_id=plan_by_unique_id)
```

Keep `report_to_execution_plan_result` as a compatibility wrapper that plans once and delegates. Change publisher and CLI to call `execution_report_to_plan_result(execution_report)`.

- [ ] **Step 4: Run publication tests**

Run: `python -B -m pytest tests/test_execution_sequence.py tests/test_main.py -q`

Expected: PASS with one planning call and identical `seq` across all outputs.

- [ ] **Step 5: Commit forced publishing and single-report export**

```bash
git add packing-system/src/config/execution_sequence_config.py packing-system/src/execution packing-system/run_packing.py packing-system/run_execution_planning.py packing-system/tests/test_config.py packing-system/tests/test_execution_sequence.py packing-system/tests/test_main.py
git commit -m "feat(execution): force support-safe WCS fallback"
```

### Task 6: Documentation and End-to-End Verification

**Files:**
- Modify: `packing-system/docs/独立执行顺序规划说明.md`
- Modify: `packing-system/config/packing_config.yaml`

- [ ] **Step 1: Document the temporary safety policy**

Explain the new flag, which gates are bypassed, which constraints remain, the warning log, and that robot-controller collision checking remains mandatory. Update the previous statement that any gate failure prevents all execution output.

- [ ] **Step 2: Run the complete focused suite**

Run:

```powershell
& 'D:\anaconda3\install\python.exe' -B -m pytest tests/test_execution_sequence.py tests/test_config.py tests/test_main.py tests/test_wcs_adapter.py -q
```

Expected: all tests PASS.

- [ ] **Step 3: Run the current 668-box report through the independent planner**

Use `ui_packing_plan_20260723_160856.json` with the repository config and temporary output paths. Verify 11 pallets and 668 boxes, three fresh execution artifacts, unique continuous `seq`, `stack_height_before` only in execution JSON, pallet 1 IDs `150,154,151,155` all before ID `1`, and pallet 11 IDs `74,75,662,78` in that relative order.

- [ ] **Step 4: Review only task-owned changes**

Run `git diff --check`, inspect `git diff` and `git status --short`, and confirm the user's pre-existing calibrated config changes and generated workspace files were not reverted or committed accidentally.

- [ ] **Step 5: Commit docs and the isolated config flag hunk**

```bash
git add packing-system/docs/独立执行顺序规划说明.md packing-system/docs/superpowers/plans/2026-07-23-height-egress-forced-wcs-plan.md
git commit -m "docs(execution): describe forced gate fallback"
```

Stage only the `force_publish_on_gate_failure: true` configuration hunk if the file also contains unrelated local calibration changes.
