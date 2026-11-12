## ADDED Requirements

### Requirement: Schema-versioned bundle

The system SHALL describe each evidence bundle with a pydantic model that carries a
`schema_version`, the QC-Studio and MRIQC versions, the participant, session, pipeline and QC
task identifiers, and the BIDS `suffix` of the scan.

#### Scenario: Round trip through JSON

- **WHEN** a bundle is serialized to `bundle.json` and loaded again
- **THEN** the loaded bundle equals the original

#### Scenario: Invalid metric context rejected

- **WHEN** a metric has a `direction_of_concern` value that is not in the allowed set
- **THEN** validation fails with an error naming the metric

### Requirement: Allowlisted acquisition metadata

The system SHALL record acquisition metadata in four groups — `scanner`, `sequence`,
`geometry` and `provenance` — limited to the allowlisted fields in the design. Geometry SHALL
come from the NIfTI header where the header holds it. Fields outside the allowlist SHALL NOT
appear in any export output.

#### Scenario: Identifying fields dropped

- **WHEN** the sidecar contains `DeviceSerialNumber`, `InstitutionName` and `AcquisitionTime`
- **THEN** none of them appears in `bundle.json`, `PACKAGE.md` or `acquisition_summary.tsv`

#### Scenario: Geometry from the image

- **WHEN** a scan is exported
- **THEN** the bundle records the image shape, voxel size and orientation codes read from the NIfTI header

#### Scenario: Missing sidecar field

- **WHEN** an allowlisted field is absent from the sidecar
- **THEN** the bundle records it as null and export continues

### Requirement: Protocol signature and like-for-like comparison

The system SHALL compute a protocol signature from the scan's suffix, acquisition type, field
strength, manufacturer, rounded TR, TE, TI, flip angle and voxel size. Project statistics
SHALL use only scans in the same signature stratum, dropping signature fields in the fixed
fallback order when the stratum is below the minimum size. `suffix`, `MRAcquisitionType` and
`MagneticFieldStrength` SHALL never be dropped. The bundle SHALL record the signature fields
used and the stratum size.

#### Scenario: Contrasts never mixed

- **WHEN** a study contains `T1w` and `T2w` scans
- **THEN** no `T2w` scan is part of a `T1w` scan's project stratum

#### Scenario: Off-protocol scan excluded

- **WHEN** one scan has a different TR from the rest of its stratum
- **THEN** that scan is not part of the other scans' stratum

#### Scenario: Fallback recorded

- **WHEN** the full-signature stratum is below the minimum size
- **THEN** fields are dropped in the fixed order until the size is reached
- **AND** the bundle lists the fields that were used

#### Scenario: No adequate stratum

- **WHEN** the stratum is below the minimum size with only the never-dropped fields left
- **THEN** project percentiles are null and the bundle records why

### Requirement: Acquisition check

The system SHALL compare each signature field of a scan with the modal value among scans of
the same suffix (and site, when known), and SHALL record every difference as an acquisition
deviation with the field, the scan's value, the expected value and the share of scans with the
expected value. Deviations SHALL appear in `bundle.json`, `PACKAGE.md` and a project-level
`acquisition_summary.tsv`.

#### Scenario: Different echo time

- **WHEN** 19 of 20 `T1w` scans have TE 2.9 ms and one has TE 3.5 ms
- **THEN** that scan's bundle records a deviation on `EchoTime` with expected value 2.9 ms and share 0.95

#### Scenario: Within rounding

- **WHEN** two scans differ in TR by less than the rounding step
- **THEN** no deviation is recorded

### Requirement: Supported structural contrasts

The system SHALL support the structural suffixes `T1w` and `T2w` through one structural
context file with per-suffix overrides. In the `T2w` context, `wm2max` SHALL be
`context_dependent`. Other structural suffixes SHALL be rejected with an error.

#### Scenario: T2w override

- **WHEN** the context for `T2w` is loaded
- **THEN** `wm2max` has direction `context_dependent` and all other structural IQMs match the `T1w` context

#### Scenario: Unsupported suffix

- **WHEN** a bundle is requested for a `FLAIR` scan
- **THEN** export fails for that scan with an error naming the suffix

### Requirement: Per-metric statistical context

The system SHALL give each metric its value, direction of concern, project percentile,
reference percentile, flags and context category (`scan`, `protocol`, `project` or `normal`).
Reference percentiles SHALL use `filter_reference_iqm` with the signature fields that the
reference data holds.

#### Scenario: Direction-aware flag

- **WHEN** a `higher_worse` metric is above the high threshold
- **THEN** the metric is flagged
- **AND** the same value on a `lower_worse` metric is not flagged

#### Scenario: Two-sided flag

- **WHEN** an `outside_range` metric is below the low threshold
- **THEN** the metric is flagged

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

The system SHALL render core views for every scan after reorienting to RAS, with display
resampled to isotropic millimetres, whole-volume percentile windowing, fixed image size and
fixed labels. Slice positions SHALL be fixed MNI coordinates when a template-space image
exists, and fractions of the brain-mask bounding box otherwise. Each view SHALL record its
placement method.

#### Scenario: Byte-identical output

- **WHEN** the same input is rendered twice in the same environment
- **THEN** the PNG files are byte-identical

#### Scenario: Non-RAS input

- **WHEN** the input volume is stored in LPS orientation
- **THEN** the rendered views match those of the RAS-reoriented volume

#### Scenario: Anisotropic voxels

- **WHEN** the input has 1 × 1 × 3 mm voxels
- **THEN** the rendered views have the correct physical aspect ratio

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
`PACKAGE.md` and `views/`, plus `<out_dir>/acquisition_summary.tsv`. It SHALL merge the rater's
QC when a `*_qc_status.tsv` is given.

#### Scenario: Export sample data

- **WHEN** the CLI runs on a copy of `sample_data/`
- **THEN** each scan directory holds a `bundle.json` that validates against the schema
- **AND** `acquisition_summary.tsv` has one row per exported scan

#### Scenario: Rater QC merged

- **WHEN** a `*_qc_status.tsv` with a rating for the scan is given
- **THEN** the bundle includes that rating and its notes
