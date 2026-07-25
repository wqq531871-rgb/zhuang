"""Siemens S7 DB19 field mapping and handshake for the packing UI."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import struct
import time
from typing import Any, Mapping


INT16_MIN = -32768
INT16_MAX = 32767

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


class PlcError(RuntimeError):
    """Base error for PLC protocol failures."""


class PlcValidationError(ValueError):
    """A database row cannot be represented by DB19 INT fields."""


class PlcCommunicationError(PlcError):
    """The S7 transport failed."""


class PlcTimeoutError(PlcError):
    """The PLC did not finish a handshake in time."""


class PlcStoppedError(PlcError):
    """User requested stop while waiting on the PLC."""


class PlcSequenceMismatch(PlcError):
    """The PLC requested a different database sequence."""


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

    def words(self) -> dict[int, int]:
        return {
            RAW_LENGTH_OFFSET: self.raw_length,
            RAW_WIDTH_OFFSET: self.raw_width,
            RAW_HEIGHT_OFFSET: self.raw_height,
            X_OFFSET: self.x,
            Y_OFFSET: self.y,
            Z_OFFSET: self.z,
            STATE_OFFSET: self.state,
            BOX_NUM_OFFSET: self.box_num,
            ALARM_OFFSET: 0,
            STACK_HEIGHT_OFFSET: self.stack_height_before,
        }


@dataclass(frozen=True)
class S7Config:
    ip: str = "10.19.40.70"
    port: int = 102
    rack: int = 0
    slot: int = 1
    db_number: int = 19
    connect_retries: int = 3
    retry_interval: float = 1.0
    # <=0：一直等到 PLC 信号（现场联调默认）；>0：秒级超时
    handshake_timeout: float = 0.0
    poll_interval: float = 0.1


def _plc_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlcValidationError(f"字段 {field} 必须是数字")
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise PlcValidationError(f"字段 {field} 必须是有限数字")
        result = int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as exc:
        raise PlcValidationError(f"字段 {field} 必须是有效数字") from exc
    if not INT16_MIN <= result <= INT16_MAX:
        raise PlcValidationError(f"字段 {field}={result} 超出 PLC INT 范围")
    return result


def build_command(row: Mapping[str, Any]) -> PlcCommand:
    state = _plc_int(row.get("state"), "state")
    if state not in (1, 2):
        raise PlcValidationError("正常下发的 state 必须是 1 或 2")
    return PlcCommand(
        sequence=_plc_int(row.get("seq"), "seq"),
        raw_length=_plc_int(row.get("raw_length"), "raw_length"),
        raw_width=_plc_int(row.get("raw_width"), "raw_width"),
        raw_height=_plc_int(row.get("raw_height"), "raw_height"),
        # 与数据库坐标一致：DBW20=pos_x，DBW22=pos_y
        x=_plc_int(row.get("pos_x"), "pos_x"),
        y=_plc_int(row.get("pos_y"), "pos_y"),
        # DBW24：放置顶面高度 = 箱底 z + 纸箱高度
        z=_plc_int(
            float(row.get("pos_z") or 0) + float(row.get("raw_height") or 0),
            "pos_z+raw_height",
        ),
        state=state,
        box_num=_plc_int(row.get("box_num"), "box_num"),
        stack_height_before=_plc_int(
            row.get("stack_height_before"), "stack_height_before"
        ),
    )


def _format_plc_exc(exc: BaseException) -> str:
    """把 snap7/ctypes 的含糊异常收成可读说明。"""
    text = str(exc).strip()
    if isinstance(exc, bytes):
        text = exc.decode("utf-8", errors="replace").strip()
    cause = exc.__cause__ or getattr(exc, "__context__", None)
    cause_text = str(cause).strip() if cause is not None else ""
    if (
        not text
        or "returned a result with an exception set" in text
        or text == str(type(exc))
    ):
        hint = cause_text or type(exc).__name__
        return (
            f"{hint}；常见原因：PLC 已被其它程序占用、上一连接未断开、"
            f"IP/机架/槽号不对或网络不通。请先点停止并断开后再连。"
        )
    return f"{type(exc).__name__}: {text}"


def pack_int(value: int) -> bytes:
    return struct.pack(">h", int(value))


def _unpack_int(data: bytes | bytearray) -> int:
    if len(data) < 2:
        raise ValueError("PLC INT 数据不足 2 字节")
    return struct.unpack(">h", bytes(data[:2]))[0]


class S7Client:
    def __init__(
        self,
        client: Any,
        config: S7Config,
        *,
        clock: Any = time.monotonic,
        sleep: Any = time.sleep,
        should_stop: Any = None,
    ) -> None:
        self._client = client
        self.config = config
        self._clock = clock
        self._sleep = sleep
        self._should_stop = should_stop or (lambda: False)

    def connect(self) -> None:
        try:
            if bool(self._client.get_connected()):
                return
        except Exception:
            # 客户端状态异常时先尝试断开再重建连接
            try:
                self._client.disconnect()
            except Exception:
                pass

        last_error: Exception | None = None
        for attempt in range(self.config.connect_retries):
            try:
                self._client.connect(
                    self.config.ip,
                    self.config.rack,
                    self.config.slot,
                    self.config.port,
                )
                try:
                    connected = bool(self._client.get_connected())
                except Exception as exc:  # noqa: BLE001
                    raise OSError(
                        f"连接后状态异常：{_format_plc_exc(exc)}"
                    ) from exc
                if not connected:
                    raise OSError("驱动未报告已连接")
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                try:
                    self._client.disconnect()
                except Exception:
                    pass
                if attempt + 1 < self.config.connect_retries:
                    self._sleep(self.config.retry_interval)
        detail = _format_plc_exc(last_error) if last_error else "未知错误"
        raise PlcCommunicationError(
            f"连接 PLC 失败：{detail}"
        ) from last_error

    def disconnect(self) -> None:
        client = self._client
        try:
            try:
                if bool(client.get_connected()):
                    client.disconnect()
            except Exception:
                try:
                    client.disconnect()
                except Exception:
                    pass
        finally:
            destroy = getattr(client, "destroy", None)
            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    pass

    def read_status(self) -> PlcStatus:
        self.connect()
        try:
            head = self._client.db_read(self.config.db_number, FP_OFFSET, 14)
            dh_over = self._client.db_read(
                self.config.db_number, DH_OVER_OFFSET, 2
            )
            if len(head) < 14:
                raise ValueError("DB19 状态数据不足 14 字节")
            words = struct.unpack(">hhhhhhh", bytes(head[:14]))
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
        except Exception as exc:  # noqa: BLE001
            raise PlcCommunicationError(f"读取 DB19 状态失败：{exc}") from exc

    def _stop_requested(self) -> bool:
        try:
            return bool(self._should_stop())
        except Exception:
            return False

    def _handshake_deadline(self) -> float | None:
        """返回单调时钟截止时间；None 表示无限等待。"""
        timeout = float(self.config.handshake_timeout)
        if timeout <= 0:
            return None
        return self._clock() + timeout

    def _timed_out(self, deadline: float | None) -> bool:
        return deadline is not None and self._clock() >= deadline

    def wait_request(self, expected_seq: int | None = None) -> PlcStatus:
        """等待 FP 请求。

        ``expected_seq`` 为 None 时：接受 PLC 给出的任意 seq（由上层按 seq 查库）。
        为具体序号时：必须与 PLC 请求一致（用于写数后的二次确认）。
        """
        deadline = self._handshake_deadline()
        while not self._timed_out(deadline):
            if self._stop_requested():
                raise PlcStoppedError("已停止")
            status = self.read_status()
            if status.fp == 1 and status.fp_over == 0 and status.dh_over == 0:
                if (
                    expected_seq is not None
                    and status.request_seq != int(expected_seq)
                ):
                    raise PlcSequenceMismatch(
                        f"PLC请求 seq={status.request_seq}，"
                        f"当前数据库箱子 seq={expected_seq}"
                    )
                return status
            self._sleep(self.config.poll_interval)
        raise PlcTimeoutError("等待 FP=1、FP_OVER=0、DH_OVER=0 超时")

    def _write_word(self, offset: int, value: int) -> None:
        try:
            self._client.db_write(
                self.config.db_number, offset, bytearray(pack_int(value))
            )
        except Exception as exc:  # noqa: BLE001
            raise PlcCommunicationError(
                f"写入 DB19 DBW{offset} 失败：{exc}"
            ) from exc

    def send_alarm(self, expected_seq: int) -> PlcStatus:
        status = self.wait_request(expected_seq)
        self._write_word(ALARM_OFFSET, 1)
        return status

    def send_normal(self, command: PlcCommand) -> PlcStatus:
        last_status = self.wait_request(command.sequence)
        for offset, value in command.words().items():
            self._write_word(offset, value)
        self._write_word(DH_OVER_OFFSET, 1)

        deadline = self._handshake_deadline()
        acknowledged = False
        while not self._timed_out(deadline):
            if self._stop_requested():
                raise PlcStoppedError("已停止")
            last_status = self.read_status()
            if not acknowledged and last_status.fp_over == 1:
                self._write_word(FP_OFFSET, 0)
                self._write_word(DH_OVER_OFFSET, 0)
                acknowledged = True
            elif (
                acknowledged
                and last_status.fp == 0
                and last_status.fp_over == 0
                and last_status.dh_over == 0
            ):
                return last_status
            self._sleep(self.config.poll_interval)
        raise PlcTimeoutError("等待 FP_OVER 回执或复位超时；本箱不会自动重发")


def create_snap7_client() -> Any:
    try:
        import snap7
    except ImportError as exc:
        raise RuntimeError(
            "缺少 python-snap7，请先执行：python -m pip install -r requirements.txt"
        ) from exc
    client_type = getattr(snap7, "Client", None)
    if client_type is None:
        from snap7.client import Client as client_type
    return client_type()
