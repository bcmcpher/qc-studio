# Configuration

QC-Studio takes three separate inputs:

- **Command-line flags** set the dataset, participants, pipeline, output location and starting options.
- **`qc.json`** defines each QC task: which files and panels to show for every QC record.
- **In-app settings on the landing page** record rater information and display choices. Two of them,
  the QC task and the default rating, replace the `--qc_task` and `--default_qc_rating` flags for the
  rest of the session.

## Command-line reference

QC-Studio is launched by running the script under `streamlit run`

```bash
streamlit run ui/main.py --server.port=8501 -- [flags]
```

You can also read the built-in help with `python ui/main.py --help`.

### Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--dataset_dir` | yes | — | Path to the dataset root. **Every relative path inside `qc.json` resolves against this directory.** |
| `--participant_list` | yes | — | Path to a TSV listing the participants to QC. See [Participant list](#participant-list-tsv). |
| `--qc_pipeline` | yes | — | Pipeline name being reviewed. Recorded in the exported `pipeline` column; also used in checkpoint/session file names. |
| `--qc_task` | yes | — | One QC task key from `qc.json`, **or the literal value `all`** to show every task on one scrollable page. See [One task or all of them](#one-task-or-all-of-them). |
| `--output_dir` | yes | — | Directory for results and checkpoints. Created on demand. |
| `--qc_json` | yes | — | Path to the QC configuration JSON describing what to display. |
| `--session_list` | see [Session labels](#session-labels) | `null` | Comma-separated BIDS session labels, for example `ses-01,ses-02`, or `none` if the dataset has no sessions. |
| `--rater_id` | no | `null` | Rater name or ID used to pre-fill the landing page. |
| `--default_qc_rating` | no | `PASS` | Rating preselected on unrated pages: `PASS`, `FAIL`, `UNCERTAIN` or `None`. See [Default rating](ratings.md#default-rating). |

Everything else is configured through `qc.json` or the landing page.

## Participant list (TSV)

A tab-separated file whose first column is `participant_id`.

```text
participant_id
sub-CMH0001
sub-CMH0002
sub-CMH0003
```

Notes:

- The `participant_id` column is **required**.
- IDs may be written with or without the `sub-` prefix; QC-Studio normalizes them to include it.

### Session labels

The participant list file can include a `session_id` column:

```text
participant_id	session_id
sub-CMH0001	ses-01
sub-CMH0001	ses-02
```

Otherwise, session labels must be specified via the `--session_list` flag
(for example `--session_list ses-01,ses-02`). Each participant is then combined with each session.

Sessions are not discovered automatically. If the dataset has no session level,
pass `--session_list none`; QC-Studio then shows one page per participant with no session.

## QC-task-config

### Structure

`qc.json` is a JSON **object** with QC tasks as top-level keys and task display configuration as values.

```json
{
  "fmriprep_anat_qc": {
    "display_name": "fMRIPrep anatomical preproc workflow",
    "base_mri_image_path": "derivatives/fmriprep/[[NIPOPPY_BIDS_PARTICIPANT_ID]]/[[NIPOPPY_BIDS_SESSION_ID]]/anat/[[NIPOPPY_BIDS_PARTICIPANT_ID]]_[[NIPOPPY_BIDS_SESSION_ID]]_run-1_desc-preproc_T1w.nii.gz",
    "overlay_mri_image_path": "derivatives/fmriprep/[[NIPOPPY_BIDS_PARTICIPANT_ID]]/[[NIPOPPY_BIDS_SESSION_ID]]/anat/[[NIPOPPY_BIDS_PARTICIPANT_ID]]_[[NIPOPPY_BIDS_SESSION_ID]]_run-1_desc-brain_mask.nii.gz",
    "montage_path": "derivatives/fmriprep/[[NIPOPPY_BIDS_PARTICIPANT_ID]]/figures/[[NIPOPPY_BIDS_PARTICIPANT_ID]]_[[NIPOPPY_BIDS_SESSION_ID]]_run-1_space-MNI152NLin2009cAsym_T1w.svg",
    "iqm_path": [
      "derivatives/mriqc/group_T1w.tsv"
    ],
    "rating": {
      "type": "multi",
      "scale": ["PASS", "FAIL", "UNCERTAIN"],
      "facets": ["Cropped", "Aliasing", "Motion", "Susceptibility", "Ringing", "Registration"]
    }
  }
}
```

```{note}
`[[NIPOPPY_BIDS_PARTICIPANT_ID]]` and `[[NIPOPPY_BIDS_SESSION_ID]]` are substitution variables.
You write each path once as a template, and QC-Studio fills in the participant and session of
every QC record as it iterates through the [participant list](#participant-list-tsv) and
[session labels](#session-labels). For example, with `sub-CMH0001` and `ses-02`, the
`base_mri_image_path` above resolves to
`derivatives/fmriprep/sub-CMH0001/ses-02/anat/sub-CMH0001_ses-02_run-1_desc-preproc_T1w.nii.gz`.
See [Path substitutions](#path-substitutions) for details.
```

The schema is defined by the `QCTask` model in [`ui/models/qc_models.py`](https://github.com/nipoppy/qc-studio/blob/main/ui/models/qc_models.py).

### Task fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `display_name` | string | no | Human-readable label shown in the UI. Falls back to the key when absent. |
| `base_mri_image_path` | path | no | Base MRI for the 3D MRI panel (NiiVue viewer). Glob patterns allowed. |
| `overlay_mri_image_path` | path | no | Overlay drawn on top of the base MRI. One overlay maximum. |
| `montage_path` | path or list of paths | no | 2D montage images for the Montage panel: **SVG, PNG, JPG/JPEG only**. |
| `iqm_path` | path or list of paths | no | IQM sources: TSV/CSV distribution tables or JSON metric files, one entry per pipeline source. |
| `rating` | object | no | Rating scheme for the task. See [Rating fields](#rating-fields). |

### Rating fields

The optional `rating` object sets how a task is rated (see [Rating schemes](ratings.md)).

| Field | Description | Default |
|-------|-------------|---------|
| `type` | `"single"` or `"multi"` | `"single"` |
| `scale` | The rating options offered (shared by all facets) | `["PASS", "FAIL", "UNCERTAIN"]` |
| `facets` | The facet names to rate (used when `type` is `"multi"`) | none |

If `type` is `"multi"` but no facets are listed, the task falls back to a single rating.
See the [example above](#structure) for a multi-facet task.

### Path substitutions

Placeholders in `qc.json` are textually replaced with values known for the current QC record
**before** Pydantic validation runs.

| Placeholder | Replaced with | Example |
|-------------|---------------|---------|
| `[[NIPOPPY_BIDS_PARTICIPANT_ID]]` | The normalized participant ID, including `sub-` | `sub-CMH0001` |
| `[[NIPOPPY_BIDS_SESSION_ID]]` | The BIDS session label | `ses-02` |

### One task or all of them

`qc.json` can define several tasks. Use `--qc_task` to select the one to start with;
you can switch to another task from the landing page sidebar.

Setting `--qc_task all` puts every task on one page.

## In-app settings

These are set on the landing page and stored in the Streamlit session, not on disk. They do not
persist across browser sessions.

### Rater information

| Field | Values | Written to |
|-------|--------|------------|
| Rater name or ID | Free text | `rater_id` |
| QC experience level | `Beginner (< 1 year)`, `Intermediate (1-5 years)`, `Expert (>5 years)` | `rater_experience` |
| Fatigue level | `Not at all`, `A bit tired ☕`, `Very tired ☕☕` | `rater_fatigue` |
| Screen size (diagonal, inches) | `14 or less`, `15-20`, `21-25`, `26-30`, `31 or above`, `Unknown` | `rater_screen_size` |
| [Autoplay](autoplay.md) duration | Seconds | Nowhere |

### QC task and default rating

The landing page sidebar also lets you:

- choose which QC task to rate
- choose the [default rating](ratings.md#default-rating) preselected on unrated pages

### Display panels

Select which panel(s) are active.

| Panel | Default | Contents |
|-------|---------|----------|
| **3D MRI (Niivue)** | on | Interactive 3D rendering of a base NIfTI (and optional overlay) in the NiiVue viewer |
| **Montage** | on | 2D image montage for the task |
| **QC Metrics** | off | IQM distribution plots and a metrics table |

### Montage grid

**Montage Grid Settings** lets you set maximum rows and columns (1–10).
Choosing **Auto-calculate** will derive a near-square layout from the number of images.

### Saving your work

| Action | Output | Where it lands |
|--------|--------|----------------|
| **🏁 Create checkpoint** | Checkpoint: a periodic snapshot of your work with a unique timestamp (never overwritten) | `<output_dir>/checkpoints/<rater>_<pipeline>_<task>_checkpoint_<timestamp>.tsv` |
| **💾 Export Final Results** | QC status TSV: the final QC ratings file (overwritten on user confirmation) | Anywhere you choose; defaults to `<output_dir>/<rater>_<pipeline>_<task>_qc_status.tsv` |

## Exported results (TSV)

Results are tab-separated with a header row. Columns always appear in this order:

| # | Column | Meaning |
|---|--------|---------|
| 1 | `pipeline` | Value of `--qc_pipeline` |
| 2 | `qc_task` | QC task key |
| 3 | `participant_id` | BIDS participant ID, with `sub-` prefix |
| 4 | `session_id` | Session label, or empty for datasets without sessions |
| 5 | `task_id` | Reserved; usually empty |
| 6 | `run_id` | Reserved; usually empty |
| 7 | `timestamp` | `YYYY-MM-DD HH:MM:SS` when the rating was recorded |
| 8 | `rater_id` | Normalized rater ID |
| 9 | `rater_experience` | Rater experience level |
| 10 | `rater_fatigue` | Rater fatigue level |
| 11 | `rater_screen_size` | Rater monitor size band |
| 12 | `final_qc` | QC rating (for multi-facet tasks, the [overall rating](ratings.md#multi-facet-rating-interface)) |
| 13 | `facet` | Facet name; empty for single-rating tasks |
| 14 | `rating_value` | Rating for that facet; empty for single-rating tasks |
| 15 | `notes` | Free text |

For [multi-facet tasks](ratings.md), each facet is written as its own row.

### Resuming a session

Upload a previous `<rater>_<pipeline>_<task>_qc_status.tsv` (CSV and TSV are both accepted) from the landing page.

## See also

- [Quickstart](../overview/quickstart.md) — the flags in context, running a demo.
- [Rating schemes](ratings.md) — single and multi-facet ratings.
- [Autoplay](autoplay.md) — the timed auto-advance settings.
- [Software Architecture](../development/architecture.md) — where each configuration value is read in the code.
