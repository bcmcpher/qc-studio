# NODDIreg QC configuration

QC-Studio loads **only** `qc.json` from this folder. Run `streamlit run ui/main.py …` from the repository root, or use **`ui/noddireg_test.sh`** from `ui/`.

Example (BIDS dataset root):

```bash
streamlit run ui/main.py --server.port=8501 -- \
  --qc_json ../pipelines/noddireg/qc.json \
  --qc_task noddireg_density \
  --qc_pipeline noddireg \
  --dataset_dir sample_data \
  --participant_list sample_data/qc_participants.tsv \
  --session_list ses-01,ses-02 \
  --output_dir ./output
```

Bundled demo: **`sub-CMH0001`** only under **`sample_data/derivatives/noddireg/`**. See [`sample_data/README.md`](../../sample_data/README.md).

For flat / project-specific layouts (e.g. SCanD CMH), see [GhazalehManj/qc-studio](https://github.com/GhazalehManj/qc-studio).

See [NODDIreg QC guidelines](https://github.com/TIGRLab/SCanD_project/blob/Fir/docs/noddireg_QC_guidelines.md) (SCanD_project) for pass/fail criteria.
