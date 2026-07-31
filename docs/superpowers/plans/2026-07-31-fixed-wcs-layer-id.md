# Fixed WCS Carton Layer ID Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every WCS `layers[].cartons[].layer_id` equal integer `1` while preserving geometric layer grouping.

**Architecture:** Keep the existing Z-derived geometric layer key solely for grouping the `layers` array. At each WCS payload boundary, emit a named constant for the carton `layer_id` field so the temporary contract is explicit and easy to reverse.

**Tech Stack:** Python 3, pytest, existing WCS adapters/exporters.

## Global Constraints

- Only WCS output `cartons[].layer_id` changes.
- `layers` remains grouped and sorted by Z.
- `seq`, `total_height`, carton dimensions, product codes, and internal geometry remain unchanged.
- Preserve unrelated user changes in the dirty worktree.

---

### Task 1: Protect the main and runtime-copy WCS adapters

**Files:**
- Modify: `packing-system/tests/test_wcs_adapter.py`
- Modify: `packing-system/packing/tests/test_wcs_adapter.py`
- Modify: `packing-system/src/adapter/wcs_adapter.py`
- Modify: `packing-system/packing/src/adapter/wcs_adapter.py`

**Interfaces:**
- Consumes: `report_to_plan_result(report: Optional[Dict], include_failed: bool = True) -> WcsPlanResult`
- Produces: WCS cases whose Z groups remain separate and whose carton `layer_id` values are all `1`.

- [ ] **Step 1: Strengthen the adapter contract tests**

Change each multi-layer end-to-end assertion from checking only the first layer to:

```python
assert len(c["layers"]) == 3
assert {
    carton["layer_id"]
    for layer in c["layers"]
    for carton in layer["cartons"]
} == {1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_wcs_adapter.py::test_end_to_end_roundtrip -q
python -m pytest packing/tests/test_wcs_adapter.py::test_end_to_end_roundtrip -q
```

Expected: each test fails because the second and third geometric groups currently emit `2` and `3`.

- [ ] **Step 3: Implement the minimal adapter change**

In both adapter modules, add:

```python
WCS_OUTPUT_LAYER_ID = 1
```

Keep the geometric lookup for grouping:

```python
geometric_layer_id = layer_of[z]
by_layer.setdefault(geometric_layer_id, []).append({
    # unchanged fields
    "layer_id": WCS_OUTPUT_LAYER_ID,
})
```

- [ ] **Step 4: Run adapter tests**

Run the two commands from Step 2. Expected: PASS.

### Task 2: Protect execution-order export

**Files:**
- Modify: `packing-system/tests/test_execution_sequence.py`
- Modify: `packing-system/src/execution/wcs_export.py`

**Interfaces:**
- Consumes: `report_to_execution_plan_result(...) -> WcsPlanResult`
- Produces: execution-ordered cartons with continuous `seq`, preserved Z groups, and `layer_id == 1`.

- [ ] **Step 1: Make the test exercise two Z groups**

Use a base carton at Z `0` and a top carton at Z `300`, then assert literal results:

```python
assert len(result.cases[0]["layers"]) == 2
assert [carton["seq"] for carton in cartons_by_seq] == [1, 2]
assert {carton["layer_id"] for carton in cartons_by_seq} == {1}
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
python -m pytest tests/test_execution_sequence.py::test_wcs_seq_follows_execution_order_and_layer_id_is_fixed -q
```

Expected: FAIL because the carton in the upper geometric group emits `layer_id == 2`.

- [ ] **Step 3: Implement the minimal export change**

Add `WCS_OUTPUT_LAYER_ID = 1`; use `geometric_layer_id` for `by_layer` and
`WCS_OUTPUT_LAYER_ID` for the emitted carton field.

- [ ] **Step 4: Run the focused test**

Run the command from Step 2. Expected: PASS.

### Task 3: Protect database reconstruction

**Files:**
- Modify: `packing-system/tests/test_success_box_db.py`
- Modify: `packing-system/src/service/success_box_db.py`

**Interfaces:**
- Consumes: `build_wcs_case_from_box_rows(box_unique_id, box_rows, box_index=1) -> Dict[str, Any]`
- Produces: reconstructed cases with preserved Z groups and fixed carton `layer_id`.

- [ ] **Step 1: Change the existing two-layer contract assertion**

Use literal expectations:

```python
assert len(case["layers"]) == 2
assert [
    carton["layer_id"]
    for layer in case["layers"]
    for carton in layer["cartons"]
] == [1, 1]
assert case["total_height"] == 720.0
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
python -m pytest tests/test_success_box_db.py::test_build_wcs_case_from_box_rows_layers_and_height -q
```

Expected: FAIL with actual layer IDs `[1, 2]`.

- [ ] **Step 3: Implement the minimal reconstruction change**

Add `WCS_OUTPUT_LAYER_ID = 1`; retain the geometric group key and emit the
constant in each carton.

- [ ] **Step 4: Run the focused test**

Run the command from Step 2. Expected: PASS.

### Task 4: Regression verification

**Files:**
- Verify only; no new files.

**Interfaces:**
- Consumes: all changes from Tasks 1-3.
- Produces: evidence that WCS output contracts pass without regressions.

- [ ] **Step 1: Run all directly affected test modules**

```powershell
python -m pytest tests/test_wcs_adapter.py tests/test_execution_sequence.py tests/test_success_box_db.py -q
python -m pytest packing/tests/test_wcs_adapter.py -q
```

Expected: PASS.

- [ ] **Step 2: Review the diff and worktree**

```powershell
git diff --check
git diff -- packing-system/src/adapter/wcs_adapter.py packing-system/packing/src/adapter/wcs_adapter.py packing-system/src/execution/wcs_export.py packing-system/src/service/success_box_db.py packing-system/tests/test_wcs_adapter.py packing-system/packing/tests/test_wcs_adapter.py packing-system/tests/test_execution_sequence.py packing-system/tests/test_success_box_db.py
git status --short
```

Expected: no whitespace errors; unrelated pre-existing changes remain untouched.

