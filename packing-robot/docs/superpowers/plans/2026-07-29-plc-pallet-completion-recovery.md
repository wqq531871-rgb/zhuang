# PLC Pallet Completion Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep an unfinished pallet active across recalculation and restart, and mark it done only after the PLC-requested maximum `seq` completes its handshake.

**Architecture:** The shared runtime JSON remains the persistence boundary. `packing-system` stops treating calculation as physical completion; `packing-robot` gains focused recovery/completion helpers, and `PlcController` invokes completion only from the existing post-handshake `box_finished(seq)` signal using the started plan's maximum sequence.

**Tech Stack:** Python 3, PySide6 signals, pytest, atomic JSON runtime files.

## Global Constraints

- A pallet is complete only when the PLC-requested maximum `seq` has returned from `send_normal()` and emitted `box_finished(seq)`.
- Recalculation, connection changes, stop, error, shutdown, and restart must not mark a pallet done.
- Startup recovery may select only the newest `active` history entry when the current session is absent.
- Existing unrelated runtime and generated files in the worktree must remain untouched.

---

### Task 1: Preserve unfinished state during recalculation and pallet selection

**Files:**
- Modify: `packing-system/src/service/live_stack_bridge.py`
- Create: `packing-system/tests/test_live_stack_bridge.py`

**Interfaces:**
- Consumes: `write_selected_pallet_session(..., workspace: Path)` and `clear_current_session_after_replan(workspace: Path)`.
- Produces: selection that leaves unrelated active history untouched, and recalculation cleanup that preserves session/history.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_selecting_new_pallet_does_not_finish_previous_active_pallet(tmp_path):
    write_selected_pallet_session(box_unique_id="old", workspace=tmp_path)
    write_selected_pallet_session(box_unique_id="new", workspace=tmp_path)
    history = list_selected_pallets(tmp_path)
    assert [(x["box_unique_id"], x["stack_status"]) for x in history] == [
        ("old", "active"),
        ("new", "active"),
    ]


def test_replan_keeps_unfinished_session_and_history(tmp_path):
    write_selected_pallet_session(box_unique_id="p1", workspace=tmp_path)
    before_session = read_json(session_path(tmp_path))
    clear_current_session_after_replan(tmp_path)
    assert read_json(session_path(tmp_path)) == before_session
    assert list_selected_pallets(tmp_path)[0]["stack_status"] == "active"
```

- [ ] **Step 2: Run the tests and verify the old behavior fails**

Run: `python -m pytest packing-system/tests/test_live_stack_bridge.py -q`

Expected: the first test sees `old=done`; the second sees a missing session and `done` history.

- [ ] **Step 3: Implement the minimal persistence change**

Remove the branch in `_upsert_history()` that rewrites other active entries as done. Change `clear_current_session_after_replan()` into a compatibility hook that preserves both files and only logs that unfinished state was retained.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest packing-system/tests/test_live_stack_bridge.py -q`

Expected: all tests pass.

### Task 2: Recover and complete runtime sessions safely

**Files:**
- Modify: `packing-robot/packing_ui/live_command.py`
- Create: `packing-robot/tests/test_live_command_recovery.py`

**Interfaces:**
- Produces: `recover_live_session(session_path=None, history_path=None) -> dict | None`.
- Produces: `mark_live_pallet_done(box_unique_id, session_path=None, history_path=None) -> bool`.

- [ ] **Step 1: Write failing recovery and completion tests**

```python
def test_recovers_newest_active_history_when_session_missing(tmp_path):
    history = tmp_path / "history.json"
    session = tmp_path / "session.json"
    write_live_command(history, [
        {"box_unique_id": "old", "stack_status": "active"},
        {"box_unique_id": "done", "stack_status": "done"},
        {"box_unique_id": "new", "stack_status": "active"},
    ])
    assert recover_live_session(session, history)["box_unique_id"] == "new"
    assert read_live_session(session)["box_unique_id"] == "new"


def test_does_not_recover_completed_history(tmp_path):
    history = tmp_path / "history.json"
    write_live_command(history, [{"box_unique_id": "p1", "stack_status": "done"}])
    assert recover_live_session(tmp_path / "session.json", history) is None


def test_marks_only_matching_pallet_done_and_clears_matching_session(tmp_path):
    history = tmp_path / "history.json"
    session = tmp_path / "session.json"
    write_live_command(history, [
        {"box_unique_id": "p1", "stack_status": "active"},
        {"box_unique_id": "p2", "stack_status": "active"},
    ])
    write_live_command(session, {"box_unique_id": "p1"})
    assert mark_live_pallet_done("p1", session, history) is True
    assert [x["stack_status"] for x in read_live_pallet_history(history)] == [
        "done", "active"
    ]
    assert read_live_session(session) is None
```

- [ ] **Step 2: Run tests and verify missing APIs fail**

Run: `python -m pytest packing-robot/tests/test_live_command_recovery.py -q`

Expected: import failure for `recover_live_session` and `mark_live_pallet_done`.

- [ ] **Step 3: Implement atomic recovery and completion**

`recover_live_session()` must return the valid current session first; otherwise scan history in reverse for `stack_status == "active"`, persist that entry as the current session, and return it. `mark_live_pallet_done()` must update only matching history entries, add `completed_at`, and delete the session file only when its UID matches; return whether an active matching history entry changed.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest packing-robot/tests/test_live_command_recovery.py -q`

Expected: all tests pass.

### Task 3: Bind completion to the maximum sequence handshake

**Files:**
- Modify: `packing-robot/packing_ui/plc_controller.py`
- Create: `packing-robot/tests/test_plc_completion.py`
- Modify: `packing-robot/tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `mark_live_pallet_done(box_unique_id) -> bool`.
- Produces: `PlcController._on_box_finished(box_unique_id: str, final_seq: int, seq: int) -> None`.
- Constructor dependency: `pallet_completion_writer`, defaulting to `mark_live_pallet_done`.

- [ ] **Step 1: Write failing controller boundary tests**

```python
def test_non_final_handshake_does_not_complete_pallet(qapp):
    completed = []
    controller = PlcController(pallet_completion_writer=completed.append)
    controller._on_box_finished("p1", 9, 8)
    assert completed == []


def test_final_sequence_handshake_completes_started_pallet(qapp):
    completed = []
    controller = PlcController(pallet_completion_writer=completed.append)
    controller._on_box_finished("p1", 9, 9)
    assert completed == ["p1"]
```

Update the UI worker fake to keep the existing `box_finished(int)` signal contract.

- [ ] **Step 2: Run and verify the new method/dependency is absent**

Run: `python -m pytest packing-robot/tests/test_plc_completion.py -q`

Expected: constructor or method failure because completion handling does not exist.

- [ ] **Step 3: Implement maximum-sequence completion**

Inject the completion writer. In `start_pallet_send()`, derive `final_seq = max(sequences)` and connect:

```python
worker.box_finished.connect(
    lambda seq, started_uid=uid, last_seq=final_seq:
        self._on_box_finished(started_uid, last_seq, seq)
)
```

`_on_box_finished()` logs every completed handshake and invokes the writer only when `int(seq) == int(final_seq)`. Catch persistence errors and log them without changing the PLC worker result.

- [ ] **Step 4: Switch session loading to recovery**

Change `try_load_session_plan()` to call `recover_live_session(default_session_path(), default_history_path())`, then load the recovered UID. This makes constructor autoload and the refresh button share the same behavior.

- [ ] **Step 5: Run controller and UI tests**

Run: `python -m pytest packing-robot/tests/test_plc_completion.py packing-robot/tests/test_ui_smoke.py -q`

Expected: all tests pass.

### Task 4: Regression verification

**Files:**
- Modify: `packing-robot/README.md`

**Interfaces:**
- Documents: physical completion boundary and restart recovery behavior.

- [ ] **Step 1: Update PLC handoff documentation**

Document that the maximum `seq` completing its PLC handshake marks the pallet done, and that unfinished active pallets are restored after restart.

- [ ] **Step 2: Run focused cross-module regression tests**

Run: `python -m pytest packing-system/tests/test_live_stack_bridge.py packing-robot/tests/test_live_command_recovery.py packing-robot/tests/test_plc_completion.py packing-robot/tests/test_plc_worker.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run both relevant test suites**

Run: `python -m pytest packing-system/tests -q`

Run: `python -m pytest packing-robot/tests -q`

Expected: both commands exit 0 with no failures.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended source, tests, docs, plus pre-existing unrelated runtime/generated changes are listed.
