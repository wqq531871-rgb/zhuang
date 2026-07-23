import pytest

from packing_ui.state_repository import (
    DatabaseStateError,
    MySqlConfig,
    ProductState,
    ProductStateRepository,
)


class FakeCursor:
    def __init__(self, rows_by_code):
        self.rows_by_code = rows_by_code
        self.calls = []
        self._rows = []
        self.closed = False

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if sql.lstrip().upper().startswith("SELECT"):
            self._rows = self.rows_by_code.get(params[0], [])

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows_by_code):
        self.cursor_value = FakeCursor(rows_by_code)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, dictionary=False):
        assert dictionary is True
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def repository(connection):
    return ProductStateRepository(
        MySqlConfig(password="secret"),
        connect_factory=lambda **_kwargs: connection,
    )


def test_batch_locks_by_product_code_updates_by_id_and_commits_once():
    connection = FakeConnection(
        {
            "BOX-A": [{"id": 101}],
            "BOX-B": [{"id": 102}],
        }
    )

    count = repository(connection).update_states(
        [ProductState("BOX-A", 1), ProductState("BOX-B", 2)]
    )

    assert count == 2
    calls = connection.cursor_value.calls
    assert calls[0][1] == ("BOX-A",)
    assert "WHERE product_code = %s" in calls[0][0]
    assert "FOR UPDATE" in calls[0][0]
    assert calls[1][1] == (1, 101)
    assert "SET state = %s" in calls[1][0]
    assert "WHERE id = %s" in calls[1][0]
    assert calls[2][1] == ("BOX-B",)
    assert calls[3][1] == (2, 102)
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.cursor_value.closed is True
    assert connection.closed is True


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "没有找到"),
        ([{"id": 1}, {"id": 2}], "存在 2 条"),
    ],
)
def test_missing_or_duplicate_product_code_rolls_back_entire_batch(rows, message):
    connection = FakeConnection(
        {"BOX-A": [{"id": 101}], "BOX-B": rows}
    )

    with pytest.raises(DatabaseStateError, match=message):
        repository(connection).update_states(
            [ProductState("BOX-A", 1), ProductState("BOX-B", 2)]
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


@pytest.mark.parametrize("state", [0, 3, True, 1.0, "1"])
def test_state_must_be_integer_one_or_two_before_connecting(state):
    calls = []
    repo = ProductStateRepository(
        MySqlConfig(),
        connect_factory=lambda **kwargs: calls.append(kwargs),
    )

    with pytest.raises(DatabaseStateError, match="state.*1.*2"):
        repo.update_states([ProductState("BOX-A", state)])

    assert calls == []


def test_connection_error_does_not_leak_password():
    config = MySqlConfig(password="top-secret-password")

    def fail(**_kwargs):
        raise RuntimeError("access denied top-secret-password")

    repo = ProductStateRepository(config, connect_factory=fail)
    with pytest.raises(DatabaseStateError) as caught:
        repo.update_states([ProductState("BOX-A", 1)])

    assert config.password not in str(caught.value)
    assert config.password not in repr(config)
