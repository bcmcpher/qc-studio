## 1. Feedback schema and validation — `ui/evidence_bundle/feedback.py`

- [ ] 1.1 Write `QCFeedback` from sandbox `QCDecision`; add optional `image_observations`
- [ ] 1.2 Write `FeedbackResult`: model id, adapter name, settings, prompt hash, bundle schema version, timestamp, raw reply, `schema_valid`, `consistency_errors`, parsed feedback
- [ ] 1.3 Write `check_consistency(feedback, bundle)`: flagged metrics ⊆ bundle flags, each flagged metric named in a reason, reason count within limits, follow-up present when decision is not `pass`
- [ ] 1.4 Write `load_feedback(path)` / `write_feedback(path, result)`
- [ ] 1.5 Tests: valid reply passes; each consistency rule fails on its own; invalid JSON stored with `schema_valid=False`

## 2. Adapter interface — `sandbox/model_adapters/base.py`

- [ ] 2.1 Write the `ModelAdapter` protocol: `name`, `model_id`, `send(bundle_dir) -> FeedbackResult`
- [ ] 2.2 Write shared helpers: prompt from `PACKAGE.md`, prompt hash, JSON extraction (code fences, first object), validation through `feedback.py`
- [ ] 2.3 Tests with a fake adapter that returns canned replies

## 3. Claude adapter — `sandbox/model_adapters/claude.py`

- [ ] 3.1 Port the client setup from `run_experiment.py`; lazy `anthropic` import; read `ANTHROPIC_API_KEY`
- [ ] 3.2 Attach `views/*.png` as image content blocks; add an IQMs-only variant that sends no images
- [ ] 3.3 Request structured output through a tool whose input schema is the `QCFeedback` JSON schema; `temperature=0`
- [ ] 3.4 Refuse to send images unless a data-use acknowledgement flag is set
- [ ] 3.5 Accept an optional `base_url` (`--base_url`, `ANTHROPIC_BASE_URL`); pass it to the client; record it in the metadata
- [ ] 3.6 Tests with a mocked client: images attached in the image variant, absent in the IQMs-only variant, refusal without the flag, `base_url` passed through

## 4. LLaVA-OneVision adapter — `sandbox/model_adapters/llava.py`

- [ ] 4.1 Port model loading, device and dtype selection from the 4B `chat_image.py`; lazy `torch`/`transformers` import
- [ ] 4.2 Send the bundle's core and targeted views instead of re-rendering middle slices
- [ ] 4.3 Replace `validate_result` with the core validator
- [ ] 4.4 Tests with a stubbed model and processor

## 5. Batch CLI — `sandbox/model_adapters/run_feedback.py`

- [ ] 5.1 Walk a bundle tree; run one adapter per invocation; write `feedback.json` beside each `bundle.json`
- [ ] 5.2 Skip bundles that already have feedback from the same model and prompt hash unless `--overwrite`
- [ ] 5.3 Catch adapter errors per bundle; record them in `feedback.json`; continue
- [ ] 5.4 Update `sandbox/README.md` and `sandbox/requirements-experiments.txt`
