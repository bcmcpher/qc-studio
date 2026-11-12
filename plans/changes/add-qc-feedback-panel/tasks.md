## 1. Configuration

- [ ] 1.1 Add optional `feedback_path` to `QCTask` in `ui/models/qc_models.py`; placeholders resolve through `parse_qc_config`
- [ ] 1.2 Add `--feedback_mode {shown,after_rating}` (default `shown`) to `parse_args` in `ui/main.py`; pass it through `get_cli_run_context` and `SessionManager`
- [ ] 1.3 Add `feedback` to `DEFAULT_PANELS` (on) and `PANEL_CONFIG` in `ui/constants.py`
- [ ] 1.4 Tests: config with and without `feedback_path` parses; placeholders resolve; flag default and both values parse

## 2. Panel component — `ui/components/feedback_viewer.py`

- [ ] 2.1 Load `feedback.json` through `ui/evidence_bundle/feedback.py` with `@st.cache_data` keyed on path and mtime
- [ ] 2.2 Render decision, confidence, summary, reasons, flagged metrics, image observations, model id, timestamp, "advisory" label; HTML disabled
- [ ] 2.3 Handle missing file, unreadable file, `schema_valid` false, and non-empty `consistency_errors`
- [ ] 2.4 Warn when `bundle.json` is newer than `feedback.json`
- [ ] 2.5 In `after_rating` mode, show a placeholder until the scan has a non-default rating
- [ ] 2.6 Tests with fixture files and `mock_streamlit` from `ui/tests/conftest.py`

## 3. Feedback rating and export

- [ ] 3.1 Add `feedback_shown`, `feedback_model_id`, `feedback_rating`, `feedback_notes` to `QCRecord` and to the column list in `ui/utils/export.py`
- [ ] 3.2 Add the feedback rating control (`agree`, `partial`, `disagree`) and notes to the panel; save through `_record_qc_for_current_participant`
- [ ] 3.3 Track per task whether panel content was rendered before the scan rating was saved
- [ ] 3.4 Tests: new columns written; empty when no feedback configured; an existing TSV without the columns merges; scan rating unchanged by feedback content

## 4. Page integration — `ui/components/qc_viewer.py`

- [ ] 4.1 Add the panel branch in `display_qc_viewers` and the right column of `_display_niivue_with_secondary_panel`, above the rating controls
- [ ] 4.2 Tests: panel hidden when toggled off or when no task has `feedback_path`; layout tests in `test_qc_viewer_panel_layout.py` still pass
- [ ] 4.3 Manual check with `sample_data/` plus a fixture `feedback.json`, in both feedback modes

## 5. Docs

- [ ] 5.1 Document `feedback_path` in `docs/source/guides/configuration.md` and `--feedback_mode` with the other CLI flags
- [ ] 5.2 Document the new TSV columns and the feedback rating scale in `docs/source/guides/ratings.md`
- [ ] 5.3 Short guide section: produce feedback offline, then enable the panel; state the data-use caveat for cloud models
