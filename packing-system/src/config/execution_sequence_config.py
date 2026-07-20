"""Configuration for the independent robot execution-order planner."""

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

    def __post_init__(self) -> None:
        for name in ("enabled", "require_suction_pose"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError("%s must be a boolean" % name)

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
