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
- Agreement threshold that would justify enabling the panel by default.
