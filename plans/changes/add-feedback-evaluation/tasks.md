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
  the variant's `bundle.json` (views filtered), a blind `PACKAGE.md` (below), copies of the kept
  views renamed `views/view_NN.png` (export names them after kind and rule, and the prompt lists
  each image's path), and `cell.json` (variant, source bundle, whether the scan is a control
  scan, and the targeted and control rules of the views this variant shows). The metadata is
  written before the views, so a view that fails to copy gives an `error` row, not a missing
  one. The adapter's `send()` runs on that folder unchanged, so the prompt hash differs per
  variant. The exported bundle and its `feedback.json` are never touched; folders with a
  `cell.json` are never read as sources, so `--out_dir` may sit inside the bundle root or hold
  it. A cell folder is `<adapter>__<model id>-<hash>`; the hash covers the raw model id, the
  endpoint (`--base_url` or the adapter's env variable) and `--max_tokens`, so one model name on
  two servers gets two folders. The endpoint is not written into the name.
- No variant says which views are controls. The export's `PACKAGE.md` labels them ", control";
  the runner drops that word, since a model that reads it knows the view is not a real flag.
  "Stated" lists `targeted <plane>, rule <rule>`; "hidden" lists only `<plane> view`, dropping
  the core/targeted kind too, since "targeted" alone suggests a problem. Hidden also shuffles
  the views, seeded by the BIDS name, since targeted views otherwise always come last.
- Blind package (review finding, user decision 2026-11-19; see design.md): `PACKAGE.md` is
  rendered from the export's `package_context` with `sandbox/evaluation/PACKAGE_eval.md`, the
  export template without the scan-identifier header and the "Rater QC" section.
  `WITHHELD_FIELDS` (`site`, `md5sum` and every `ScannerMetadata` field) are removed from the
  acquisition table and the deviations. Each distribution shows only `used` or `none`: its size,
  filters and note are left out, since a site- or scanner-cut stratum size can name the site
  and a note can hold raw error text. `mriqc_version` stays.
- 2.2: the runner calls the adapter's `send()` directly, as `run_feedback.py` does, rather than
  shelling out to it. `run_feedback.py` gained `add_adapter_args` and `resolve_model_id` so both
  CLIs share the adapter options. An existing `feedback.json` in a cell folder is read, not
  resent, when it is final: any reply, schema-valid or not, or the skip of an unsupported
  bundle. Resending invalid replies until one parses would inflate schema validity. An error or
  an unreadable file is resent. `cell.json` records a staging hash (prompt template, blind
  package, view names and bytes); a cell whose hash differs from what it would send now is
  resent, so a changed template, blinding rule or re-exported bundle needs no `--overwrite`.
  `--overwrite` removes the old result before restaging. `run_feedback.py` itself still resends
  invalid replies, as the product wants a valid one.
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
  metrics), `control_nonpass` (control scans only, every variant: the decision is not `pass`),
  label, original label, agreement, error. A cell folder that cannot be read gets no row; it is
  logged and the run exits 1. `--labels` takes a TSV of `bids_name`,
  `label` (`pass`/`fail`/`uncertain`), optional `original_label` — the shape task 1.3 must write; blank lines are skipped, an empty or duplicate `bids_name` is an error.
- 2.5: `ui/tests/test_feedback_evaluation.py` (35 tests): a flagged scan with a targeted noise
  view and a clean scan with the same view as a control.

## 3. Report — `sandbox/evaluation/report.py`

- [x] 3.1 Compute schema validity, consistency validity, agreement with labels (with and without `uncertain`), false-confirmation rate on controls
- [x] 3.2 Report rater agreement where the dataset has several raters
- [x] 3.3 Report `supported` and `fallback` bundles separately, per contrast
- [x] 3.4 Write a Markdown report with sample size, seed, model ids and prompt hashes

As built (section 3):

- `report.py RESULTS [--seed S] [--rater_labels TSV] [--out PATH]` reads only the results TSV and
  the optional rater-label TSV; default output `report.md` beside the TSV. The report names the
  TSV by file name and the first 16 hex digits of its SHA-256, not by its full path.
- 3.1: per cell. Schema validity is over sent rows (`ok` + `error`), so staging, transport and
  refusal errors count against it; `missing` rows are counted, not in the rate. Consistency
  validity is over schema-valid rows. Agreement is computed from `decision` and `label`, 3-class
  and pass/fail (rows where either is `uncertain` left out), each with Cohen's kappa, since
  raw agreement is high on a pass-heavy sample. Two control measures (review finding,
  2026-11-19): control non-pass, the share of control-scan rows with a `fail` or `uncertain`
  decision, in every variant, so `core` gives the baseline for the same scans without the
  control view; and false confirmation (metric), over rows with a `control_confirmed` value.
  The metric form is near 0 by design, since control views go only on scans with no flagged
  metric and flagging one also fails the consistency check.
- 3.2: `--rater_labels` takes `bids_name`, `rater`, `label` (mapped labels; blank lines skipped,
  a rater labelling a scan twice is an error). Pairwise agreement and kappa, 3-class and
  pass/fail, on the sampled scans both raters labelled. Task 1.3 must write this file when the
  dataset has several raters.
- 3.3: a second table splits each cell by support tier and contrast (`suffix`). Unsupported
  scans are counted in the header and left out of every table.
- 3.4: header has sample size (scans, labelled scans, control scans), seed, cell count. The seed
  is a CLI option, since the TSV does not carry it; section 1 decides where the sampler records
  it. The cell table lists adapter, model id, variant, the number of distinct prompt hashes and
  a digest over them (equal digests mean equal prompts); one hash per row stays in the TSV.
- Tests: 10 more in `ui/tests/test_feedback_evaluation.py` (45 total), including a report built
  from a copied TSV after the cell folders are deleted.

Review fixes (2026-11-19): invalid replies kept; staging hash; endpoint in the cell key; empty
`CLAUDE_MODEL` falls back to the default; staged cells found by `cell.json`; broken cells exit
1; distribution size, filters and note withheld; hidden views shuffled; control non-pass.
Tests: 52 in `ui/tests/test_feedback_evaluation.py`, one more in `test_model_adapters.py`.

## 4. Decisions back to other changes

- [ ] 4.1 Recommend the core view count; update `add-evidence-bundle-export` task 3.3 note
- [ ] 4.2 Recommend a default adapter and whether the feedback panel is offered to all projects
- [ ] 4.3 Draft the #40 comment for the user to post
