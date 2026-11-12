## 1. Configuration

- [ ] 1.1 Add optional `feedback_path` to `QCTask` in `ui/models/qc_models.py`; placeholders resolve through `parse_qc_config`
- [ ] 1.2 Add `feedback` to `DEFAULT_PANELS` (off) and `PANEL_CONFIG` in `ui/constants.py`
- [ ] 1.3 Tests: config with and without `feedback_path` parses; placeholders resolve

## 2. Panel component — `ui/components/feedback_viewer.py`

- [ ] 2.1 Load `feedback.json` through `ui/evidence_bundle/feedback.py` with `@st.cache_data` keyed on path and mtime
- [ ] 2.2 Render decision, confidence, summary, reasons, flagged metrics, image observations, model id, timestamp, "advisory" label
- [ ] 2.3 Handle missing file, unreadable file, `schema_valid` false, and non-empty `consistency_errors`
- [ ] 2.4 Warn when `bundle.json` is newer than `feedback.json`
- [ ] 2.5 Tests with fixture files and `mock_streamlit` from `ui/tests/conftest.py`

## 3. Page integration — `ui/components/qc_viewer.py`

- [ ] 3.1 Add the panel branch in `display_qc_viewers` and the right column of `_display_niivue_with_secondary_panel`, above the rating controls
- [ ] 3.2 Confirm no rating callback reads feedback; `*_qc_status.tsv` columns unchanged
- [ ] 3.3 Tests: panel hidden when toggled off or when no task has `feedback_path`; layout tests in `test_qc_viewer_panel_layout.py` still pass
- [ ] 3.4 Manual check with `sample_data/` plus a fixture `feedback.json`

## 4. Docs

- [ ] 4.1 Document `feedback_path` in `docs/source/guides/configuration.md`
- [ ] 4.2 Short guide section: produce feedback offline, then enable the panel; state the data-use caveat for cloud models
