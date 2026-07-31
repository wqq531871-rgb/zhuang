# Manual 4.5 Reqpallet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual 4.5 pallet-completion sender to the existing interface-maintenance dialog, using the latest 4.6 physical pallet data and the currently executing `box_unique_id`.

**Architecture:** Persist every accepted 4.6 request to one atomic runtime state file. The UI reads that state plus `live_stack_command.json`, loads the selected pallet's full carton rows from `wcs_success_box`, converts them to the exact 4.5 schema, previews the association, and sends only after an explicit operator confirmation.

**Tech Stack:** Python 3, PyQt5, requests, YAML configuration, pytest.

## Global Constraints

- `pallet_code`, `robot_id`, and `station_id` come from the latest 4.6 request.
- `box_unique_id` defaults from the current live-stack command and remains editable.
- A completed physical pallet sends `empty_flag=false` with populated `case_data`.
- Tests must never contact the real WCS URL.
- Existing 4.7 behavior and its disabled per-second JSON logging must remain unchanged.

---

### Task 1: Persist and read the latest 4.6 pallet

**Files:**
- Create: `src/service/pallet_arrival_store.py`
- Create: `packing/src/service/pallet_arrival_store.py`
- Modify: `local_wcs_receiver/app/handlers.py`
- Test: `tests/test_pallet_arrival_store.py`
- Test: `tests/test_wcs_receiver_status_logging.py`

**Interfaces:**
- Produces: `write_latest_pallet_arrival(body, workspace=None) -> dict`
- Produces: `read_latest_pallet_arrival(workspace=None) -> dict`
- Consumes: the 4.6 JSON request body.

- [ ] Write failing tests proving an atomic runtime record contains `robot_id`, `station_id`, `pallet_code`, `case_type`, and a receive timestamp.
- [ ] Run those tests and confirm failure because the store and handler integration do not exist.
- [ ] Implement the focused store, its packing bridge, and call it from `handle_palletarrive`.
- [ ] Run the focused tests and confirm both 4.6 persistence and existing 4.7 logging behavior pass.

### Task 2: Build and send the exact 4.5 payload

**Files:**
- Modify: `packing/src/service/wcs_service.py`
- Modify: `config/packing_config.yaml`
- Test: `tests/test_wcs_reqpallet.py`

**Interfaces:**
- Produces: `build_reqpallet_payload(arrival: dict, wcs_case: dict, empty_flag: bool = False) -> dict`
- Produces: `push_reqpallet(base_url: str, payload: dict, reqpallet_path: str, timeout: int = 30) -> dict`
- Produces: `DataSourceConfig.reqpallet_url() -> str` using `/api/wcs/reqpallet`
- Consumes: one case returned by `build_wcs_cases_for_unique_ids`.

- [ ] Write failing tests proving `case_data` contains layers and only the documented carton fields `length`, `width`, `height`, and `product_code`.
- [ ] Write failing tests proving `empty_flag=false`, the 4.6 identifiers are retained, blank 4.6 `case_type` falls back to the selected WCS case, and a nonzero WCS response raises an error.
- [ ] Run the tests and confirm failure because the builder, path, and sender do not exist.
- [ ] Implement the minimal configuration field, payload builder, and HTTP sender.
- [ ] Run the focused tests and confirm they pass using a mocked HTTP response.

### Task 3: Add the manual 4.5 section to interface maintenance

**Files:**
- Modify: `ui/wcs_api_maintain_dialog.py`
- Test: `ui/tests/test_wcs_api_maintain_dialog.py`

**Interfaces:**
- Consumes: latest 4.6 state, `runtime/live_stack_command.json`, `get_success_box_repo`, `build_reqpallet_payload`, and `push_reqpallet`.
- Produces: an operator-facing preview and a separate `发送4.5码垛完成` button.

- [ ] Write failing UI tests proving the latest 4.6 pallet code and current command `box_unique_id` are prefilled.
- [ ] Write a failing UI test proving clicking send builds `empty_flag=false`, displays layer/carton counts, confirms the target, and invokes an injected sender without closing the dialog.
- [ ] Run the tests and confirm failure because the controls and send workflow do not exist.
- [ ] Implement the compact 4.5 group, refresh/preview behavior, validations, confirmation, result message, and request snapshot logging.
- [ ] Run the focused UI tests and confirm they pass without a real network call.

### Task 4: Regression verification

**Files:**
- Verify all files changed in Tasks 1–3.

**Interfaces:**
- Consumes: the complete implementation.
- Produces: fresh evidence that receiver, service, import switching, and UI behavior remain compatible.

- [ ] Run the new 4.5 tests plus existing receiver status and WCS import-switching tests.
- [ ] Run Python compilation for every changed Python file.
- [ ] Inspect `git diff` to ensure unrelated dirty files are untouched and no real request was sent.
- [ ] Compare the final payload field-by-field with interface document section 4.5.
