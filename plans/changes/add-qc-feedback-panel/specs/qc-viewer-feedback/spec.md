## ADDED Requirements

### Requirement: Feedback location in qc.json

A QC task in `qc.json` SHALL accept an optional `feedback_path`, resolved with the same
placeholder substitution as other per-scan paths.

#### Scenario: Key absent

- **WHEN** no task in `qc.json` has `feedback_path`
- **THEN** the configuration parses and the review page shows no feedback panel

#### Scenario: Placeholders resolved

- **WHEN** `feedback_path` contains `[[NIPOPPY_BIDS_PARTICIPANT_ID]]`
- **THEN** the panel reads the file for the current participant

### Requirement: Feedback panel

For tasks with `feedback_path`, the review page SHALL offer a "Model feedback" panel that can
be toggled like the other panels. It SHALL show decision, confidence, summary, reasons, flagged
metrics, image observations, model id and timestamp, labelled as advisory.

#### Scenario: Valid feedback shown

- **WHEN** the panel is on, the mode is `shown`, and a valid, consistent `feedback.json` exists
- **THEN** the panel shows its fields and the advisory label

#### Scenario: Toggled off

- **WHEN** the rater turns the panel off
- **THEN** no feedback content is rendered

### Requirement: Configurable feedback display mode

The application SHALL accept `--feedback_mode` with values `shown` (default) and
`after_rating`. In `after_rating` mode the panel content SHALL stay hidden until the scan has a
rating other than the default.

#### Scenario: Shown mode

- **WHEN** the mode is `shown`
- **THEN** feedback content is visible before the scan is rated

#### Scenario: After-rating mode

- **WHEN** the mode is `after_rating` and the scan has no rating yet
- **THEN** the panel shows a placeholder instead of the feedback
- **AND** the feedback appears after the rater saves a scan rating

### Requirement: Feedback rating

The panel SHALL let the rater rate valid feedback as `agree`, `partial` or `disagree`, with
optional notes, and SHALL save the rating with the scan's QC record.

#### Scenario: Feedback rated

- **WHEN** the rater selects `partial` and writes a note
- **THEN** the saved record has `feedback_rating` `partial` and the note in `feedback_notes`

#### Scenario: Invalid feedback not rateable

- **WHEN** `schema_valid` is false
- **THEN** the panel shows that the feedback is invalid and offers no feedback rating control

### Requirement: Feedback use recorded in the export

The `*_qc_status.tsv` export SHALL include `feedback_shown`, `feedback_model_id`,
`feedback_rating` and `feedback_notes`. `feedback_shown` SHALL be true only if feedback content
was rendered for the task before that rating was saved. The columns SHALL be empty when the
task has no feedback configured. Existing files without these columns SHALL still merge.

#### Scenario: Rated with feedback in view

- **WHEN** the mode is `shown` and the rater saves a scan rating
- **THEN** the row has `feedback_shown` true and the feedback's model id

#### Scenario: Rated blind

- **WHEN** the mode is `after_rating` and the rater saves the first scan rating
- **THEN** the row has `feedback_shown` false

#### Scenario: No feedback configured

- **WHEN** the task has no `feedback_path`
- **THEN** the four feedback columns are empty

#### Scenario: Old export merged

- **WHEN** an existing TSV without the feedback columns is merged with a new record
- **THEN** the written file has all columns and the old rows have empty feedback values

### Requirement: Graceful degradation

The panel SHALL show a short notice and leave the rest of the page working when the feedback
file is missing, unreadable, schema-invalid or inconsistent.

#### Scenario: Missing file

- **WHEN** the panel is on and the resolved `feedback.json` does not exist
- **THEN** the panel says no feedback is available and the rating controls work

#### Scenario: Inconsistent feedback

- **WHEN** `consistency_errors` is not empty
- **THEN** the panel shows the feedback with a warning listing the errors

#### Scenario: Stale feedback

- **WHEN** the scan's `bundle.json` is newer than its `feedback.json`
- **THEN** the panel shows a staleness warning

### Requirement: Scan rating independent of model output

The application SHALL NOT call a model, and model feedback SHALL NOT set, pre-fill or change
the scan rating.

#### Scenario: Rating untouched

- **WHEN** feedback with decision `fail` is shown and the rater has not rated
- **THEN** the scan rating control keeps the configured default rating
