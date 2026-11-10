# QSIPrep QC configuration

QC-Studio loads **only** `qc.json` from this folder. Run `streamlit run ui/main.py …` from the repository root, or use **`ui/qsiprep_test.sh`** (from `ui/`) for the same defaults.

Example (after `cd` to the qc-studio root):

```bash
streamlit run ui/main.py --server.port=8501 -- \
  --qc_json ../pipelines/qsiprep/qc.json \
  --qc_task seg_brainmask_qc \
  --qc_pipeline qsiprep \
  --dataset_dir sample_data \
  --participant_list sample_data/qc_participants.tsv \
  --session_list ses-01,ses-02 \
  --output_dir ./output
```

Use **`--session_list`** with comma-separated BIDS session labels (e.g. `ses-01,ses-02`). The app builds one review **page** per **(participant × session)** from your participant list. If `qc_participants.tsv` includes a **`session_id`** column, that file defines the exact rows instead (one row per participant–session pair).

### Multiple tasks in `qc.json` (`seg_brainmask_qc`, `t1_2_mni_qc`, `sdc_wf_qc`, `coreg_wf_qc`)

See [QSIPrep QC guidelines](https://github.com/TIGRLab/SCanD_project/blob/Fir/docs/qsiprep_QC_guidelines.md) (SCanD_project) for pass/fail criteria. `qc.json` defines **four** tasks matching the doc panels.

`qc.json` can define **several** tasks. You choose how to run QC-Studio:

- **One task per run** (default): pass the task key with **`--qc_task`** (e.g. `seg_brainmask_qc`). The UI does not switch tasks mid-session.
- **All tasks on one scrollable page**: use **`--qc_task all`**. Each cohort page gets a PASS / FAIL / UNCERTAIN (and notes) **per task**, and the sidebar marks a page complete only when **every** task in `qc.json` has a decided rating.

Examples:

- From `ui/` with **`qsiprep_test.sh`**: `./qsiprep_test.sh ../pipelines/qsiprep/qc.json sdc_wf_qc`, or `./qsiprep_test.sh ../pipelines/qsiprep/qc.json all`, or set **`QC_TASK=all ./qsiprep_test.sh`**.

Paths inside `qc.json` are relative to **`--dataset_dir`**. Use **`[[NIPOPPY_BIDS_PARTICIPANT_ID]]`** and **`[[NIPOPPY_BIDS_SESSION_ID]]`** where filenames include those entities. For QSIPrep’s internal workflow slug (`dwi_denoise_ses_01_…`), use **`[[NIPOPPY_QSIPREP_SESSION_SLUG]]`** (underscore form, e.g. `ses_02` for BIDS `ses-02`).

Sample data lives under **`sample_data/qsiprep/<subject>/figures/`**. The shipped `qc.json` targets **`acq-multishelldir92`** and **`run-1`**.
