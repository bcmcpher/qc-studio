# XCP-D QC configuration

QC-Studio loads **only** `qc.json` from this folder. Run `streamlit run ui/main.py …` from the repository root or use **`ui/xcpd_test.sh`** (from `ui/`) for the same defaults.

Example (after `cd` to the qc-studio root):

```bash
streamlit run ui/main.py --server.port=8501 -- \
  --qc_json ../pipelines/xcpd/qc.json \
  --qc_task atlas_coverage_qc \
  --qc_pipeline xcpd \
  --dataset_dir sample_data \
  --participant_list sample_data/qc_participants.tsv \
  --session_list ses-01 \
  --output_dir ./output
```

Use **`--session_list`** with comma-separated BIDS session labels (e.g. `ses-01`). The app builds one review **page** per **(participant × session)** from your participant list. If `qc_participants.tsv` includes a **`session_id`** column, that file defines the exact rows instead (one row per participant–session pair).

### Multiple tasks in `qc.json` (`atlas_coverage_qc`, `coreg_wf_qc`, `denoised_bold_qc`)

See [XCP-D QC guidelines](https://github.com/TIGRLab/SCanD_project/blob/Fir/docs/xcpd_QC_guidelines.md) (SCanD_project) for pass/fail criteria. `qc.json` defines **three** tasks matching the doc panels.

`qc.json` can define **several** tasks. You choose how to run QC-Studio:

- **One task per run** (default): pass the task key with **`--qc_task`** (e.g. `atlas_coverage_qc`). The UI does not switch tasks mid-session.
- **All tasks on one scrollable page**: use **`--qc_task all`**. Each cohort page gets a PASS / FAIL / UNCERTAIN (and notes) **per task**, and the sidebar marks a page complete only when **every** task in `qc.json` has a decided rating.

Examples:

- From `ui/` with **`xcpd_test.sh`**: `./xcpd_test.sh ../pipelines/xcpd/qc.json atlas_coverage_qc`, or `./xcpd_test.sh ../pipelines/xcpd/qc.json all`, or set **`QC_TASK=all ./xcpd_test.sh`**.

Paths inside `qc.json` are relative to **`--dataset_dir`**. Use **`[[NIPOPPY_BIDS_PARTICIPANT_ID]]`** and **`[[NIPOPPY_BIDS_SESSION_ID]]`** where filenames include those entities.

Sample data lives under **`sample_data/xcpd/<subject>/figures/`**.

**Atlas slices:** `atlas_coverage_qc` uses session-level T1 montages (`…_ses-XX_run-1_desc-Axial*_T1w.png`, etc.). The bundled sample ships **`ses-01`** only.

**Session-level BOLD QC:** `coreg_wf_qc` and `denoised_bold_qc` use `task-*_run-*` globs so each session page can include every task and run’s bbregister and ESQC figures.
