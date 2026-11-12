## Why

[#13](https://github.com/nipoppy/qc-studio/issues/13) asks for model-written descriptions of
image quality next to the images a rater reviews. After `add-model-feedback`, each scan can
have a validated `feedback.json`, but raters cannot see it in QC-Studio. The feedback is also
unproven: raters must judge the model's feedback as critically as the scan, and the project
must know which ratings were made with feedback in view. This change shows precomputed model
feedback on the QC review page, lets raters rate it, and records both in the export.

## What Changes

- New optional `qc.json` task key for the location of `feedback.json`, with the existing
  placeholder substitution.
- New toggleable "Model feedback" panel on the review page.
- New CLI flag `--feedback_mode` (`shown` or `after_rating`) that controls when the panel
  content appears. Default `shown`.
- The panel shows decision, confidence, summary, reasons, flagged metrics, image observations,
  model id and validation status, with an "advisory" label.
- A feedback rating control in the panel: `agree`, `partial` or `disagree`, plus notes.
- New `*_qc_status.tsv` columns: `feedback_shown`, `feedback_model_id`, `feedback_rating`,
  `feedback_notes`. **BREAKING** for tools that expect the exact current column set.
- Missing, unreadable or invalid feedback shows a short notice; the rest of the page works.
- The app never calls a model, and model output never sets or pre-fills the scan rating.

## Capabilities

### New Capabilities

- `qc-viewer-feedback`: display precomputed model feedback on the QC review page, rate it, and
  record its use in the QC export.

### Modified Capabilities

- None. (QC-Studio's existing UI and export behaviour has no spec in `plans/specs/` yet; the
  new `qc.json` key, CLI flag and export columns are covered by the new capability.)

## Impact

- `ui/main.py`: `--feedback_mode` in `parse_args`, passed through `get_cli_run_context`.
- `ui/models/qc_models.py`: optional `feedback_path` on `QCTask`; new fields on `QCRecord`.
- `ui/constants.py`: `PANEL_CONFIG` and `DEFAULT_PANELS` entries.
- `ui/components/qc_viewer.py`: panel branch in `display_qc_viewers` and the right column of
  `_display_niivue_with_secondary_panel`; feedback fields in `_record_qc_for_current_participant`.
- `ui/utils/export.py`: four new columns in the written TSV; old files without them still merge.
- New `ui/components/feedback_viewer.py`; reads files through `ui/evidence_bundle/feedback.py`.
- Tests in `ui/tests/`; docs in `docs/source/guides/configuration.md` and
  `docs/source/guides/ratings.md`.
- Depends on the `QCFeedback`/`FeedbackResult` schema from `add-model-feedback`. Can be built
  against a fixture `feedback.json` while `add-feedback-evaluation` runs.
