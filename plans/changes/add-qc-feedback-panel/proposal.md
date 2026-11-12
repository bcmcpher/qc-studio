## Why

[#13](https://github.com/nipoppy/qc-studio/issues/13) asks for model-written descriptions of
image quality next to the images a rater reviews. After `add-model-feedback`, each scan can
have a validated `feedback.json`, but raters cannot see it in QC-Studio. This change shows
precomputed model feedback as an optional, advisory panel on the QC review page.

## What Changes

- New optional `qc.json` task key for the location of `feedback.json`, with the existing
  placeholder substitution.
- New toggleable "Model feedback" panel on the review page, off by default.
- The panel shows decision, confidence, summary, reasons, flagged metrics, image observations,
  model id and validation status, with an "advisory" label.
- Missing, unreadable or invalid feedback shows a short notice; the rest of the page works.
- The app never calls a model, and model output never sets or pre-fills a rating.
- `*_qc_status.tsv` columns stay unchanged.

## Capabilities

### New Capabilities

- `qc-viewer-feedback`: display precomputed model feedback on the QC review page.

### Modified Capabilities

- None. (QC-Studio's existing UI behaviour has no spec in `plans/specs/` yet; the new optional
  `qc.json` key is covered by the new capability.)

## Impact

- `ui/models/qc_models.py`: optional `feedback_path` on `QCTask`.
- `ui/constants.py`: `PANEL_CONFIG` and `DEFAULT_PANELS` entries.
- `ui/components/qc_viewer.py`: panel branch in `display_qc_viewers` and the right column of
  `_display_niivue_with_secondary_panel`.
- New `ui/components/feedback_viewer.py`; reads files through `ui/evidence_bundle/feedback.py`.
- Tests in `ui/tests/`; docs for the `qc.json` key in `docs/source/guides/configuration.md`.
- Depends on the `QCFeedback`/`FeedbackResult` schema from `add-model-feedback`. Can be built
  against a fixture `feedback.json` while `add-feedback-evaluation` runs.
