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
- Ratings are saved by `_record_qc_for_current_participant` → `_save_qc_record` →
  `save_qc_results_to_csv` (`ui/utils/export.py`), which drops any column not in its list.
- The IQM panel degrades on load errors with `st.error` (`ui/components/iqm_viewer.py`, around
  `_display_iqm_panel` at line 714).

## Goals / Non-Goals

**Goals:**

- Raters can read model feedback beside the images, when a project provides it.
- Raters judge the feedback, and the judgement is saved with the scan rating.
- The export records whether feedback was in view for each rating.
- No effect on the review page for projects that do not configure feedback.
- Model output cannot change a stored scan rating.

**Non-Goals:**

- Calling models from the app, API keys in the app, or a "run model" button.
- Pre-filling ratings or bulk-accepting model decisions.
- Highlighting flagged metrics inside the IQM panel (possible follow-up).

## Decisions

- **Precomputed files only.** The app reads `feedback.json`. Model runs happen offline with
  `run_feedback.py`. This keeps secrets, GPUs and latency out of Streamlit and keeps the panel
  testable with fixtures.
- **Path from `qc.json`.** Optional `feedback_path` per task, using the same placeholders as
  `iqm_path`. Alternative: a CLI flag pointing at a bundle tree; rejected as a second location
  mechanism.
- **Display mode is a CLI flag.** `--feedback_mode shown|after_rating`, beside
  `--default_qc_rating`, because it is a property of the rating session, not of the dataset.
  Default `shown`: the current study rates the feedback itself, so raters see it from the start.
  In `after_rating` the panel content appears once the scan has a rating other than the default.
- **Panel on when feedback is configured.** `DEFAULT_PANELS["feedback"]` is true, but the
  panel renders only for tasks with `feedback_path`. Rating the feedback is the point of the
  current study; hiding it by default would lose ratings.
- **Fixed feedback rating scale.** `agree` (feedback correct and complete), `partial` (some
  reasons wrong or missing), `disagree` (decision wrong). Plus free-text notes. A configurable
  scale can follow if the study needs one.
- **Export columns in the existing TSV.** `feedback_shown` (bool), `feedback_model_id`,
  `feedback_rating`, `feedback_notes`, added to the column list in `ui/utils/export.py`. They
  repeat on each facet row, like `final_qc`. Empty when no feedback is configured. Alternative:
  a separate feedback TSV; rejected because "was feedback shown" must sit beside the rating it
  qualifies. Existing files without the columns merge with empty values.
- **`feedback_shown` semantics.** True when the panel content was rendered for that task
  before the scan rating was saved. In `after_rating` mode it is false for the first save and
  true for later edits.
- **Validation status visible.** If `schema_valid` is false the panel shows only "invalid
  feedback" and no feedback rating control; if `consistency_errors` is non-empty it shows the
  feedback with a warning listing them.
- **Separate component module.** `ui/components/feedback_viewer.py`, mirroring
  `iqm_viewer.py`, so `qc_viewer.py` gains only a branch.
- **Cached load.** `@st.cache_data` keyed on path and mtime, like the IQM tables.

## Risks / Trade-offs

- [Anchoring: raters copy the model] → `after_rating` mode; `feedback_shown` lets analysis
  separate the two conditions.
- [New TSV columns break downstream readers that expect exact columns] → document in the
  ratings guide; columns are appended at the end.
- [Stale feedback after re-export] → show the bundle schema version and feedback timestamp;
  warn when the bundle file is newer than the feedback.
- [Unvalidated model text in the UI] → render with HTML disabled.

## Open Questions

- Ship the panel for all projects after `add-feedback-evaluation`, or keep it study-only?
