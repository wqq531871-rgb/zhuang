import math

import pytest

from packing_ui.layout_state import (
    STATE_PATH_CAMERA,
    STATE_PATH_LAYOUT,
    LayoutStateError,
    assign_pallet_layout_states,
    normalize_state_path,
    state_from_layout_dims,
)


SETTINGS = {
    "host": "db",
    "port": 3306,
    "user": "operator",
    "password": "secret",
    "database": "zhuangdb",
    "charset": "utf8mb4",
}


class FakeCursor:
    def __init__(self, rows, *, fail_update=False):
        self.rows = list(rows)
        self.fail_update = fail_update
        self.calls = []
        self.closed = False
        self.rowcount = 0

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if sql.lstrip().upper().startswith("UPDATE"):
            if self.fail_update:
                raise RuntimeError("update exploded")
            self.rowcount = 1

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows, *, fail_update=False):
        self.cursor_value = FakeCursor(rows, fail_update=fail_update)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    ("x_size", "y_size", "expected"),
    [
        (300, 400, 1),
        (400, 300, 2),
        (400, 400, 1),
        ("300.5", "400.5", 1),
    ],
)
def test_state_from_layout_dims_uses_pallet_xy_footprint(
    x_size, y_size, expected
):
    assert state_from_layout_dims(x_size, y_size) == expected


@pytest.mark.parametrize(
    ("x_size", "y_size"),
    [
        (0, 100),
        (100, 0),
        (-1, 100),
        (100, math.inf),
        (math.nan, 100),
        ("not-a-number", 100),
    ],
)
def test_state_from_layout_dims_rejects_invalid_dimensions(x_size, y_size):
    with pytest.raises(LayoutStateError, match="X/Y"):
        state_from_layout_dims(x_size, y_size)


def test_state_path_normalization_accepts_only_supported_paths():
    assert normalize_state_path(" CAMERA ") == STATE_PATH_CAMERA
    assert normalize_state_path("Layout") == STATE_PATH_LAYOUT
    with pytest.raises(LayoutStateError, match="判态路径"):
        normalize_state_path("unknown")


def test_layout_assignment_locks_current_pallet_updates_changed_rows_and_commits():
    connection = FakeConnection(
        [
            {
                "id": 11,
                "seq": 1,
                "raw_length": 300,
                "raw_width": 400,
                "state": None,
            },
            {
                "id": 12,
                "seq": 2,
                "raw_length": 500,
                "raw_width": 200,
                "state": 1,
            },
            {
                "id": 13,
                "seq": 3,
                "raw_length": 400,
                "raw_width": 400,
                "state": 1,
            },
        ]
    )
    connect_calls = []

    result = assign_pallet_layout_states(
        "a" * 32,
        settings=SETTINGS,
        connect_factory=lambda **kwargs: connect_calls.append(kwargs) or connection,
    )

    assert result.box_unique_id == "a" * 32
    assert result.box_count == 3
    assert result.changed_count == 2
    assert [decision.state for decision in result.decisions] == [1, 2, 1]
    assert [decision.previous_state for decision in result.decisions] == [
        None,
        1,
        1,
    ]

    calls = connection.cursor_value.calls
    select_sql, select_params = calls[0]
    assert "WHERE box_unique_id = %s" in select_sql
    assert "ORDER BY seq ASC" in select_sql
    assert "FOR UPDATE" in select_sql
    assert select_params == ("a" * 32,)
    assert [params for sql, params in calls[1:] if sql.startswith("UPDATE")] == [
        (1, 11),
        (2, 12),
    ]
    assert all("WHERE id = %s" in sql for sql, _params in calls[1:])
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.cursor_value.closed is True
    assert connection.closed is True
    assert connect_calls[0]["autocommit"] is False


def test_layout_assignment_is_idempotent_when_states_already_match():
    connection = FakeConnection(
        [
            {
                "id": 21,
                "seq": 1,
                "raw_length": 300,
                "raw_width": 400,
                "state": 1,
            },
            {
                "id": 22,
                "seq": 2,
                "raw_length": 500,
                "raw_width": 200,
                "state": 2,
            },
        ]
    )

    result = assign_pallet_layout_states(
        "b" * 32,
        settings=SETTINGS,
        connect_factory=lambda **_kwargs: connection,
    )

    assert result.changed_count == 0
    assert len(connection.cursor_value.calls) == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "没有箱子记录"),
        (
            [
                {
                    "id": 31,
                    "seq": 2,
                    "raw_length": 300,
                    "raw_width": 400,
                    "state": None,
                }
            ],
            "seq 必须从 1 开始连续",
        ),
        (
            [
                {
                    "id": 31,
                    "seq": 1,
                    "raw_length": 300,
                    "raw_width": 400,
                    "state": None,
                },
                {
                    "id": 32,
                    "seq": 3,
                    "raw_length": 300,
                    "raw_width": 400,
                    "state": None,
                },
            ],
            "seq 必须从 1 开始连续",
        ),
    ],
)
def test_layout_assignment_rolls_back_invalid_pallet_rows(rows, message):
    connection = FakeConnection(rows)

    with pytest.raises(LayoutStateError, match=message):
        assign_pallet_layout_states(
            "c" * 32,
            settings=SETTINGS,
            connect_factory=lambda **_kwargs: connection,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_layout_assignment_rolls_back_database_update_failure():
    connection = FakeConnection(
        [
            {
                "id": 41,
                "seq": 1,
                "raw_length": 300,
                "raw_width": 400,
                "state": None,
            }
        ],
        fail_update=True,
    )

    with pytest.raises(LayoutStateError, match="垛型 state 写入失败"):
        assign_pallet_layout_states(
            "d" * 32,
            settings=SETTINGS,
            connect_factory=lambda **_kwargs: connection,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.cursor_value.closed is True
    assert connection.closed is True
