# Feedback evaluation

Scripts that measure how well model feedback agrees with expert QC labels. They implement
the `add-feedback-evaluation` change (`plans/changes/add-feedback-evaluation/`).

## Dataset

The candidate dataset is MR-ART, pending the maintainers' confirmation (task 1.1).

| Item | Value |
|---|---|
| Name | Movement-related artefacts (MR-ART) dataset |
| Source | OpenNeuro `ds004173`, `doi:10.18112/openneuro.ds004173.v1.0.2` |
| Licence | CC0 (public domain). No data-use agreement or login is needed. |
| Content | T1w scans of 148 adults, 3 acquisitions each (`acq-standard`, `acq-headmotion1`, `acq-headmotion2`); 436 scans |
| Labels | `derivatives/scores.tsv`: one neuroradiologist score per scan (1 good, 2 medium, 3 bad) |
| IQMs | `derivatives/mriqc-0.16.1/group_T1w.tsv` |
| Size | About 11 MB per T1w image; about 4.8 GB for all scans. Metadata is under 1 MB. |

Cite: Nárai, Á., Hermann, P., Auer, T. et al. Movement-related artefacts (MR-ART) dataset of
matched motion-corrupted and clean structural MRI brain scans. *Sci Data* 9, 630 (2022).
<https://doi.org/10.1038/s41597-022-01694-8>

Score distribution: 129 scans score 1, 109 score 2, 198 score 3. MR-ART has one score per
scan, so the report has no rater agreement for it.

## Label mapping

`labels.py` maps each score to an evaluation label. The original score stays in
`original_label`.

| Score | MR-ART meaning | Label |
|---|---|---|
| 1 | Good quality image | `pass` |
| 2 | Medium quality image | `uncertain` |
| 3 | Bad quality image (unusable for clinical diagnostic use) | `fail` |

The report gives agreement with `uncertain` as a class and without it.

## Workflow

Keep all data, bundles and results outside the repository. The scripts refuse a data or bundle
folder inside it.

1. Fetch the metadata (scores, IQMs, participants):

   ```bash
   .venv/bin/python sandbox/evaluation/download.py --data_dir ~/data/mrart
   ```

2. Map the scores to labels:

   ```bash
   .venv/bin/python sandbox/evaluation/labels.py ~/data/mrart/derivatives/scores.tsv --out ~/eval/labels.tsv
   ```

3. Draw a stratified, seeded sample (strata: label × acquisition):

   ```bash
   .venv/bin/python sandbox/evaluation/sample.py ~/eval/labels.tsv --out_dir ~/eval/sample --n_per_stratum 20 --seed 20261119
   ```

4. Fetch the T1w images of the sampled participants only:

   ```bash
   .venv/bin/python sandbox/evaluation/download.py --data_dir ~/data/mrart --sample ~/eval/sample/sample.tsv
   ```

5. Export the bundles, one QC task per acquisition (`mrart_qc.json`):

   ```bash
   .venv/bin/python sandbox/evaluation/build.py --data_dir ~/data/mrart --sample ~/eval/sample/sample.tsv --out_dir ~/eval/bundles
   ```

6. Check the request count and token estimate, then run each adapter:

   ```bash
   .venv/bin/python sandbox/evaluation/run_eval.py ~/eval/bundles --out_dir ~/eval/runs --adapter claude --acknowledge_data_use --dry_run
   .venv/bin/python sandbox/evaluation/run_eval.py ~/eval/bundles --out_dir ~/eval/runs --adapter claude --acknowledge_data_use \
       --labels ~/eval/sample/sample.tsv
   ```

7. Write the report, with the seed from `sample.json`:

   ```bash
   .venv/bin/python sandbox/evaluation/report.py ~/eval/runs/results.tsv --seed 20261119
   ```

Every step can be rerun. The download skips files it already has, and the runner keeps final
results.

## Known limits

- **Control views are not exported yet.** `sample.py` marks control scans, but the export CLI
  has no option to render control views, so no bundle has one and the control measures are
  empty. This is an open decision (task 1.4).
- **No MRIQC reference.** The reference distribution needs `REFERENCE_DATA_URL`, which is not
  set yet, so bundles have project percentiles only.
- **Skewed project distribution.** Two thirds of MR-ART scans are head-motion acquisitions, so
  project percentiles compare each scan against a mostly corrupted cohort. Project-outlier
  flags, and the targeted views they trigger, are rare. In a two-participant check, a score-3
  scan had no flag.
- **Native views.** MR-ART has no preprocessed images, so views are drawn from the raw,
  defaced T1w with a threshold head mask.
- **Cost.** A two-participant dry run estimated about 2,700 input tokens per request. All
  436 scans × 4 variants is about 1,750 requests and 4.7 M input tokens per model.
