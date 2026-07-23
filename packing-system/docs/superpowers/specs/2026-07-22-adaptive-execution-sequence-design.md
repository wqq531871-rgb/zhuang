# Adaptive Execution Sequence Design

## Goal

Keep the final packing layout unchanged while making the robot execution order predictable and safer:

- use layerwise execution for regular or sparsely mixed pallets;
- use staircase execution only for pallets with frequent height transitions inside a geometric layer;
- scan each comparable execution band from the configured origin by X column and then Y;
- in a staircase wave, place lower outer foundations before a higher inner box in the same wave phase;
- preserve support, vertical descent, suction descent, open-direction, and final replay gates.

## Mode Classification

Group boxes into geometric layers by physical bottom Z using the numeric coordinate tolerance. Within each layer, build side-adjacency edges using the configured side-neighbor clearance and positive overlap on the orthogonal axis.

An adjacency edge is a significant height transition when the two physical top heights differ by at least `staircase_height_difference_threshold_mm`. A pallet uses staircase execution only when at least one layer has both:

- at least `staircase_min_transition_edges` significant transition edges; and
- `significant_edges / all_adjacency_edges >= staircase_transition_ratio_threshold`.

The initial values are four edges and a ratio of 0.25. On the current 668-box fixture this selects pallet 11 only.

## Origin Scan

For `x_min_y_min`, comparable boxes are ordered by X column and then increasing Y. Other configured origins transform X and Y to progress away from that corner before applying the same rule. X coordinates within `scan_column_tolerance_mm` belong to one anchored column; clustering must not chain distant coordinates through intermediate values. The initial tolerance is 5 mm because mixed footprints in the real layout shift an intended column by that amount.

The scan order is the strongest scheduling preference after hard dependency eligibility. If the exact next scan box cannot be selected without violating support, descent, or open-direction constraints, the planner selects the closest later safe candidate and resumes the scan. Such a deviation is deterministic and logged; it is never a random global reorder.

## Staircase Frontier

Derive a vertical support tier from the support DAG instead of dividing Z by the smallest box height. The horizontal shell remains the footprint BFS distance from the configured origin.

Use:

```text
phase = horizontal_shell + support_tier
```

Within one phase, lower support tiers precede higher support tiers. Within the same phase and tier, use the origin X-column/Y scan. This keeps the staircase wave but ensures an outer lower foundation in the same phase is placed before an inner upper box.

## Output And Failure Behavior

The original packing report and relative box layout remain unchanged. Execution JSON, WCS cases, and WCS map continue to use the single `seq` field. `stack_height_before` is recomputed from the final order and retained only in execution JSON; it is not part of WCS cases or WCS map.

Planning diagnostics record the selected mode, trigger layer, transition counts and ratio, and any necessary scan deviations. Diagnostics are logs, not new WCS fields.

If no order satisfies the existing hard gates, execution publishing fails through the existing error path; safety constraints are not relaxed.

## Acceptance Criteria

- The 668-box input remains 11 pallets and 668 boxes with continuous unique `seq` values.
- Only pallet 11 selects staircase mode.
- Pallet 6 starts with box `569`; pallet 8 starts with box `578`.
- On pallet 11, box `644` precedes box `324`.
- All support, box descent, suction descent, open-direction, centered-layout, and replay checks pass.
- Execution JSON, WCS cases, and WCS map agree on every `seq`; only execution JSON contains `stack_height_before`.
