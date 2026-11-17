# Evidence bundle export

An **evidence bundle** is the QC evidence for one scan, in a form that does not depend on a model.
It holds the scan's IQMs with their statistical context, allowlisted acquisition metadata, 2D views and the rater's QC.
The export runs from the command line, without Streamlit.
For the design, see the [Evidence bundle design note](../development/evidence_bundle_design.md).

## Run the export

The export takes the same dataset, participant list and `qc.json` as QC-Studio.
It exports one QC task per run.

```bash
python ui/evidence_bundle/export.py \
  --dataset_dir sample_data \
  --participant_list sample_data/qc_participants.tsv \
  --session_list ses-01,ses-02 \
  --qc_json pipelines/fmriprep/qc.json \
  --qc_task anat_wf_qc \
  --qc_pipeline fmriprep \
  --out_dir evidence_bundles
```

| Option | Meaning |
|--------|---------|
| `--dataset_dir` | Dataset directory. The `qc.json` paths are relative to it. |
| `--participant_list` | TSV with a `participant_id` column, and optionally a `session_id` column. |
| `--session_list` | Comma-separated sessions. Without it and without a `session_id` column, the session is `ses-01`. |
| `--qc_json` | The pipeline's `qc.json`, relative to the current directory. |
| `--qc_task` | One QC task key from `qc.json`. |
| `--qc_pipeline` | Pipeline name recorded in each bundle. |
| `--out_dir` | Output directory. |
| `--qc_status` | Optional `*_qc_status.tsv` from QC-Studio. The latest rating per scan goes into its bundle. |
| `--contrast_map` | Optional JSON object, or a path to one, that maps a suffix to the suffix whose metric context it uses. |
| `--stats_config` | Optional JSON object, or a path to one, with statistical cutoffs (see below). |

To use the MRIQC reference distribution, set `REFERENCE_DATA_URL`, as for the QC Metrics panel.
Without it, the bundles record that no reference was available.

## Which scan is exported

The export writes one bundle per participant, session and QC task.
The scan is the image that `base_mri_image_path` names.
The export removes the `space-`, `res-` and `desc-` entities from the image name to get the scan's BIDS name.
For example, `sub-01_ses-01_run-1_desc-preproc_T1w.nii.gz` gives `sub-01_ses-01_run-1_T1w`.
The export finds the IQMs for that name in the group TSVs of `iqm_path`.

A `base_mri_image_path` glob must match exactly one file.

## Output

```text
<out_dir>/
  acquisition_summary.tsv
  <participant_id>/<session_id>/<pipeline>/<qc_task>/
    bundle.json
    PACKAGE.md
    views/
```

- `bundle.json` holds the evidence. It validates against the `EvidenceBundle` schema.
- `PACKAGE.md` is a readable rendering of `bundle.json`.
- `views/` holds the core views and any targeted views as PNG files.
- `acquisition_summary.tsv` has one row per participant and session, with the export status.

The `status` column has three values:

| Status | Meaning |
|--------|---------|
| `ok` | The bundle and its views are written. |
| `partial` | The bundle is written without views, because the image is missing or cannot be read. The `error` column gives the reason. |
| `error` | No bundle is written, for example because the scan has no IQMs. The `error` column gives the reason. |

One failed scan does not stop the export.
The command exits with status 1 only when it writes no bundle.

## Statistics

The group TSVs of `iqm_path` are the project distribution.
The export compares each scan only with scans of the same **protocol signature**: the same suffix, acquisition type, field strength, manufacturer, rounded repetition, echo and inversion times, flip angle and voxel size.
If too few scans match, the export drops fields in a fixed order.
The suffix, acquisition type and field strength are never dropped.

Set the cutoffs with `--stats_config`:

```bash
--stats_config '{"min_stratum_size": 10, "project_z_threshold": 3.0, "reference_percentile_low": 2.5, "reference_percentile_high": 97.5}'
```

Each bundle records the cutoffs that produced it.

## Acquisition check

The export also checks each scan's protocol.
For each signature field, it finds the most common value among scans of the same suffix.
An **acquisition deviation** is a field whose value differs from that common value.
For example, one T1w scan with an echo time of 3.5 ms has a deviation on `EchoTime` when the other T1w scans use 2.9 ms.

Deviations appear in `bundle.json`, in `PACKAGE.md` and in the `deviations` column of `acquisition_summary.tsv`.
A deviation is a finding about the protocol, not about image quality.

## Contrast support tiers

The metric context tells the export how to read an IQM, for example whether a high value is bad.
Only some contrasts have their own context.
The export never rejects a scan for its contrast.
Instead, each bundle records a **support tier**:

| Tier | Suffixes | What the bundle holds |
|------|----------|-----------------------|
| `supported` | `T1w`, `T2w`, `bold`, `dwi` | The suffix's own context, project and reference percentiles, and flags. |
| `fallback` | `FLAIR` and `T2starw` by default | The context of the mapped suffix (`T2w`) and project percentiles only. IQMs that depend on tissue contrast are not interpreted. |
| `unsupported` | Any other suffix, for example `PDw` | IQMs, metadata, views and percentiles, but no interpretation and no flags. |

`PACKAGE.md` states the tier, and the context used, at the top.

To change the fallback map, pass `--contrast_map`.
The map replaces the default.
For example, `--contrast_map '{}'` makes `FLAIR` unsupported.
A suffix with its own context stays `supported` whatever the map says.

## Identifying metadata

The export keeps only allowlisted acquisition fields.
Fields such as `DeviceSerialNumber`, `InstitutionName`, `StationName` and `AcquisitionTime` never appear in any output.
