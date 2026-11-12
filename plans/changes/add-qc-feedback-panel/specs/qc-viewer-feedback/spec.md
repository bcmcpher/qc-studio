## ADDED Requirements

### Requirement: Feedback location in qc.json

A QC task in `qc.json` SHALL accept an optional `feedback_path`, resolved with the same
placeholder substitution as other per-scan paths.

#### Scenario: Key absent

- **WHEN** no task in `qc.json` has `feedback_path`
- **THEN** the configuration parses and the review page behaves as before

#### Scenario: Placeholders resolved

- **WHEN** `feedback_path` contains `[[NIPOPPY_BIDS_PARTICIPANT_ID]]`
- **THEN** the panel reads the file for the current participant

### Requirement: Optional feedback panel

The review page SHALL offer a "Model feedback" panel that is off by default and can be toggled
like the other panels. When on, it SHALL show decision, confidence, summary, reasons, flagged
metrics, image observations, model id and timestamp, labelled as advisory.

#### Scenario: Default off

- **WHEN** a rater opens the review page without changing panel settings
- **THEN** the feedback panel is not shown

#### Scenario: Valid feedback shown

- **WHEN** the panel is on and a valid, consistent `feedback.json` exists
- **THEN** the panel shows its fields and the advisory label

### Requirement: Graceful degradation

The panel SHALL show a short notice and leave the rest of the page working when the feedback
file is missing, unreadable, schema-invalid or inconsistent.

#### Scenario: Missing file

- **WHEN** the panel is on and the resolved `feedback.json` does not exist
- **THEN** the panel says no feedback is available and the rating controls work

#### Scenario: Schema-invalid file

- **WHEN** `schema_valid` is false
- **THEN** the panel shows only that the feedback is invalid

#### Scenario: Inconsistent feedback

- **WHEN** `consistency_errors` is not empty
- **THEN** the panel shows the feedback with a warning listing the errors

#### Scenario: Stale feedback

- **WHEN** the scan's `bundle.json` is newer than its `feedback.json`
- **THEN** the panel shows a staleness warning

### Requirement: Ratings independent of model output

The application SHALL NOT call a model, and model feedback SHALL NOT set, pre-fill or change a
rating. The columns of `*_qc_status.tsv` SHALL be unchanged.

#### Scenario: Rating untouched

- **WHEN** feedback with decision `fail` is shown and the rater has not rated
- **THEN** the rating control keeps the configured default rating

#### Scenario: Export unchanged

- **WHEN** a rating is saved with the panel on
- **THEN** the written TSV has the same columns as with the panel off
