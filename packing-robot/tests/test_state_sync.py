import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import QApplication

from packing_ui.state_repository import DatabaseStateError, ProductState
from packing_ui.state_sync import StateSyncWorker, load_shared_mysql_config


def _app():
    return QApplication.instance() or QApplication([])


class FakeSettings:
    def __init__(self, values):
        self.values = values

    def value(self, key, default):
        return self.values.get(key, default)


def test_shared_config_uses_old_plc_ui_settings_and_environment_password():
    config = load_shared_mysql_config(
        settings=FakeSettings(
            {
                "mysql/host": "10.0.0.8",
                "mysql/port": "3307",
                "mysql/user": "operator",
                "mysql/database": "factory",
            }
        ),
        environ={"ZHUANGDB_PASSWORD": "memory-only"},
    )

    assert (config.host, config.port, config.user, config.database) == (
        "10.0.0.8",
        3307,
        "operator",
        "factory",
    )
    assert config.password == "memory-only"


def test_worker_emits_success_count_and_finished():
    _app()
    received = []

    class Repo:
        def __init__(self, config):
            received.append(config)

        def update_states(self, updates):
            received.append(tuple(updates))
            return len(tuple(updates))

    worker = StateSyncWorker(
        load_shared_mysql_config(settings=FakeSettings({}), environ={}),
        [ProductState("BOX-A", 1), ProductState("BOX-B", 2)],
        repository_factory=Repo,
    )
    succeeded = []
    failed = []
    finished = []
    worker.succeeded.connect(succeeded.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert succeeded == [2]
    assert failed == []
    assert finished == [True]
    assert received[1] == (
        ProductState("BOX-A", 1),
        ProductState("BOX-B", 2),
    )


def test_worker_reports_repository_error_and_always_finishes():
    _app()

    class Repo:
        def __init__(self, _config):
            pass

        def update_states(self, _updates):
            raise DatabaseStateError("数据库不可用")

    worker = StateSyncWorker(
        load_shared_mysql_config(settings=FakeSettings({}), environ={}),
        [ProductState("BOX-A", 1)],
        repository_factory=Repo,
    )
    failed = []
    finished = []
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert failed == ["数据库不可用"]
    assert finished == [True]
