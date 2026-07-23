"""Transactional MySQL update of calculated product rotation states."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


SELECT_PRODUCT = """
SELECT id
FROM wcs_success_box
WHERE product_code = %s
FOR UPDATE
""".strip()

UPDATE_STATE = """
UPDATE wcs_success_box
SET state = %s
WHERE id = %s
""".strip()


class DatabaseStateError(RuntimeError):
    """Calculated state could not be safely persisted."""


@dataclass(frozen=True)
class ProductState:
    product_code: str
    state: int


@dataclass(frozen=True)
class MySqlConfig:
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = field(default="", repr=False)
    database: str = "zhuangdb"
    charset: str = "utf8mb4"
    connection_timeout: int = 5

    def safe_summary(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.database}"

    def connect_kwargs(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": self.charset,
            "connection_timeout": self.connection_timeout,
        }


class ProductStateRepository:
    def __init__(
        self,
        config: MySqlConfig,
        *,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self._connect_factory = connect_factory

    def _connect(self) -> Any:
        if self._connect_factory is not None:
            return self._connect_factory(**self.config.connect_kwargs())
        try:
            import mysql.connector
        except ImportError as exc:
            raise DatabaseStateError(
                "缺少 mysql-connector-python，请安装 requirements.txt"
            ) from exc
        return mysql.connector.connect(**self.config.connect_kwargs())

    @staticmethod
    def _validate(updates: Iterable[ProductState]) -> tuple[ProductState, ...]:
        values = tuple(updates)
        if not values:
            raise DatabaseStateError("没有可同步的 product_code/state")
        seen: set[str] = set()
        for update in values:
            if not isinstance(update.product_code, str) or not update.product_code.strip():
                raise DatabaseStateError("product_code 必须是非空字符串")
            if update.product_code in seen:
                raise DatabaseStateError(
                    f"同步批次中 product_code 重复：{update.product_code}"
                )
            seen.add(update.product_code)
            if type(update.state) is not int or update.state not in (1, 2):
                raise DatabaseStateError("state 必须是整数 1 或 2")
        return values

    def update_states(self, updates: Iterable[ProductState]) -> int:
        values = self._validate(updates)
        connection = None
        cursor = None
        try:
            connection = self._connect()
            cursor = connection.cursor(dictionary=True)
            for update in values:
                cursor.execute(SELECT_PRODUCT, (update.product_code,))
                rows = cursor.fetchall()
                if not rows:
                    raise DatabaseStateError(
                        f"product_code={update.product_code} 没有找到数据库记录"
                    )
                if len(rows) != 1:
                    raise DatabaseStateError(
                        f"product_code={update.product_code} 存在 {len(rows)} 条记录，"
                        "拒绝更新"
                    )
                row = rows[0]
                record_id = row["id"] if isinstance(row, dict) else row[0]
                cursor.execute(UPDATE_STATE, (update.state, record_id))
            connection.commit()
            return len(values)
        except DatabaseStateError:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            message = str(exc)
            if self.config.password:
                message = message.replace(self.config.password, "***")
            raise DatabaseStateError(
                f"MySQL state 同步失败（{self.config.safe_summary()}）：{message}"
            ) from exc
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
