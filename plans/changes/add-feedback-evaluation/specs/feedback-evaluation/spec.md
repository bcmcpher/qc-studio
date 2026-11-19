## ADDED Requirements

### Requirement: Labelled dataset retrieval

The system SHALL download a labelled QC dataset to a directory outside the repository and
SHALL map its labels to `pass`, `fail` or `uncertain` with a documented table.

#### Scenario: Data stays out of the repository

- **WHEN** the download script runs
- **THEN** no file is written inside the repository working tree

#### Scenario: Label mapping

- **WHEN** a scan has a dataset label
- **THEN** the evaluation uses the mapped label and keeps the original

### Requirement: Factorial evaluation runner

The system SHALL evaluate every combination of view set (IQMs only, core, core + targeted),
targeted-view reason (stated or hidden) and model adapter on the same scan sample, and SHALL
write one TSV row per scan and combination.

#### Scenario: Traceable row

- **WHEN** a result row is written
- **THEN** it records the scan, view set, reason mode, adapter, model id and prompt hash

#### Scenario: Dry run

- **WHEN** the runner is called with dry-run
- **THEN** it prints the request count and a token estimate and sends no request

#### Scenario: Reuse external results

- **WHEN** `feedback.json` files for a cell already exist
- **THEN** the runner reads them instead of calling the adapter

### Requirement: Blind evaluation package

The package sent to a model in the evaluation SHALL contain no scan identifier, no rater QC,
and no site, scanner or file-hash field, and SHALL NOT say which views are controls. These
fields SHALL stay available to the analysis.

#### Scenario: No identifying field in the prompt

- **WHEN** a bundle with a participant id, site, scanner metadata, `md5sum` and rater QC is
  sent in any cell
- **THEN** none of those values appear in the prompt or in an attached image's name

#### Scenario: No distribution size

- **WHEN** the package describes the project or reference distribution
- **THEN** it says only whether the distribution was used, without its size, filters or note

#### Scenario: Identifiers kept for analysis

- **WHEN** the results TSV is written
- **THEN** each row still records the scan's participant, session and BIDS name

### Requirement: Control scans

The evaluation SHALL include label-clean scans with targeted views added in control mode, and
SHALL report the false-confirmation rate on them.

#### Scenario: False confirmation

- **WHEN** the model flags the metric family of a control scan's targeted view
- **THEN** the scan counts as a false confirmation

#### Scenario: Non-pass on a control scan

- **WHEN** the model returns `fail` or `uncertain` for a control scan
- **THEN** the row counts as a control non-pass, reported for every variant so the variants
  without the control view give a baseline

### Requirement: Evaluation report

The system SHALL report schema validity, consistency validity, agreement with labels with and
without `uncertain`, and the false-confirmation rate, per combination, with sample size and
seed.

#### Scenario: Report from TSV only

- **WHEN** the report runs on a results TSV
- **THEN** it produces the same report without access to images or models
