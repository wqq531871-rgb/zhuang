"""Qt worker for persisting camera-derived product states."""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import QObject, QSettings, Signal, Slot

from .state_repository import (
    MySqlConfig,
    ProductState,
    ProductStateRepository,
)


def load_shared_mysql_config(
    *,
    settings: Any | None = None,
    environ: Mapping[str, str] | None = None,
) -> MySqlConfig:
    settings = settings or QSettings("OpenAI", "PLCPalletSender")
    environ = os.environ if environ is None else environ
    return MySqlConfig(
        host=str(settings.value("mysql/host", "localhost")),
        port=int(settings.value("mysql/port", 3306)),
        user=str(settings.value("mysql/user", "root")),
        password=environ.get("ZHUANGDB_PASSWORD", ""),
        database=str(settings.value("mysql/database", "zhuangdb")),
    )


class StateSyncWorker(QObject):
    succeeded = Signal(int)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        config: MySqlConfig,
        updates: Sequence[ProductState],
        *,
        repository_factory: Callable[
            [MySqlConfig], ProductStateRepository
        ] = ProductStateRepository,
    ) -> None:
        super().__init__()
        self.config = config
        self.updates = tuple(updates)
        self._repository_factory = repository_factory

    @Slot()
    def run(self) -> None:
        try:
            count = self._repository_factory(self.config).update_states(self.updates)
            self.succeeded.emit(count)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
