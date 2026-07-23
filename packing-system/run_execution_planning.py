"""Create a centered robot execution plan from an existing packing report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from src.config import ConfigLoader
from src.execution import (
    ExecutionSequenceConfig,
    ExecutionSequenceError,
    plan_execution_report,
    publish_json_files as _publish_json_files,
    report_to_execution_plan_result,
)


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent / "config" / "packing_config.yaml"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reorder packed_items with support topology and a directed "
            "diagonal-approach wave, then center the pallet layout."
        )
    )
    parser.add_argument("input", help="Existing packing_plan JSON")
    parser.add_argument(
        "--config",
        help="Configuration YAML (default: config/packing_config.yaml)",
    )
    parser.add_argument(
        "--output",
        help="Same-schema execution JSON (default: <input>_execution.json)",
    )
    parser.add_argument(
        "--wcs-output",
        help="Optional WCS case-array JSON whose seq follows execution order",
    )
    parser.add_argument(
        "--wcs-map-output",
        help=(
            "Optional box_unique_id-to-full-plan mapping JSON. When omitted "
            "with --wcs-output, defaults to <wcs_output_stem>_map.json"
        ),
    )
    parser.add_argument(
        "--origin",
        choices=(
            "x_min_y_min",
            "x_min_y_max",
            "x_max_y_min",
            "x_max_y_max",
        ),
        default=None,
        help="Override execution_sequence.origin for this run",
    )
    parser.add_argument(
        "--coordinate-tolerance-mm",
        type=float,
        default=None,
        help="Override execution_sequence.coordinate_tolerance_mm",
    )
    parser.add_argument(
        "--xy-clearance-mm",
        type=float,
        default=None,
        help="Override both configured box and suction XY clearances",
    )
    parser.add_argument(
        "--box-xy-clearance-mm",
        type=float,
        default=None,
        help="Override execution_sequence.box_xy_clearance_mm",
    )
    parser.add_argument(
        "--suction-xy-clearance-mm",
        type=float,
        default=None,
        help="Override execution_sequence.suction_xy_clearance_mm",
    )
    parser.add_argument(
        "--z-clearance-mm",
        type=float,
        default=None,
        help="Override execution_sequence.suction_z_clearance_mm",
    )
    suction_group = parser.add_mutually_exclusive_group()
    suction_group.add_argument(
        "--require-suction-pose",
        dest="require_suction_pose",
        action="store_true",
        default=None,
        help="Require complete suction fields for this run",
    )
    suction_group.add_argument(
        "--allow-missing-suction",
        dest="require_suction_pose",
        action="store_false",
        help="Allow boxes without suction fields for this run",
    )
    return parser


def _default_output(source: Path) -> Path:
    return source.with_name(source.stem + "_execution.json")


def _same_path(first: Path, second: Path) -> bool:
    return first.resolve() == second.resolve()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    if args.config and not config_path.exists():
        parser.error("configuration file does not exist: %s" % config_path)
    try:
        settings = ConfigLoader(config_path).load_execution_sequence_config()
    except (OSError, TypeError, ValueError) as exc:
        print("execution configuration failed: %s" % exc, file=sys.stderr)
        return 1
    if not settings.enabled:
        print("execution planning disabled by config: %s" % config_path)
        return 0

    source = Path(args.input)
    output = Path(args.output) if args.output else _default_output(source)
    wcs_output = Path(args.wcs_output) if args.wcs_output else None
    wcs_map_output = Path(args.wcs_map_output) if args.wcs_map_output else None
    if wcs_output is not None and wcs_map_output is None:
        wcs_map_output = wcs_output.with_name(wcs_output.stem + "_map.json")
    if wcs_map_output is not None and wcs_output is None:
        parser.error("--wcs-map-output requires --wcs-output")

    if _same_path(source, output):
        parser.error("execution output must not overwrite the source JSON")
    if wcs_output is not None and _same_path(source, wcs_output):
        parser.error("WCS output must not overwrite the source JSON")
    if wcs_output is not None and _same_path(output, wcs_output):
        parser.error("execution output and WCS output must be different files")
    for other, label in (
        (source, "source JSON"),
        (output, "execution output"),
        (wcs_output, "WCS output"),
    ):
        if (
            wcs_map_output is not None
            and other is not None
            and _same_path(wcs_map_output, other)
        ):
            parser.error("WCS map output must differ from %s" % label)

    try:
        report = json.loads(source.read_text(encoding="utf-8"))
        combined_xy = args.xy_clearance_mm
        box_xy = (
            args.box_xy_clearance_mm
            if args.box_xy_clearance_mm is not None
            else combined_xy
            if combined_xy is not None
            else settings.box_xy_clearance_mm
        )
        suction_xy = (
            args.suction_xy_clearance_mm
            if args.suction_xy_clearance_mm is not None
            else combined_xy
            if combined_xy is not None
            else settings.suction_xy_clearance_mm
        )
        config = ExecutionSequenceConfig(
            origin=args.origin or settings.origin,
            coordinate_tolerance_mm=(
                args.coordinate_tolerance_mm
                if args.coordinate_tolerance_mm is not None
                else settings.coordinate_tolerance_mm
            ),
            box_xy_clearance_mm=box_xy,
            suction_xy_clearance_mm=suction_xy,
            suction_z_clearance_mm=(
                args.z_clearance_mm
                if args.z_clearance_mm is not None
                else settings.suction_z_clearance_mm
            ),
            approach_offset_x_mm=settings.approach_offset_x_mm,
            approach_offset_y_mm=settings.approach_offset_y_mm,
            approach_z_clearance_mm=settings.approach_z_clearance_mm,
            approach_box_xy_clearance_mm=(
                settings.approach_box_xy_clearance_mm
            ),
            approach_suction_xy_clearance_mm=(
                settings.approach_suction_xy_clearance_mm
            ),
            require_suction_pose=(
                args.require_suction_pose
                if args.require_suction_pose is not None
                else settings.require_suction_pose
            ),
            max_occupied_directions=settings.max_occupied_directions,
            side_neighbor_clearance_mm=settings.side_neighbor_clearance_mm,
            side_height_tolerance_mm=settings.side_height_tolerance_mm,
            preserve_open_direction=settings.preserve_open_direction,
            max_sequence_search_seconds_per_pallet=(
                settings.max_sequence_search_seconds_per_pallet
            ),
            scan_column_tolerance_mm=settings.scan_column_tolerance_mm,
        )
        execution_report = plan_execution_report(report, config=config)
        wcs_result = None
        if wcs_output is not None:
            wcs_result = report_to_execution_plan_result(
                report, config=config
            )
    except (
        OSError,
        json.JSONDecodeError,
        ExecutionSequenceError,
        TypeError,
        ValueError,
    ) as exc:
        print("execution planning failed: %s" % exc, file=sys.stderr)
        return 1

    source_pallets = report.get("pallets") or []
    execution_pallets = execution_report.get("pallets") or []
    changed = 0
    boxes = 0
    for before, after in zip(source_pallets, execution_pallets):
        before_ids = [item.get("id") for item in before.get("packed_items") or []]
        after_ids = [item.get("id") for item in after.get("packed_items") or []]
        boxes += len(after_ids)
        if before_ids != after_ids:
            changed += 1

    try:
        if wcs_output is None:
            _publish_json_files(
                [(output, execution_report)], release_path=output
            )
        else:
            _publish_json_files(
                [
                    (output, execution_report),
                    (wcs_map_output, wcs_result.plan_by_unique_id),
                    (wcs_output, wcs_result.cases),
                ],
                release_path=wcs_output,
            )
    except OSError as exc:
        print("execution output failed: %s" % exc, file=sys.stderr)
        return 1

    if wcs_result is not None:
        try:
            from src.service.success_box_db import persist_success_boxes

            persist_success_boxes(
                execution_report,
                wcs_result,
                config_path=config_path,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                "[WCS-DB] wcs_success_box 后置写入异常：%s" % exc,
                file=sys.stderr,
            )
        try:
            from src.service.box_orientation_db import persist_box_orientations

            persist_box_orientations(wcs_result, config_path=config_path)
        except Exception as exc:  # noqa: BLE001
            print(
                "[WCS-DB] wcs_box_orientation 后置写入异常：%s" % exc,
                file=sys.stderr,
            )

    print(
        "execution plan written: pallets=%d boxes=%d reordered_pallets=%d path=%s"
        % (len(execution_pallets), boxes, changed, output)
    )
    if wcs_output is not None:
        print("WCS execution cases written: %s" % wcs_output)
        print("WCS execution plan map written: %s" % wcs_map_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
