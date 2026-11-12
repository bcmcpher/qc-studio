## Context

The full design rationale is in
[`docs/source/development/evidence_bundle_design.md`](../../../docs/source/development/evidence_bundle_design.md).
This file records only the decisions this change commits to.

Starting point: branch `24-evidence-bundle-export` (from `upstream/evidence_bundle` with
`upstream/main` merged). Sandbox code to port: `sandbox/qc_package.py` (reference stats,
template rendering) and `sandbox/iqms_context/*.json` (metric context).

## Goals / Non-Goals

**Goals:**

- A bundle that any model adapter can consume, with no model-specific content.
- All arithmetic and flagging done in code, with tests on synthetic data.
- Byte-identical view images for identical input.

**Non-Goals:**

- Calling any model (`add-model-feedback`).
- Choosing the final view set (`add-feedback-evaluation`).
- A UI export button.
- An image-embedding outlier score (out of scope for the first implementation).

## Decisions

- **Placement under `ui/evidence_bundle/`.** Reuses `ui/utils` loaders and runs in the existing
  CI test job. Alternative: a top-level `evidence_bundle/` package as #24 sketches; it would
  need a second import path and test setup. Pending maintainer confirmation.
- **Robust statistics in numpy.** Median/MAD, empirical percentiles, Mahalanobis distance with
  shrinkage covariance. No scikit-learn, to keep `requirements.txt` unchanged.
- **Reference filtering through `filter_reference_iqm`.** One filter in the codebase. The
  sandbox's stepwise filter (skip a filter that leaves no rows) is dropped; if that fallback is
  needed it goes into `filter_reference_iqm` in its own commit.
- **Pillow for rendering.** Deterministic output, no matplotlib font or backend variation.
- **Template-space slice positions with a mask-bbox fallback.** Positions are comparable across
  scans when an MNI-space image exists; the fallback method is recorded in `ViewRef`.
- **`PACKAGE.md` via `str.format`.** Ported as is from `render_markdown_template`; literal
  braces in templates are written `{{ }}`.

## Risks / Trade-offs

- [Small strata give unstable percentiles] → record stratum size in the bundle; fall back to
  the unstratified project distribution below a minimum count.
- [Reference filter leaves few rows] → record the filter applied and the row count.
- [PNG bytes differ across Pillow versions] → test determinism within one environment only.
- [`sample_data/` is tiny] → statistics tests use synthetic distributions.

## Open Questions

- `ui/` versus a top-level package (maintainers).
- Minimum stratum size before fallback.
- Whether `plans/` ships in upstream PRs or stays local.
