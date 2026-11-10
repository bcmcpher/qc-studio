# Sample data

Bundled examples use a **BIDS community-standard** layout. Point **`--dataset_dir`** at **`sample_data/`** with configs in **`pipelines/<pipeline>/qc.json`**.

```
sample_data/
├── bids/sub-CMH0001/ses-*/func/          # reference BOLD (first-volume demo)
└── derivatives/
    ├── fmriprep/sub-CMH0001/             # figures/ + ses-*/anat/
    ├── fmriprep/23.1.3/output/sub-ED01/  # legacy demo
    ├── qsiprep/sub-CMH0001/figures/
    ├── xcpd/sub-CMH0001/figures/
    └── noddireg/sub-CMH0001/
```

Launch: **`ui/fmriprep_test.sh`**, **`ui/freesurfer_test.sh`**, **`ui/qsiprep_test.sh`**, **`ui/xcpd_test.sh`**, **`ui/noddireg_test.sh`**.

Flat / project-specific pipeline shares (non-BIDS `--dataset_dir` roots) are documented in the upstream pipeline bundle — see [GhazalehManj/qc-studio](https://github.com/GhazalehManj/qc-studio) for a full flat-layout reference.

## Participant lists

| File | Use |
|------|-----|
| `qc_participants.tsv` | `sub-CMH0001` — bundled demos |
| `qc_participants_demo.tsv` | `sub-ED01` — `fmriprep_demo.sh` |
