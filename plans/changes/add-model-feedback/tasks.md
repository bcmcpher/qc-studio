## 1. Feedback schema and validation — `ui/evidence_bundle/feedback.py`

- [x] 1.1 Write `QCFeedback` from sandbox `QCDecision`; add optional `image_observations`
- [x] 1.2 Write `FeedbackResult`: `status` (`ok`, `error`, `skipped_unsupported`), model id, adapter name, settings, prompt hash, bundle schema version, bundle `support` and `context_suffix`, timestamp, raw reply, `schema_valid`, `consistency_errors`, parsed feedback
- [x] 1.3 Write `check_consistency(feedback, bundle)`: flagged metrics ⊆ bundle flags, each flagged metric named in a reason, reason count within limits, follow-up present when decision is not `pass`
- [x] 1.4 Write `load_feedback(path)` / `write_feedback(path, result)`
- [x] 1.5 Tests: valid reply passes; each consistency rule fails on its own; invalid JSON stored with `schema_valid=False`

As built (section 1):

- `FeedbackResult` also has `endpoint` (the cloud endpoint, task 3.5), `schema_errors` (the
  validation errors the spec's "Invalid reply kept" scenario stores) and `error` (status
  `error`). A validator ties the fields to the status: parsed feedback only when
  `schema_valid`; `ok` holds the raw reply; `skipped_unsupported` only for unsupported bundles.
- JSON extraction (`extract_json`: code fence, then first object) and `parse_reply` live in
  `feedback.py`, not `base.py`, so one function validates every reply. `parse_reply` also takes
  an already-parsed object, for Claude tool input. Adapters build results with
  `reply_result`, `error_result` and `skipped_result`.
- `QCFeedback` rejects unknown fields (`extra="forbid"`, as every bundle model). Blank
  reasons and follow-ups do not count.
- `write_feedback` writes to a temporary file and renames it, so a failed write keeps the
  earlier result. `load_feedback`/`write_feedback` accept a bundle folder or the file path.

## 2. Adapter interface — `sandbox/model_adapters/base.py`

- [x] 2.1 Write the `ModelAdapter` protocol: `name`, `model_id`, `send(bundle_dir) -> FeedbackResult`
- [x] 2.2 Write shared helpers: prompt from a template that wraps `PACKAGE.md`, prompt hash, JSON extraction (code fences, first object), validation through `feedback.py`
- [x] 2.3 Tests with a fake adapter that returns canned replies

As built (section 2):

- `ModelAdapter` is an abstract base class rather than a `typing.Protocol`: it is the interface
  (`name`, `model_id`, `send`) and holds the shared flow. Subclasses implement only
  `complete(prompt, images)`, which returns reply text or a parsed object.
- The data-use rule is in the base constructor, so every adapter refuses images without the
  acknowledgement before any request (tasks 3.4 and 4.4 inherit it).
- The template is `sandbox/model_adapters/prompt.md` (`string.Template`, so braces and `$` in
  `PACKAGE.md` need no escaping). It holds the role, the rules from the sandbox
  `image_evidence_exp` template adapted to the bundle (flags only from "Flagged metrics",
  deviations as protocol notes, fallback caution, the reason limits) and the reply fields.
  The sandbox "default to pass" heuristics were left out; the evaluation can add them back.
- `render_prompt` removes the `## Rater QC` section of `PACKAGE.md` (`strip_section`), so the
  model never sees the rater's verdict. The exported `PACKAGE.md` is unchanged.
- The prompt hash covers the rendered prompt and each attached image's name and bytes, so
  re-rendered views also mark feedback stale. IQMs-only runs hash the prompt alone.
- `send` raises only when `bundle.json` is unreadable; a missing `PACKAGE.md` or view, or a
  model error, becomes an `error` result.
- Adapter tests are in `ui/tests/test_model_adapters.py` (sandbox path added in the test), so CI
  runs them without model SDKs.

## 3. Claude adapter — `sandbox/model_adapters/claude.py`

- [x] 3.1 Port the client setup from `run_experiment.py`; lazy `anthropic` import; read `ANTHROPIC_API_KEY`
- [x] 3.2 Attach `views/*.png` as image content blocks; add an IQMs-only variant that sends no images
- [x] 3.3 Request structured output through a tool whose input schema is the `QCFeedback` JSON schema; `temperature=0`
- [x] 3.4 Refuse to send images unless a data-use acknowledgement flag is set
- [x] 3.5 Accept an optional `base_url` (`--base_url`, `ANTHROPIC_BASE_URL`); pass it to the client; record it in the metadata
- [x] 3.6 Tests with a mocked client: images attached in the image variant, absent in the IQMs-only variant, refusal without the flag, `base_url` passed through

As built (section 3):

- 3.3 changed (user decision 2026-11-18): `claude-sonnet-5-5` returns a 400 for forced
  `tool_choice` and for a non-default `temperature`. The adapter requests
  `output_config.format` (`json_schema`) instead, sends no temperature, and records
  `sampling: default`, `output: json_schema` and `max_tokens` (16000) in the settings.
- `reply_schema()` in `base.py` gives the strict-output form of the `QCFeedback` schema: every
  property required, `minLength`/`title`/`default` dropped. `feedback.py` still validates the
  full model. Section 4 reuses it for `response_format`.
- 3.1: the SDK resolves credentials itself (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or an
  `ant auth` profile); the adapter does not read the key. A missing `anthropic` package raises
  at construction with an install hint, not once per bundle. A `client` argument injects a
  fake client for tests.
- A refusal (`stop_reason: refusal`) becomes an `error` result with its category; no fallback
  model. A reply cut off at `max_tokens` is kept as an invalid `ok` reply with its raw text.
- Images go before the prompt text in the user message, in bundle order.
- 3.5: `base_url` comes from the argument, then `ANTHROPIC_BASE_URL`. The `--base_url` flag is
  wired in section 5 (CLI).
- 3.4 is inherited from the base constructor; a test covers it for this adapter.

## 4. OpenAI-compatible adapter — `sandbox/model_adapters/openai_compat.py`

- [ ] 4.1 Lazy `openai` import; required `base_url` (`--base_url`, `OPENAI_BASE_URL`) and model id; optional `OPENAI_API_KEY`
- [ ] 4.2 Send the bundle's core and targeted views as base64 PNG data URLs; IQMs-only variant sends none
- [ ] 4.3 Request `response_format` with the `QCFeedback` JSON schema, `temperature=0`; validate through `feedback.py` (free-text JSON also accepted)
- [ ] 4.4 Refuse to send images unless the data-use acknowledgement flag is set; record the endpoint in the metadata
- [ ] 4.5 Tests with a mocked client: images attached or absent, schema requested, refusal without the flag, endpoint recorded, free-text reply parsed

## 5. Batch CLI — `sandbox/model_adapters/run_feedback.py`

- [ ] 5.1 Walk a bundle tree; run one adapter per invocation; write `feedback.json` beside each `bundle.json`
- [ ] 5.2 Skip bundles that already have feedback from the same model and prompt hash unless `--overwrite`
- [ ] 5.3 Catch adapter errors per bundle; record them in `feedback.json`; continue
- [ ] 5.4 Skip bundles with `support` `unsupported`; write a `feedback.json` with status `skipped_unsupported` and no model call
- [ ] 5.5 Tests: an unsupported bundle is skipped without calling the adapter; a fallback bundle is sent and its result records `support` and `context_suffix`
- [ ] 5.6 Update `sandbox/README.md` and `sandbox/requirements-experiments.txt` (`anthropic`, `openai`); document serving a model behind an OpenAI-compatible server
