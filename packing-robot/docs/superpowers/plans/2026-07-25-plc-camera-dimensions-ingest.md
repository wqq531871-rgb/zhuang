# PLC Camera Dimensions Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read camera dimensions from PLC DB19 DBW6/8/10, persist them for the current `box_unique_id + seq`, wait for the existing state watcher, and send only REV fields back to the PLC.

**Architecture:** Extend the PLC status model so the existing DBW0..12 read exposes camera dimensions, and make request waiting a public protocol operation. Inject a focused database writer into `PlcSendWorker`; the worker writes camera dimensions once before polling `state`, while the existing `CameraStateWatcher` remains the sole state judge.

**Tech Stack:** Python 3, PySide6, python-snap7, PyMySQL, pytest

## Global Constraints

- DBW6/8/10 are PLC SEND fields and must never be included in a normal REV write.
- DBW34 remains `stack_height_before: Int`.
- The ready condition remains `FP=1`, `FP_OVER=0`, `DH_OVER=0`.
- After REV is complete, set DBW30 last; only clear DBW0 and DBW30 after DBW4 becomes 1.
- Camera dimensions are written only for the exact `box_unique_id + seq`.
- The existing always-on state watcher remains responsible for computing `state=0/1/2`.
- Tests must not connect to a real PLC or MySQL server.

---

### Task 1: Correct the PLC SEND/REV boundary

**Files:**
- Modify: `packing-robot/packing_ui/plc_protocol.py:60-263`
- Test: `packing-robot/tests/test_plc_protocol.py`

**Interfaces:**
- Consumes: DB19 signed big-endian INT values at DBW0..12 and DBW30.
- Produces: `PlcStatus(fp, request_seq, fp_over, camera_length, camera_width, camera_height, idle, dh_over)` and `S7Client.wait_request(expected_seq) -> PlcStatus`.

- [ ] **Step 1: Write failing protocol tests**

Update the fake status payload so DBW6/8/10 contain camera dimensions, then add assertions that the status read exposes them and the REV command omits those offsets:

```python
def status(
    *,
    fp=1,
    seq=7,
    fp_over=0,
    camera_length=401,
    camera_width=302,
    camera_height=203,
    idle=0,
    dh_over=0,
):
    return {
        "fp": fp,
        "request_seq": seq,
        "fp_over": fp_over,
        "camera_length": camera_length,
        "camera_width": camera_width,
        "camera_height": camera_height,
        "idle": idle,
        "dh_over": dh_over,
    }


def test_wait_request_reads_camera_dimensions_from_send_area():
    raw = FakeSnap7([status()])
    received = S7Client(
        raw, config(), sleep=lambda _seconds: None
    ).wait_request(7)
    assert (
        received.camera_length,
        received.camera_width,
        received.camera_height,
    ) == (401, 302, 203)


def test_command_writes_only_rev_fields_and_preserves_dbw34_int():
    command = build_command(ROW)
    assert command.words() == {
        14: 400,
        16: 300,
        18: 200,
        20: 110,
        22: 100,
        24: 120,
        26: 2,
        28: 12,
        32: 0,
        34: 480,
    }
    assert {6, 8, 10}.isdisjoint(command.words())
```

In `FakeSnap7.db_read`, pack the seven DBW0..12 words as:

```python
words = [
    current["fp"],
    current["request_seq"],
    current["fp_over"],
    current["camera_length"],
    current["camera_width"],
    current["camera_height"],
    current["idle"],
]
```

- [ ] **Step 2: Run the protocol tests and verify RED**

Run:

```powershell
python -m pytest tests/test_plc_protocol.py -q
```

Expected: fail because `PlcStatus` has no camera dimension fields, `wait_request` is not public, and `command.words()` still contains offsets 6/8/10.

- [ ] **Step 3: Implement the minimal protocol change**

Change the status and command models:

```python
@dataclass(frozen=True)
class PlcStatus:
    fp: int
    request_seq: int
    fp_over: int
    camera_length: int
    camera_width: int
    camera_height: int
    idle: int
    dh_over: int


@dataclass(frozen=True)
class PlcCommand:
    sequence: int
    raw_length: int
    raw_width: int
    raw_height: int
    x: int
    y: int
    z: int
    state: int
    box_num: int
    stack_height_before: int
```

Remove `CAMERA_LENGTH_OFFSET`, `CAMERA_WIDTH_OFFSET`, and
`CAMERA_HEIGHT_OFFSET` from `PlcCommand.words()` and remove the three
`camera_*` reads from `build_command`. Preserve the constants because
`read_status` still uses those addresses.

Map the DBW0..12 read into `PlcStatus`:

```python
return PlcStatus(
    fp=words[0],
    request_seq=words[1],
    fp_over=words[2],
    camera_length=words[3],
    camera_width=words[4],
    camera_height=words[5],
    idle=words[6],
    dh_over=_unpack_int(dh_over),
)
```

Rename `_wait_ready` to public `wait_request`, then update
`send_alarm` and `send_normal` to call `wait_request`.

- [ ] **Step 4: Run protocol tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_plc_protocol.py -q
```

Expected: all protocol tests pass, including the unchanged acknowledgement ordering test.

- [ ] **Step 5: Commit Task 1**

```powershell
git add packing-robot/packing_ui/plc_protocol.py packing-robot/tests/test_plc_protocol.py
git commit -m "fix: read camera dimensions from PLC send area"
```

---

### Task 2: Add the exact-row camera dimension database writer

**Files:**
- Modify: `packing-robot/packing_ui/plan_from_db.py:71-139`
- Test: `packing-robot/tests/test_plc_state_repository.py`

**Interfaces:**
- Consumes: `box_unique_id`, `seq`, and three positive PLC INT camera dimensions.
- Produces: `update_camera_dimensions(box_unique_id, seq, camera_length, camera_width, camera_height, *, config_path=None, settings=None, connect_factory=pymysql.connect) -> int`; returns `1` when the row exists, including an idempotent same-value update, and `0` when it does not exist.

- [ ] **Step 1: Write failing repository tests**

Extend the fake cursor so it records multiple SQL calls and returns a configurable existence row:

```python
class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row
```

Add:

```python
def test_update_camera_dimensions_targets_uid_and_seq():
    connection = FakeConnection({"found": 1})
    result = update_camera_dimensions(
        "a" * 32,
        7,
        401,
        302,
        203,
        settings=SETTINGS,
        connect_factory=lambda **_kwargs: connection,
    )
    assert result == 1
    update_sql, params = connection.cursor_value.executed[-1]
    assert "camera_length = %s" in update_sql
    assert "camera_width = %s" in update_sql
    assert "camera_height = %s" in update_sql
    assert params == (401.0, 302.0, 203.0, "a" * 32, 7)
    assert connection.closed is True


def test_update_camera_dimensions_returns_zero_for_missing_row():
    connection = FakeConnection(None)
    assert update_camera_dimensions(
        "b" * 32,
        8,
        401,
        302,
        203,
        settings=SETTINGS,
        connect_factory=lambda **_kwargs: connection,
    ) == 0
    assert len(connection.cursor_value.executed) == 1
```

Define `SETTINGS` once in the test module with the existing fake connection
values, and update existing assertions to use `executed[0]`.

- [ ] **Step 2: Run repository tests and verify RED**

Run:

```powershell
python -m pytest tests/test_plc_state_repository.py -q
```

Expected: collection fails because `update_camera_dimensions` does not exist.

- [ ] **Step 3: Implement the focused database writer**

Add:

```python
_CAMERA_ROW_EXISTS_SQL = (
    "SELECT 1 AS found FROM wcs_success_box "
    "WHERE box_unique_id = %s AND seq = %s LIMIT 1"
)

_UPDATE_CAMERA_DIMENSIONS_SQL = (
    "UPDATE wcs_success_box SET "
    "camera_length = %s, camera_width = %s, camera_height = %s "
    "WHERE box_unique_id = %s AND seq = %s"
)
```

Implement `update_camera_dimensions` using the same configuration and
connection construction as `fetch_plc_row`. Validate non-empty UID,
`seq >= 1`, and all three dimensions `> 0`. Within one cursor, query
existence first; return `0` if absent, otherwise execute the update with
float values and return `1`. Always close the connection in `finally`.
Do not update or reset `state`.

- [ ] **Step 4: Run repository tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_plc_state_repository.py -q
```

Expected: all repository tests pass and no real MySQL connection is made.

- [ ] **Step 5: Commit Task 2**

```powershell
git add packing-robot/packing_ui/plan_from_db.py packing-robot/tests/test_plc_state_repository.py
git commit -m "feat: persist PLC camera dimensions by sequence"
```

---

### Task 3: Sequence camera ingest before state polling and REV sending

**Files:**
- Modify: `packing-robot/packing_ui/plc_worker.py:17-106`
- Test: `packing-robot/tests/test_plc_worker.py`

**Interfaces:**
- Consumes: `S7Client.wait_request(seq) -> PlcStatus`, `row_loader(uid, seq) -> dict | None`, and `camera_writer(uid, seq, length, width, height) -> int`.
- Produces: a serialized per-box flow that performs `wait_request → camera_writer → state polling → alarm/normal send`.

- [ ] **Step 1: Write failing worker ordering and safety tests**

Import `SimpleNamespace` and `PlcSequenceMismatch`, then give `FakeProtocol`
an event log and a configurable `wait_request` result:

```python
from types import SimpleNamespace

from packing_ui.plc_protocol import PlcSequenceMismatch


class FakeProtocol:
    def __init__(self, *, events=None, inbound=None, request_error=None):
        self.events = events if events is not None else []
        self.inbound = inbound or SimpleNamespace(
            camera_length=401,
            camera_width=302,
            camera_height=203,
        )
        self.request_error = request_error
        self.normal = []
        self.alarms = []
        self.disconnected = False

    def connect(self):
        return None

    def disconnect(self):
        self.disconnected = True

    def wait_request(self, expected_seq):
        self.events.append(("wait_request", expected_seq))
        if self.request_error is not None:
            raise self.request_error
        return self.inbound

    def send_normal(self, command):
        self.normal.append(command)

    def send_alarm(self, expected_seq):
        self.alarms.append(expected_seq)
```

Replace the old iterator-only worker helper with:

```python
def make_worker(*, protocol, row_loader, camera_writer):
    return PlcSendWorker(
        config=object(),
        box_unique_id="a" * 32,
        sequences=(7,),
        row_loader=row_loader,
        camera_writer=camera_writer,
        client_factory=lambda: object(),
        protocol_factory=lambda *_args, **_kwargs: protocol,
        sleep=lambda _seconds: None,
    )
```

Add the ordering test:

```python
def test_worker_writes_camera_dimensions_before_polling_state():
    events = []
    protocol = FakeProtocol(events=events)

    def camera_writer(uid, seq, length, width, height):
        events.append(("camera_write", uid, seq, length, width, height))
        return 1

    def row_loader(uid, seq):
        events.append(("state_read", uid, seq))
        return ROW

    target = make_worker(
        protocol=protocol,
        row_loader=row_loader,
        camera_writer=camera_writer,
    )
    target.run()

    assert events[:3] == [
        ("wait_request", 7),
        ("camera_write", "a" * 32, 7, 401, 302, 203),
        ("state_read", "a" * 32, 7),
    ]
    assert [command.sequence for command in protocol.normal] == [7]
```

Add explicit safety tests:

```python
def test_worker_rejects_nonpositive_camera_dimensions_before_db_or_rev_write():
    calls = []
    protocol = FakeProtocol(
        inbound=SimpleNamespace(
            camera_length=0,
            camera_width=302,
            camera_height=203,
        )
    )
    target = make_worker(
        protocol=protocol,
        row_loader=lambda *_args: calls.append("state_read"),
        camera_writer=lambda *_args: calls.append("camera_write"),
    )
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == [
        "seq=7 的 PLC 相机尺寸无效：DBW6=0，DBW8=302，DBW10=203"
    ]
    assert calls == []
    assert protocol.alarms == []
    assert protocol.normal == []


def test_worker_stops_when_camera_database_row_is_missing():
    calls = []
    protocol = FakeProtocol()
    target = make_worker(
        protocol=protocol,
        row_loader=lambda *_args: calls.append("state_read"),
        camera_writer=lambda *_args: 0,
    )
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == [
        f"数据库中找不到 box_unique_id={'a' * 32} seq=7"
    ]
    assert calls == []
    assert protocol.alarms == []
    assert protocol.normal == []


def test_worker_sequence_mismatch_never_writes_camera_or_rev():
    calls = []
    protocol = FakeProtocol(
        request_error=PlcSequenceMismatch(
            "PLC请求 seq=8，当前数据库箱子 seq=7"
        )
    )
    target = make_worker(
        protocol=protocol,
        row_loader=lambda *_args: calls.append("state_read"),
        camera_writer=lambda *_args: calls.append("camera_write"),
    )
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == ["PLC请求 seq=8，当前数据库箱子 seq=7"]
    assert calls == []
    assert protocol.alarms == []
    assert protocol.normal == []
```

Keep and adapt the existing NULL-state, state-0, state-1/2, and illegal-state
tests so every worker first receives and persists camera dimensions.

- [ ] **Step 2: Run worker tests and verify RED**

Run:

```powershell
python -m pytest tests/test_plc_worker.py -q
```

Expected: fail because `PlcSendWorker` has no `camera_writer` dependency and
polls `state` before reading PLC camera dimensions.

- [ ] **Step 3: Implement the worker sequence**

Add the constructor dependency:

```python
camera_writer: Callable[[str, int, int, int, int], int],
```

Store it as `self._camera_writer`. For each sequence, before the existing
state loop:

```python
inbound = protocol.wait_request(seq)
self.plc_status.emit(inbound)
dims = (
    int(inbound.camera_length),
    int(inbound.camera_width),
    int(inbound.camera_height),
)
if any(value <= 0 for value in dims):
    raise ValueError(
        f"seq={seq} 的 PLC 相机尺寸无效："
        f"DBW6={dims[0]}，DBW8={dims[1]}，DBW10={dims[2]}"
    )
written = int(self._camera_writer(self.box_unique_id, seq, *dims))
if written <= 0:
    raise ValueError(
        f"数据库中找不到 box_unique_id={self.box_unique_id} seq={seq}"
    )
self.status.emit(
    f"seq={seq} 相机尺寸已写库 "
    f"{dims[0]}×{dims[1]}×{dims[2]}，等待数据库 state"
)
```

Only then enter the existing `while state is NULL` loop. Preserve
`send_alarm(seq)` for state 0 and `send_normal(build_command(row))` for
state 1/2; both protocol methods recheck FP, seq, FP_OVER, and DH_OVER before
writing.

- [ ] **Step 4: Run worker and adjacent tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_plc_worker.py tests/test_plc_protocol.py tests/test_plc_state_repository.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add packing-robot/packing_ui/plc_worker.py packing-robot/tests/test_plc_worker.py
git commit -m "feat: gate REV sending on PLC camera ingest"
```

---

### Task 4: Wire the database writer into the UI and update protocol documentation

**Files:**
- Modify: `packing-robot/packing_ui/main_window.py:40-79,559-569`
- Modify: `packing-robot/tests/test_ui_smoke.py`
- Modify: `packing-robot/README.md:37-53`

**Interfaces:**
- Consumes: `update_camera_dimensions(...) -> int` from Task 2 and the `camera_writer` constructor argument from Task 3.
- Produces: production `PlcSendWorker` instances configured to persist DBW6/8/10 before state polling.

- [ ] **Step 1: Write a failing UI dependency test**

Add an injectable constructor argument and test the desired default/injected
dependency:

```python
def test_window_accepts_camera_dimension_writer_dependency():
    _app()
    writer = lambda *_args: 1
    window = _test_window(camera_dimension_writer=writer)
    assert window._camera_dimension_writer is writer
    window.close()
```

- [ ] **Step 2: Run the UI test and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:QT_API='pyside6'
python -m pytest tests/test_ui_smoke.py::test_window_accepts_camera_dimension_writer_dependency -q
```

Expected: fail because `PackingMainWindow.__init__` does not accept
`camera_dimension_writer`.

- [ ] **Step 3: Wire the production callback**

Import `update_camera_dimensions` beside `fetch_plc_row`. Add:

```python
camera_dimension_writer: Any = None,
```

to `PackingMainWindow.__init__`, then store:

```python
self._camera_dimension_writer = (
    camera_dimension_writer or update_camera_dimensions
)
```

When constructing `PlcSendWorker`, pass:

```python
camera_writer=lambda box_uid, seq, length, width, height: (
    self._camera_dimension_writer(
        box_uid,
        seq,
        length,
        width,
        height,
        config_path=self._config_path,
    )
)
```

Update README’s DB19 section to state that DBW6/8/10 are read from PLC and
persisted to `camera_length/width/height`; DBW14..34 are the REV payload;
DBW34 remains `stack_height_before`.

- [ ] **Step 4: Run focused UI and PLC tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:QT_API='pyside6'
python -m pytest tests/test_ui_smoke.py tests/test_plc_protocol.py tests/test_plc_state_repository.py tests/test_plc_worker.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Run the complete packing-robot test suite**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:QT_API='pyside6'
python -m pytest -q
```

Expected: all tests pass with no real PLC or MySQL access.

- [ ] **Step 6: Inspect the final diff against the approved design**

Run:

```powershell
git diff --check
git diff -- packing-robot/packing_ui packing-robot/tests packing-robot/README.md
```

Confirm:

- DBW6/8/10 appear only in PLC reads and status parsing.
- `PlcCommand.words()` contains only DBW14..34 REV values.
- DBW34 remains an INT carrying `stack_height_before`.
- Camera database writes precede current-box state polling.
- Unrelated `packing-workspace` files are absent from the diff.

- [ ] **Step 7: Commit Task 4**

```powershell
git add packing-robot/packing_ui/main_window.py packing-robot/tests/test_ui_smoke.py packing-robot/README.md
git commit -m "feat: connect PLC camera ingest to live sender"
```
