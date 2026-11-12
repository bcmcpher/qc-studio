## 1. Labelled data — `sandbox/evaluation/download.py`

- [ ] 1.1 Choose the dataset with the maintainers; record licence and access terms in `sandbox/evaluation/README.md`
- [ ] 1.2 Write the download script to `--data_dir` outside the repo; fetch IQMs, images needed for views, and labels
- [ ] 1.3 Write the label-mapping table to `pass` / `fail` / `uncertain`
- [ ] 1.4 Build bundles for a stratified, seeded sample with the export CLI; include control-mode scans

## 2. Runner — `sandbox/evaluation/run_eval.py`

- [ ] 2.1 Define cells: view set × reason stated/hidden × adapter
- [ ] 2.2 Run adapters through `run_feedback.py`, or read existing `feedback.json` files produced elsewhere
- [ ] 2.3 Add a dry-run mode that prints request count and token estimate
- [ ] 2.4 Write one TSV row per (scan, cell)
- [ ] 2.5 Tests on two synthetic bundles with a fake adapter

## 3. Report — `sandbox/evaluation/report.py`

- [ ] 3.1 Compute schema validity, consistency validity, agreement with labels (with and without `uncertain`), false-confirmation rate on controls
- [ ] 3.2 Report rater agreement where the dataset has several raters
- [ ] 3.3 Report `supported` and `fallback` bundles separately, per contrast
- [ ] 3.4 Write a Markdown report with sample size, seed, model ids and prompt hashes

## 4. Decisions back to other changes

- [ ] 4.1 Recommend the core view count; update `add-evidence-bundle-export` task 3.3 note
- [ ] 4.2 Recommend a default adapter and whether the feedback panel is offered to all projects
- [ ] 4.3 Draft the #40 comment for the user to post
