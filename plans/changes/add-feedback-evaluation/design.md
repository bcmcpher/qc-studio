## Context

Background: [`evidence_bundle_design.md`](../../../docs/source/development/evidence_bundle_design.md),
section "Evaluation". Candidate labelled data: MRIQC expert ratings for ABIDE and DS030, or
braindr ratings for HBN. Labels are per scan (accept / doubtful / exclude, or a pass score).

## Goals / Non-Goals

**Goals:**

- Reproducible runs: every result row traces to a bundle, a view set, a prompt hash and a
  model id.
- Numbers that answer #40: which view set, whether targeted views bias the model, which model.

**Non-Goals:**

- Training or calibrating a classifier.
- Committing any imaging data or labels.
- A public benchmark.

## Decisions

- **Factorial design.** View set (IQMs only, core, core + targeted) × reason stated or hidden
  × adapter. Each cell runs on the same scan sample.
- **Label mapping.** Map dataset labels to `pass` / `fail` / `uncertain` with a documented
  table; report agreement both with and without `uncertain`.
- **Controls.** A fixed fraction of label-clean scans get targeted views through the control
  mode of `add-evidence-bundle-export`. False-confirmation rate = share of controls where the
  model flags the targeted view's metric family.
- **Sample size.** Stratified sample across sites and labels, sized for the API budget; the
  size and seed are recorded in the report.
- **Data location.** Downloads go to a path outside the repo given by `--data_dir`.
- **Output.** One TSV, one row per (scan, cell): validity flags, decision, label, agreement.
  The report reads only that TSV.
- **Several results per bundle.** `run_eval.py` writes each cell's result to
  `<out>/<cell_id>/<bundle>/feedback.json` under its own output directory. The one
  `feedback.json` beside each bundle, written by `run_feedback.py` and read by the panel, stays
  as it is.
- **Variants at prompt time.** Bundles are exported once. `run_eval.py` makes the view-set and
  hidden-reason variants by filtering `bundle.views` and blanking the targeted-view reason
  before the prompt is built. The export CLI gets no new flags.
- **Blind package** (user decision 2026-11-19). The package a model sees in the evaluation has
  the IQM values, percentiles, flags, outlier score, acquisition table, acquisition deviations
  and the views with their labels. It has no scan identifier (participant, session, pipeline,
  QC task, BIDS name), no rater QC, and no site, scanner fields or file `md5sum` — not in the
  acquisition table, the deviations or the distributions. Each of these can stand in for the
  label (an ID or hash names the scan; site and scanner cluster with labels in multi-site
  data). A distribution shows only whether it was used: its size, filters and note are left
  out, since the project stratum is cut by site and the reference subset by scanner, so a size
  or fallback note can name either. They stay in `bundle.json` and the results TSV for the analysis. No view
  label says "control", and staged views get neutral file names. Flags are computed from the
  IQMs, not by raters, so they stay. The product's export is unchanged.
- **Hidden reason.** Hidden mode drops the kind and rule from each view label and shuffles
  the views, seeded by the BIDS name. Two cues remain: a targeted view adds a second view of a
  plane, and its window can look unlike a core view (the noise view saturates the head). So
  "hidden" removes the stated reason, not every sign that a view is targeted.
- **Control measures** (review finding, 2026-11-19). Control non-pass is the share of control
  scans with a `fail` or `uncertain` decision, in every variant; the `core` variant gives the
  rate for the same scans without the control view. False confirmation (metric) counts a
  flagged metric of the control view's rule; it is near 0 by design, since control views go
  only on scans with no flagged metric and such a flag also fails the consistency check.
- **Final results.** A reply is final whether or not it parses; only errors are resent, so
  reruns do not inflate schema validity.
- **Order.** Section 2 (runner and synthetic tests) comes before section 1, because the dataset
  waits on the maintainers.

## Risks / Trade-offs

- [Dataset licences or access] → confirm terms before download; script fails clearly without
  credentials.
- [MRIQC ratings disagree between raters] → report rater agreement as the ceiling.
- [API cost grows with cells] → dry-run mode prints the request count and token estimate.
- [Local 8B models need a GPU] → run them on lab or HPC hardware; the runner reads existing
  `feedback.json` files so runs can happen elsewhere.

## Open Questions

- Which labelled dataset is available to the group, and under what terms?
- Budget for cloud runs; where 8B+ local models run.
- Agreement threshold that would justify offering the panel to all projects.
- Whether to add the in-study feedback ratings (`feedback_rating` in `*_qc_status.tsv`) to the
  report once enough exist. Deferred (2026-11-19): left out until enough ratings exist.
