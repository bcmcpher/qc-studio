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
- `filter_reference_iqm` filtered only on `Manufacturer` and `MagneticFieldStrength`. The
  reference host is set by `REFERENCE_DATA_URL` and is not in the repository.
- Reference columns (task 2.1, from `scripts/fetch_mriqc_reference.py`, which builds the
  reference tables from the MRIQC Web API): every IQM, plus `Manufacturer`,
  `MagneticFieldStrength` and `ManufacturersModelName` lifted from `bids_meta`. No sequence
  fields (TR, TE, TI, flip angle, acquisition type). The voxel size is in the `spacing_*` IQMs.
  The script fetches only `T1w` and `bold`, so a `T2w.parquet` is not expected; this is not
  confirmed against the host. A supported scan with no reference table gets no reference
  percentiles, and the bundle records why.

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
  Times are rounded to 0.1 ms (TE), 1 ms (TR) or 10 ms (TI), voxel size to 0.1 mm, flip
  angle to 1°. TE uses 0.1 ms because anatomical TEs are a few ms; 1 ms would merge 2.9 ms and
  3.5 ms. TR uses 1 ms so short-TR gradient-echo protocols (6.95 ms vs 8.2 ms) stay apart.
  Manufacturer is normalized (`normalize_manufacturer`) before it enters the signature.
  Rounding constants live in `constants.py`. A missing field is part of the signature as null.
- **Stratification by signature with a fixed fallback.** The project stratum starts with the
  full signature (plus site when known). Below the minimum stratum size, fields are dropped in
  this order: `FlipAngle`, `InversionTime`, `EchoTime`, `RepetitionTime`, voxel size,
  `Manufacturer`. `suffix`, `MRAcquisitionType` and `MagneticFieldStrength` are never
  dropped. If the stratum is still too small, project percentiles are null. The bundle records
  the fields used and `n`. A scan is never part of its own stratum. The reference filter uses
  the same signature, limited to the fields the reference data holds (`MagneticFieldStrength`,
  `Manufacturer`, voxel size), and drops voxel size, then `Manufacturer`, below the minimum.
- **Configurable cutoffs, recorded per bundle.** `StatsConfig` holds `min_stratum_size`
  (default 10), `project_z_threshold` (3.0) and `reference_percentile_low`/`_high`
  (2.5/97.5). A project can set a laxer cutoff to flag more scans. Each bundle stores the
  config that produced it, because a flag means nothing without its cutoff. Rounding steps and
  the fallback order stay fixed: they define which scans are comparable, not how strict QC is.
- **Flags.** A metric is a `project_outlier` when its robust z ((value − median) / (1.4826 ×
  MAD) over the stratum) passes `project_z_threshold` in its direction of concern, and a
  `reference_outlier` when its reference percentile passes the percentile cutoff.
  `outside_range` is two-sided. Robust z is used for the project because strata are small and
  percentiles would move in coarse steps; the reference is large, so percentiles suit it.
- **Acquisition check against the project's modal value.** For each signature field, the
  modal value among scans of the same suffix (and site when known) is the expected value. A
  scan whose rounded value differs is recorded as an `AcquisitionDeviation` (field, value,
  expected, share of scans with the expected value). When values tie for most common, the field has no
  expected value and no scan deviates on it. Deviations go into `bundle.json`,
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
  | `unsupported` | anything unmapped (for example `PDw`) | IQMs, metadata, views and percentiles are written. All metrics are `context_dependent` with `evidence_strength` `none`, so there are no flags. `display_name` and `category` come from the modality's base catalog (`anat.json` for anatomical suffixes), because they do not depend on contrast; an IQM missing from it gets its own name and `uncategorized`. Adapters skip the bundle. |

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
- Whether the reference host serves `T2w.parquet` (the fetch script does not build one).
- Whether `plans/` ships in upstream PRs or stays local.
