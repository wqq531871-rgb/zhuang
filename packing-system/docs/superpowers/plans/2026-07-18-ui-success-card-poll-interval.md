# Frontend Success Pallet Card and Poll Interval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second, full-width successful-pallet total card and a configurable WCS polling interval to the PyQt frontend without changing packing backend algorithms.

**Architecture:** Put result counting and polling-interval normalization in a small pure-Python frontend helper so behavior is testable without constructing Qt widgets. Reuse the helper from the V2 dashboard layout and V3 temporary-config workflow; V3 continues to launch the existing WCS service, but supplies the user-selected interval through YAML.

**Tech Stack:** Python 3, PyQt5, PyYAML, pytest

## Global Constraints

- Modify only `ui/`, frontend tests, and Superpowers documentation.
- Do not modify `packing/src`, `packing/run_packing.py`, or backend packing behavior.
- Poll interval range is exactly `1–86400` seconds; invalid configuration falls back to `200` seconds.
- The new card counts all pallets whose normalized `mpm_status` is `SUCCESS`, independent of UI filters and pagination.

---

### Task 1: Pure frontend state helpers

**Files:**
- Create: `ui/dashboard_state.py`
- Create: `ui/tests/test_dashboard_state.py`

**Interfaces:**
- Produces: `successful_pallet_count(pallets) -> int`
- Produces: `normalize_download_interval(value, default=200) -> int`
- Produces: `apply_download_interval(config, value) -> int`

- [ ] **Step 1: Write failing helper tests**

```python
from dashboard_state import (
    apply_download_interval,
    normalize_download_interval,
    successful_pallet_count,
)


def test_successful_pallet_count_uses_all_status_values_case_insensitively():
    pallets = [
        {"mpm_status": "SUCCESS"},
        {"mpm_status": "success"},
        {"mpm_status": "FAILED"},
        {},
    ]
    assert successful_pallet_count(pallets) == 2


def test_download_interval_normalization_and_config_write():
    assert normalize_download_interval("360") == 360
    assert normalize_download_interval(0) == 200
    assert normalize_download_interval(86401) == 200
    config = {}
    assert apply_download_interval(config, 15) == 15
    assert config["data_source"]["download_interval"] == 15
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd ui && python -m pytest -q tests/test_dashboard_state.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'dashboard_state'`.

- [ ] **Step 3: Implement the pure helper module**

```python
from typing import Iterable, MutableMapping

DEFAULT_DOWNLOAD_INTERVAL = 200
MIN_DOWNLOAD_INTERVAL = 1
MAX_DOWNLOAD_INTERVAL = 86400


def successful_pallet_count(pallets: Iterable[dict]) -> int:
    return sum(
        1 for pallet in (pallets or [])
        if str((pallet or {}).get("mpm_status") or "").strip().upper() == "SUCCESS"
    )


def normalize_download_interval(value, default: int = DEFAULT_DOWNLOAD_INTERVAL) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = int(default)
    if not MIN_DOWNLOAD_INTERVAL <= interval <= MAX_DOWNLOAD_INTERVAL:
        interval = int(default)
    return interval


def apply_download_interval(config: MutableMapping, value) -> int:
    interval = normalize_download_interval(value)
    data_source = config.setdefault("data_source", {})
    data_source["download_interval"] = interval
    return interval
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd ui && python -m pytest -q tests/test_dashboard_state.py`

Expected: `2 passed`.

### Task 2: Full-width successful-pallet card

**Files:**
- Modify: `ui/realtime_dashboard_v2.py:1052-1067`
- Modify: `ui/realtime_dashboard_v2.py:2391-2418`

**Interfaces:**
- Consumes: `successful_pallet_count(pallets) -> int`
- Produces: widget attribute `card_success_total`

- [ ] **Step 1: Add the new card to the overview grid**

Create `MetricCard("成功托盘总数")` and add it at row 3 spanning both columns, after the average fill card and before the advanced-parameter step.

- [ ] **Step 2: Update and clear the card**

In `populate_after_load`, calculate the global successful count from `self.pallets` and set the new card value with unit text `全部结果中的成功托盘`. In `clear_current_views`, reset it to `--`.

- [ ] **Step 3: Run the helper and existing UI tests**

Run: `cd ui && python -m pytest -q tests`

Expected: all UI tests pass.

### Task 3: Configurable WCS polling interval control

**Files:**
- Modify: `ui/realtime_dashboard_v3_clean.py:59-78`
- Modify: `ui/realtime_dashboard_v3_clean.py:181-216`
- Modify: `ui/realtime_dashboard_v3_clean.py:492-507`
- Modify: `ui/realtime_dashboard_v3_clean.py:607-627`
- Modify: `ui/realtime_dashboard_v3_clean.py:681-683`
- Modify: `ui/realtime_dashboard_v3_clean.py:867-927`
- Test: `ui/tests/test_dashboard_state.py`

**Interfaces:**
- Consumes: `normalize_download_interval(value) -> int`
- Consumes: `apply_download_interval(config, value) -> int`
- Changes: `_write_ui_config_api_only(project_dir, base_config_path, download_interval=None) -> Path`
- Changes: `UiPackingWorker(..., download_interval=200, ...)`

- [ ] **Step 1: Add interval behavior tests to the helper test file**

Cover non-numeric fallback, lower/upper valid boundaries, and preservation of existing `data_source` keys when writing the interval.

- [ ] **Step 2: Run the new tests and verify RED**

Run: `cd ui && python -m pytest -q tests/test_dashboard_state.py`

Expected: new boundary/preservation assertion fails until the helper is adjusted if necessary.

- [ ] **Step 3: Add the top-bar spin box**

Create `QSpinBox` beside “接口模式”, set range `1..86400`, suffix ` 秒`, and initialize it from the base YAML's `data_source.download_interval` through `normalize_download_interval`. Enable it only while interface mode is checked and no worker is running.

- [ ] **Step 4: Propagate the value to runtime configuration and messages**

Pass the spin-box value to `_write_ui_config_api_only`, write it through `apply_download_interval`, store it on `UiPackingWorker`, and replace every hard-coded “200 秒” API-mode status/log message with the selected interval.

- [ ] **Step 5: Run UI tests and compile the frontend**

Run: `cd ui && python -m pytest -q tests`

Expected: all UI tests pass.

Run: `python -m compileall -q ui`

Expected: exit code `0`.

### Task 4: Regression and scope verification

**Files:**
- Verify only; no production file changes.

**Interfaces:**
- Verifies the approved frontend-only scope.

- [ ] **Step 1: Run algorithm regression tests**

Run: `python -m pytest -q packing/tests`

Expected: `129 passed`.

- [ ] **Step 2: Run all UI tests from their supported working directory**

Run: `cd ui && python -m pytest -q tests`

Expected: all UI tests pass.

- [ ] **Step 3: Verify backend source is untouched**

Run: `git diff --name-only HEAD -- packing/src packing/run_packing.py`

Expected: no output.

- [ ] **Step 4: Review the final diff**

Run: `git diff --check && git diff --stat`

Expected: no whitespace errors; changes limited to the approved frontend, tests, and plan documentation.
