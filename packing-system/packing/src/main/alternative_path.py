"""Guarded selection between GCP and a time-bounded full alternative path."""

from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .result_formatter import ResultFormatter


def _alternative_path_worker(
    output_path: str,
    boxes: List[Dict],
    constraint_data: Dict,
) -> None:
    """Run the complete beam/recipe/rescue workflow in an isolated process."""

    payload: Dict
    log_buffer = StringIO()
    with redirect_stdout(log_buffer), redirect_stderr(log_buffer):
        try:
            from run_packing import build_workflow
            from src.config import ConstraintConfig
            from src.main.report_persister import NullReportPersister

            config_data = dict(constraint_data)
            config_data["main_packer"] = "beam"
            config_data["dual_path_enabled"] = False
            workflow = build_workflow(
                constraint_config=ConstraintConfig.from_dict(config_data)
            )
            workflow._report_persister = NullReportPersister()
            report = workflow.run_with_boxes(boxes)
            payload = {"status": "ok", "report": report, "error": None}
        except BaseException as exc:  # Serialize child failures for the parent.
            payload = {
                "status": "error",
                "report": None,
                "error": "%s: %s" % (type(exc).__name__, exc),
            }
    payload["log"] = log_buffer.getvalue()
    Path(output_path).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _success_count(plans: List[Dict]) -> int:
    return sum(1 for plan in plans if plan.get("mpm_status") == "SUCCESS")


def has_uncaptured_opportunity(
    boxes: List[Dict], plans: List[Dict], target_mpm: Optional[float]
) -> bool:
    """Return whether index mass permits more successful pallets than captured."""

    if target_mpm is None or target_mpm <= 0:
        return False
    total = sum(
        float(box.get("min_pack_multiple", 0) or 0) for box in boxes
    )
    upper_bound = int(total // float(target_mpm))
    return _success_count(plans) < upper_bound


def candidate_rank(plans: List[Dict]) -> Tuple[int, int, float]:
    """Rank by successes, then fewer pallets, then strongest failed pallet."""

    failed_peak = max(
        (
            float(plan.get("mpm_total", 0) or 0)
            for plan in plans
            if plan.get("mpm_status") != "SUCCESS"
        ),
        default=0.0,
    )
    return (_success_count(plans), -len(plans), failed_peak)


def candidate_passes_gates(
    raw_boxes: List[Dict], plans: List[Dict], constraint_config
) -> bool:
    """Run conservation/business gates and the final full pallet constraints."""

    try:
        ResultFormatter.validate_output_quality(raw_boxes, plans)
        ResultFormatter.validate_final_constraints(
            plans, constraint_config=constraint_config
        )
    except (KeyError, TypeError, ValueError):
        return False
    return True


def choose_guarded_candidate(
    raw_boxes: List[Dict],
    gcp_plans: List[Dict],
    alternative_plans: Optional[List[Dict]],
    pallet_dims: Dict,
    constraint_config,
) -> Tuple[List[Dict], str]:
    """Adopt the alternative only when it is valid and strictly better."""

    del pallet_dims  # Pallet dimensions are read from each packed item by gates.
    if not alternative_plans:
        return gcp_plans, "gcp"
    if not candidate_passes_gates(
        raw_boxes, alternative_plans, constraint_config
    ):
        return gcp_plans, "gcp"
    if candidate_rank(alternative_plans) <= candidate_rank(gcp_plans):
        return gcp_plans, "gcp"
    return alternative_plans, "alternative"


def run_alternative_full_path(
    boxes: List[Dict],
    constraint_config,
    timeout_seconds: float,
) -> Dict:
    """Run the complete alternative workflow with a hard process timeout."""

    started = time.time()
    fd, output_path = tempfile.mkstemp(
        prefix="packing-alternative-", suffix=".json"
    )
    os.close(fd)
    try:
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_alternative_path_worker,
            args=(
                output_path,
                list(boxes),
                constraint_config.to_dict(),
            ),
            daemon=True,
        )
        process.start()
        process.join(max(0.0, float(timeout_seconds)))
        if process.is_alive():
            process.terminate()
            process.join(5.0)
            return {
                "status": "timeout",
                "report": None,
                "error": None,
                "elapsed_seconds": time.time() - started,
            }
        try:
            payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            payload = {
                "status": "error",
                "report": None,
                "error": "alternative worker produced no valid result: %s" % exc,
            }
        payload["elapsed_seconds"] = time.time() - started
        return payload
    finally:
        try:
            Path(output_path).unlink()
        except FileNotFoundError:
            pass
