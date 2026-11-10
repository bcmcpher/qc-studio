# Evidence Bundle: Design Note

Status: proposal. Tracks [#24](https://github.com/nipoppy/qc-studio/issues/24) and
[#40](https://github.com/nipoppy/qc-studio/issues/40).

## Goal

QC-Studio exports the QC information for one scan as an **evidence bundle**. An evidence bundle
is a model-independent package of metrics, statistical context and rendered images. An
image-aware LLM reads the bundle and returns structured feedback on the scan.

## Summary of the design

- Code makes the statistical judgement. Percentiles, direction-aware flags and an outlier score
  are computed before any model sees the scan.
- The LLM explains. It checks whether the images agree with the computed flags, names visible
  artifacts and writes structured feedback.
- Images are 2D. A fixed set of **core views** is rendered for every scan. A small set of
  **targeted views** is added by explicit rules.
- The bundle format does not depend on a model. A separate **model adapter** sends a bundle to
  one model and parses the reply.

## Key terms

| Term | Meaning |
|------|---------|
| Evidence bundle | The per-scan export: `bundle.json`, rendered views and a prompt rendering (`PACKAGE.md`). |
| IQM | Image quality metric, as computed by MRIQC. |
| Direction of concern | Whether a high or a low value of an IQM indicates poor quality. |
| Project distribution | The IQMs of all scans in the current dataset, split by site or scanner. |
| Reference distribution | MRIQC Web API IQMs, filtered to scans with comparable acquisition metadata. |
| Outlier score | One multivariate score of how unusual a scan's IQMs are, with the metrics that drive it. |
| Core view | A rendered 2D view that every scan gets, at fixed template-space positions. |
| Targeted view | A rendered 2D view that a rule adds when a specific flag is present. |
| Model adapter | Code that sends a bundle to one model and validates the reply. |

## Decision model or LLM

The two kinds of model do different jobs.

| | Embedding model + classifier or outlier detector | Image-aware LLM |
|---|---|---|
| Output | A score or probability, which can be calibrated | Text or JSON, which is not calibrated |
| Same input, same output | Yes | Not reliably |
| Arithmetic and metric direction | Built into the model | Error-prone |
| Explains its call | No | Yes |
| Needs labelled data | Yes, or a reference distribution | No, but evaluation needs labels |
| Runs locally | Easily | Only small models, which perform badly |
| Handles 3D | Yes | Generalist models: no |

The sandbox experiments support this split:

- Claude on IQMs alone gave the most faithful result, because the package rules did the
  reasoning.
- LLaVA-OneVision 4B returned valid JSON. It misread the direction of concern and its flags did
  not match its reasons.

The design therefore moves all arithmetic and flagging into code. The LLM gets interpreted
evidence, not raw distributions.

An embedding model (for example V-JEPA over a slice stack) can add an image-based outlier score
later. It needs a reference set of scans with known quality. It is out of scope for the first
implementation.

Related work: Esteban et al. 2017 (MRIQC classifier, poor generalization to new sites),
Sujit et al. 2019 (3D CNN QC of T1w), Fonov et al. 2022 (2D-slice registration QC),
Keshavan et al. 2019 (braindr, QC from single 2D slices).

## Statistical context

Raw IQMs carry little meaning without context. Each metric in a bundle has two percentiles.

1. **Project percentile.** Use robust statistics (median and MAD). Split by site or scanner when
   the metadata permits.
2. **Reference percentile.** Filter the MRIQC reference to comparable scans: manufacturer and
   field strength. `ui/utils/reference_data.py` already does this filtering.

The two percentiles are combined into a context category:

| Project | Reference | Category | Interpretation |
|---------|-----------|----------|----------------|
| Outlier | Outlier | `scan` | The scan is bad. |
| Normal | Outlier | `protocol` | A site-wide or protocol effect, not a single-scan failure. |
| Outlier | Normal | `project` | Unusual for this dataset. Review it. |
| Normal | Normal | `normal` | No concern. |

IQMs are strongly correlated. Per-metric flags therefore overcount one problem. The bundle also
holds a multivariate outlier score: a robust Mahalanobis distance over the standardized IQMs. It
lists the metrics that contribute most.

The prompt states each metric as an interpretation. Example: "fwhm_avg: 97th percentile in
project (site A), 88th in matched reference, higher is worse → flagged."

## 2D views

Generalist image-aware models accept only 2D images. 3D medical VLMs exist, but they target CT
and radiology reports, not acquisition-artifact QC. Raters and the fMRIPrep and MRIQC reports
also work from 2D slices.

Model input resolution is the main limit. Claude downsamples images above about 1568 px on the
long side. LLaVA-OneVision splits images into 384 px tiles. Dense montages lose small artifacts.
Each rendered image therefore holds few slices, and a bundle holds several images.

### Core views

Every scan gets the same core views.

- Slice positions are fixed in template space (MNI coordinates), not by voxel index. When no
  template-space image is available, positions fall back to fractions of the brain-mask bounding
  box.
- The volume is reoriented to RAS before rendering.
- Intensity windowing uses fixed percentiles of the whole volume, not of each slice.
- Image size and labels are fixed.

The same input always gives byte-identical images. The core views make scans comparable and
permit few-shot examples.

### Targeted views

Rules add targeted views. Each rule maps a flag to one view.

| Trigger | Targeted view |
|---------|---------------|
| Motion or rotation flags | Sagittal slices through the cortex |
| Noise or ghosting metrics (`snr`, `efc`, `fber`) | Background-enhanced window |
| Segmentation or skull-strip outputs present | Mask or contour overlay |
| Registration outputs present | Template edges over the image |
| Field-of-view or cropping metrics | Edge slices |

A targeted view can prime the model to confirm a flag. The evaluation controls for this:

- The prompt does not state why a targeted view was added.
- Some clean scans receive targeted views as controls, to measure false confirmations.

## Bundle format

One directory per scan:

```text
<out_dir>/<participant_id>/<session_id>/<pipeline>/<qc_task>/
  bundle.json     # schema-versioned evidence (see below)
  PACKAGE.md      # prompt rendering of bundle.json
  views/
    core_axial.png
    core_coronal.png
    core_sagittal.png
    targeted_<rule>.png
```

`bundle.json` holds:

- `schema_version`, and the QC-Studio and MRIQC versions;
- participant, session, pipeline and QC task identifiers;
- selected acquisition metadata from the BIDS sidecar;
- per metric: value, direction of concern, project and reference percentiles, flags and context
  category;
- the outlier score and its top contributors;
- the reference filter that was applied, and the project stratum;
- per view: path, kind (`core` or `targeted`), rule, plane and slice positions;
- the rater's QC rating and notes, if present.

## Model feedback

A model adapter returns feedback that validates against one schema: `decision`, `confidence`,
`summary`, `reasons`, `flagged_metrics` and `recommended_followup`.

Validation has two levels.

1. **Schema validation.** The reply parses and matches the schema.
2. **Consistency validation.** Each flagged metric is flagged in the bundle. The flagged metrics
   match the reasons. The count of reasons is within limits. Follow-up is present when the
   decision is not `pass`.

## Evaluation

Three scans from one subject cannot separate the design options. The evaluation needs a labelled
dataset, for example the MRIQC expert ratings for ABIDE and DS030, or the braindr ratings for HBN.

The evaluation compares:

- core views only, core plus targeted views, and IQMs only;
- targeted views with and without a stated reason;
- each model adapter.

It reports schema validity, consistency validity and agreement with the labels.

## Placement in the code

- `ui/evidence_bundle/`: the bundle schema, statistics, rendering, view rules and export. This
  code reuses `ui/utils/reference_data.py`, `ui/utils/cohort.py` and the `qc.json` path
  resolution. It runs without Streamlit, and CI tests it with the rest of `ui/tests`.
- `sandbox/`: model adapters, prompt templates and the evaluation runner. These need optional
  dependencies (`anthropic`, `torch`, `transformers`).

## Open questions

- Placement: #24 sketches a top-level `evidence_bundle/` package. This note places it under
  `ui/` to reuse existing loaders. Confirm with the maintainers.
- Privacy: sending MRI images to a cloud model can break data-use agreements. Is a cloud model a
  deployment option or a benchmark only?
- Labelled data: which labelled dataset is available to the group?
- Compute: where can the larger local models (8B and up) run?
- UI: should the landing page or the QC viewer get an export button, or is a CLI enough?
