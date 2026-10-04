# Pluggable Packing Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the selected index or fill-rate target drive packing, stopping, rescue, incremental behavior, and final publication while preserving the existing index-mode result.

**Architecture:** Add one target-policy abstraction and inject it into the existing packing and rescue pipeline. Geometry and physical constraints remain shared; index mode uses the historical metrics and fill-rate mode substitutes additive box-volume contribution and a selected pallet-volume threshold.

**Tech Stack:** Python 3.11, dataclasses/typing, PyYAML, PyQt5, OR-Tools CP-SAT, pytest

**Spec:** `docs/superpowers/specs/2026-10-04-pluggable-packing-target-design.md`

## Global Constraints

- Preserve the existing index mode's pallet count, box assignment, positions, and statuses for fixed inputs.
- Fill-rate mode supports only 0.70, 0.75, 0.80, 0.85, and 0.90, with an inclusive boundary.
- In fill-rate mode, index values remain visible but never influence selection, stopping, rescue, ordering, or final status.
- Both modes retain all geometry, weight, stability, suction, flat-top, case-group, order-isolation, and conservation gates.
- Reuse the packing and rescue pipeline; do not duplicate a standalone fill-rate algorithm.
- Every input box must appear exactly once in output, including boxes left after a pallet reaches its target.

## Review Focus

- Missing, zero, or non-finite pallet dimensions in fill-rate mode must fail with a clear data error; Task 1 pins this behavior.
- Floating-point values exactly at each allowed fill-rate threshold must count as reached; Task 1 pins the tolerance.
- Rotated or layered boxes must contribute their original physical volume exactly once; Task 2 tests raw/original dimension handling.
- A fill-rate run containing an index-failed/fill-passed pallet and an index-passed/fill-failed pallet must route each solely by fill status; Tasks 3 and 5 test both cases.
- Normal, incremental, and WCS entry points must construct the same policy from the same YAML; Tasks 4 and 5 test propagation.

---

### Task 1: Target Policy Domain Model

**Files:**
- Create: `packing-system/packing/src/main/target_policy.py`
- Modify: `packing-system/packing/src/main/success_target.py`
- Modify: `packing-system/packing/src/main/__init__.py`
- Test: `packing-system/packing/tests/test_target_policy.py`

**Interfaces:**
- Consumes: `SuccessTarget(mode: str, threshold: float)` from `src.main.success_target`.
- Produces: `PackingTargetPolicy`, `IndexTargetPolicy`, `FillRateTargetPolicy`, and `make_target_policy(success_target: SuccessTarget, index_target: float, pallet_dims: dict) -> PackingTargetPolicy`.
- `PackingTargetPolicy` exposes `mode`, `threshold`, `box_value(box: dict) -> float`, `items_value(items: Sequence[dict]) -> float`, `is_reached(items: Sequence[dict]) -> bool`, `gap(items: Sequence[dict]) -> float`, and `annotate_plan(plan: dict) -> dict`.

- [ ] **Step 1: Write failing policy tests**

Add tests named `test_index_policy_matches_historical_mpm_math`, `test_fill_policy_uses_volume_and_ignores_mpm`, `test_fill_policy_inclusive_boundary_for_all_steps`, `test_fill_policy_rejects_invalid_pallet_volume`, and `test_fill_policy_uses_original_box_volume_after_rotation`. Assert that fill policy gives identical values when only `min_pack_multiple` changes and raises `ValueError` for missing, zero, negative, NaN, or infinite pallet dimensions.

- [ ] **Step 2: Run the policy tests and verify RED**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_policy.py -q`

Expected: FAIL because `src.main.target_policy` does not exist.

- [ ] **Step 3: Implement the target policies**

Implement the exact interfaces above. Index policy stores the supplied per-pallet-type index target. Fill policy validates pallet volume once, uses `volume` when it is a finite positive raw volume and otherwise uses `original_length × original_width × original_height` before falling back to `length × width × height`, and compares with a `1e-12` inclusive tolerance. `annotate_plan` must preserve true `mpm_total`, `mpm_target`, `mpm_gap`, and `index_status`, then write goal/final fields separately.

- [ ] **Step 4: Run the policy tests and verify GREEN**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_policy.py tests/test_success_target.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit the policy layer**

```powershell
git add packing-system/packing/src/main/target_policy.py packing-system/packing/src/main/success_target.py packing-system/packing/src/main/__init__.py packing-system/packing/tests/test_target_policy.py packing-system/packing/tests/test_success_target.py
git commit -m "feat: add pluggable packing target policy"
```

### Task 2: Target-Aware Main Packing

**Files:**
- Modify: `packing-system/packing/src/packing/beam_search_packer.py`
- Modify: `packing-system/packing/src/packing/direct_layer_packer.py`
- Modify: `packing-system/packing/src/packing/global_column_packer.py`
- Modify: `packing-system/packing/src/main/pallet_packer.py`
- Test: `packing-system/packing/tests/test_target_aware_packing.py`
- Test: `packing-system/packing/tests/test_global_column_packer.py`
- Test: `packing-system/packing/tests/test_layered_packer.py`

**Interfaces:**
- Consumes: `PackingTargetPolicy` from Task 1.
- Produces: optional `target_policy: PackingTargetPolicy = None` parameters on public packing entry points; `None` creates historical index behavior from the existing `target_mpm` argument.
- Candidate ranking uses `target_policy.is_reached(...)`, then fewer pallets, then the highest failed-pallet `items_value(...)`.

- [ ] **Step 1: Write failing main-packer tests**

Add `test_beam_fill_mode_stops_at_fill_threshold_and_returns_remainder`, `test_beam_fill_mode_is_invariant_to_mpm_values`, `test_gcp_fill_mode_maximizes_fill_target_success_count`, `test_gcp_fill_mode_minimizes_volume_overshoot`, and `test_index_mode_candidate_output_is_unchanged`. The fill tests must include remaining boxes and assert every input ID appears exactly once across placed and remaining collections.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_aware_packing.py tests/test_global_column_packer.py -q`

Expected: new tests FAIL because packing entry points do not accept `target_policy`.

- [ ] **Step 3: Generalize Beam Search stopping and scoring**

Add the optional policy parameter without removing `target_mpm`. Replace state MPM sums used for target scoring/stopping with policy calls. Preserve the exact current branch when policy is omitted. Ensure target-reached states append all unprocessed boxes to `unfitted_items`.

- [ ] **Step 4: Generalize direct-layer and GCP target selection**

Thread the policy through direct-layer construction, CP-SAT target-subset selection, GCP plan annotation, and `_plan_rank`. In fill mode CP-SAT uses scaled box-volume ratios, the selected fill threshold, and minimum target overshoot; in index mode retain existing integer scaling and ordering.

- [ ] **Step 5: Run packing tests and verify GREEN**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_aware_packing.py tests/test_global_column_packer.py tests/test_layered_packer.py tests/test_flat_top.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit target-aware main packing**

```powershell
git add packing-system/packing/src/packing packing-system/packing/src/main/pallet_packer.py packing-system/packing/tests/test_target_aware_packing.py packing-system/packing/tests/test_global_column_packer.py packing-system/packing/tests/test_layered_packer.py
git commit -m "feat: drive main packing with selected target"
```

### Task 3: Target-Aware Rescue and Evaluation

**Files:**
- Modify: `packing-system/packing/src/rescue/pallet_evaluator.py`
- Modify: `packing-system/packing/src/rescue/failed_pool_rebuilder.py`
- Modify: `packing-system/packing/src/rescue/hole_fill_rescuer.py`
- Modify: `packing-system/packing/src/rescue/topup_rescuer.py`
- Modify: `packing-system/packing/src/rescue/recipe_rebuilder.py`
- Modify: `packing-system/packing/src/rescue/low_fill_repacker.py`
- Modify: `packing-system/packing/src/rescue/low_load_rebuilder.py`
- Modify: `packing-system/packing/src/rescue/tail_fragment_absorber.py`
- Modify: `packing-system/packing/src/rescue/rescue_optimizer.py`
- Modify: `packing-system/packing/src/rescue/directed_exchange.py`
- Test: `packing-system/packing/tests/test_target_aware_rescue.py`

**Interfaces:**
- Consumes: `PackingTargetPolicy` from Task 1 and target-aware packers from Task 2.
- Produces: optional `target_policy: PackingTargetPolicy = None` on rescue entry points and `PalletEvaluator.recompute_type_stats(plans, target_policy=None) -> dict`.
- Index-only helpers in `index_builder.py` and `index_swap.py` remain unchanged and are called only by index mode.

- [ ] **Step 1: Write failing rescue tests**

Add `test_fill_rescue_selects_failed_pallets_by_fill_not_index`, `test_fill_rescue_accepts_index_failed_fill_success`, `test_fill_rescue_rejects_index_success_fill_failure`, `test_fill_rescue_reaches_threshold_then_stops`, and `test_index_rescue_behavior_is_unchanged`. Use plans covering both discordant status combinations and assert the rescue input IDs, accepted plan, and final statuses.

- [ ] **Step 2: Run the rescue tests and verify RED**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_aware_rescue.py -q`

Expected: FAIL because rescue entry points still read index fields directly.

- [ ] **Step 3: Generalize pallet evaluation and generic rescue gates**

Make evaluator counts and rescue eligibility use the policy. Thread the optional policy through failed-pool rebuild, hole fill, top-up, recipe rebuild, low-fill/low-load rebuild, tail absorption, consolidation, and directed exchange. Replace target-relevant MPM sums/gaps/status reads with policy calls while leaving diagnostic index fields intact.

- [ ] **Step 4: Gate truly index-only optimizers**

At orchestration boundaries, run `index_builder` and `index_swap` only for `mode == "index"`. Fill mode must continue through generic rescue stages and must never use an index-only result as an acceptance condition.

- [ ] **Step 5: Run rescue tests and verify GREEN**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_aware_rescue.py tests/test_rescue_consolidation.py tests/test_directed_exchange.py tests/test_index_swap.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit target-aware rescue**

```powershell
git add packing-system/packing/src/rescue packing-system/packing/tests/test_target_aware_rescue.py
git commit -m "feat: evaluate rescue by selected packing target"
```

### Task 4: Workflow and Incremental Propagation

**Files:**
- Modify: `packing-system/packing/src/main/workflow.py`
- Modify: `packing-system/packing/src/main/result_formatter.py`
- Modify: `packing-system/packing/src/incremental/service.py`
- Modify: `packing-system/packing/run_packing.py`
- Test: `packing-system/packing/tests/test_target_workflow.py`
- Test: `packing-system/packing/tests/test_incremental.py`

**Interfaces:**
- Consumes: `make_target_policy(...)` and target-aware main/rescue entry points.
- Produces: one policy per `(pallet_type, sales_order_no, case_group)` group, created from the selected `SuccessTarget`, group index target, and group pallet dimensions.
- `run_incremental_packing(..., target_policy_factory: Callable[[dict], PackingTargetPolicy] | None = None)` uses the selected policy during both initial and incremental phases.

- [ ] **Step 1: Write failing workflow tests**

Add `test_workflow_fill_mode_ignores_index_during_packing_and_rescue`, `test_workflow_index_mode_matches_saved_baseline`, `test_incremental_fill_mode_keeps_fill_success_index_failure`, `test_incremental_fill_mode_repacks_fill_failure_index_success`, and `test_group_policy_uses_each_pallet_types_dimensions`.

- [ ] **Step 2: Run workflow tests and verify RED**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_workflow.py tests/test_incremental.py -q`

Expected: new behavior tests FAIL because workflow currently applies fill target only after packing.

- [ ] **Step 3: Inject policies through normal workflow**

Build a policy after resolving group dimensions and index target. Pass it through main packing, candidate comparison, all applicable rescue stages, stats, and report formatting. Remove the temporary final-only semantic while keeping final annotation idempotent.

- [ ] **Step 4: Make incremental orchestration policy-aware**

Replace direct `mpm_status` decisions in incremental keep/repack/recovery calculations with the policy's status. Run both phases with the selected policy; preserve index-mode results and the merged report's top-level target metadata.

- [ ] **Step 5: Run workflow tests and verify GREEN**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_workflow.py tests/test_incremental.py tests/test_success_target.py tests/test_main.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit workflow propagation**

```powershell
git add packing-system/packing/src/main packing-system/packing/src/incremental/service.py packing-system/packing/run_packing.py packing-system/packing/tests/test_target_workflow.py packing-system/packing/tests/test_incremental.py packing-system/packing/tests/test_success_target.py packing-system/packing/tests/test_main.py
git commit -m "feat: propagate packing target through workflows"
```

### Task 5: UI, WCS, Output, and End-to-End Compatibility

**Files:**
- Modify: `packing-system/config/packing_config.yaml`
- Modify: `packing-system/packing/src/service/wcs_service.py`
- Modify: `packing-system/packing/src/main/report_persister.py`
- Modify: `packing-system/ui/realtime_dashboard_v3_clean.py`
- Modify: `packing-system/ui/realtime_dashboard_v2.py`
- Test: `packing-system/ui/tests/test_success_target_ui.py`
- Test: `packing-system/packing/tests/test_wcs_service.py`
- Test: `packing-system/packing/tests/test_execution_planning_hook.py`
- Test: `packing-system/packing/tests/test_output_split.py`
- Create: `packing-system/packing/tests/test_target_end_to_end.py`

**Interfaces:**
- Consumes: selected target YAML and policy-aware workflow from Task 4.
- Produces: unchanged six-option UI; output that exposes true index fields plus final target fields; output bucket, robot sequence, execution hook, and WCS filters keyed by final target status.

- [ ] **Step 1: Write failing integration tests**

Add `test_ui_writes_fill_target_for_reused_excel_and_api`, `test_wcs_builds_fill_policy_from_default_and_explicit_yaml`, `test_execution_accepts_index_failed_fill_success`, `test_execution_rejects_index_success_fill_failure`, and `test_end_to_end_fill_mode_stops_at_target_without_losing_boxes`. The end-to-end test must assert target metadata, discordant index/final status, box conservation, and all final constraint gates.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_end_to_end.py tests/test_wcs_service.py tests/test_execution_planning_hook.py tests/test_output_split.py -q`

Expected: new end-to-end behavior tests FAIL until all consumers use the target-aware workflow.

- [ ] **Step 3: Complete entry-point and output wiring**

Ensure normal CLI, WCS service, API temporary YAML, reused Excel runs, and default YAML all resolve the same `SuccessTarget`. Keep `mpm_status` as the compatibility final status; use `index_status` for the index card and Excel “指数状态”; include explicit final-target columns.

- [ ] **Step 4: Verify UI and integration behavior**

Run from `packing-system/ui`:

`$env:QT_QPA_PLATFORM='offscreen'; D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_success_target_ui.py -q`

Run from `packing-system/packing`:

`D:\anaconda\envs\packing-zhuang\python.exe -m pytest tests/test_target_end_to_end.py tests/test_wcs_service.py tests/test_execution_planning_hook.py tests/test_output_split.py -q`

Expected: all targeted tests PASS.

- [ ] **Step 5: Commit integration wiring**

```powershell
git add packing-system/config/packing_config.yaml packing-system/packing/src/service/wcs_service.py packing-system/packing/src/main/report_persister.py packing-system/ui/realtime_dashboard_v3_clean.py packing-system/ui/realtime_dashboard_v2.py packing-system/ui/tests/test_success_target_ui.py packing-system/packing/tests/test_wcs_service.py packing-system/packing/tests/test_execution_planning_hook.py packing-system/packing/tests/test_output_split.py packing-system/packing/tests/test_target_end_to_end.py
git commit -m "feat: expose target-driven packing end to end"
```

### Task 6: Full Regression and Delivery

**Files:**
- Modify only files required to correct regressions found by this task.

**Interfaces:**
- Consumes: completed Tasks 1–5.
- Produces: verified index compatibility, verified fill behavior, and a clean reviewable diff.

- [ ] **Step 1: Run the complete packing suite**

Run from `packing-system/packing`:

`D:\anaconda\envs\packing-zhuang\python.exe -m pytest -q`

Expected: zero failures.

- [ ] **Step 2: Run the complete UI suite**

Run from `packing-system/ui`:

`$env:QT_QPA_PLATFORM='offscreen'; D:\anaconda\envs\packing-zhuang\python.exe -m pytest -q`

Expected: no new failures compared with the three documented unrelated baseline failures; all target-selection tests pass.

- [ ] **Step 3: Run static and dependency checks**

Run from repository root:

```powershell
git diff --check
D:\anaconda\envs\packing-zhuang\python.exe -m compileall -q packing-system/packing packing-system/ui
D:\anaconda\envs\packing-zhuang\python.exe -m pip check
```

Expected: clean diff, successful compilation, and `No broken requirements found.`

- [ ] **Step 4: Review target semantics in a generated report**

Run one fixed fixture in index mode and one in fill-rate mode. Assert index-mode output matches its saved baseline; in fill mode inspect at least one index-failed/fill-passed pallet and verify it is final `SUCCESS`, sequence eligible, and WCS eligible.

- [ ] **Step 5: Request whole-change review and address only confirmed findings**

Use a fresh reviewer to compare the implementation against the spec, with special attention to hidden reads of `mpm_status`, `mpm_total`, `mpm_gap`, `target_mpm`, and `min_pack_multiple` in target-sensitive code.

- [ ] **Step 6: Commit verified regression fixes, if any**

```powershell
git add <only-files-changed-by-confirmed-regression-fixes>
git commit -m "fix: preserve packing target semantics"
```
