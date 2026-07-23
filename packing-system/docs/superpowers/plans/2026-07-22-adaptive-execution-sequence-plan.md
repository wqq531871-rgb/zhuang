# Adaptive Execution Sequence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select staircase execution from layer-local height-transition frequency and produce deterministic X-column/Y scan order with lower-frontier priority.

**Architecture:** Extend the existing execution planner rather than the packing algorithm. Reuse its physical geometry, dependency graph, reverse peeling, deadline, and final replay gates; add focused helpers for classification, support tiers, scan columns, and diagnostics. Keep all output schemas unchanged.

**Tech Stack:** Python 3.8, dataclasses, PyYAML configuration, pytest.

---

### Task 1: Lock Mode Classification With Failing Tests

**Files:**
- Modify: `packing-system/tests/test_execution_sequence.py`
- Modify: `packing-system/tests/test_config.py`

- [ ] Add a test where large height spread exists only between flat geometric layers and assert `_uses_staircase_wave` is false.
- [ ] Add a sparse mixed-layer grid with fewer than the configured transition ratio and assert layerwise mode.
- [ ] Add an alternating mixed-layer grid with at least four significant adjacency transitions and assert staircase mode.
- [ ] Add validation and YAML loading tests for `staircase_transition_ratio_threshold`, `staircase_min_transition_edges`, and `scan_column_tolerance_mm`.
- [ ] Run the new tests and confirm they fail because the fields and layer-local classifier do not exist.

Run:

```powershell
python -B -m pytest tests/test_execution_sequence.py tests/test_config.py -q
```

Expected: the new assertions fail while existing collection succeeds.

### Task 2: Implement Layer-Local Mode Classification

**Files:**
- Modify: `packing-system/src/execution/sequence_planner.py`
- Modify: `packing-system/src/config/execution_sequence_config.py`
- Modify: `packing-system/src/config/loader.py`
- Modify: `packing-system/config/packing_config.yaml`

- [ ] Add validated defaults: transition ratio `0.25`, minimum transition edges `4`, and scan column tolerance `5.0 mm`.
- [ ] Group physical geometry by bottom Z within coordinate tolerance.
- [ ] Count side-adjacency edges and significant top-height transitions per layer.
- [ ] Return staircase mode only when one layer satisfies both count and ratio thresholds.
- [ ] Keep `adaptive_staircase_enabled=false` as an unconditional layerwise override.
- [ ] Run the Task 1 tests and confirm they pass.

### Task 3: Lock Origin Column Scan With Failing Tests

**Files:**
- Modify: `packing-system/tests/test_execution_sequence.py`

- [ ] Add a same-layer case containing `(x=0,y=900)` and `(x=100,y=0)` and assert the first box precedes the second for `x_min_y_min`.
- [ ] Add column-tolerance cases showing near X values share a column while values outside tolerance do not.
- [ ] Cover the opposite configured origin by asserting transformed X/Y progress is reversed deterministically.
- [ ] Preserve the existing three-sided-pocket gate test.
- [ ] Run the focused tests and confirm the current Euclidean-distance order fails the new expectations.

### Task 4: Implement Deterministic Scan Preference

**Files:**
- Modify: `packing-system/src/execution/sequence_planner.py`

- [ ] Build anchored X-column ranks from origin-relative leading edges.
- [ ] Replace Euclidean distance as the primary comparable-band preference with `(column_rank, y_progress, stable_index)`.
- [ ] In reverse peeling, use the exact reverse of the desired forward scan after hard candidate eligibility.
- [ ] Retain open-direction candidate filtering and use enclosure/height risk only to resolve candidates that cannot follow the preferred scan safely.
- [ ] Add deterministic logging for any scan inversion forced by hard dependencies.
- [ ] Run the Task 3 tests and the existing open-direction tests.

### Task 5: Lock And Implement Lower-Frontier Staircase Priority

**Files:**
- Modify: `packing-system/tests/test_execution_sequence.py`
- Modify: `packing-system/src/execution/sequence_planner.py`

- [ ] Replace the old test that expects `origin_top` before `outer_base` with a failing expectation that the equal-phase lower outer box comes first.
- [ ] Add a diagonal two-axis outer-foundation case matching pallet 11: inner upper `(0,0,240)` and outer base `(350,535,0)` must have the base first when their phases match.
- [ ] Compute support tiers from the support DAG.
- [ ] Change the staircase key to forward order `(phase, support_tier, scan_column, y_progress, stable_index)` and apply its reverse during peeling.
- [ ] Verify that lower-frontier preference does not bypass support, descent, or open-direction gates.
- [ ] Run all execution-sequence tests.

### Task 6: Document Configuration And Validate The Real Fixture

**Files:**
- Modify: `packing-system/README.md`
- Modify: `packing-system/docs/independent execution sequence planning documentation (Chinese filename)`
- Modify: `packing-system/config/packing_config.yaml`

- [ ] Document the local-transition meaning of the existing 120 mm threshold and the three new settings.
- [ ] Run execution planning against `ui_packing_plan_20260722_222030.json` into a temporary directory.
- [ ] Assert 11 pallets, 668 boxes, staircase classification only for pallet 11, pallet 6 first ID 569, pallet 8 first ID 578, and pallet 11 ID 644 before ID 324.
- [ ] Compare execution JSON, WCS cases, and WCS map by `seq`; verify that only execution JSON contains `stack_height_before`.
- [ ] Do not modify or stage any `packing-workspace` input, output, log, spreadsheet, or temporary configuration file.

### Task 7: Full Verification And Review

**Files:**
- Review all modified code, tests, configuration, and documentation.

- [ ] Run the complete packing-system test suite with third-party pytest plugin auto-loading disabled.
- [ ] Run the UI/WCS service integration tests.
- [ ] Run `git diff --check`.
- [ ] Request a spec-compliance review, then a code-quality review, and fix all findings.
- [ ] Inspect `git status` and ensure only intended code, tests, configuration, and documentation are candidates for a future commit.

Run:

```powershell
python -B -c "import os, pytest; os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'; raise SystemExit(pytest.main(['-p','no:cacheprovider','tests','-q']))"
```

Expected: zero failures.
