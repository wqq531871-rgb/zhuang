from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget
from PySide6.QtCore import Qt

from .animation import PHASES
from .data import RobotAction


class PlaybackController(QObject):
    frameChanged = Signal(int, str, float)
    playingChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.actions: list[RobotAction] = []
        self.current_step_index = 0
        self.phase_index = 0
        self.fraction = 0.0
        self.speed = 1.0
        self._playing = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    @property
    def phase(self) -> str:
        return PHASES[self.phase_index]

    @property
    def step_count(self) -> int:
        return len(self.actions)

    @property
    def is_playing(self) -> bool:
        return self._playing

    def set_actions(self, actions: list[RobotAction]) -> None:
        self.pause()
        self.actions = list(actions)
        self.reset()

    def _emit_frame(self) -> None:
        self.frameChanged.emit(self.current_step_index, self.phase, self.fraction)

    def reset(self) -> None:
        self.current_step_index = 0
        self.phase_index = 0
        self.fraction = 0.0
        self._emit_frame()

    def seek_step(self, index: int) -> None:
        self.pause()
        self.current_step_index = max(0, min(int(index), max(0, self.step_count - 1)))
        self.phase_index = 0
        self.fraction = 0.0
        self._emit_frame()

    def previous_step(self) -> None:
        self.seek_step(self.current_step_index - 1)

    def next_step(self) -> None:
        self.seek_step(self.current_step_index + 1)

    def end(self) -> None:
        if not self.step_count:
            return
        self.current_step_index = self.step_count - 1
        self.phase_index = len(PHASES) - 1
        self.fraction = 1.0
        self._emit_frame()

    def play(self) -> None:
        if not self.step_count or self._playing:
            return
        self._playing = True
        self._timer.start()
        self.playingChanged.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._timer.stop()
        self.playingChanged.emit(False)

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.1, float(speed))

    def advance(self, amount: float) -> None:
        if not self.step_count:
            return
        self.fraction += max(0.0, float(amount))
        while self.fraction >= 1.0:
            self.fraction -= 1.0
            if self.phase_index < len(PHASES) - 1:
                self.phase_index += 1
            elif self.current_step_index < self.step_count - 1:
                self.current_step_index += 1
                self.phase_index = 0
            else:
                self.fraction = 1.0
                self.pause()
                break
        self._emit_frame()

    def _tick(self) -> None:
        self.advance(0.033 * self.speed)


class PlaybackPanel(QWidget):
    def __init__(self, controller: PlaybackController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.first_button = QPushButton("|◀")
        self.previous_button = QPushButton("◀")
        self.play_button = QPushButton("播放")
        self.next_button = QPushButton("▶")
        self.last_button = QPushButton("▶|")
        self.step_label = QLabel("0 / 0")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.phase_label = QLabel("READY")
        self.speed_combo = QComboBox()
        for label, value in (("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x", 4.0)):
            self.speed_combo.addItem(label, value)
        self.speed_combo.setCurrentText("1x")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        for widget in (
            self.first_button,
            self.previous_button,
            self.play_button,
            self.next_button,
            self.last_button,
            self.step_label,
            self.slider,
            self.phase_label,
            self.speed_combo,
        ):
            layout.addWidget(widget)
        layout.setStretchFactor(self.slider, 1)

        self.first_button.clicked.connect(controller.reset)
        self.previous_button.clicked.connect(controller.previous_step)
        self.play_button.clicked.connect(controller.toggle)
        self.next_button.clicked.connect(controller.next_step)
        self.last_button.clicked.connect(controller.end)
        self.slider.valueChanged.connect(controller.seek_step)
        self.speed_combo.currentIndexChanged.connect(self._speed_changed)
        controller.frameChanged.connect(self._frame_changed)
        controller.playingChanged.connect(
            lambda playing: self.play_button.setText("暂停" if playing else "播放")
        )

    def refresh_range(self) -> None:
        self.slider.setRange(0, max(0, self.controller.step_count - 1))
        self._frame_changed(
            self.controller.current_step_index,
            self.controller.phase,
            self.controller.fraction,
        )

    def _speed_changed(self, index: int) -> None:
        value = self.speed_combo.itemData(index)
        if value is not None:
            self.controller.set_speed(float(value))

    def _frame_changed(self, index: int, phase: str, _fraction: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)
        self.step_label.setText(
            f"{index + 1 if self.controller.step_count else 0} / {self.controller.step_count}"
        )
        self.phase_label.setText(phase)
