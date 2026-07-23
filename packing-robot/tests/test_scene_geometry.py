import pytest

import pyvista as pv
import packing_ui.scene as scene_module

from vtkmodules.vtkRenderingAnnotation import vtkCornerAnnotation

from packing_ui.scene import (
    _cuboid_mesh,
    _set_annotation_text,
    conveyor_bounds,
    default_camera_position,
    oriented_cuboid_points,
    pickup_marker_positions,
)


def test_ninety_degree_cuboid_swaps_xy_extents_about_center():
    points = oriented_cuboid_points(100, 200, 0, 600, 800, 50, 90)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]

    assert max(xs) - min(xs) == pytest.approx(800)
    assert max(ys) - min(ys) == pytest.approx(600)
    assert (min(zs), max(zs)) == pytest.approx((0, 50))


def test_pickup_marker_positions_define_a_and_b_on_box_top():
    markers = pickup_marker_positions(100, 200, 10, 700, 530, 480, 0)

    assert markers["A"] == pytest.approx((100, 200, 490))
    assert markers["B"] == pytest.approx((800, 200, 490))


def test_pickup_marker_positions_relabel_current_bounds_after_ninety_degree_turn():
    markers = pickup_marker_positions(350, -1200, 0, 700, 530, 480, 90)

    assert markers["A"] == pytest.approx((435, -1285, 480))
    assert markers["B"] == pytest.approx((965, -1285, 480))


def test_conveyor_is_centered_in_x_and_entirely_below_x_axis():
    bounds = conveyor_bounds(1440, 2240)

    assert 0 <= bounds[0] < bounds[1] <= 1440
    assert bounds[2:4] == pytest.approx((-1800.0, -350.0))
    assert bounds[3] < 0


def test_dynamic_cuboid_mesh_accepts_geometry_tuple():
    points = oriented_cuboid_points(0, 0, 0, 600, 800, 50, 0)

    mesh = _cuboid_mesh(pv, points)

    assert mesh.n_points == 8
    assert mesh.n_cells == 6


def test_corner_annotation_text_is_updated_with_supported_vtk_api():
    actor = vtkCornerAnnotation()

    _set_annotation_text(actor, "READY 1/16")

    assert actor.GetText(2) == "READY 1/16"


def test_default_camera_includes_negative_y_conveyor_and_positive_y_pallet():
    position, focal, view_up = default_camera_position(1440, 2240)

    assert position[0] > focal[0]
    assert position[1] > focal[1]
    assert position[2] > focal[2]
    assert -1800 < focal[1] < 2240
    assert view_up == (0.0, 0.0, 1.0)


def test_already_placed_boxes_are_opaque_and_future_targets_are_transparent():
    opacity_for_step = getattr(scene_module, "box_target_opacity", None)

    assert opacity_for_step is not None
    assert opacity_for_step(item_index=0, step_index=1) == 1.0
    assert opacity_for_step(item_index=2, step_index=1) == 0.10


def test_only_a_box_that_has_just_been_placed_uses_orange_highlight():
    color_for_frame = getattr(scene_module, "active_box_color", None)
    orange = getattr(scene_module, "CURRENT_PLACED_COLOR", None)
    normal = scene_module._type_color("ZX222")

    assert color_for_frame is not None
    assert orange is not None
    assert color_for_frame("ZX222", "TRANSFER", 0.5) == normal
    assert color_for_frame("ZX222", "PLACE_DESCEND", 0.99) == normal
    assert color_for_frame("ZX222", "PLACE_DESCEND", 1.0) == orange
    assert color_for_frame("ZX222", "RELEASE", 0.0) == orange
    assert color_for_frame("ZX222", "RETRACT", 1.0) == orange
    assert color_for_frame("ZX222", "READY", 0.0) == normal


def test_latest_placed_box_stays_current_until_next_box_reaches_pallet():
    current_placed_index = getattr(
        scene_module, "current_placed_box_index", None
    )

    assert current_placed_index is not None
    assert current_placed_index(0, "READY", 0.0) is None
    assert current_placed_index(0, "RELEASE", 0.0) == 0
    assert current_placed_index(1, "READY", 0.0) == 0
    assert current_placed_index(1, "TRANSFER", 0.7) == 0
    assert current_placed_index(1, "PLACE_DESCEND", 0.99) == 0
    assert current_placed_index(1, "PLACE_DESCEND", 1.0) == 1
    assert current_placed_index(1, "RELEASE", 0.0) == 1
    assert current_placed_index(2, "PICK_DESCEND", 0.5) == 1
