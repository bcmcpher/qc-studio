## Context

Background: [`evidence_bundle_design.md`](../../../docs/source/development/evidence_bundle_design.md),
section "Model feedback".

Sandbox state:

- `sandbox/cloud_model_experiments/IQMs_only_exp/run_experiment.py`: `QCDecision` (decision
  `pass|fail|uncertain`, confidence `high|medium|low`, summary, flagged_metrics, reasons,
  recommended_followup). Text-only `messages.create`, `temperature=1.0`, code-fence stripping,
  writes `result.json` or `result_error.json` without deleting the other.
- `sandbox/cloud_model_experiments/image_evidence_exp/`: the template asks for
  `image_observations`, which no validator accepts; the image path is named but never attached.
- `sandbox/local_model_experiments/exp_LLaVA-OneVision-1.5-4B-Instruct/chat_image.py`:
  greedy decoding, first-JSON-object extraction, hand-written check including "4 to 7 reasons".

## Goals / Non-Goals

**Goals:**

- One reply schema and one validator used by every adapter.
- Every stored reply is traceable: model id, adapter, prompt hash, bundle schema version, time.
- Images actually reach image-aware models.

**Non-Goals:**

- Choosing a default model or view set (`add-feedback-evaluation`).
- Showing feedback in the UI (`add-qc-feedback-panel`).
- Calling models from the Streamlit app.

## Decisions

- **Schema and validator in core, adapters in sandbox.** The UI needs to read and validate
  `feedback.json` without optional dependencies. Adapters need `anthropic`/`torch`, so they
  stay in `sandbox/model_adapters/` until evaluation picks what to keep.
- **`QCFeedback` fields.** Keep the `QCDecision` fields and enums. Add optional
  `image_observations: list[str]` (empty for IQMs-only runs) so the image template has a home.
- **Reason count as a consistency rule, not a schema rule.** The schema accepts any list; the
  consistency validator enforces limits from `constants.py`. A reply with the wrong count is
  stored and marked inconsistent, not discarded, so evaluation can count it.
- **One result file per run.** `feedback.json` always holds a `FeedbackResult`: metadata, raw
  reply, `schema_valid`, `consistency_errors`, and the parsed `QCFeedback` when valid. This
  replaces the `result.json`/`result_error.json` pair.
- **Structured output for Claude.** Use tool use with the `QCFeedback` JSON schema as the
  input schema, so the reply is JSON by construction. Keep code-fence stripping for local
  models.
- **Deterministic settings where available.** `temperature=0` for Claude, greedy decoding for
  local models. Record settings in the metadata.
- **Model ids are arguments.** Defaults live in each adapter; the CLI and env var override.
- **Cloud models are a deployment option.** Not only a benchmark. The data-use
  acknowledgement flag stays, so each deployment makes the choice explicitly.
- **Endpoint is an argument.** The Claude adapter accepts an optional `base_url` (CLI
  `--base_url`, env `ANTHROPIC_BASE_URL`) and passes it to the client, so a compatible proxy
  or institutional endpoint works without code changes. The URL is recorded in the
  `FeedbackResult` metadata. Adapters for other API families (for example OpenAI-compatible
  servers for local models) are a later change.

## Risks / Trade-offs

- [Sending MRI views to a cloud API can breach data-use agreements] → the Claude adapter
  refuses to run unless an explicit flag acknowledges this; docs state it.
- [Tool-use output differs from free-text behaviour seen in the sandbox] → evaluation compares
  both on the same bundles before a default is chosen.
- [No local NVIDIA GPU on the dev machine] → LLaVA adapter tested with a stubbed model;
  real runs on lab or HPC hardware.
- [Prompt drift between adapters] → prompts render from the bundle's `PACKAGE.md`; the prompt
  hash is stored.

## Open Questions

- Do adapters move into `ui/` after evaluation, or into a separate optional package? Deferred
  until `add-feedback-evaluation` reports.
- Reason-count limits: keep 4–7 from the sandbox, or derive from the number of bundle flags?
- Which LLaVA-OneVision size is the reference local model (4B now, 8B needs more compute)?
