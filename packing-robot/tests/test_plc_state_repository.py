from packing_ui.plan_from_db import fetch_plc_row, update_camera_dimensions


SETTINGS = {
    "host": "db",
    "port": 3306,
    "user": "u",
    "password": "p",
    "database": "zhuangdb",
    "charset": "utf8mb4",
}


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.cursor_value = FakeCursor(row)
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def close(self):
        self.closed = True


def test_fetch_plc_row_selects_latest_command_fields_by_uid_and_seq():
    expected = {"seq": 3, "state": None, "box_num": 12}
    connection = FakeConnection(expected)
    calls = []

    def connect_factory(**kwargs):
        calls.append(kwargs)
        return connection

    result = fetch_plc_row(
        "a" * 32,
        3,
        settings=SETTINGS,
        connect_factory=connect_factory,
    )

    assert result == expected
    sql, params = connection.cursor_value.executed[0]
    for field in (
        "camera_length",
        "camera_width",
        "camera_height",
        "raw_length",
        "raw_width",
        "raw_height",
        "pos_x",
        "pos_y",
        "pos_z",
        "stack_height_before",
        "box_num",
        "state",
    ):
        assert field in sql
    assert params == ("a" * 32, 3)
    assert connection.closed is True
    assert calls[0]["cursorclass"].__name__ == "DictCursor"


def test_fetch_plc_row_preserves_missing_state_and_missing_row():
    connection = FakeConnection(None)
    result = fetch_plc_row(
        "b" * 32,
        8,
        settings=SETTINGS,
        connect_factory=lambda **_kwargs: connection,
    )
    assert result is None


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
    result = update_camera_dimensions(
        "b" * 32,
        8,
        401,
        302,
        203,
        settings=SETTINGS,
        connect_factory=lambda **_kwargs: connection,
    )

    assert result == 0
    assert len(connection.cursor_value.executed) == 1
    assert connection.closed is True
