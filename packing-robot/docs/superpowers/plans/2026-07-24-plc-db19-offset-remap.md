# PLC DB19 Offset Remap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real DB19 communication to `packing-robot`, driven manually or by WCS-selected pallets, with the approved offsets, live database state gating, sequence validation, and alarm-only handling for `state=0`.

**Architecture:** A pure protocol module owns INT16 conversion, offsets, status reads, sequence checks and handshake writes. A small repository API supplies the latest row for one `box_unique_id + seq`; a Qt worker serializes the pallet without blocking the UI. `PackingMainWindow` owns connection controls, the default-off automatic-send toggle, manual start, and the existing `load_pallet` WCS trigger.

**Tech Stack:** Python 3.13, PySide6 6.7–6.9, PyMySQL, python-snap7 3.x, pytest 8

## Global Constraints

- Modify only `D:\research_code\final\zhuang\packing-robot`; never modify `D:\research_code\tongxun`.
- DB19 offsets are exactly DBW0 through DBW34 as recorded in the approved design.
- `box_num` is written only to DBW28; DBW2 is PLC-owned and must match database `seq`.
- `state IS NULL` waits; `state=0` writes only DBW32=1; `state=1/2` sends a normal command.
- Normal acknowledgement must observe DBW4=1 before clearing DBW0 and DBW30.
- “自动下发” is off on every application start.
- Tests never connect to a real PLC or MySQL server.

---

### Task 1: DB19 protocol and handshake

**Files:**
- Create: `packing_ui/plc_protocol.py`
- Create: `tests/test_plc_protocol.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `PlcCommand`, `PlcStatus`, `S7Config`, `build_command(row, box_num)`, `S7Client.read_status()`, `S7Client.send_normal(command)`, `S7Client.send_alarm(expected_seq)`, `create_snap7_client()`
- Consumes: mapping keys `seq`, `camera_length`, `camera_width`, `camera_height`, `raw_length`, `raw_width`, `raw_height`, `pos_x`, `pos_y`, `pos_z`, `state`, `stack_height_before`

- [ ] **Step 1: Write failing mapping and handshake tests**

```python
def test_command_maps_every_approved_dbw():
    command = build_command(ROW, box_num=12)
    assert command.words() == {
        6: 401, 8: 302, 10: 203,
        14: 400, 16: 300, 18: 200,
        20: 100, 22: 110, 24: 120,
        26: 2, 28: 12, 32: 0, 34: 480,
    }

def test_normal_send_rejects_wrong_plc_sequence_without_writes():
    client = FakeSnap7(reads=[status(fp=1, seq=8)])
    with pytest.raises(PlcSequenceMismatch):
        S7Client(client, CONFIG).send_normal(build_command(ROW, box_num=12))
    assert client.writes == []

def test_state_zero_writes_only_alarm_word():
    client = FakeSnap7(reads=[status(fp=1, seq=7)])
    S7Client(client, CONFIG).send_alarm(expected_seq=7)
    assert client.writes == [(19, 32, pack_int(1))]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_plc_protocol.py -q`
Expected: collection fails because `packing_ui.plc_protocol` does not exist.

- [ ] **Step 3: Implement constants, data models and fake-client-testable handshake**

```python
FP_OFFSET = 0
REQUEST_SEQ_OFFSET = 2
FP_OVER_OFFSET = 4
CAMERA_LENGTH_OFFSET = 6
CAMERA_WIDTH_OFFSET = 8
CAMERA_HEIGHT_OFFSET = 10
IDLE_OFFSET = 12
RAW_LENGTH_OFFSET = 14
RAW_WIDTH_OFFSET = 16
RAW_HEIGHT_OFFSET = 18
X_OFFSET = 20
Y_OFFSET = 22
Z_OFFSET = 24
STATE_OFFSET = 26
BOX_NUM_OFFSET = 28
DH_OVER_OFFSET = 30
ALARM_OFFSET = 32
STACK_HEIGHT_OFFSET = 34
```

Implement `read_status` as individual or grouped reads covering DBW0/2/4/12/30. `send_normal` must wait for `FP=1, FP_OVER=0, DH_OVER=0`, compare DBW2, write all command words except DBW30, write DBW30 last, observe DBW4=1, clear DBW0 and DBW30, then wait for DBW0/4/30 all zero. `send_alarm` validates DBW2 and writes only DBW32=1.

- [ ] **Step 4: Add runtime dependency**

Add `python-snap7>=3,<4` to `requirements.txt`, with import delayed inside `create_snap7_client`.

- [ ] **Step 5: Run protocol tests**

Run: `python -m pytest tests/test_plc_protocol.py -q`
Expected: all protocol tests pass.

- [ ] **Step 6: Commit**

```powershell
git add packing_ui/plc_protocol.py tests/test_plc_protocol.py requirements.txt
git commit -m "feat: add remapped DB19 protocol"
```

### Task 2: Live database state and command rows

**Files:**
- Modify: `packing_ui/plan_from_db.py`
- Create: `tests/test_plc_state_repository.py`

**Interfaces:**
- Produces: `fetch_plc_row(box_unique_id, seq, config_path=None) -> dict | None`, `count_pallet_boxes(box_unique_id, config_path=None) -> int`
- Consumes: the existing packing database YAML configuration and `wcs_success_box`

- [ ] **Step 1: Write failing repository tests**

```python
def test_fetch_plc_row_selects_all_command_fields_by_uid_and_seq(fake_connect):
    row = fetch_plc_row("a" * 32, 3, config_path=CONFIG)
    assert row["seq"] == 3
    sql, params = fake_connect.cursor.executed
    assert "camera_length" in sql
    assert "stack_height_before" in sql
    assert "box_unique_id = %s" in sql and "seq = %s" in sql
    assert params == ("a" * 32, 3)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_plc_state_repository.py -q`
Expected: import fails because `fetch_plc_row` is absent.

- [ ] **Step 3: Implement focused queries**

Use one connection per polling call with `DictCursor`, always close it, and select exactly the approved command fields. Treat a missing row as `None`; do not convert `state=None` to zero.

- [ ] **Step 4: Preserve fields in loaded item data**

Add `stack_height_before` and any available `box_num` to `PackedItem.original`. If `box_num` is not a physical database column, derive the total with `count_pallet_boxes` and pass it separately to `build_command`.

- [ ] **Step 5: Run repository and existing DB tests**

Run: `python -m pytest tests/test_plc_state_repository.py tests/test_data.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add packing_ui/plan_from_db.py tests/test_plc_state_repository.py
git commit -m "feat: query live PLC box state"
```

### Task 3: Background pallet sender

**Files:**
- Create: `packing_ui/plc_worker.py`
- Create: `tests/test_plc_worker.py`

**Interfaces:**
- Produces: `PlcSendWorker(config, box_unique_id, sequences, box_num, row_loader, client_factory)`, signals `status`, `plc_status`, `box_finished`, `alarm`, `failed`, `finished`
- Consumes: Task 1 protocol objects and Task 2 `fetch_plc_row`

- [ ] **Step 1: Write failing worker tests**

```python
def test_worker_waits_for_null_state_then_sends_latest_row():
    rows = iter([{**ROW, "state": None}, {**ROW, "state": 2}])
    worker = PlcSendWorker(..., row_loader=lambda *_: next(rows), sleep=lambda _: None)
    worker.run()
    assert fake_protocol.normal_sequences == [7]

def test_worker_state_zero_only_alarms_and_stops():
    worker = PlcSendWorker(..., row_loader=lambda *_: {**ROW, "state": 0})
    worker.run()
    assert fake_protocol.alarm_sequences == [7]
    assert fake_protocol.normal_sequences == []
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_plc_worker.py -q`
Expected: collection fails because `packing_ui.plc_worker` does not exist.

- [ ] **Step 3: Implement serial worker**

For every expected sequence, poll the row until `state is not None` or stop is requested. Route `0` to `send_alarm` and end the task; route `1/2` through `build_command` and `send_normal`; reject all other values. Never retry a command after an uncertain write.

- [ ] **Step 4: Run worker tests**

Run: `python -m pytest tests/test_plc_worker.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add packing_ui/plc_worker.py tests/test_plc_worker.py
git commit -m "feat: add live-state PLC sender"
```

### Task 4: Main-window controls and WCS/manual triggers

**Files:**
- Modify: `packing_ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `_connect_plc()`, `_start_current_pallet_send(source)`, `_stop_plc_send()`, `auto_plc_checkbox`
- Consumes: existing `apply_live_load_pallet`, Task 3 worker, and Task 1 `S7Config`

- [ ] **Step 1: Write failing UI tests**

```python
def test_plc_auto_is_off_on_every_window_start():
    window = _test_window()
    assert window.auto_plc_checkbox.isChecked() is False

def test_wcs_load_only_starts_when_auto_enabled(monkeypatch):
    window = _test_window()
    starts = []
    monkeypatch.setattr(window, "_start_current_pallet_send", starts.append)
    window.auto_plc_checkbox.setChecked(False)
    window.apply_live_load_pallet(COMMAND)
    assert starts == []
    window.auto_plc_checkbox.setChecked(True)
    window.apply_live_load_pallet({**COMMAND, "box_unique_id": OTHER_UID})
    assert starts == ["wcs"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_ui_smoke.py -q`
Expected: fails because PLC widgets and handlers are absent.

- [ ] **Step 3: Build the PLC panel**

Add IP, rack, slot and DB controls; connect/disconnect, manual-send and stop buttons; default-off `QCheckBox("自动下发")`; labels for current UID, expected/requested seq, FP, FP_OVER, KONGXIAN and DH_OVER; and a read-only log. Do not reuse `plc_launcher`.

- [ ] **Step 4: Wire one send entry point**

`_start_current_pallet_send(source)` validates the current plan, connection and single-task guard, creates the worker/thread, and connects signals. The manual button calls it with `"manual"`. `apply_live_load_pallet` calls it with `"wcs"` only if `auto_plc_checkbox.isChecked()`; when disconnected, retain the loaded pallet and show “等待 PLC 连接”.

- [ ] **Step 5: Update documentation**

Document starting `local_wcs_receiver` and `packing-robot`, connecting PLC, default-off automatic mode, manual mode, state gating, exact offset table and the removal of the `tongxun` runtime dependency.

- [ ] **Step 6: Run UI and focused tests**

Run: `python -m pytest tests/test_ui_smoke.py tests/test_plc_protocol.py tests/test_plc_state_repository.py tests/test_plc_worker.py -q`
Expected: all pass without opening a real socket or database.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add packing_ui/main_window.py tests/test_ui_smoke.py README.md
git commit -m "feat: integrate PLC controls with WCS trigger"
```
