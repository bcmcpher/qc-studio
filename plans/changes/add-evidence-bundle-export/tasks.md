## 0. Baseline

- [x] 0.1 Create branch `24-evidence-bundle-export` from `upstream/evidence_bundle` and merge `upstream/main`
- [x] 0.2 Write the design note `docs/source/development/evidence_bundle_design.md` and add it to the docs toctree
- [x] 0.3 Run the full checks (`pre-commit run --all-files`, Sphinx with `-n -W`) on the merged branch

## 1. Bundle schema — `ui/evidence_bundle/models.py`

- [x] 1.1 Write pydantic models `MetricEvidence`, `OutlierScore`, `ViewRef`, `RaterQC` and `EvidenceBundle`, with a `schema_version` field
- [x] 1.2 Port `direction_of_concern` and metric context from `sandbox/iqms_context/*.json` to `ui/evidence_bundle/iqms/`; rename `tw1.json` to `t1w.json`
  - As built: copied, not moved (sandbox scripts still read the originals). Directions normalized to `higher_worse | lower_worse | outside_range | context_dependent | not_quality_metric`: `target_range`/`normative_range` → `outside_range`; `inu_*` split into `inu_med` (`outside_range`) and `inu_range` (`higher_worse`); DWI `expected_lower_bound` → `expected_range: [lo, null]`. Loader and pattern lookup in `ui/evidence_bundle/context.py`.
- [x] 1.3 Tests: round-trip a bundle through JSON; reject an unknown `direction_of_concern`

## 2. Statistics — `ui/evidence_bundle/stats.py`

- [ ] 2.1 Write robust project statistics (median, MAD, empirical percentile) per stratum; strata come from the BIDS sidecar (manufacturer, field strength, site when known)
- [ ] 2.2 Get reference percentiles through `utils.reference_data.filter_reference_iqm`; drop the duplicate sandbox filter `filter_reference_by_metadata` and record that in the commit
- [ ] 2.3 Write direction-aware flags with thresholds in `ui/evidence_bundle/constants.py`
- [ ] 2.4 Assign the context category (`scan`, `protocol`, `project`, `normal`)
- [ ] 2.5 Write the robust Mahalanobis outlier score in numpy, with shrinkage covariance and top contributors; do not add scikit-learn
- [ ] 2.6 Tests on synthetic distributions: known percentiles, both flag directions, all four categories, an injected outlier ranked first

## 3. Rendering — `ui/evidence_bundle/render.py`

- [ ] 3.1 Reorient to RAS (`nibabel.as_closest_canonical`); window with fixed whole-volume percentiles; fixed output size; draw labels with Pillow, no matplotlib
- [ ] 3.2 Place core views at fixed MNI coordinates when a template-space image exists (fMRIPrep `space-MNI152NLin2009cAsym`); otherwise fall back to fractions of the brain-mask bounding box; record the method in `ViewRef`
- [ ] 3.3 Render one image per plane with few slices per image (start with 3; tune in `add-feedback-evaluation`)
- [ ] 3.4 Tests: a synthetic NIfTI gives byte-identical PNGs on two runs; orientation is correct for a non-RAS volume; the fallback is used when no template image exists

## 4. Targeted views — `ui/evidence_bundle/view_rules.py`

- [ ] 4.1 Write the rule table flag → view; start with motion (sagittal cortex) and noise (background-enhanced window); add the mask overlay when `overlay_mri_image_path` is set in `qc.json`
- [ ] 4.2 Add a control mode that adds targeted views to clean scans
- [ ] 4.3 Tests: each rule fires on its flag and on nothing else

## 5. Export — `ui/evidence_bundle/export.py`

- [ ] 5.1 Build bundles from `--dataset_dir`, `--participant_list`, `--qc_json`, `--qc_task` and `--out_dir`; reuse `utils.cohort` and `utils.config.parse_qc_config` placeholder substitution
- [ ] 5.2 Use the `iqm_path` group TSVs as the project distribution
- [ ] 5.3 Merge in the rater's QC from a `*_qc_status.tsv`, if one is given
- [ ] 5.4 Write `bundle.json`, `views/` and `PACKAGE.md`; port `render_markdown_template` from `sandbox/qc_package.py`
- [ ] 5.5 Add a CLI entry point (`python ui/evidence_bundle/export.py …`); a UI export button is out of scope
- [ ] 5.6 Tests: export on a `tmp_path` copy of `sample_data/`; the bundle validates against the schema
- [ ] 5.7 Docs: one section in `docs/source/guides/` that shows the CLI
