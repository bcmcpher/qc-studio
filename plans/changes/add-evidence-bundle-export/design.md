## Context

The full design rationale is in
[`docs/source/development/evidence_bundle_design.md`](../../../docs/source/development/evidence_bundle_design.md).
This file records only the decisions this change commits to.

Starting point: branch `24-evidence-bundle-export` (from `upstream/evidence_bundle` with
`upstream/main` merged). Sandbox code to port: `sandbox/qc_package.py` (reference stats,
template rendering) and `sandbox/iqms_context/*.json` (metric context).

Metadata sources found in `sample_data/`:

- MRIQC per-scan JSON: `bids_meta` (44 sidecar fields in the sample) and `provenance` (MRIQC
  version, input md5).
- BIDS sidecar: 59 fields in the sample, a superset.
- NIfTI header: grid, voxel size, orientation.
- `filter_reference_iqm` filters only on `Manufacturer` and `MagneticFieldStrength`. The
  reference host is set by `REFERENCE_DATA_URL` and is not in the repository, so its columns
  and its `T2w.parquet` are not yet confirmed (task 2.1).

## Goals / Non-Goals

**Goals:**

- A bundle that any model adapter can consume, with no model-specific content.
- All arithmetic and flagging done in code, with tests on synthetic data.
- Scans compared only with scans of the same contrast and a matching protocol.
- Out-of-place acquisitions reported as their own finding.
- Byte-identical view images for identical input.

**Non-Goals:**

- Calling any model (`add-model-feedback`).
- Choosing the final view set (`add-feedback-evaluation`).
- Contrast-specific metric context for structural contrasts other than `T1w` and `T2w` (FLAIR,
  PDw, neuromelanin, …). They get the `fallback` or `unsupported` tier instead.
- A study protocol file with expected values and tolerances; the acquisition check uses the
  project's own modal values. A protocol file can follow in a later change.
- A UI export button.
- An image-embedding outlier score.

## Decisions

- **Placement under `ui/evidence_bundle/`.** Reuses `ui/utils` loaders and runs in the existing
  CI test job. Alternative: a top-level `evidence_bundle/` package as #24 sketches. Pending
  maintainer confirmation.
- **Allowlisted acquisition metadata.** Bundles can be sent to cloud models, so only these
  fields are kept:

  | Group | Fields | Source |
  |---|---|---|
  | `scanner` | Manufacturer, ManufacturersModelName, MagneticFieldStrength, SoftwareVersions, ReceiveCoilName (or CoilString) | sidecar |
  | `sequence` | suffix, MRAcquisitionType, ScanningSequence, SequenceVariant, RepetitionTime, EchoTime, InversionTime, FlipAngle, PixelBandwidth, ParallelReductionFactorInPlane, PartialFourier | sidecar |
  | `geometry` | shape, voxel size (mm), orientation codes, field of view (mm), SliceThickness, SpacingBetweenSlices | NIfTI header, sidecar |
  | `provenance` | MRIQC version, input md5 | MRIQC JSON |

  `site` comes from the participant list or configuration, never from `InstitutionName`.
  Fields such as `DeviceSerialNumber`, `InstitutionName`, `InstitutionAddress`,
  `StationName`, `AcquisitionTime` and accession IDs are never read into the bundle.
- **Protocol signature.** A tuple of `suffix`, `MRAcquisitionType`, `MagneticFieldStrength`,
  `Manufacturer`, `RepetitionTime`, `EchoTime`, `InversionTime`, `FlipAngle` and voxel size.
  Times are rounded to 1 ms (TE) or 10 ms (TR, TI), voxel size to 0.1 mm, flip angle to 1°.
  Rounding constants live in `constants.py`. A missing field is part of the signature as null.
- **Stratification by signature with a fixed fallback.** The project stratum starts with the
  full signature (plus site when known). Below the minimum stratum size, fields are dropped in
  this order: `FlipAngle`, `InversionTime`, `EchoTime`, `RepetitionTime`, voxel size,
  `Manufacturer`. `suffix`, `MRAcquisitionType` and `MagneticFieldStrength` are never
  dropped. If the stratum is still too small, project percentiles are null. The bundle records
  the fields used and `n`. The reference filter uses the same signature, limited to the fields
  the reference data holds.
- **Acquisition check against the project's modal value.** For each signature field, the
  modal value among scans of the same suffix (and site when known) is the expected value. A
  scan whose rounded value differs is recorded as an `AcquisitionDeviation` (field, value,
  expected, share of scans with the expected value). Deviations go into `bundle.json`,
  `PACKAGE.md` and a project-level `acquisition_summary.tsv`.
- **Structural context: one base, per-suffix overrides.** `iqms/anat.json` (renamed from
  `t1w.json`) holds the structural IQMs. `iqms/t2w.json` holds only overrides. In the first
  pass the only override is `wm2max`, which becomes `context_dependent`, because its
  `[0.6, 0.8]` range is T1w-derived. `T1w` uses the base unchanged.
- **Three contrast support tiers; no scan is rejected.** The bundle records `suffix` (the
  actual contrast), `context_suffix` (whose metric context is used) and `support`:

  | `support` | Suffixes | Behaviour |
  |---|---|---|
  | `supported` | `T1w`, `T2w` | Own context; project and reference percentiles. |
  | `fallback` | mapped (default `FLAIR`→`T2w`, `T2starw`→`T2w`) | Context of the mapped suffix. Project-only percentiles. The forced set (`wm2max`, `cjv`, `tpm_overlap_*`, `icvs_*`, `rpve_*`) becomes `context_dependent`. |
  | `unsupported` | anything unmapped (for example `PDw`) | IQMs, metadata, views and percentiles are written. All metrics are `context_dependent`, so there are no flags. Adapters skip the bundle. |

  The fallback changes only how metrics are interpreted. Stratification always uses the actual
  `suffix`, so a FLAIR scan is compared only with FLAIR scans. Fallback scans get no reference
  percentiles, because no MRIQC reference exists for them and a T2w reference would turn a
  protocol difference into a scan finding. `PDw` is unmapped because its contrast is close to
  neither T1w nor T2w. The default map lives in `constants.py`; `--contrast_map` replaces it.
- **Export never stops on one scan.** Per-scan errors are recorded in
  `acquisition_summary.tsv`. Bundle export is independent of rating in the UI, so a failed or
  unsupported bundle never blocks QC.
- **`suffix` replaces `modality` in the bundle.** It is the BIDS value and a required stratum
  key, so `T1w` and `T2w` are never compared with each other.
- **Robust statistics in numpy.** Median/MAD, empirical percentiles, Mahalanobis distance with
  shrinkage covariance. No scikit-learn.
- **One reference filter.** `filter_reference_iqm` is extended, not duplicated. The sandbox's
  stepwise filter is dropped.
- **Pillow for rendering.** Deterministic output, no matplotlib font or backend variation.
  Display resampled to isotropic mm.
- **Template-space slice positions with a mask-bbox fallback.** The method is recorded in
  `ViewRef`.
- **`PACKAGE.md` via `str.format`.** Ported as is from `render_markdown_template`.

## Risks / Trade-offs

- [Small studies make every stratum small] → fixed fallback order; record fields used and `n`.
- [Reference data lacks sequence fields] → reference filter uses only the fields it has; the
  bundle records which.
- [Modal value is wrong when a study has two intended protocols] → deviations report the
  expected value's share; a low share signals a mixed study. A protocol file is a later change.
- [Rounding hides a real change or splits one protocol] → rounding constants are tested and
  documented.
- [T2w segmentation-based IQMs (`tpm_overlap_*`, `icvs_*`, `rpve_*`) are less tested than for
  T1w] → keep their T1w direction, add a caveat in the override file, revisit after evaluation.
- [A fallback context misleads on a contrast-specific metric outside the forced set] → the
  tier is shown in `PACKAGE.md`, the summary and the feedback panel; evaluation reports
  fallback scans separately; the forced set can grow.
- [PNG bytes differ across Pillow versions] → test determinism within one environment only.
- [`sample_data/` is tiny] → statistics tests use synthetic data.

## Open Questions

- `ui/` versus a top-level package (maintainers).
- Minimum stratum size before fallback.
- Whether the reference host serves `T2w.parquet` and which sequence columns it has (task 2.1).
- Whether `plans/` ships in upstream PRs or stays local.
