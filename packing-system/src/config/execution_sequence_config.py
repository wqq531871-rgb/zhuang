"""Configuration for the independent robot execution-order planner."""

import math
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ExecutionSequenceSettings:
    """Enable flag and default values for execution-order planning."""

    enabled: bool = False
    origin: str = "x_min_y_min"
    coordinate_tolerance_mm: float = 1e-6
    box_xy_clearance_mm: float = 0.0
    suction_xy_clearance_mm: float = 0.0
    suction_z_clearance_mm: float = 0.0
    require_suction_pose: bool = True
    max_occupied_directions: int = 2
    side_neighbor_clearance_mm: float = 5.0
    side_height_tolerance_mm: float = 2.0
    preserve_open_direction: bool = True
    prefer_adjacent_occupied_sides: bool = True
    max_sequence_search_seconds_per_pallet: float = 1.0
    adaptive_staircase_enabled: bool = False
    staircase_height_difference_threshold_mm: float = 120.0
    staircase_transition_ratio_threshold: float = 0.25
    staircase_min_transition_edges: int = 4
    scan_column_tolerance_mm: float = 5.0

    def __post_init__(self) -> None:
        for name in (
            "enabled",
            "require_suction_pose",
            "preserve_open_direction",
            "prefer_adjacent_occupied_sides",
            "adaptive_staircase_enabled",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError("%s must be a boolean" % name)
        if (
            isinstance(self.max_occupied_directions, bool)
            or not isinstance(self.max_occupied_directions, int)
            or not 0 <= self.max_occupied_directions <= 4
        ):
            raise ValueError(
                "max_occupied_directions must be an integer from 0 to 4"
            )
        for name in (
            "side_neighbor_clearance_mm",
            "side_height_tolerance_mm",
            "max_sequence_search_seconds_per_pallet",
            "staircase_height_difference_threshold_mm",
            "staircase_transition_ratio_threshold",
            "scan_column_tolerance_mm",
        ):
            try:
                raw_value = getattr(self, name)
                if isinstance(raw_value, bool):
                    raise ValueError
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("%s must be a finite number" % name) from exc
            if not math.isfinite(value):
                raise ValueError("%s must be finite" % name)
            if value < 0:
                raise ValueError("%s must be non-negative" % name)
            object.__setattr__(self, name, value)
        if self.max_sequence_search_seconds_per_pallet <= 0:
            raise ValueError(
                "max_sequence_search_seconds_per_pallet must be positive"
            )
        if not 0 <= self.staircase_transition_ratio_threshold <= 1:
            raise ValueError(
                "staircase_transition_ratio_threshold must be between 0 and 1"
            )
        if (
            isinstance(self.staircase_min_transition_edges, bool)
            or not isinstance(self.staircase_min_transition_edges, int)
            or self.staircase_min_transition_edges <= 0
        ):
            raise ValueError(
                "staircase_min_transition_edges must be a positive integer"
            )

    @classmethod
    def from_dict(
        cls, data: Optional[Dict]
    ) -> "ExecutionSequenceSettings":
        """Create settings from the YAML/API section, using defaults as needed."""
        if data is None:
            return cls()
        return cls(**{
            key: value
            for key, value in data.items()
            if key in cls.__annotations__
        })
