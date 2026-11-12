## Context

Review page layout (`ui/components/qc_viewer.py`):

- `display_qc_viewers` (line 252) branches on which of Niivue, montage and IQM panels are on,
  then calls `_display_qc_rating_for_task` (line 769) per task.
- `_display_niivue_with_secondary_panel` (line 363) splits into `[0.3, 0.7]` columns; the right
  column stacks montage and IQM panels.
- Panel toggles come from `DEFAULT_PANELS` / `PANEL_CONFIG` (`ui/constants.py:20-23`) and are
  drawn by `PanelLayoutManager.render_panel_header_with_controls`.
- Paths per task come from `QCTask` (`ui/models/qc_models.py:83`) with placeholders resolved by
  `parse_qc_config` (`ui/utils/config.py`).
- The IQM panel degrades on load errors with `st.error` (`ui/components/iqm_viewer.py`, around
  `_display_iqm_panel` at line 714).

## Goals / Non-Goals

**Goals:**

- Raters can read model feedback beside the images, when a project provides it.
- Zero effect on projects that do not configure it.
- Model output cannot change a stored rating.

**Non-Goals:**

- Calling models from the app, API keys in the app, or a "run model" button.
- Pre-filling ratings or bulk-accepting model decisions.
- Highlighting flagged metrics inside the IQM panel (possible follow-up).

## Decisions

- **Precomputed files only.** The app reads `feedback.json`. Model runs happen offline with
  `run_feedback.py`. This keeps secrets, GPUs and latency out of Streamlit and keeps the panel
  testable with fixtures.
- **Path from `qc.json`.** Optional `feedback_path` per task, using the same placeholders as
  `iqm_path`. Consistent with how every other per-scan file is located. Alternative: a CLI
  flag pointing at a bundle tree; rejected as a second location mechanism.
- **Off by default.** `DEFAULT_PANELS["feedback"] = False`. Projects opt in per session.
- **Validation status visible.** If `schema_valid` is false the panel shows only "invalid
  feedback"; if `consistency_errors` is non-empty it shows the feedback with a warning listing
  them.
- **Separate component module.** `ui/components/feedback_viewer.py`, mirroring
  `iqm_viewer.py`, so `qc_viewer.py` gains only a branch.
- **Cached load.** `@st.cache_data` keyed on path and mtime, like the IQM tables.

## Risks / Trade-offs

- [Anchoring: raters copy the model] → off by default; see open question on blind mode.
- [Stale feedback after re-export] → show the bundle schema version and feedback timestamp;
  warn when the bundle file is newer than the feedback.
- [Unvalidated model text in the UI] → render text with `st.text`/`st.markdown` with HTML
  disabled.

## Open Questions

- Blind mode: show feedback only after the rater saves a rating?
- Record in the export whether feedback was shown (needs new `*_qc_status.tsv` column)?
- Ship enabled by default after `add-feedback-evaluation` results, or always opt-in?
