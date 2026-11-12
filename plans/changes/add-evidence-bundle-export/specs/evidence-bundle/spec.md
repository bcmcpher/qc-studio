## ADDED Requirements

### Requirement: Schema-versioned bundle

The system SHALL describe each evidence bundle with a pydantic model that carries a
`schema_version`, the QC-Studio and MRIQC versions, the participant, session, pipeline and QC
task identifiers, and selected acquisition metadata.

#### Scenario: Round trip through JSON

- **WHEN** a bundle is serialized to `bundle.json` and loaded again
- **THEN** the loaded bundle equals the original

#### Scenario: Invalid metric context rejected

- **WHEN** a metric has a `direction_of_concern` value that is not in the allowed set
- **THEN** validation fails with an error naming the metric

### Requirement: Per-metric statistical context

The system SHALL give each metric its value, direction of concern, project percentile,
reference percentile, flags and context category (`scan`, `protocol`, `project` or `normal`).
Project percentiles SHALL use robust statistics within the scan's stratum. Reference
percentiles SHALL use `filter_reference_iqm`.

#### Scenario: Direction-aware flag

- **WHEN** a `higher_worse` metric is above the high threshold
- **THEN** the metric is flagged
- **AND** the same value on a `lower_worse` metric is not flagged

#### Scenario: Protocol effect

- **WHEN** a metric is normal in the project but an outlier in the reference
- **THEN** its context category is `protocol`

#### Scenario: Filter recorded

- **WHEN** a bundle is built
- **THEN** it records the reference filter applied, the reference row count and the project stratum

### Requirement: Multivariate outlier score

The system SHALL compute a robust Mahalanobis distance over standardized IQMs and list the
metrics that contribute most.

#### Scenario: Injected outlier

- **WHEN** one synthetic scan has shifted values on several correlated metrics
- **THEN** it has the highest outlier score
- **AND** the shifted metrics are its top contributors

### Requirement: Deterministic core views

The system SHALL render core views for every scan after reorienting to RAS, with whole-volume
percentile windowing, fixed image size and fixed labels. Slice positions SHALL be fixed MNI
coordinates when a template-space image exists, and fractions of the brain-mask bounding box
otherwise. Each view SHALL record its placement method.

#### Scenario: Byte-identical output

- **WHEN** the same input is rendered twice in the same environment
- **THEN** the PNG files are byte-identical

#### Scenario: Non-RAS input

- **WHEN** the input volume is stored in LPS orientation
- **THEN** the rendered views match those of the RAS-reoriented volume

#### Scenario: No template-space image

- **WHEN** no MNI-space image is available for the scan
- **THEN** the bounding-box fallback is used and recorded in the view reference

### Requirement: Rule-based targeted views

The system SHALL add a targeted view only when a rule in the rule table fires on a bundle flag.
A control mode SHALL add targeted views to scans with no flags.

#### Scenario: Rule fires on its flag only

- **WHEN** a motion metric is flagged and no noise metric is flagged
- **THEN** the motion view is added and the noise view is not

#### Scenario: Control mode

- **WHEN** control mode is on and the scan has no flags
- **THEN** targeted views are added and marked as controls

### Requirement: Bundle export CLI

The system SHALL provide a CLI that takes `--dataset_dir`, `--participant_list`, `--qc_json`,
`--qc_task` and `--out_dir`, and writes
`<out_dir>/<participant_id>/<session_id>/<pipeline>/<qc_task>/` containing `bundle.json`,
`PACKAGE.md` and `views/`. It SHALL merge the rater's QC when a `*_qc_status.tsv` is given.

#### Scenario: Export sample data

- **WHEN** the CLI runs on a copy of `sample_data/`
- **THEN** each scan directory holds a `bundle.json` that validates against the schema

#### Scenario: Rater QC merged

- **WHEN** a `*_qc_status.tsv` with a rating for the scan is given
- **THEN** the bundle includes that rating and its notes
