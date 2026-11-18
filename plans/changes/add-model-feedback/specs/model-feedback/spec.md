## ADDED Requirements

### Requirement: Feedback schema

The system SHALL define one `QCFeedback` schema with `decision` (`pass`, `fail`,
`uncertain`), `confidence` (`high`, `medium`, `low`), `summary`, `reasons`, `flagged_metrics`,
`recommended_followup` and optional `image_observations`. Every model adapter SHALL validate
replies against it.

#### Scenario: Valid reply

- **WHEN** a model reply is JSON that matches the schema
- **THEN** the stored result has `schema_valid` true and the parsed feedback

#### Scenario: Fenced reply

- **WHEN** a model wraps valid JSON in a Markdown code fence
- **THEN** the fence is removed before validation and the reply is valid

#### Scenario: Invalid reply kept

- **WHEN** a reply does not parse or does not match the schema
- **THEN** the stored result has `schema_valid` false, the raw reply and the validation errors

### Requirement: Consistency validation

The system SHALL check a schema-valid reply against its bundle and record every failed rule
in `consistency_errors`. Rules: each flagged metric is flagged in the bundle; each flagged
metric appears in a reason; the reason count is within the configured limits; follow-up is
present when the decision is not `pass`.

#### Scenario: Metric not flagged in bundle

- **WHEN** a reply flags a metric that the bundle does not flag
- **THEN** `consistency_errors` names that metric

#### Scenario: Missing follow-up

- **WHEN** the decision is `fail` and `recommended_followup` is empty
- **THEN** `consistency_errors` contains the follow-up rule

#### Scenario: Consistent reply

- **WHEN** a reply satisfies every rule
- **THEN** `consistency_errors` is empty

### Requirement: Traceable feedback file

The system SHALL write one `feedback.json` per bundle and model run, beside `bundle.json`. It
SHALL record the adapter name, model id, generation settings, prompt hash, bundle schema
version and timestamp, together with the raw reply and validation outcome.

#### Scenario: Error and success use one file

- **WHEN** a run fails after an earlier run succeeded
- **THEN** `feedback.json` holds only the latest result and no stale result file remains

#### Scenario: Skip unchanged

- **WHEN** feedback exists for the same model id and prompt hash and `--overwrite` is not set
- **THEN** the bundle is skipped

### Requirement: Model adapter interface

The system SHALL define an adapter interface `send(bundle_dir) -> FeedbackResult`. Adapters
SHALL import model SDKs only when used, so the core package runs without them.

#### Scenario: Core without optional dependencies

- **WHEN** `anthropic` and `openai` are not installed
- **THEN** `ui/evidence_bundle/feedback.py` imports and its tests pass

### Requirement: Independent model judgment

The prompt SHALL NOT contain the rater's QC verdict. Adapters SHALL leave the "Rater QC" section
of `PACKAGE.md` out of the prompt; `PACKAGE.md` itself keeps it for human readers.

#### Scenario: Bundle with rater QC

- **WHEN** a bundle's `PACKAGE.md` has a "Rater QC" section with a rater's verdict
- **THEN** the rendered prompt has every other section and no rater verdict

### Requirement: Image delivery

An image-aware adapter SHALL send the bundle's view images to the model. An IQMs-only variant
SHALL send no images. A cloud adapter SHALL refuse to send images unless the user sets an
explicit data-use acknowledgement.

#### Scenario: Image variant

- **WHEN** the Claude adapter runs in image mode with the acknowledgement set
- **THEN** each file in `views/` is attached to the request

#### Scenario: No acknowledgement

- **WHEN** the Claude adapter runs in image mode without the acknowledgement
- **THEN** it exits with an error before any request is sent

### Requirement: Configurable cloud endpoint

A cloud adapter SHALL accept an optional endpoint URL and SHALL record the endpoint used in the
feedback metadata.

#### Scenario: Custom endpoint

- **WHEN** the Claude adapter runs with `--base_url https://proxy.example.org`
- **THEN** the request goes to that endpoint and `feedback.json` records it

### Requirement: OpenAI-compatible endpoint

The system SHALL provide an adapter for any OpenAI-compatible chat completions endpoint. It
SHALL require the endpoint URL and model id, send the bundle's views as images in image
mode, request the `QCFeedback` JSON schema as the response format, apply the data-use
acknowledgement rule to every endpoint, and record the endpoint in the feedback metadata.

#### Scenario: Self-hosted model

- **WHEN** the adapter runs with `--base_url http://gpu-host:8000/v1`, a model id and the
  acknowledgement set
- **THEN** each file in `views/` is attached, the request asks for the `QCFeedback` schema and
  `feedback.json` records the endpoint

#### Scenario: Local endpoint still needs the acknowledgement

- **WHEN** the adapter runs in image mode against `http://localhost:8000/v1` without the
  acknowledgement
- **THEN** it exits with an error before any request is sent

#### Scenario: Server ignores the response format

- **WHEN** the server replies with free text that contains a valid JSON object
- **THEN** the reply is parsed and `schema_valid` is true

### Requirement: Batch feedback CLI

The system SHALL provide a CLI that runs one adapter over a tree of bundles and continues past
per-bundle errors.

#### Scenario: One bundle fails

- **WHEN** the adapter raises an error for one bundle
- **THEN** that bundle's `feedback.json` records the error and the other bundles are processed

### Requirement: Contrast support respected

The batch CLI SHALL NOT send a bundle with `support` `unsupported` to a model, and SHALL write
a `feedback.json` with status `skipped_unsupported` for it. Every `feedback.json` SHALL record
the bundle's `support` and `context_suffix`.

#### Scenario: Unsupported bundle skipped

- **WHEN** the batch CLI reaches a `PDw` bundle with `support` `unsupported`
- **THEN** no request is sent and `feedback.json` has status `skipped_unsupported`

#### Scenario: Fallback bundle sent

- **WHEN** the batch CLI reaches a `FLAIR` bundle with `support` `fallback`
- **THEN** the adapter is called and `feedback.json` records `context_suffix` `T2w`
