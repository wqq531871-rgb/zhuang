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
    approach_offset_x_mm: float = 20.0
    approach_offset_y_mm: float = 20.0
    approach_z_clearance_mm: float = 20.0
    approach_box_xy_clearance_mm: float = 0.0
    approach_suction_xy_clearance_mm: float = 0.0
    require_suction_pose: bool = True
    max_occupied_directions: int = 2
    side_neighbor_clearance_mm: float = 5.0
    side_height_tolerance_mm: float = 2.0
    preserve_open_direction: bool = True
    force_publish_on_gate_failure: bool = False
    max_sequence_search_seconds_per_pallet: float = 1.0
    forced_sequence_search_seconds_per_pallet: float = 30.0
    scan_column_tolerance_mm: float = 5.0

    def __post_init__(self) -> None:
        for name in (
            "enabled",
            "require_suction_pose",
            "preserve_open_direction",
            "force_publish_on_gate_failure",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError("%s must be a boolean" % name)
        if (
            isinstance(self.max_occupied_directions, bool)
            or not isinstance(self.max_occupied_directions, int)
            or not 0 <= self.max_occupied_directions <= 2
        ):
            raise ValueError(
                "max_occupied_directions must be an integer from 0 to 2"
            )
        for name in (
            "side_neighbor_clearance_mm",
            "side_height_tolerance_mm",
            "max_sequence_search_seconds_per_pallet",
            "forced_sequence_search_seconds_per_pallet",
            "scan_column_tolerance_mm",
            "approach_offset_x_mm",
            "approach_offset_y_mm",
            "approach_z_clearance_mm",
            "approach_box_xy_clearance_mm",
            "approach_suction_xy_clearance_mm",
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
        if self.forced_sequence_search_seconds_per_pallet <= 0:
            raise ValueError(
                "forced_sequence_search_seconds_per_pallet must be positive"
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
