# “重复当前箱”按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在三维播放控制条增加“重复当前箱”按钮，使当前选中箱从头完整播放一次并自动暂停。

**Architecture:** `PlaybackPanel` 只负责提供按钮并把当前索引交给已有的
`PlaybackController.play_one_step(index)`。单箱重播继续由现有动画状态机完成，
不经过主窗口的现场指令、数据库状态同步或 PLC 发送链路。

**Tech Stack:** Python 3、PySide6、pytest

## Global Constraints

- 按钮文字必须为“重复当前箱”，并放在现有“播放/暂停”按钮右侧。
- 重播从当前箱 `READY`、进度 `0.0` 开始，完整动作结束后自动暂停。
- 重播结束后保持当前箱索引，不前进到下一箱。
- 不读取或修改 MySQL，不改变 `state`，不调用 PLC 发送。
- 保持普通播放、暂停、上一箱、下一箱和速度选择行为不变。
- 不修改 `packing-workspace` 中的现场运行文件。

---

### Task 1: 增加当前箱重播入口并验证完整行为

**Files:**
- Modify: `packing-robot/tests/test_ui_smoke.py`
- Modify: `packing-robot/packing_ui/playback.py:138-202`

**Interfaces:**
- Consumes: `PlaybackController.current_step_index: int`
- Consumes: `PlaybackController.play_one_step(index: int | None = None) -> None`
- Produces: `PlaybackPanel.replay_button: QPushButton`
- Produces: `PlaybackPanel._replay_current_step() -> None`

- [ ] **Step 1: 写入失败的 UI 行为测试**

在 `packing-robot/tests/test_ui_smoke.py` 中把 `PHASES` 加入导入，并新增：

```python
from packing_ui.animation import PHASES


def test_replay_current_box_button_replays_only_selected_box():
    _app()
    window = _test_window()
    window.load_path(SAMPLE)
    window.box_list.setCurrentRow(1)
    controller = window.playback_controller
    selected_index = controller.current_step_index
    controller.phase_index = 3
    controller.fraction = 0.5

    assert window.playback_panel.replay_button.text() == "重复当前箱"
    window.playback_panel.replay_button.click()

    assert controller.current_step_index == selected_index
    assert controller.phase == "READY"
    assert controller.fraction == 0.0
    assert controller.is_playing is True

    controller.advance(float(len(PHASES)))

    assert controller.current_step_index == selected_index
    assert controller.phase == PHASES[-1]
    assert controller.fraction == 1.0
    assert controller.is_playing is False
    window.close()
```

- [ ] **Step 2: 运行新测试并确认按预期失败**

Run:

```powershell
python -m pytest tests/test_ui_smoke.py::test_replay_current_box_button_replays_only_selected_box -q
```

Expected: `FAIL`，失败原因为 `PlaybackPanel` 尚无 `replay_button`。

- [ ] **Step 3: 写入最小 UI 实现**

在 `PlaybackPanel.__init__` 中创建按钮、放入“播放”按钮右侧并连接处理方法：

```python
self.play_button = QPushButton("播放")
self.replay_button = QPushButton("重复当前箱")
self.next_button = QPushButton("▶")
```

```python
for widget in (
    self.first_button,
    self.previous_button,
    self.play_button,
    self.replay_button,
    self.next_button,
    self.last_button,
    self.step_label,
    self.slider,
    self.phase_label,
    self.speed_combo,
):
```

```python
self.play_button.clicked.connect(controller.toggle)
self.replay_button.clicked.connect(self._replay_current_step)
self.next_button.clicked.connect(controller.next_step)
```

在 `PlaybackPanel` 中新增：

```python
def _replay_current_step(self) -> None:
    self.controller.play_one_step(self.controller.current_step_index)
```

- [ ] **Step 4: 运行新测试并确认通过**

Run:

```powershell
python -m pytest tests/test_ui_smoke.py::test_replay_current_box_button_replays_only_selected_box -q
```

Expected: `1 passed`。

- [ ] **Step 5: 运行播放与 UI 回归测试**

Run:

```powershell
python -m pytest tests/test_animation.py tests/test_ui_smoke.py -q
```

Expected: 两个测试文件全部通过。

- [ ] **Step 6: 运行项目测试并隔离已知旧失败**

Run:

```powershell
python -m pytest -q
python -m pytest -q -k "not test_camera_data_overrides_manual_orientation_and_is_exported_for_plc"
```

Expected: 全量运行除既有的
`test_camera_data_overrides_manual_orientation_and_is_exported_for_plc` 外无新增失败；
排除该既有失败后全部通过。

- [ ] **Step 7: 提交实现**

```powershell
git add -- packing-robot/packing_ui/playback.py packing-robot/tests/test_ui_smoke.py packing-robot/docs/superpowers/plans/2026-07-24-replay-current-box-button.md
git commit -m "feat: replay current box animation"
```
