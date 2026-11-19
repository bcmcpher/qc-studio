## 1. Labelled data — `sandbox/evaluation/download.py`

- [ ] 1.1 Choose the dataset with the maintainers; record licence and access terms in `sandbox/evaluation/README.md`
- [ ] 1.2 Write the download script to `--data_dir` outside the repo; fetch IQMs, images needed for views, and labels
- [ ] 1.3 Write the label-mapping table to `pass` / `fail` / `uncertain`
- [ ] 1.4 Build bundles for a stratified, seeded sample with the export CLI; include control-mode scans

## 2. Runner — `sandbox/evaluation/run_eval.py`

- [x] 2.1 Define cells: view set × reason stated/hidden × adapter
- [x] 2.2 Run adapters through `run_feedback.py`, or read existing `feedback.json` files produced elsewhere
- [x] 2.3 Add a dry-run mode that prints request count and token estimate
- [x] 2.4 Write one TSV row per (scan, cell)
- [x] 2.5 Tests on two synthetic bundles with a fake adapter

As built (section 2):

- Done before section 1 (user decision 2026-11-19): the dataset waits on the maintainers.
- 2.1: four variants per adapter and model, not six: `iqms`, `core`, `core_targeted_stated`,
  `core_targeted_hidden`. The reason mode only matters with targeted views, so IQMs-only and
  core have one variant each. A cell is `<adapter>__<model id>/<variant>`. One invocation runs
  one adapter; more adapters are more invocations into the same `--out_dir`.
- Variants are staged per (bundle, cell) in `OUT/<model_key>/<variant>/<bundle path>/`:
  the variant's `bundle.json` (views filtered), a re-rendered `PACKAGE.md` (export's
  `package_context` and template, with only the "Views" section replaced), copies of the kept
  views renamed `views/view_NN.png` (export names them after kind and rule, and the prompt lists
  each image's path), and `cell.json` (variant, source bundle, whether the scan is a control
  scan, and the targeted and control rules of the views this variant shows). The metadata is
  written before the views, so a view that fails to copy gives an `error` row, not a missing
  one. The adapter's `send()` runs on that folder unchanged, so the prompt hash differs per
  variant. The exported bundle and its `feedback.json` are never touched; bundles under
  `--out_dir` are never read as sources. A cell folder is `<adapter>__<model id>-<hash>`, the
  hash of the raw model id keeping ids that differ only in replaced characters apart.
- No variant says which views are controls. The export's `PACKAGE.md` labels them ", control";
  the runner drops that word, since a model that reads it knows the view is not a real flag.
  "Stated" lists `targeted <plane>, rule <rule>`; "hidden" lists only `<plane> view`, dropping
  the core/targeted kind too, since "targeted" alone suggests a problem.
- 2.2: the runner calls the adapter's `send()` directly, as `run_feedback.py` does, rather than
  shelling out to it. `run_feedback.py` gained `add_adapter_args` and `resolve_model_id` so both
  CLIs share the adapter options. An existing `feedback.json` in a cell folder is read, not
  resent, when it is final: a schema-valid reply, or the skip of an unsupported bundle. An
  error, an invalid reply or an unreadable file is resent. The prompt hash is not rechecked, so
  a re-exported bundle needs `--overwrite`, which removes the old result before restaging.
  Runs made on another host are copied into `OUT` and collected
  with `--collect_only`. An adapter in IQMs-only mode runs only the `iqms` variant.
- 2.3: `--dry_run` prints bundles, variants, requests, kept, skipped unsupported and an input
  token estimate (prompt characters / 4, plus width × height / 750 per PNG, or 1600 when the
  size is unreadable). It needs no credentials and writes nothing.
- 2.4: every run ends by collecting all cell folders under `OUT` into `OUT/results.tsv`
  (`--results` to change). Columns: scan ids, support, source bundle, cell id, adapter, model id,
  variant, view set, reason, view count, `control_scan`, the control and targeted rules of the
  views shown (empty for `iqms` and `core`, which cannot confirm a control view), prompt hash,
  status (`missing` without `feedback.json`), schema and consistency validity, decision,
  confidence, flagged metrics, `control_confirmed` (a flagged metric matches a control rule's
  metrics), label, original label, agreement, error. `--labels` takes a TSV of `bids_name`,
  `label` (`pass`/`fail`/`uncertain`), optional `original_label` — the shape task 1.3 must write; blank lines are skipped, an empty or duplicate `bids_name` is an error.
- 2.5: `ui/tests/test_feedback_evaluation.py` (33 tests): a flagged scan with a targeted noise
  view and a clean scan with the same view as a control.

## 3. Report — `sandbox/evaluation/report.py`

- [ ] 3.1 Compute schema validity, consistency validity, agreement with labels (with and without `uncertain`), false-confirmation rate on controls
- [ ] 3.2 Report rater agreement where the dataset has several raters
- [ ] 3.3 Report `supported` and `fallback` bundles separately, per contrast
- [ ] 3.4 Write a Markdown report with sample size, seed, model ids and prompt hashes

## 4. Decisions back to other changes

- [ ] 4.1 Recommend the core view count; update `add-evidence-bundle-export` task 3.3 note
- [ ] 4.2 Recommend a default adapter and whether the feedback panel is offered to all projects
- [ ] 4.3 Draft the #40 comment for the user to post
