# fMRIPrep QC configuration

QC-Studio loads **only** `qc.json` from this folder. Run `streamlit run ui/main.py …` from the repository root, or use **`fmriprep_demo.sh`** (repo root) / **`ui/fmriprep_test.sh`** (from `ui/`) for the same defaults.

Example (BIDS dataset root):

```bash
streamlit run ui/main.py --server.port=8501 -- \
  --qc_json ../pipelines/fmriprep/qc.json \
  --qc_task sdc_wf_qc \
  --qc_pipeline fmriprep \
  --dataset_dir sample_data \
  --participant_list sample_data/qc_participants.tsv \
  --session_list ses-01,ses-02 \
  --output_dir ./output
```

Paths inside `qc.json` are relative to **`--dataset_dir`**. The bundled config uses **`bids/<subject>/<session>/func/`** for reference BOLD and **`derivatives/fmriprep/<subject>/figures/`** for QC montages. See [`sample_data/README.md`](../../sample_data/README.md).

Legacy **`sub-ED01`** demo: **`qc_demo.json`** + **`fmriprep_demo.sh`**.

For a **flat per-pipeline share** (non-BIDS layout), see [GhazalehManj/qc-studio](https://github.com/GhazalehManj/qc-studio).

See [fMRIPrep QC guidelines](https://github.com/TIGRLab/SCanD_project/blob/Fir/docs/fmriprep_QC_guidelines.md) (SCanD_project) for pass/fail criteria.
