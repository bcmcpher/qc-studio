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
  `feedback.json` without optional dependencies. Adapters need `anthropic`/`openai`, so they
  stay in `sandbox/model_adapters/` until evaluation picks what to keep.
- **`QCFeedback` fields.** Keep the `QCDecision` fields and enums. Add optional
  `image_observations: list[str]` (empty for IQMs-only runs) so the image template has a home.
- **Reason count as a consistency rule, not a schema rule.** The schema accepts any list; the
  consistency validator enforces limits from `constants.py`. A reply with the wrong count is
  stored and marked inconsistent, not discarded, so evaluation can count it.
- **Reason limits 1 to 7.** The sandbox required 4 to 7, which forces filler reasons for a
  clean scan with no flags. `MIN_REASONS = 1`, `MAX_REASONS = 7` in `constants.py`.
- **Prompt template in the adapter layer.** `PACKAGE.md` is evidence only (the export change
  removed the task and reply rules from it). A template in `sandbox/model_adapters/` holds the
  role, task and reply rules and inserts `PACKAGE.md`; the prompt hash covers the whole
  rendered prompt.
- **No rater verdict in the prompt.** The template drops the "Rater QC" section of `PACKAGE.md`
  (decided 2026-11-18). A rater verdict in the prompt would anchor the model, and the
  evaluation compares model and rater decisions, which must be independent. `PACKAGE.md` keeps
  the section for human readers.
- **One result file per run.** `feedback.json` always holds a `FeedbackResult`: metadata, raw
  reply, `schema_valid`, `consistency_errors`, and the parsed `QCFeedback` when valid. This
  replaces the `result.json`/`result_error.json` pair.
- **Structured output for Claude.** Use tool use with the `QCFeedback` JSON schema as the
  input schema, so the reply is JSON by construction. Keep code-fence stripping for local
  models.
- **Deterministic settings where available.** `temperature=0` for Claude, greedy decoding for
  local models. Record settings in the metadata.
- **Respect the bundle's support tier.** `unsupported` bundles are never sent; the CLI writes
  a `skipped_unsupported` result so the panel can say why there is no feedback. `fallback`
  bundles are sent; `PACKAGE.md` already states the context suffix used.
- **Model ids are arguments.** Defaults live in each adapter; the CLI and env var override.
- **Cloud models are a deployment option.** Not only a benchmark. The data-use
  acknowledgement flag stays, so each deployment makes the choice explicitly.
- **Endpoint is an argument.** The Claude adapter accepts an optional `base_url` (CLI
  `--base_url`, env `ANTHROPIC_BASE_URL`) and passes it to the client, so a compatible proxy
  or institutional endpoint works without code changes. The URL is recorded in the
  `FeedbackResult` metadata.
- **Self-hosted models through an OpenAI-compatible API.** Most deployments are expected to
  serve a model (for example LLaVA-OneVision under vLLM) behind an OpenAI-compatible HTTP
  endpoint, remote or on a local GPU workstation. One adapter, `openai_compat.py`, covers
  both: `chat.completions` with views as base64 PNG data URLs, `response_format` with the
  `QCFeedback` JSON schema, `temperature=0`. `base_url` (`--base_url`, `OPENAI_BASE_URL`)
  and the model id are required, since there is no meaningful default; the API key
  (`OPENAI_API_KEY`) is optional. A server that ignores `response_format` still works,
  because `parse_reply` extracts JSON from free text. Decided 2026-11-17.
- **No in-process local adapter.** The HTTP adapter replaces the planned `llava.py` port of
  `chat_image.py`. A workstation runs the same server locally, so the core and sandbox need
  no `torch` or `transformers`. Decided 2026-11-17.
- **Data-use acknowledgement for every endpoint.** Both adapters refuse to send images
  without the flag, local host or not. Each deployment states its choice; the code does not
  guess which hosts are internal. Decided 2026-11-17.

## Risks / Trade-offs

- [Sending MRI views to a cloud API can breach data-use agreements] → the Claude adapter
  refuses to run unless an explicit flag acknowledges this; docs state it.
- [Tool-use output differs from free-text behaviour seen in the sandbox] → evaluation compares
  both on the same bundles before a default is chosen.
- [No local NVIDIA GPU on the dev machine] → the HTTP adapter is tested with a mocked
  client; real runs against a remote server or a GPU workstation running one.
- [Servers differ in their support for `response_format` and image input] → the adapter
  records the request settings; a live check against the chosen server is part of the
  evaluation, not CI.
- [Prompt drift between adapters] → every adapter renders one shared template around the
  bundle's `PACKAGE.md`; the prompt hash is stored.

## Open Questions

- Do adapters move into `ui/` after evaluation, or into a separate optional package? Deferred
  until `add-feedback-evaluation` reports.
- Default Claude model: `claude-sonnet-5-5` (the sandbox used `claude-sonnet-4-6`); `--model`
  overrides it. Decided 2026-11-17.
- Which LLaVA-OneVision size is the reference self-hosted model (4B now, 8B needs more
  compute)? A server setting, not code; the evaluation decides.
- Which host runs the first live check (remote server or GPU workstation)? Decided when the
  evaluation needs it.
