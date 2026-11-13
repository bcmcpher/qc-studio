## 0. Baseline

- [x] 0.1 Create branch `24-evidence-bundle-export` from `upstream/evidence_bundle` and merge `upstream/main`
- [x] 0.2 Write the design note `docs/source/development/evidence_bundle_design.md` and add it to the docs toctree
- [x] 0.3 Run the full checks (`pre-commit run --all-files`, Sphinx with `-n -W`) on the merged branch

## 1. Bundle schema — `ui/evidence_bundle/models.py`

- [x] 1.1 Write pydantic models `MetricEvidence`, `OutlierScore`, `ViewRef`, `RaterQC` and `EvidenceBundle`, with a `schema_version` field
- [x] 1.2 Port `direction_of_concern` and metric context from `sandbox/iqms_context/*.json` to `ui/evidence_bundle/iqms/`; rename `tw1.json` to `t1w.json`
  - As built: copied, not moved (sandbox scripts still read the originals). Directions normalized to `higher_worse | lower_worse | outside_range | context_dependent | not_quality_metric`: `target_range`/`normative_range` → `outside_range`; `inu_*` split into `inu_med` (`outside_range`) and `inu_range` (`higher_worse`); DWI `expected_lower_bound` → `expected_range: [lo, null]`. Loader and pattern lookup in `ui/evidence_bundle/context.py`.
- [x] 1.3 Tests: round-trip a bundle through JSON; reject an unknown `direction_of_concern`
- [x] 1.4 Replace `AcquisitionMetadata` with grouped, allowlisted fields: `scanner`, `sequence`, `geometry`, `provenance` (see design); rename `EvidenceBundle.modality` to `suffix` (BIDS suffix: `T1w`, `T2w`, `bold`, `dwi`)
  - As built: model fields use the BIDS key names, so the allowlist is the model fields; `AcquisitionMetadata.from_sidecar` keeps only those (`CoilString` fills `ReceiveCoilName`). `suffix` is top-level only, not repeated in `sequence`. `mriqc_version` moved from the bundle into `provenance`. Geometry adds `field_of_view`; header values win over sidecar `SliceThickness`/`SpacingBetweenSlices`.
- [x] 1.5 Add `ProtocolSignature` and `AcquisitionDeviation` models; add `protocol_signature` and `acquisition_deviations` to the bundle; record the signature fields used for the project stratum and the reference filter
  - As built: signature in sidecar units (seconds, degrees; voxel size mm). `AcquisitionDeviation` also records `n` (scans compared). `DistributionContext` gains `signature_fields` and `note` (why a distribution is reduced or skipped).
- [x] 1.6 Structural context: rename `iqms/t1w.json` to `iqms/anat.json`; add `iqms/t2w.json` holding only overrides (`wm2max` → `context_dependent`, caveat that the range is T1w-derived; caveats on `tpm_overlap_*`, `icvs_*`, `rpve_*`); loader merges base + overrides by suffix
  - As built: override file format `MetricContextOverrideFile` (only set fields replace; `add_caveats` appends); overrides naming entries missing from the base fail. `wm2max` range set to null in T2w. `CONTEXT_FILES` in `ui/evidence_bundle/constants.py` maps suffix → base + overrides; loaded `modality` is the suffix.
- [x] 1.7 Contrast support tiers: add `context_suffix` and `support` (`supported`, `fallback`, `unsupported`) to the bundle; add the fallback map (`FLAIR`→`T2w`, `T2starw`→`T2w`; `PDw` unmapped) and the forced `context_dependent` set (`wm2max`, `cjv`, `tpm_overlap_*`, `icvs_*`, `rpve_*`) to `constants.py`; allow a user map to override the default; validators: `unsupported` bundles carry no flags, `fallback` bundles carry no reference percentiles
  - As built: `resolve_context(suffix, contrast_map)` in `context.py`. Constants in `ui/evidence_bundle/constants.py`. Every suffix in `CONTEXT_FILES` is `supported`, so `bold` and `dwi` are too; a user map cannot demote a supported suffix, and its targets must have their own context. `unsupported` bundles require every metric `context_dependent` (so no flags) and a null `context_suffix`.
- [x] 1.8 Tests: allowlist drops identifying sidecar fields; T1w and T2w contexts load; the T2w override applies; `FLAIR` resolves to `T2w` context with the forced set `context_dependent`; `PDw` resolves to `unsupported`; a user map overrides the default
  - As built: 90 tests in `ui/tests/test_evidence_bundle_models.py`.
  - Review (2026-11-13): floats reject NaN/inf; an unknown `direction_of_concern` error names the metric; suffixes and contrast-map keys match case-insensitively; `load_metric_context` returns deep copies. `unsupported` bundles also require `evidence_strength` `none`; the exporter takes `display_name`/`category` from the base catalog (see `design.md`, contrast support).

## 2. Statistics — `ui/evidence_bundle/stats.py` and `acquisition.py`

- [x] 2.1 Check the reference parquet columns for T1w and T2w (sequence fields, voxel size) and whether `T2w.parquet` is served; record the result in `design.md`
- [x] 2.2 Extract acquisition metadata from the MRIQC JSON `bids_meta` and `provenance`, the BIDS sidecar, and the NIfTI header (`acquisition.py`)
- [x] 2.3 Build the protocol signature with the rounding in `constants.py`
- Decision (2026-11-13): TE rounds to 0.1 ms (0.0001 s in sidecar units), not 1 ms, so the spec's 2.9 ms vs 3.5 ms deviation scenario holds. `design.md` updated.
- [x] 2.4 Acquisition check: compare each signature field with the project's modal value for the same suffix (and site when known); record deviations
- [x] 2.5 Write robust project statistics (median, MAD, empirical percentile) within the signature stratum; drop signature fields in the fixed fallback order below the minimum stratum size; never drop `suffix`, `MRAcquisitionType` or `MagneticFieldStrength`
- [x] 2.6 Get reference percentiles through `utils.reference_data.filter_reference_iqm`, extended to the signature fields that the reference data holds (result of 2.1); skip the reference for `fallback` and `unsupported` bundles and record why; drop the duplicate sandbox filter `filter_reference_by_metadata` and record that in the commit
- [x] 2.7 Write direction-aware flags with thresholds in `ui/evidence_bundle/constants.py`, including two-sided flags for `outside_range`
- [x] 2.8 Assign the context category (`scan`, `protocol`, `project`, `normal`)
- [x] 2.9 Write the robust Mahalanobis outlier score in numpy, with shrinkage covariance and top contributors; do not add scikit-learn
- [x] 2.10 Tests on synthetic data: signature rounding; one off-protocol scan (TR changed) reported as a deviation and excluded from the others' stratum; fallback order; T1w and T2w never mixed; a FLAIR scan stratified only with FLAIR scans and given no reference percentiles; an `unsupported` scan gets percentiles but no flags; known percentiles; both flag directions and `outside_range`; all four categories; an injected outlier ranked first
  - As built (2026-11-13): `acquisition.py` (`extract_acquisition`, `nifti_geometry`, `protocol_signature`, `acquisition_deviations`) and `stats.py` (`select_stratum`, `reference_subset`, `metric_flags`, `outlier_score`, `scan_statistics`). 2.1: columns read from `scripts/fetch_mriqc_reference.py` (IQMs + `Manufacturer`, `MagneticFieldStrength`, `ManufacturersModelName`; voxel size via `spacing_*`; no sequence fields; no T2w fetched); host not checked, so a real-data check remains. TR rounds to 1 ms (user, 2026-11-13). Cutoffs in `StatsConfig` (min stratum 10, robust z 3.0, reference percentile 2.5/97.5), recorded as `EvidenceBundle.stats_config`. `filter_reference_frame` split out of `filter_reference_iqm` (adds voxel size) so an export loads each parquet once; the sandbox filter `filter_reference_by_metadata` is replaced by it. Without geometry from an image, `extract_acquisition` uses the MRIQC `size_*`/`spacing_*` IQMs. Non-finite IQMs are skipped and listed. The outlier score uses directional metrics with evidence, standardized by median/MAD, member z clipped at 5, Ledoit–Wolf shrinkage; its percentile is against the stratum members' own scores. Tests: 54 in `ui/tests/test_evidence_bundle_stats.py`, synthetic reference tables built in the tests.
  - Review (2026-11-13): a tie for the most common value means no mode, so no scan deviates on that field; voxel size and field of view are in RAS axis order to match MRIQC `spacing_*`; each source is cleaned before merging, so an invalid sidecar value does not erase a valid `bids_meta` one; rounding uses the step's decimal places; the outlier percentile scores members leave-one-out (the in-sample version put ordinary scans at a median percentile of about 73 in strata of 12). The sandbox again uses the whole reference and falls back to it when the scanner has no rows; it no longer matches `ManufacturersModelName`.

## 3. Rendering — `ui/evidence_bundle/render.py`

- [x] 3.1 Reorient to RAS (`nibabel.as_closest_canonical`); resample display to isotropic mm so anisotropic voxels are not distorted; window with fixed whole-volume percentiles; fixed output size; draw labels with Pillow, no matplotlib
- [x] 3.2 Place core views at fixed MNI coordinates when a template-space image exists (fMRIPrep `space-MNI152NLin2009cAsym`); otherwise fall back to fractions of the brain-mask bounding box; record the method in `ViewRef`
- [x] 3.3 Render one image per plane with few slices per image (start with 3; tune in `add-feedback-evaluation`)
- [x] 3.4 Tests: a synthetic NIfTI gives byte-identical PNGs on two runs; orientation is correct for a non-RAS volume; an anisotropic volume renders with correct aspect; the fallback is used when no template image exists
  - As built (2026-11-13): `render.py` (`load_volume`, `window_limits`, `mni_indices`, `bbox_indices`, `render_plane`, `render_core_views`). Each slice is resized with Pillow bilinear so one pixel covers the same mm along both axes, then centred in a 256 px panel; three panels per PNG plus a 20 px label strip (768 x 276 px). Neurological display (subject left on the left; side letters L/R or P/A on each panel). Window: 0.5th and 99.5th percentiles of all finite voxels, shared by the three planes; recorded in `ViewRef.window_percentiles`. MNI positions (mm): axial z -20/10/40, coronal y -60/-15/20, sagittal x -35/0/35; with a template image the template-space image itself is rendered. Fallback positions are fractions 0.3/0.5/0.7 of the bounding box of the brain mask, or of a threshold head mask (voxels above 10% of the 99th percentile) when no mask is given; `ViewRef.slice_positions` holds mm for `mni` and fractions for `bbox_fraction`. A 4D image is averaged over time. A mask on another grid, or an MNI coordinate outside the template image, raises `ValueError`; the exporter (section 5) decides how to recover. PNGs are written without metadata. Checked by eye on `sample_data` sub-ED01 (native T1w, native preproc + brain mask, MNI res-2). Tests: 19 in `ui/tests/test_evidence_bundle_render.py`; the aspect and reorientation tests fail when the mm scaling or `as_closest_canonical` is removed.

## 4. Targeted views — `ui/evidence_bundle/view_rules.py`

- [ ] 4.1 Write the rule table flag → view; start with motion (sagittal cortex) and noise (background-enhanced window); add the mask overlay when `overlay_mri_image_path` is set in `qc.json`
- [ ] 4.2 Add a control mode that adds targeted views to clean scans
- [ ] 4.3 Tests: each rule fires on its flag and on nothing else

## 5. Export — `ui/evidence_bundle/export.py`

- [ ] 5.1 Build bundles from `--dataset_dir`, `--participant_list`, `--qc_json`, `--qc_task` and `--out_dir`; reuse `utils.cohort` and `utils.config.parse_qc_config` placeholder substitution
- [ ] 5.2 Use the `iqm_path` group TSVs as the project distribution; read per-scan MRIQC JSON for `bids_meta`
- [ ] 5.3 Merge in the rater's QC from a `*_qc_status.tsv`, if one is given
- [ ] 5.4 Write `bundle.json`, `views/` and `PACKAGE.md`; port `render_markdown_template` from `sandbox/qc_package.py`; `PACKAGE.md` states acquisition deviations, the stratum used, and the support tier (for example "interpreted using T2w metric context")
- [ ] 5.5 Write a project-level `acquisition_summary.tsv` (one row per scan: signature fields, deviations, `support`, `context_suffix`, export status) beside the bundles
- [ ] 5.6 Make per-scan errors non-fatal: record the error in `acquisition_summary.tsv` and continue; exit non-zero only if no bundle was written
- [ ] 5.7 Add a CLI entry point (`python ui/evidence_bundle/export.py …`) with `--contrast_map` for a user fallback map; a UI export button is out of scope
- [ ] 5.8 Tests: export on a `tmp_path` copy of `sample_data/`; the bundle validates against the schema; no identifying sidecar field appears in any output; one unreadable scan does not stop the export
- [ ] 5.9 Docs: one section in `docs/source/guides/` that shows the CLI and explains the acquisition check and the contrast support tiers
