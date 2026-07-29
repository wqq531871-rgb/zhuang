# WCS Zero-Dimension Input Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude every WCS inventory record with a missing, non-numeric, non-finite, zero, or negative dimension before either local stock table is updated.

**Architecture:** Add one pure validation/splitting helper at the WCS service input boundary, after the existing case-type filter and before repository calls. Keep the raw response unchanged, pass only valid entries to both repositories, and log invalid samples for diagnosis.

**Tech Stack:** Python 3, pytest, existing WCS service and repository abstractions.

## Global Constraints

- The raw WCS JSON must remain complete and unmodified.
- Valid dimensions require finite numeric `length`, `width`, and `height`, each strictly greater than 0.
- Invalid records must enter neither `wcs_stock_box` nor `wcs_stock_box_all`.
- Do not weaken the final output quality gate.
- Do not hard-code product codes.

---

### Task 1: Pure dimension validation boundary

**Files:**
- Modify: `packing-system/packing/src/service/wcs_service.py`
- Modify: `packing-system/packing/tests/test_wcs_service.py`

**Interfaces:**
- Produces: `_split_positive_dimension_entries(entries: List[Dict]) -> tuple[List[Dict], List[Dict]]`.

- [ ] **Step 1: Write failing table-driven tests**

Add tests with literal records proving that positive finite dimensions are retained, while zero, negative, missing, text, infinity, and NaN dimensions are rejected. Assert the original list and dictionaries are unchanged.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_wcs_service.py -q`

Expected: import failure because `_split_positive_dimension_entries` does not exist.

- [ ] **Step 3: Implement the pure helper**

Use `float()` plus `math.isfinite()` for each of `length`, `width`, and `height`. Catch `TypeError`, `ValueError`, and `OverflowError`; do not mutate records.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_wcs_service.py -q`

Expected: all tests pass.

### Task 2: Apply filtering before both database writes

**Files:**
- Modify: `packing-system/packing/src/service/wcs_service.py`
- Modify: `packing-system/packing/tests/test_wcs_service.py`

**Interfaces:**
- Consumes: `_split_positive_dimension_entries`.
- Produces: `fetch_once()` repository calls containing only valid records.

- [ ] **Step 1: Write a failing fetch boundary test**

Construct `WcsPackingService` without its external constructor, replace `fetch_stock_response`, `_repo`, `_repo_all`, and `_need_repack` with controlled fakes, and supply one valid plus one zero-dimension MH423C record. Assert both repository methods receive only the valid record and captured output contains the invalid `product_code`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_wcs_service.py -q`

Expected: repository fakes receive both records.

- [ ] **Step 3: Integrate the helper**

After `_filter_mh423c`, split the retained list. Log the count and up to five samples formatted as `product_code/box_type/length×width×height`. Pass only the valid list to `sync_stock_entries()` and `insert_new_stock_entries()`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_wcs_service.py -q`

Expected: all tests pass.

### Task 3: Regression verification

**Files:**
- Modify: `packing-system/docs/API_INTEGRATION.md`

**Interfaces:**
- Documents: invalid WCS dimension handling.

- [ ] **Step 1: Document filtering behavior**

State that raw responses retain invalid rows for audit, but local stock tables and packing exclude non-positive or malformed dimensions.

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/test_wcs_service.py tests/test_stock_db.py tests/test_wcs_adapter.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run the complete packing test suite**

Run: `python -m pytest tests -q`

Expected: exit 0 with no failures.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check`

Expected: no whitespace errors and only the intended service, tests, and documentation are changed beyond pre-existing user files.
