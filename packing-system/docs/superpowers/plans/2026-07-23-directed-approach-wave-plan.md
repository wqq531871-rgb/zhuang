# Directed Approach Wave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace adaptive layer/staircase selection with one deterministic `x_min_y_min` directed spatial wave that validates the robot's `+X/+Y` pre-position and short `-X/-Y` diagonal insertion path.

**Architecture:** Add a pure `approach_geometry.py` module for moving-rectangle sweep tests. Keep dependency construction and stable topological scheduling in `sequence_planner.py`, but replace footprint-BFS/adaptive classification with coordinate ranks and a single directed-wave key. Configuration owns all measured approach offsets and clearances; WCS output remains unchanged.

**Tech Stack:** Python 3.8, dataclasses, PyYAML, pytest, existing execution planner and WCS adapters.

---

## File Map

- Create `packing-system/src/execution/approach_geometry.py`: pure rectangle/segment and Z-overlap predicates.
- Modify `packing-system/src/execution/sequence_planner.py`: approach dependency edges, replay gate, coordinate wave keys, one planner path.
- Modify `packing-system/src/config/execution_sequence_config.py`: remove adaptive fields and add approach fields.
- Modify `packing-system/src/config/loader.py`: new defaults and removal of obsolete defaults.
- Modify `packing-system/config/packing_config.yaml`:现场参数 and comments.
- Modify `packing-system/run_packing.py` and `packing-system/run_execution_planning.py`: pass the new fields and remove adaptive CLI/config plumbing.
- Modify `packing-system/tests/test_execution_sequence.py`: geometry, ordering, replay, and output regression coverage.
- Modify `packing-system/tests/test_config.py` and `packing-system/tests/test_main.py`: configuration and entrypoint coverage.
- Modify `packing-system/docs/独立执行顺序规划说明.md` and `packing-system/README.md`: replace adaptive mode documentation.

### Task 1: Replace The Configuration Contract

**Files:**
- Modify: `packing-system/src/config/execution_sequence_config.py`
- Modify: `packing-system/src/config/loader.py`
- Modify: `packing-system/config/packing_config.yaml`
- Test: `packing-system/tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Add assertions for the new defaults and assert the dataclass no longer exposes adaptive fields:

```python
assert settings.approach_offset_x_mm == 35.0
assert settings.approach_offset_y_mm == 35.0
assert settings.approach_z_clearance_mm == 0.0
assert settings.approach_box_xy_clearance_mm == 0.0
assert settings.approach_suction_xy_clearance_mm == 2.0
assert not hasattr(settings, "adaptive_staircase_enabled")
assert not hasattr(settings, "staircase_min_transition_edges")
```

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'D:\anaconda3\install\python.exe' -m pytest tests/test_config.py -q
```

Expected: failures for missing approach fields and obsolete adaptive fields still present.

- [ ] **Step 3: Implement the minimal configuration change**

Use these dataclass fields in both settings/config objects:

```python
approach_offset_x_mm: float = 35.0
approach_offset_y_mm: float = 35.0
approach_z_clearance_mm: float = 0.0
approach_box_xy_clearance_mm: float = 0.0
approach_suction_xy_clearance_mm: float = 2.0
```

Validate every value as finite and non-negative. Delete
`adaptive_staircase_enabled`, `staircase_height_difference_threshold_mm`,
`staircase_transition_ratio_threshold`, `staircase_min_transition_edges`, and
`prefer_adjacent_occupied_sides` from dataclasses, defaults, and YAML.

- [ ] **Step 4: Run the configuration tests**

Expected: `tests/test_config.py` passes.

- [ ] **Step 5: Commit**

```powershell
git add packing-system/src/config packing-system/config/packing_config.yaml packing-system/tests/test_config.py
git commit -m "refactor(execution): replace adaptive sequence config"
```

### Task 2: Add Pure Diagonal Sweep Geometry

**Files:**
- Create: `packing-system/src/execution/approach_geometry.py`
- Test: `packing-system/tests/test_execution_sequence.py`

- [ ] **Step 1: Write failing geometry tests**

Cover a near-side blocker intersecting a `(+35,+35) -> (0,0)` moving box, a blocker outside the diagonal corridor, a blocker below the moving box, and a blocker overlapping the pre-position descent rectangle.

```python
path = MovingRectPath(
    final_rect=(0.0, 100.0, 0.0, 100.0),
    offset_x=35.0,
    offset_y=35.0,
    z_min=0.0,
    z_max=100.0,
)
assert moving_path_blocked(path, (100.0, 200.0, 0.0, 100.0), 0.0, 100.0, 0.0)
assert not moving_path_blocked(path, (0.0, 100.0, 150.0, 250.0), 0.0, 100.0, 0.0)
```

- [ ] **Step 2: Verify tests fail because the module is absent**

Run the named tests and confirm an import/function failure.

- [ ] **Step 3: Implement the pure geometry API**

Create:

```python
@dataclass(frozen=True)
class MovingRectPath:
    final_rect: Tuple[float, float, float, float]
    offset_x: float
    offset_y: float
    z_min: float
    z_max: float

def segment_intersects_rect(start, end, rect, tolerance=1e-6):
    x0, y0 = start
    dx, dy = end[0] - x0, end[1] - y0
    xmin, xmax, ymin, ymax = rect
    enter, leave = 0.0, 1.0
    for p, q in (
        (-dx, x0 - xmin),
        (dx, xmax - x0),
        (-dy, y0 - ymin),
        (dy, ymax - y0),
    ):
        if abs(p) <= tolerance:
            if q < -tolerance:
                return False
            continue
        ratio = q / p
        if p < 0:
            enter = max(enter, ratio)
        else:
            leave = min(leave, ratio)
        if enter - leave > tolerance:
            return False
    return True

def moving_path_blocked(
    path: MovingRectPath,
    blocker_rect: Tuple[float, float, float, float],
    blocker_z_min: float,
    blocker_z_max: float,
    xy_clearance: float,
    tolerance: float = 1e-6,
) -> bool:
    if path.z_max <= blocker_z_min + tolerance:
        return False
    if blocker_z_max <= path.z_min + tolerance:
        return False
    x0, x1, y0, y1 = path.final_rect
    bx0, bx1, by0, by1 = blocker_rect
    expanded = (
        bx0 - (x1 - x0) - xy_clearance,
        bx1 + xy_clearance,
        by0 - (y1 - y0) - xy_clearance,
        by1 + xy_clearance,
    )
    return segment_intersects_rect(
        (x0 + path.offset_x, y0 + path.offset_y),
        (x0, y0),
        expanded,
        tolerance,
    )
```

Use slab-based segment/AABB intersection against the blocker rectangle expanded by the moving rectangle dimensions and clearance. Check the translated start rectangle separately for the pre-position vertical descent. Reject non-finite geometry.

- [ ] **Step 4: Run geometry tests**

Expected: all new pure geometry tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packing-system/src/execution/approach_geometry.py packing-system/tests/test_execution_sequence.py
git commit -m "feat(execution): model diagonal approach sweep"
```

### Task 3: Replace Adaptive Sorting With One Directed Wave

**Files:**
- Modify: `packing-system/src/execution/sequence_planner.py`
- Test: `packing-system/tests/test_execution_sequence.py`

- [ ] **Step 1: Replace adaptive tests with failing directed-wave tests**

Test a 3x3 irregular first layer and stacked origin column. Expected base order starts at ring 0 and expands by anchored X/Y ranks; the origin upper box occurs in wave 1 before ring-1 boxes that would close its approach corridor.

```python
keys = _directed_wave_keys(geometry, supports, config, PALLET_DIMS)
assert sorted(range(4), key=keys.__getitem__) == [0, 1, 2, 3]
```

Assert classification helpers and regular planner functions are absent.

- [ ] **Step 2: Verify the directed-wave tests fail**

Expected: `_directed_wave_keys` missing and old adaptive helpers still present.

- [ ] **Step 3: Implement coordinate ranks and one scheduler path**

Cluster X and Y origin progress independently with `scan_column_tolerance_mm`, calculate:

```python
ring = max(x_rank, y_rank)
wave = ring + support_tier
key = (wave, ring, x_rank, y_rank, support_tier, stable_index)
```

Delete `_classify_staircase_wave`, `_uses_staircase_wave`, `_staircase_shells`, `_stable_regular_order`, and the adaptive branch. `sequence_pallet_items()` always invokes `_stable_directed_wave_order()`.

- [ ] **Step 4: Run sequence ordering tests**

Expected: deterministic directed-wave tests pass and no classification log remains.

- [ ] **Step 5: Commit**

```powershell
git add packing-system/src/execution/sequence_planner.py packing-system/tests/test_execution_sequence.py
git commit -m "feat(execution): use one directed spatial wave"
```

### Task 4: Add Approach Dependencies And Replay Gate

**Files:**
- Modify: `packing-system/src/execution/sequence_planner.py`
- Test: `packing-system/tests/test_execution_sequence.py`

- [ ] **Step 1: Write failing dependency tests**

Test that a far box precedes a near blocker, direct supports still precede upper boxes, a support/approach cycle raises `ExecutionSequenceError`, and final replay rejects a manually unsafe prefix.

```python
ordered = sequence_pallet_items(_pallet([near, far]), config)
assert [item["id"] for item in ordered] == ["far", "near"]
```

- [ ] **Step 2: Verify failure under the current vertical-only graph**

Expected: near/far order is not constrained or unsafe replay passes.

- [ ] **Step 3: Implement approach edges and replay**

Add `_add_approach_edges()` after existing clearance edges. Build moving box and suction paths from physical geometry and `suction_rect_*`; add `target -> blocker` for every blocking final box. Add `_assert_approach_replay_safe()` to the pre-centering and final-layout gates. Uniform centering preserves relative sweep geometry.

- [ ] **Step 4: Run execution tests**

Expected: dependency, cycle, replay, centering, WCS and stack-height tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packing-system/src/execution packing-system/tests/test_execution_sequence.py
git commit -m "feat(execution): gate diagonal robot approach"
```

### Task 5: Update Entrypoints And Documentation

**Files:**
- Modify: `packing-system/run_packing.py`
- Modify: `packing-system/run_execution_planning.py`
- Modify: `packing-system/tests/test_main.py`
- Modify: `packing-system/README.md`
- Modify: `packing-system/docs/独立执行顺序规划说明.md`

- [ ] **Step 1: Write failing entrypoint tests**

Assert config values reach `ExecutionSequenceConfig`, removed CLI flags are rejected, and one-command output still creates execution/WCS/map files with `stack_height_before` only in execution JSON.

- [ ] **Step 2: Verify failures**

Run `tests/test_main.py` and the CLI tests in `tests/test_execution_sequence.py`.

- [ ] **Step 3: Update wiring and docs**

Pass all five approach values in both entrypoints. Remove adaptive arguments and descriptions. Document the `x_max_y_max` robot side, `x_min_y_min` far origin, four sweep phases, calibration values, and failure policy.

- [ ] **Step 4: Run focused integration tests**

Expected: `tests/test_main.py`, `tests/test_config.py`, `tests/test_execution_sequence.py`, and `tests/test_wcs_adapter.py` pass.

- [ ] **Step 5: Commit**

```powershell
git add packing-system/run_*.py packing-system/README.md packing-system/docs packing-system/tests
git commit -m "docs(execution): document directed approach planner"
```

### Task 6: Validate The Real 668-Box Workflow

**Files:**
- No production changes unless a failing gate exposes a documented defect.
- Use: `packing-workspace/runtime/packing-realtime/exports/ui_packing_plan_20260723_102112.json`

- [ ] **Step 1: Run the complete focused suite**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'D:\anaconda3\install\python.exe' -m pytest tests/test_execution_sequence.py tests/test_config.py tests/test_main.py tests/test_wcs_adapter.py -q
```

- [ ] **Step 2: Verify the repository config fails safely**

Run `run_execution_planning.py` with the repository config and write to a temporary output directory outside `packing-workspace` tracked source paths. With the uncalibrated `approach_z_clearance_mm: 0`, pallet 11 must report a cyclic dependency and no execution/WCS artifacts may be published.

- [ ] **Step 3: Run the uncalibrated sensitivity diagnostic**

Run a separate in-memory diagnostic with `approach_z_clearance_mm: 120`. Check 11 pallets, 668 unique boxes, continuous per-pallet `seq`, approach replay success, first-layer directed-wave inversions, WCS field contract, and source JSON immutability. This value only demonstrates parameter sensitivity; it is not production acceptance and must not be written to the repository config without robot measurement.

- [ ] **Step 4: Run `git diff --check` and review the final diff**

Expected: no whitespace errors and no runtime/data files staged.

- [ ] **Step 5: Create the final local commit**

```powershell
git add packing-system
git commit -m "feat(execution): add directed diagonal approach planner"
```
