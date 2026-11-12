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

### Requirement: Control scans

The evaluation SHALL include label-clean scans with targeted views added in control mode, and
SHALL report the false-confirmation rate on them.

#### Scenario: False confirmation

- **WHEN** the model flags the metric family of a control scan's targeted view
- **THEN** the scan counts as a false confirmation

### Requirement: Evaluation report

The system SHALL report schema validity, consistency validity, agreement with labels with and
without `uncertain`, and the false-confirmation rate, per combination, with sample size and
seed.

#### Scenario: Report from TSV only

- **WHEN** the report runs on a results TSV
- **THEN** it produces the same report without access to images or models
