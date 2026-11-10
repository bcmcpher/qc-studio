# Plan: evidence bundle export (#24, #40)

Branch: `24-evidence-bundle-export`, from `upstream/evidence_bundle` with `upstream/main` merged in.
Design: [`docs/source/development/evidence_bundle_design.md`](../docs/source/development/evidence_bundle_design.md).

Sections 1–5 are the core. They go under `ui/evidence_bundle/`, use only the existing
`requirements.txt` (numpy, pandas, nibabel, Pillow, pydantic), and CI tests them. Sections 6–7
are experimental and stay in `sandbox/`. Commit and stop for review after each section.

## Success criteria

- `pytest ui/tests` passes, including the new tests. black, flake8 and codespell pass.
- An export on `sample_data/` writes a bundle that validates against the schema.
- The same input renders byte-identical view images.
- The evaluation runner writes one results table: views × model × prompt variant.

## 0. Baseline

- [x] Create the branch from `upstream/evidence_bundle` and merge `upstream/main`.
- [x] Write the design note and add it to the docs toctree.
- [x] Run the full checks (`pre-commit run --all-files`, Sphinx with `-n -W`) on the merged branch.

## 1. Bundle schema — `ui/evidence_bundle/models.py`

- [ ] Write pydantic models: `MetricEvidence`, `OutlierScore`, `ViewRef`, `RaterQC` and
      `EvidenceBundle`, with a `schema_version` field.
- [ ] Write `QCFeedback`, the model reply schema. Move it from the sandbox `QCDecision`.
- [ ] Port `direction_of_concern` from `sandbox/iqms_context/*.json` to
      `ui/evidence_bundle/iqms/`. Rename `tw1.json` to `t1w.json`.
- [ ] Tests: round-trip a bundle through JSON; reject a bad `direction_of_concern`.

## 2. Statistics — `ui/evidence_bundle/stats.py`

- [ ] Write robust project statistics (median, MAD, empirical percentile) per stratum. The
      strata come from the BIDS sidecar (manufacturer, field strength, site when known).
- [ ] Get reference percentiles through `utils.reference_data.filter_reference_iqm`. Drop the
      duplicate sandbox filter (`filter_reference_by_metadata`) and record that in the commit.
- [ ] Write direction-aware flags with thresholds in `ui/evidence_bundle/constants.py`.
- [ ] Assign the context category (`scan`, `protocol`, `project`, `normal`).
- [ ] Write the robust Mahalanobis outlier score in numpy, with shrinkage covariance and the top
      contributors. Do not add scikit-learn.
- [ ] Tests on synthetic distributions: known percentiles, both flag directions, all four
      categories, an injected outlier ranked first.

## 3. Rendering — `ui/evidence_bundle/render.py`

- [ ] Reorient to RAS (`nibabel.as_closest_canonical`). Window with fixed whole-volume
      percentiles. Use a fixed output size. Draw labels with Pillow, without matplotlib.
- [ ] Place core views at fixed MNI coordinates when a template-space image exists (fMRIPrep
      `space-MNI152NLin2009cAsym`). Otherwise fall back to fractions of the brain-mask bounding
      box. Record the method in `ViewRef`.
- [ ] Render one image per plane with few slices per image (start with 3; tune in section 7).
- [ ] Tests: a synthetic NIfTI gives byte-identical PNGs on two runs; the orientation is
      correct for a volume that is not RAS; the fallback is used when no template image exists.

## 4. Targeted views — `ui/evidence_bundle/view_rules.py`

- [ ] Write the rule table: flag → view. Start with the motion (sagittal cortex) and noise
      (background-enhanced window) rules. Add the mask overlay when a mask path is in `qc.json`.
- [ ] Add a control mode that adds targeted views to clean scans.
- [ ] Tests: each rule fires on its flag and on nothing else.

## 5. Export — `ui/evidence_bundle/export.py`

- [ ] Build bundles from `--dataset_dir`, `--participant_list`, `--qc_json`, `--qc_task` and
      `--out_dir`. Reuse `utils.cohort` and the `qc.json` placeholder substitution.
- [ ] Use the `iqm_path` group TSVs as the project distribution.
- [ ] Merge in the rater's QC from a `*_qc_status.tsv`, if one is given.
- [ ] Write `bundle.json`, `views/` and `PACKAGE.md`. Port `render_markdown_template` from
      `sandbox/qc_package.py`.
- [ ] Add a CLI entry point (`python ui/evidence_bundle/export.py …`). A UI button is out of scope.
- [ ] Tests: export on a `tmp_path` copy of the sample data; the bundle validates.
- [ ] Docs: one section in `guides/` that shows the CLI.

## 6. Model adapters — `sandbox/model_adapters/`

- [ ] Write the adapter interface: `send(bundle_dir) -> QCFeedback`.
- [ ] Write a Claude adapter from `run_experiment.py`, with an image and an IQMs-only variant.
- [ ] Write a LLaVA-OneVision adapter from the 4B `chat_image.py`.
- [ ] Write consistency validation: flagged metrics ⊆ bundle flags, flags match reasons, reason
      count within limits, follow-up present when the decision is not `pass`.

## 7. Evaluation — `sandbox/evaluation/`

- [ ] Write a download script for a labelled dataset (MRIQC ABIDE/DS030 ratings or braindr HBN).
      Do not commit the data.
- [ ] Write a runner over views (IQMs only, core, core + targeted), the reason stated or hidden,
      and each adapter.
- [ ] Report schema validity, consistency validity, agreement with the labels, and the
      false-confirmation rate on controls.
- [ ] Post the results and the chosen view set to #40 (a draft for the user to post).

## Open decisions (from the design note)

- Placement under `ui/` versus a top-level package.
- Cloud models: deployment option or benchmark only.
- Which labelled dataset is available.
- Compute for 8B+ local models.
- Whether to add a UI export button later.
- Whether this plan file stays in the repo for the PR or moves to a local note.
