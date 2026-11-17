## Why

An evidence bundle is only useful once a model reads it and its reply can be trusted. The
sandbox has three model scripts with no shared interface: the Claude script sends text only
(no image ever reached the model), and the two validators disagree (pydantic `QCDecision` in
`run_experiment.py` versus a hand-written dict check in the LLaVA `chat_image.py`). Replies
that parse can still contradict the bundle; the LLaVA 4B run flagged metrics its reasons did
not mention. This change defines one feedback schema, one validator and one adapter interface.

## What Changes

- `QCFeedback` reply schema in the core package, unified from the two sandbox validators.
- Consistency validation of a reply against its bundle, in core and tested in CI.
- A model adapter interface, `send(bundle_dir) -> FeedbackResult`.
- A Claude adapter that attaches the bundle's view images, plus an IQMs-only variant.
- An OpenAI-compatible HTTP adapter for self-hosted models (for example LLaVA-OneVision
  behind vLLM), the expected deployment path. It replaces the in-process LLaVA script.
- A batch CLI that runs one adapter over a tree of bundles and writes `feedback.json` beside
  each `bundle.json`.
- Adapters import their SDKs lazily; their dependencies stay optional.

## Capabilities

### New Capabilities

- `model-feedback`: request, validate and store structured model feedback for an evidence
  bundle.

### Modified Capabilities

- None. (`evidence-bundle` is unchanged; this change only reads bundles.)

## Impact

- New core code: `ui/evidence_bundle/feedback.py` (schema, validator, `feedback.json` I/O).
  No new runtime dependencies.
- New optional code: `sandbox/model_adapters/` (`base.py`, `claude.py`, `openai_compat.py`,
  `run_feedback.py`, `prompt.md`). Depends on `anthropic` and `openai` through
  `sandbox/requirements-experiments.txt`. No `torch` or `transformers`: models run on the
  server.
- Retired: `QCDecision` in `run_experiment.py`, `validate_result` in `chat_image.py` (the
  scripts may stay as history but stop being the reference).
- Depends on `add-evidence-bundle-export`. Consumed by `add-feedback-evaluation` and
  `add-qc-feedback-panel`.
