# Serialized WCS Fetch Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent WCS inventory pulls during packing while preserving a 200-second schedule anchored to the previous pull start.

**Architecture:** Replace the continuous mode's fetch and packing threads with one serialized cycle. Record `time.monotonic()` immediately before each pull, perform the pull and any required packing synchronously, then wait only the positive remainder of `download_interval`.

**Tech Stack:** Python 3, `threading.Event`, `time.monotonic`, pytest.

## Global Constraints

- Packing in progress must block the next pull.
- If packing finishes before the interval deadline, wait only the remaining duration.
- If packing finishes at or after the interval deadline, pull again without delay.
- Continuous and until-success API modes use the same timing rule.
- Once and Excel modes remain unchanged.
- Preserve unrelated worktree changes and runtime data.

---

### Task 1: Serialize WCS pull and packing cycles

**Files:**
- Modify: `packing-system/packing/src/service/wcs_service.py`
- Test: `packing-system/packing/tests/test_wcs_service.py`

**Interfaces:**
- Consumes: `DataSourceConfig.download_interval`, `fetch_once()`, `pack_once()`, and `self._stop.wait(timeout)`.
- Produces: `_wait_for_next_fetch(started_at: float) -> bool` and serialized `run_loop()` behavior.

- [ ] **Step 1: Write the two failing timing tests**

Use a fake monotonic clock and the existing recording stop event:

```python
def test_waits_only_for_interval_remainder_after_fast_pack(monkeypatch):
    service = _make_service([1])
    service._ds.download_interval = 200
    monkeypatch.setattr(
        wcs_service_module.time,
        "monotonic",
        Mock(return_value=200.0),
    )

    service._wait_for_next_fetch(100.0)

    assert service._stop.wait_calls == [100.0]


def test_does_not_wait_after_pack_exceeds_interval(monkeypatch):
    service = _make_service([1])
    service._ds.download_interval = 200
    monkeypatch.setattr(
        wcs_service_module.time,
        "monotonic",
        Mock(return_value=350.0),
    )

    service._wait_for_next_fetch(100.0)

    assert service._stop.wait_calls == [0.0]
```

- [ ] **Step 2: Run the tests and verify RED**

```powershell
python -m pytest packing/tests/test_wcs_service.py::test_waits_only_for_interval_remainder_after_fast_pack packing/tests/test_wcs_service.py::test_does_not_wait_after_pack_exceeds_interval -q
```

Expected: both fail because `_wait_for_next_fetch` does not exist.

- [ ] **Step 3: Implement the timing helper and serialized cycle**

Import `time` and add:

```python
def _wait_for_next_fetch(self, started_at: float) -> bool:
    elapsed = max(0.0, time.monotonic() - started_at)
    remaining = max(0.0, float(self._ds.download_interval) - elapsed)
    return self._stop.wait(remaining)
```

Change `run_loop()` to one loop that records `started_at`, calls
`fetch_once()`, conditionally reloads reference data and calls `pack_once()`,
then calls `_wait_for_next_fetch(started_at)`. Keep fetch and packing exception
handling equivalent to the current loops.

In `run_until_success()`, record `started_at` before each pull and replace the
full-interval wait with `_wait_for_next_fetch(started_at)`.

- [ ] **Step 4: Run focused and module tests**

```powershell
python -m pytest packing/tests/test_wcs_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Run regression checks and commit**

```powershell
python -m pytest packing/tests/test_wcs_service.py packing/tests/test_wcs_adapter.py -q
git diff --check
git add packing-system/packing/src/service/wcs_service.py packing-system/packing/tests/test_wcs_service.py
git commit -m "fix: serialize WCS fetch and packing schedule"
```

