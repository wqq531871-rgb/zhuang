from __future__ import annotations

import hashlib
import math

from PySide6.QtWidgets import QVBoxLayout, QWidget

from .animation import trajectory_pose
from .data import PalletPlan, RobotAction


CURRENT_PLACED_COLOR = (1.0, 0.42, 0.05)


def conveyor_bounds(
    pallet_length: float, pallet_width: float
) -> tuple[float, float, float, float, float, float]:
    width = min(1200.0, float(pallet_length))
    x_min = max(0.0, (float(pallet_length) - width) / 2.0)
    return x_min, x_min + width, -1800.0, -350.0, -120.0, 0.0


def box_target_opacity(item_index: int, step_index: int) -> float:
    """Completed boxes are solid; only future target positions are translucent."""
    return 1.0 if item_index < step_index else 0.10


def _current_box_has_reached_pallet(phase: str, fraction: float) -> bool:
    return phase in {"RELEASE", "RETRACT"} or (
        phase == "PLACE_DESCEND" and float(fraction) >= 1.0
    )


def current_placed_box_index(
    step_index: int, phase: str, fraction: float
) -> int | None:
    """Return the latest box on the pallet, keeping it current until replaced."""
    step_index = max(0, int(step_index))
    if _current_box_has_reached_pallet(phase, fraction):
        return step_index
    return step_index - 1 if step_index > 0 else None


def active_box_color(
    box_type: str, phase: str, fraction: float
) -> tuple[float, float, float]:
    return (
        CURRENT_PLACED_COLOR
        if _current_box_has_reached_pallet(phase, fraction)
        else _type_color(box_type)
    )


def default_camera_position(
    pallet_length: float, pallet_width: float
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    focal = (
        float(pallet_length) / 2.0,
        (float(pallet_width) - 1800.0) / 2.0,
        350.0,
    )
    position = (focal[0] + 4900.0, focal[1] + 6100.0, focal[2] + 3700.0)
    return position, focal, (0.0, 0.0, 1.0)


def oriented_cuboid_points(
    x: float,
    y: float,
    z: float,
    length: float,
    width: float,
    height: float,
    yaw_deg: float,
) -> tuple[tuple[float, float, float], ...]:
    cx, cy = x + length / 2.0, y + width / 2.0
    angle = math.radians(yaw_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    base: list[tuple[float, float]] = []
    for local_x, local_y in (
        (-length / 2.0, -width / 2.0),
        (length / 2.0, -width / 2.0),
        (length / 2.0, width / 2.0),
        (-length / 2.0, width / 2.0),
    ):
        base.append(
            (
                cx + local_x * cosine - local_y * sine,
                cy + local_x * sine + local_y * cosine,
            )
        )
    return tuple((px, py, level) for level in (z, z + height) for px, py in base)


def pickup_marker_positions(
    x: float,
    y: float,
    z: float,
    length: float,
    width: float,
    height: float,
    yaw_deg: float,
) -> dict[str, tuple[float, float, float]]:
    """Return A/B from the current oriented box's XY bounding corners."""
    points = oriented_cuboid_points(
        x, y, z, length, width, height, yaw_deg
    )
    top_points = points[4:]
    x_min = min(point[0] for point in top_points)
    x_max = max(point[0] for point in top_points)
    y_min = min(point[1] for point in top_points)
    top_z = z + height
    return {
        "A": (x_min, y_min, top_z),
        "B": (x_max, y_min, top_z),
    }


def _type_color(box_type: str) -> tuple[float, float, float]:
    digest = hashlib.sha256(box_type.encode("utf-8")).digest()
    return tuple(0.32 + component / 255.0 * 0.5 for component in digest[:3])


def _cuboid_mesh(pv, points):
    faces = [
        4, 0, 3, 2, 1,
        4, 4, 5, 6, 7,
        4, 0, 1, 5, 4,
        4, 1, 2, 6, 5,
        4, 2, 3, 7, 6,
        4, 3, 0, 4, 7,
    ]
    return pv.PolyData(list(points), faces)


def _set_annotation_text(actor, text: str) -> None:
    if hasattr(actor, "SetInput"):
        actor.SetInput(text)
    else:
        actor.SetText(2, text)


class PackingScene(QWidget):
    """Interactive PyVista packing scene modeled after the reference project."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyvista as pv
        from pyvistaqt import QtInteractor

        self._pv = pv
        self.plotter = QtInteractor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plotter.interactor)
        self.plotter.set_background("#0e1922")
        self.plotter.add_axes(line_width=2)
        self.plan: PalletPlan | None = None
        self.actions: list[RobotAction] = []
        self._box_actors: dict[str, object] = {}
        self._box_colors: dict[str, tuple[float, float, float]] = {}
        self._active_box_actor = None
        self._suction_actor = None
        self._pickup_marker_actors: dict[str, object] = {}
        self._phase_text = None

    def _reset_scene(self) -> None:
        self.plotter.clear()
        self.plotter.add_axes(line_width=2)
        self._box_actors.clear()
        self._box_colors.clear()
        self._active_box_actor = None
        self._suction_actor = None
        self._pickup_marker_actors.clear()
        self._phase_text = None

    def set_plan(self, plan: PalletPlan | None) -> None:
        self.plan = plan
        self.actions = []
        self._reset_scene()
        if plan is None:
            self.plotter.render()
            return
        pallet = self._pv.Box(
            bounds=(0, plan.pallet_length, 0, plan.pallet_width, -80, 0)
        )
        self.plotter.add_mesh(
            pallet, color="#b88952", opacity=0.96, show_edges=True, edge_color="#d6aa72", name="pallet"
        )
        self._add_conveyor()
        for item in plan.items:
            mesh = self._pv.Box(
                bounds=(
                    item.x,
                    item.x + item.length,
                    item.y,
                    item.y + item.width,
                    item.z,
                    item.z + item.height,
                )
            )
            color = _type_color(item.box_type)
            actor = self.plotter.add_mesh(
                mesh,
                color=color,
                opacity=0.12,
                show_edges=True,
                edge_color="#9db4c2",
                name=f"target-{item.id}",
            )
            self._box_actors[item.id] = actor
            self._box_colors[item.id] = color
        self._phase_text = self.plotter.add_text(
            "READY", position="upper_left", font_size=11, color="#d8e7ef", name="phase-text"
        )
        self._set_default_camera()
        self.plotter.render()

    def _set_default_camera(self) -> None:
        if self.plan is None:
            return
        position, focal, view_up = default_camera_position(
            self.plan.pallet_length, self.plan.pallet_width
        )
        self.plotter.camera.position = position
        self.plotter.camera.focal_point = focal
        self.plotter.camera.up = view_up
        self.plotter.reset_camera_clipping_range()

    def _add_conveyor(self) -> None:
        if self.plan is None:
            return
        x0, x1, y0, y1, z0, z1 = conveyor_bounds(
            self.plan.pallet_length, self.plan.pallet_width
        )
        base = self._pv.Box(bounds=(x0, x1, y0, y1, z0, z1))
        self.plotter.add_mesh(base, color="#273846", opacity=1.0, show_edges=True, edge_color="#647988", name="conveyor")
        belt = self._pv.Box(bounds=(x0 + 35, x1 - 35, y0 + 55, y1 - 55, 0, 35))
        self.plotter.add_mesh(belt, color="#202a32", opacity=1.0, name="belt")
        span = y1 - y0
        for index in range(10):
            roller_y = y0 + 90 + index * (span - 180) / 9
            roller = self._pv.Cylinder(
                center=((x0 + x1) / 2.0, roller_y, 38),
                direction=(1, 0, 0),
                radius=34,
                height=max(10.0, x1 - x0 - 130),
                resolution=20,
            )
            self.plotter.add_mesh(roller, color="#71818c", metallic=0.35, roughness=0.55)

    def set_actions(self, actions: list[RobotAction]) -> None:
        self.actions = list(actions)
        if self.actions:
            self.show_frame(0, "READY", 0.0)

    def _update_dynamic_actor(self, actor, mesh, **mesh_options):
        if actor is None:
            return self.plotter.add_mesh(mesh, **mesh_options)
        actor.mapper.SetInputData(mesh)
        actor.SetVisibility(True)
        return actor

    def show_frame(self, step_index: int, phase: str, fraction: float) -> None:
        if self.plan is None or not self.actions:
            return
        step_index = max(0, min(int(step_index), len(self.actions) - 1))
        action = self.actions[step_index]
        pose = trajectory_pose(
            action,
            phase,
            fraction,
            self.plan.pallet_length,
            self.plan.pallet_width,
        )

        highlighted_index = current_placed_box_index(step_index, phase, fraction)
        for index, item in enumerate(self.plan.items):
            actor = self._box_actors.get(item.id)
            if actor is None:
                continue
            if index < step_index:
                actor.SetVisibility(True)
                actor.GetProperty().SetOpacity(box_target_opacity(index, step_index))
                actor.GetProperty().SetColor(
                    CURRENT_PLACED_COLOR
                    if index == highlighted_index
                    else self._box_colors[item.id]
                )
            elif index == step_index:
                actor.SetVisibility(False)
            else:
                actor.SetVisibility(True)
                actor.GetProperty().SetOpacity(box_target_opacity(index, step_index))
                actor.GetProperty().SetColor(self._box_colors[item.id])

        box_yaw_relative_to_target = pose.yaw_deg - action.target_orientation_deg
        box_points = oriented_cuboid_points(
            pose.box_x,
            pose.box_y,
            pose.box_z,
            action.box_size[0],
            action.box_size[1],
            action.box_size[2],
            box_yaw_relative_to_target,
        )
        active_color = active_box_color(action.box_type, phase, fraction)
        self._active_box_actor = self._update_dynamic_actor(
            self._active_box_actor,
            _cuboid_mesh(self._pv, box_points),
            color=active_color,
            opacity=1.0,
            show_edges=True,
            edge_color="#f7d35c",
            name="active-box",
        )
        self._active_box_actor.GetProperty().SetColor(active_color)
        marker_positions = pickup_marker_positions(
            pose.box_x,
            pose.box_y,
            pose.box_z,
            action.box_size[0],
            action.box_size[1],
            action.box_size[2],
            box_yaw_relative_to_target,
        )
        for label, marker_position in marker_positions.items():
            selected = label == action.pickup_point
            marker = self._pv.Sphere(radius=28.0, center=marker_position)
            actor = self._update_dynamic_actor(
                self._pickup_marker_actors.get(label),
                marker,
                color="#84cc16" if selected else "#94a3b8",
                opacity=1.0,
                name=f"pickup-marker-{label}",
            )
            actor.GetProperty().SetColor(
                (0.52, 0.80, 0.09) if selected else (0.58, 0.64, 0.72)
            )
            self._pickup_marker_actors[label] = actor
            self.plotter.add_point_labels(
                [marker_position],
                [label],
                name=f"pickup-label-{label}",
                font_size=14,
                text_color="#d9f99d" if selected else "#cbd5e1",
                point_size=0,
                shape=None,
                always_visible=True,
            )
        cup_points = oriented_cuboid_points(
            pose.cup_x - 300.0,
            pose.cup_y - 400.0,
            pose.cup_z,
            600.0,
            800.0,
            50.0,
            pose.yaw_deg,
        )
        self._suction_actor = self._update_dynamic_actor(
            self._suction_actor,
            _cuboid_mesh(self._pv, cup_points),
            color="#38bdf8",
            opacity=0.45,
            show_edges=True,
            edge_color="#bcecff",
            name="suction",
        )
        if self._phase_text is not None:
            _set_annotation_text(
                self._phase_text,
                f"{phase}   {step_index + 1}/{len(self.actions)}   箱子 {action.item_id}",
            )
        self.plotter.render()

    def reset_camera(self) -> None:
        self._set_default_camera()
        self.plotter.render()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.plotter.close()
        super().closeEvent(event)
