# Sandbox Experiments

This folder keeps shared MRI QC inputs separate from experiment-specific outputs.

## Layout

- `data/qc_inputs/`: shared scan data for experiments. Each scan folder keeps source sidecar JSON, MRIQC JSON, and shared processed `metadata.json`/`iqms.json`.
- `iqms_context/`: shared IQM semantic context files by modality.
- `qc_package.py`: shared Python helpers for loading QC inputs, enriching IQMs, building Markdown template context, and rendering templates.
- `cloud_model_experiments/`: experiments that call cloud-hosted models. Each experiment writes evidence bundles, model results, and validation artifacts inside its own folder.
- `local_model_experiments/`: experiments that run local models. Each experiment writes compact prompts, rendered images, raw responses, validation reports, and results inside its own folder.

Shared data folders should stay JSON-only. Markdown evidence bundles (`PACKAGE.md`), raw model responses, validation reports, and result JSON files belong to the experiment that produced them.

## Default Flow

Build the default evidence package from shared raw inputs:

```bash
.venv/bin/python sandbox/cloud_model_experiments/IQMs_only_exp/build_package.py
```

Run the default Claude experiment on generated packages:

```bash
ANTHROPIC_API_KEY=... .venv/bin/python sandbox/cloud_model_experiments/IQMs_only_exp/run_experiment.py
```

Run a local LLaVA experiment from its own folder or from the repo root. Generated files are written back to that experiment folder.

## Model Feedback on Evidence Bundles

`model_adapters/` sends exported evidence bundles to a model. It writes a `feedback.json` beside each `bundle.json`. The QC panel reads that file; it never calls a model.

Install the adapter dependencies into the project environment:

```bash
uv pip install --python .venv/bin/python anthropic openai
```

### Data use

Image mode sends the bundle's MRI views to the model endpoint. This can breach a data-use agreement, also for a server on your own network. The CLI refuses image mode without `--acknowledge_data_use`. Use `--iqms_only` to send only the metrics text.

### Run Claude

```bash
ANTHROPIC_API_KEY=... .venv/bin/python sandbox/model_adapters/run_feedback.py BUNDLE_ROOT \
    --adapter claude --acknowledge_data_use
```

- The default model is `claude-sonnet-5-5`. Set another with `--model_id` or `CLAUDE_MODEL`.
- Set a proxy or institutional endpoint with `--base_url` or `ANTHROPIC_BASE_URL`.

### Run a self-hosted model

The `openai_compat` adapter calls any OpenAI-compatible chat completions server. The same command works for a remote GPU host and for a local workstation.

1. Start the server on the GPU machine, for example with vLLM:

   ```bash
   vllm serve llava-hf/llava-onevision-qwen2-7b-ov-hf --port 8000
   ```

2. Run the CLI with the server URL and the model name the server reports:

   ```bash
   .venv/bin/python sandbox/model_adapters/run_feedback.py BUNDLE_ROOT \
       --adapter openai_compat --base_url http://gpu-host:8000/v1 \
       --model_id llava-hf/llava-onevision-qwen2-7b-ov-hf --acknowledge_data_use
   ```

- `--base_url` (or `OPENAI_BASE_URL`) and `--model_id` (or `OPENAI_MODEL`) are required.
- `OPENAI_API_KEY` is optional. Without it, the adapter sends the placeholder key `EMPTY`.
- The adapter requests the `QCFeedback` JSON schema through `response_format`. A server that ignores it can reply in free text; the CLI extracts the JSON object from the text.

### Reruns

- A bundle is skipped when its `feedback.json` came from the same adapter, model and prompt hash. The prompt hash covers the prompt text and the attached images.
- An `error` result is always retried. Use `--overwrite` to rerun every bundle.
- A bundle with `support` `unsupported` is never sent. It gets a `skipped_unsupported` result.
- An error for one bundle is recorded in its `feedback.json`, and the run continues. The CLI exits with status 1 only when a `bundle.json` cannot be read.

## Adding a New Markdown Package Experiment

Create a new experiment folder with its own template and renderer:

```text
sandbox/cloud_model_experiments/my_new_exp/
  PACKAGE_TEMPLATE.md
  render_package.py
  package/
```

Use `sandbox.qc_package` in `render_package.py` for the shared work:

- `prepare_qc_data(...)`: load BIDS metadata, MRIQC IQMs, reference stats, and semantic context
- `write_shared_qc_data(...)`: write reusable `metadata.json` and `iqms.json` into `data/qc_inputs`
- `build_template_context(...)`: create common placeholders such as `{metadata_table}`, `{iqm_table}`, and `{warnings_section}`
- `render_markdown_template(...)`: render any experiment-specific `PACKAGE_TEMPLATE.md`

For templates with additional placeholders, pass `extra_context`:

```python
context = build_template_context(
    scan_id=args.scan_id,
    participant_id=args.participant_id,
    session_id=args.session_id,
    modality=args.modality,
    acquisition=args.acquisition,
    qc_data=qc_data,
    extra_context={
        "image_section": render_image_section(args.image),
    },
)
```

See `cloud_model_experiments/image_evidence_exp/` for a copyable example that adds an `{image_section}` placeholder.
