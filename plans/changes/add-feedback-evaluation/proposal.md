## Why

The sandbox has three scans from one subject. That cannot separate the design options in
[#40](https://github.com/nipoppy/qc-studio/issues/40): which views to send, whether targeted
views prime false confirmations, and which model to use. A labelled evaluation is needed
before any model output is shown to raters (`add-qc-feedback-panel`).

## What Changes

- A download script for a public labelled QC dataset. No data is committed.
- An evaluation runner over view sets (IQMs only, core, core + targeted), targeted-view reason
  stated or hidden, and each model adapter.
- Control scans: clean scans that receive targeted views, to measure false confirmations.
- One results table and a short report: schema validity, consistency validity, agreement with
  labels, false-confirmation rate.
- A draft comment for #40 with the results and the recommended view set and model.

## Capabilities

### New Capabilities

- `feedback-evaluation`: run and report a labelled evaluation of model feedback over evidence
  bundles.

### Modified Capabilities

- None.

## Impact

- New code: `sandbox/evaluation/` (`download.py`, `run_eval.py`, `report.py`).
- Uses the export CLI from `add-evidence-bundle-export` and adapters from `add-model-feedback`.
- Results decide the core view count (task 3.3 of `add-evidence-bundle-export`), the default
  adapter, and whether the panel in `add-qc-feedback-panel` ships enabled.
- Compute: cloud API cost for Claude runs; GPU time for local models (not available on the
  dev machine).
