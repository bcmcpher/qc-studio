## Why

QC-Studio shows raw IQMs, montages and volumes, but nothing packages that information for a
model to read. The sandbox experiments ([#24](https://github.com/nipoppy/qc-studio/issues/24),
[#40](https://github.com/nipoppy/qc-studio/issues/40)) showed that models misread raw IQMs and
metric direction. Code must make the statistical judgement and render comparable images, so a
model only has to explain. This change builds that package: the evidence bundle.

IQMs and images are only comparable between scans with the same acquisition. Different TR, TE,
voxel size or contrast change how a scan looks and what its IQMs mean. The bundle therefore
records a small, allowlisted set of acquisition fields, compares each scan only with like
scans, and reports scans whose acquisition is out of place in the study. That last check is a
QC result in its own right, in the spirit of the ReproNim/ReproIn protocol checks.

## What Changes

- New package `ui/evidence_bundle/` that runs without Streamlit and is tested in CI.
- Bundle schema (pydantic, schema-versioned) for metrics, statistical context, outlier score,
  acquisition metadata, views and the rater's QC.
- Allowlisted acquisition metadata (scanner, sequence, geometry, provenance) from the MRIQC
  JSON, the BIDS sidecar and the NIfTI header. Identifying sidecar fields are never exported.
- A protocol signature per scan. Project statistics and the reference filter use it, so scans
  are compared only with like scans.
- An acquisition check that reports signature fields that differ from the study's usual value.
- Structural support for `T1w` and `T2w` through one structural context with per-suffix
  overrides. Other structural contrasts (FLAIR, PDw, …) are out of scope.
- Robust project statistics, reference percentiles, direction-aware flags, context category
  and a multivariate outlier score.
- Deterministic 2D rendering: core views at fixed template-space positions, plus targeted views
  added by explicit rules.
- Export CLI that writes one bundle directory per scan and a project-level acquisition summary.
- Metric context files move from `sandbox/iqms_context/` into the package.
- No new runtime dependencies.

## Capabilities

### New Capabilities

- `evidence-bundle`: build, render and export a model-independent per-scan evidence bundle,
  including acquisition metadata and the acquisition check.

### Modified Capabilities

- None.

## Impact

- New code: `ui/evidence_bundle/` (`models.py`, `context.py`, `acquisition.py`, `stats.py`,
  `render.py`, `view_rules.py`, `export.py`, `constants.py`, `iqms/`).
- Reused: `ui/utils/reference_data.py` (`filter_reference_iqm`, possibly extended to more
  signature fields), `ui/utils/cohort.py`, `ui/utils/config.py` (`parse_qc_config`
  placeholder substitution), `ui/models/qc_models.py`.
- Removed duplicate: `sandbox/qc_package.py:filter_reference_by_metadata`.
- Docs: one guide section for the export CLI and the acquisition check.
- Downstream: `add-model-feedback` consumes bundles.
