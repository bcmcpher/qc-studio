## Why

QC-Studio shows raw IQMs, montages and volumes, but nothing packages that information for a
model to read. The sandbox experiments ([#24](https://github.com/nipoppy/qc-studio/issues/24),
[#40](https://github.com/nipoppy/qc-studio/issues/40)) showed that models misread raw IQMs and
metric direction. Code must make the statistical judgement and render comparable images, so a
model only has to explain. This change builds that package: the evidence bundle.

## What Changes

- New package `ui/evidence_bundle/` that runs without Streamlit and is tested in CI.
- Bundle schema (pydantic, schema-versioned) for metrics, statistical context, outlier score,
  views and the rater's QC.
- Robust project statistics per stratum, reference percentiles from the MRIQC Web API data,
  direction-aware flags, context category and a multivariate outlier score.
- Deterministic 2D rendering: core views at fixed template-space positions, plus targeted views
  added by explicit rules.
- Export CLI that writes one bundle directory per scan (`bundle.json`, `views/`, `PACKAGE.md`).
- Metric context files move from `sandbox/iqms_context/` into the package.
- No new runtime dependencies.

## Capabilities

### New Capabilities

- `evidence-bundle`: build, render and export a model-independent per-scan evidence bundle.

### Modified Capabilities

- None.

## Impact

- New code: `ui/evidence_bundle/` (`models.py`, `stats.py`, `render.py`, `view_rules.py`,
  `export.py`, `constants.py`, `iqms/`).
- Reused: `ui/utils/reference_data.py` (`filter_reference_iqm`), `ui/utils/cohort.py`,
  `ui/utils/config.py` (`parse_qc_config` placeholder substitution), `ui/models/qc_models.py`.
- Removed duplicate: `sandbox/qc_package.py:filter_reference_by_metadata`.
- Docs: one guide section for the export CLI.
- Downstream: `add-model-feedback` consumes bundles.
