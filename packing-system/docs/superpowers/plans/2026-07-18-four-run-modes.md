# Four Dashboard Run Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the API checkbox with a four-option run-mode selector and add a WCS loop that stops after the first result containing a successful pallet.

**Architecture:** Keep mode labels and UI control policy in the pure frontend `dashboard_state.py` helper. Add a small `PackRunResult` value object to the WCS orchestration service so `run_until_success()` can make an explicit stop decision without parsing logs or changing the packing workflow.

**Tech Stack:** Python 3, PyQt5, pytest, threading events

## Global Constraints

- Default mode is `continuous` (“接口持续运行”).
- Modes are exactly `continuous`, `once`, `excel`, and `until-success`.
- Polling interval is enabled only for `continuous` and `until-success`.
- Excel selection is enabled only for `excel`.
- Stop on the first round with at least one `SUCCESS` pallet, even if failed pallets remain.
- Do not modify `packing/src/main`, `packing/src/packing`, or `packing/src/rescue`.

---

### Task 1: WCS pack outcome and until-success loop

**Files:**
- Modify: `packing/src/service/wcs_service.py`
- Create: `packing/tests/test_wcs_service.py`

**Interfaces:**
- Produces: `PackRunResult(executed: bool, success_pallets: int, report_path: Optional[Path])`
- Produces: `WcsPackingService.run_until_success() -> bool`

- [ ] **Step 1: Write failing tests**

```python
def test_until_success_repeats_until_pack_result_has_success():
    service = make_service(fetch_results=[1, 1])
    service.pack_once = Mock(side_effect=[
        PackRunResult(True, 0, None),
        PackRunResult(True, 2, Path("success.json")),
    ])
    assert service.run_until_success() is True
    assert service.pack_once.call_count == 2


def test_until_success_does_not_repack_when_fetch_has_no_new_data():
    service = make_service(fetch_results=[0, 0, 1])
    service.pack_once = Mock(return_value=PackRunResult(True, 1, None))
    assert service.run_until_success() is True
    service.pack_once.assert_called_once()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q packing/tests/test_wcs_service.py`

Expected: import fails because `PackRunResult` and `run_until_success` do not exist.

- [ ] **Step 3: Implement `PackRunResult` and return it from `pack_once`**

Count successful pallets from the complete report, preserve all existing output writes and `[UI-RESULT]`, and return an explicit outcome for empty, failed, and successful calculations.

- [ ] **Step 4: Implement `run_until_success`**

Loop over `fetch_once`; call `pack_once` only when `inserted > 0`; return `True` when `success_pallets > 0`; otherwise wait on `_stop` for `download_interval`. Catch per-round exceptions, log, and continue after the interval.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest -q packing/tests/test_wcs_service.py`

Expected: all new service tests pass.

### Task 2: WCS CLI mode routing

**Files:**
- Modify: `packing/run_wcs_service.py`
- Extend: `packing/tests/test_wcs_service.py`

**Interfaces:**
- Produces: `_parse_cli(argv) -> (config_path, safe_compare, run_mode)`
- Produces: `main(argv=None) -> int`

- [ ] **Step 1: Add failing routing tests**

Test all three accepted modes and assert `main()` calls exactly one of `run_loop`, `run_once`, or `run_until_success`. Test that an unknown mode raises `SystemExit`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q packing/tests/test_wcs_service.py`

Expected: tuple shape or missing `main` assertion fails.

- [ ] **Step 3: Implement explicit `--run-mode` parsing and dispatch**

Keep `continuous` as the default. Instantiate the service once, dispatch through a fixed mapping, and return exit code `0` for successful completion and `1` only when a single/until-success call reports failure.

- [ ] **Step 4: Run service tests and verify GREEN**

Run: `python -m pytest -q packing/tests/test_wcs_service.py`

Expected: all service and CLI tests pass.

### Task 3: Pure four-mode frontend policy

**Files:**
- Modify: `ui/dashboard_state.py`
- Modify: `ui/tests/test_dashboard_state.py`

**Interfaces:**
- Produces: `RUN_MODE_OPTIONS: tuple[tuple[str, str], ...]`
- Produces: `run_mode_policy(mode) -> RunModePolicy`

- [ ] **Step 1: Add failing policy tests**

Assert exact label-to-key order, default first option, interval enabled for `continuous`/`until-success`, Excel enabled only for `excel`, and API classification for all non-Excel modes.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd ui && python -m pytest -q tests/test_dashboard_state.py`

Expected: missing `RUN_MODE_OPTIONS` or `run_mode_policy` import failure.

- [ ] **Step 3: Implement immutable mode policy**

Use a frozen dataclass with fields `uses_api`, `uses_interval`, and `uses_excel`; reject unknown modes with `ValueError`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd ui && python -m pytest -q tests/test_dashboard_state.py`

Expected: all helper tests pass.

### Task 4: Replace checkbox with run-mode combo box

**Files:**
- Modify: `ui/realtime_dashboard_v3_clean.py`
- Verify: `ui/tests/test_dashboard_state.py`

**Interfaces:**
- Consumes: `RUN_MODE_OPTIONS` and `run_mode_policy(mode)`
- Changes: `UiPackingWorker(..., run_mode="excel", download_interval=200, ...)`

- [ ] **Step 1: Replace `chk_api_mode` with `cmb_run_mode`**

Populate the combo with the four approved labels and internal keys, default to index zero, and call one `_on_run_mode_changed` handler that updates interval and Excel button states.

- [ ] **Step 2: Route starts by selected mode**

For `excel`, preserve the current Excel selection/config/output path flow. For API modes, generate API YAML and launch `run_wcs_service.py --run-mode <mode>`; only continuous/until-success use the interval control.

- [ ] **Step 3: Make logs and completion state mode-specific**

Continuous says it runs until stopped; once says the single run completed; until-success says it is waiting for the first successful pallet and reports normal completion when the service exits.

- [ ] **Step 4: Run UI tests, compile, and offscreen Qt smoke**

Run: `cd ui && python -m pytest -q tests`

Run: `python -m compileall -q ui packing`

Instantiate `IndustrialPackingWorkbenchClean` offscreen and assert the checkbox is absent, the combo has four items in the approved order, and control enablement changes with all four selections.

### Task 5: Full regression and scope verification

**Files:**
- Verify only.

- [ ] **Step 1: Run all algorithm and UI tests**

Run: `python -m pytest -q packing/tests`

Run: `cd ui && python -m pytest -q tests`

- [ ] **Step 2: Verify core algorithm scope**

Run: `git diff --name-only origin/main -- packing/src/main packing/src/packing packing/src/rescue`

Expected: no output.

- [ ] **Step 3: Verify final diff quality**

Run: `git diff --check && git status --short --branch`

Expected: no whitespace errors; changes limited to WCS orchestration, frontend, tests, and documentation.
