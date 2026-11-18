"""Tests for the sandbox model adapters (``sandbox/model_adapters``), with fake model clients."""

import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from evidence_bundle.feedback import load_feedback
from evidence_bundle.models import DistributionContext, EvidenceBundle, MetricEvidence, ViewRef

SANDBOX_DIR = Path(__file__).resolve().parents[2] / "sandbox"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from model_adapters.base import (  # noqa: E402
    NO_IMAGE_SECTION,
    DataUseError,
    ModelAdapter,
    _clean_schema,
    image_label,
    prompt_hash,
    render_prompt,
    reply_schema,
)
from model_adapters.claude import DEFAULT_MODEL, ClaudeAdapter  # noqa: E402
from model_adapters.openai_compat import OpenAICompatAdapter  # noqa: E402
from model_adapters import run_feedback  # noqa: E402

PACKAGE_TEXT = "# MRI QC Evidence Package\n\nFlagged metrics: cjv\n\nCosts $5 {not a placeholder}.\n"

REPLY: dict[str, Any] = dict(
    decision="fail",
    confidence="medium",
    summary="CJV is high for this protocol.",
    reasons=["cjv=0.9, project percentile 99."],
    flagged_metrics=["cjv"],
    recommended_followup=["Inspect the axial view."],
)


def _view(name, kind: Any = "core", plane: Any = "axial"):
    rule = "noise" if kind == "targeted" else None
    return ViewRef(
        path=f"views/{name}.png", kind=kind, plane=plane, slice_positions=[0.0], placement="mni", window_percentiles=(1.0, 99.0), rule=rule
    )


def _metric(name, flags=(), category: Any = "normal"):
    return MetricEvidence(
        name=name,
        value=0.5,
        display_name=name.upper(),
        category="noise_and_tissue_contrast",
        direction_of_concern="higher_worse",
        evidence_strength="medium",
        project_percentile=50.0,
        reference_percentile=50.0,
        flags=list(flags),
        context_category=category,
    )


@pytest.fixture
def bundle_dir(tmp_path):
    bundle = EvidenceBundle(
        participant_id="sub-01",
        session_id="ses-01",
        pipeline="mriqc",
        qc_task="anat",
        bids_name="sub-01_ses-01_T1w",
        suffix="T1w",
        support="supported",
        context_suffix="T1w",
        project=DistributionContext(n=40),
        reference=DistributionContext(n=1200),
        metrics=[_metric("cjv", flags=["project_outlier", "reference_outlier"], category="scan"), _metric("snr_wm")],
        views=[_view("core_axial"), _view("core_coronal", plane="coronal"), _view("noise_axial", kind="targeted")],
    )
    (tmp_path / "views").mkdir()
    for view in bundle.views:
        (tmp_path / view.path).write_bytes(f"png {view.path}".encode())
    (tmp_path / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    (tmp_path / "PACKAGE.md").write_text(PACKAGE_TEXT, encoding="utf-8")
    return tmp_path


class FakeAdapter(ModelAdapter):
    name = "fake"

    def __init__(self, reply: Any = None, error: Optional[Exception] = None, **kwargs):
        kwargs.setdefault("acknowledge_data_use", True)
        super().__init__("fake-1", **kwargs)
        self.reply = json.dumps(REPLY) if reply is None else reply
        self.error = error
        self.calls: list[tuple[str, list[Path]]] = []

    def complete(self, prompt, images):
        self.calls.append((prompt, list(images)))
        if self.error is not None:
            raise self.error
        return self.reply


class TestPrompt:
    def test_package_inserted_verbatim(self, bundle_dir):
        prompt = render_prompt(bundle_dir, images=True)
        assert PACKAGE_TEXT.strip() in prompt
        assert "$image_section" not in prompt and "$package" not in prompt

    def test_image_section(self, bundle_dir):
        assert "attached as images" in render_prompt(bundle_dir, images=True)
        assert NO_IMAGE_SECTION in render_prompt(bundle_dir, images=False)

    def test_reason_limits(self, bundle_dir):
        assert "Give 1 to 7 reasons" in render_prompt(bundle_dir, images=False)

    def test_hash_stable(self, bundle_dir):
        prompt = render_prompt(bundle_dir, images=True)
        images = sorted((bundle_dir / "views").iterdir())
        assert prompt_hash(prompt, images) == prompt_hash(prompt, images)

    def test_hash_changes_with_prompt_and_views(self, bundle_dir):
        prompt = render_prompt(bundle_dir, images=True)
        images = sorted((bundle_dir / "views").iterdir())
        before = prompt_hash(prompt, images)
        assert prompt_hash(prompt + " ", images) != before
        assert prompt_hash(prompt, images[:-1]) != before
        images[0].write_bytes(b"re-rendered")
        assert prompt_hash(prompt, images) != before

    def test_rater_qc_left_out(self, bundle_dir):
        package = "# MRI QC Evidence Package\n\n## Views\n\nview list\n\n## Rater QC\n\nfail by rater1: motion\n\n" "## Later\n\nkept\n"
        (bundle_dir / "PACKAGE.md").write_text(package, encoding="utf-8")
        prompt = render_prompt(bundle_dir, images=True)
        assert "Rater QC" not in prompt and "rater1" not in prompt
        assert "## Views\n\nview list" in prompt and "## Later\n\nkept" in prompt

    def test_rater_qc_last_section(self, bundle_dir):
        (bundle_dir / "PACKAGE.md").write_text("# Package\n\n## Views\n\nv\n\n## Rater QC\n\nNo rater QC.\n", encoding="utf-8")
        prompt = render_prompt(bundle_dir, images=False)
        assert "Rater QC" not in prompt and "## Views\n\nv" in prompt

    def test_template_change_changes_hash(self, bundle_dir, tmp_path_factory):
        template = tmp_path_factory.mktemp("tpl") / "prompt.md"
        template.write_text("Other task.\n$image_section\n$min_reasons $max_reasons\n$package\n", encoding="utf-8")
        assert prompt_hash(render_prompt(bundle_dir, True, template)) != prompt_hash(render_prompt(bundle_dir, True))


class TestAdapter:
    def test_images_need_acknowledgement(self):
        with pytest.raises(DataUseError, match="data-use"):
            FakeAdapter(acknowledge_data_use=False)

    def test_iqms_only_needs_no_acknowledgement(self, bundle_dir):
        adapter = FakeAdapter(images=False, acknowledge_data_use=False)
        result = adapter.send(bundle_dir)
        assert result.schema_valid
        assert adapter.calls[0][1] == []
        assert result.settings == {"images": False}

    def test_images_sent_in_bundle_order(self, bundle_dir):
        adapter = FakeAdapter()
        adapter.send(bundle_dir)
        assert [p.name for p in adapter.calls[0][1]] == ["core_axial.png", "core_coronal.png", "noise_axial.png"]

    def test_valid_reply_recorded(self, bundle_dir):
        adapter = FakeAdapter()
        result = adapter.send(bundle_dir)
        prompt, images = adapter.calls[0]
        assert result.status == "ok" and result.schema_valid and result.consistency_errors == []
        assert (result.adapter, result.model_id) == ("fake", "fake-1")
        assert result.prompt_hash == prompt_hash(prompt, images)
        assert result.settings == {"images": True}

    def test_fenced_reply(self, bundle_dir):
        assert FakeAdapter(reply=f"```json\n{json.dumps(REPLY)}\n```").send(bundle_dir).schema_valid

    def test_structured_reply(self, bundle_dir):
        assert FakeAdapter(reply=REPLY).send(bundle_dir).schema_valid

    def test_invalid_reply_stored(self, bundle_dir):
        result = FakeAdapter(reply="The scan looks fine.").send(bundle_dir)
        assert result.status == "ok" and not result.schema_valid
        assert result.raw_reply == "The scan looks fine."

    def test_inconsistent_reply_stored(self, bundle_dir):
        reply = dict(REPLY, flagged_metrics=["snr_wm"], reasons=["snr_wm is low."])
        result = FakeAdapter(reply=reply).send(bundle_dir)
        assert result.schema_valid
        assert result.consistency_errors == ["flagged metric 'snr_wm' is not flagged in the bundle"]

    def test_model_error_recorded(self, bundle_dir):
        result = FakeAdapter(error=TimeoutError("no reply in 60 s")).send(bundle_dir)
        assert result.status == "error"
        assert result.error == "TimeoutError: no reply in 60 s"
        assert result.prompt_hash is not None

    def test_missing_view_recorded(self, bundle_dir):
        (bundle_dir / "views" / "noise_axial.png").unlink()
        adapter = FakeAdapter()
        result = adapter.send(bundle_dir)
        assert result.status == "error" and "noise_axial.png" in result.error
        assert adapter.calls == []

    def test_unreadable_bundle_raises(self, bundle_dir):
        (bundle_dir / "bundle.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError):
            FakeAdapter().send(bundle_dir)


class FakeMessages:
    """Stands in for ``anthropic.Anthropic().messages``; records each request."""

    def __init__(self, text: str, stop_reason: str = "end_turn", category: Optional[str] = None):
        self.response = SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=SimpleNamespace(category=category) if category else None,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        )
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


def _claude(text: str = json.dumps(REPLY), stop_reason: str = "end_turn", category: Optional[str] = None, **kwargs):
    messages = FakeMessages(text, stop_reason, category)
    kwargs.setdefault("acknowledge_data_use", True)
    return ClaudeAdapter(client=SimpleNamespace(messages=messages), **kwargs), messages


def _fake_sdk(monkeypatch) -> dict[str, Any]:
    """Install a fake ``anthropic`` module; return the keyword arguments its client receives."""
    seen: dict[str, Any] = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))
    return seen


class TestClaudeAdapter:
    def test_images_attached(self, bundle_dir):
        adapter, messages = _claude()
        result = adapter.send(bundle_dir)
        content = messages.requests[0]["messages"][0]["content"]
        assert [block["type"] for block in content] == ["text", "image"] * 3 + ["text"]
        assert content[0]["text"] == "Image 1: views/core_axial.png"
        assert content[4]["text"] == "Image 3: views/noise_axial.png"
        assert content[1]["source"]["media_type"] == "image/png"
        assert base64.standard_b64decode(content[1]["source"]["data"]) == b"png views/core_axial.png"
        assert result.status == "ok" and result.schema_valid

    def test_iqms_only_sends_no_images(self, bundle_dir):
        adapter, messages = _claude(images=False, acknowledge_data_use=False)
        result = adapter.send(bundle_dir)
        content = messages.requests[0]["messages"][0]["content"]
        assert [block["type"] for block in content] == ["text"]
        assert NO_IMAGE_SECTION in content[0]["text"]
        assert result.settings["images"] is False

    def test_images_refused_without_acknowledgement(self):
        with pytest.raises(DataUseError):
            ClaudeAdapter(client=SimpleNamespace(messages=None))

    def test_structured_output_requested(self, bundle_dir):
        adapter, messages = _claude()
        adapter.send(bundle_dir)
        request = messages.requests[0]
        assert request["model"] == DEFAULT_MODEL
        schema = request["output_config"]["format"]["schema"]
        assert request["output_config"]["format"]["type"] == "json_schema"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert "tool_choice" not in request and "temperature" not in request

    def test_settings_recorded(self, bundle_dir):
        result = _claude()[0].send(bundle_dir)
        assert result.settings == {"images": True, "max_tokens": 16000, "sampling": "default", "output": "json_schema"}
        assert result.endpoint is None

    def test_base_url_from_argument(self, bundle_dir):
        result = _claude(base_url="https://proxy.example.org")[0].send(bundle_dir)
        assert result.endpoint == "https://proxy.example.org"

    def test_base_url_from_environment(self, monkeypatch):
        seen = _fake_sdk(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env.example.org")
        adapter = ClaudeAdapter(acknowledge_data_use=True)
        assert adapter.endpoint == "https://env.example.org"
        assert seen == {"base_url": "https://env.example.org"}

    def test_injected_client_ignores_environment(self, bundle_dir, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env.example.org")
        assert _claude()[0].send(bundle_dir).endpoint is None

    def test_base_url_passed_to_client(self, monkeypatch):
        seen = _fake_sdk(monkeypatch)
        ClaudeAdapter(base_url="https://proxy.example.org", acknowledge_data_use=True)
        assert seen == {"base_url": "https://proxy.example.org"}

    def test_missing_sdk(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "anthropic", None)
        with pytest.raises(ImportError, match="uv pip install anthropic"):
            ClaudeAdapter(acknowledge_data_use=True)

    def test_refusal_recorded_as_error(self, bundle_dir):
        result = _claude(text="", stop_reason="refusal", category="bio")[0].send(bundle_dir)
        assert result.status == "error"
        assert result.error == "RefusalError: model declined the request (category: bio)"

    def test_truncated_reply_kept(self, bundle_dir):
        result = _claude(text='{"decision": "pass", "conf', stop_reason="max_tokens")[0].send(bundle_dir)
        assert result.status == "ok" and not result.schema_valid
        assert result.raw_reply == '{"decision": "pass", "conf'


GPU_HOST = "http://gpu-host:8000/v1"


class FakeCompletions:
    """Stands in for ``openai.OpenAI().chat.completions``; records each request."""

    def __init__(self, content: Optional[str], refusal: Optional[str] = None):
        message = SimpleNamespace(content=content, refusal=refusal)
        self.response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


def _compat(content: Optional[str] = json.dumps(REPLY), refusal: Optional[str] = None, **kwargs):
    completions = FakeCompletions(content, refusal)
    kwargs.setdefault("acknowledge_data_use", True)
    kwargs.setdefault("base_url", GPU_HOST)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatAdapter("llava-onevision", client=client, **kwargs), completions


def _fake_openai(monkeypatch) -> dict[str, Any]:
    """Install a fake ``openai`` module; return the keyword arguments its client receives."""
    seen: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    return seen


class TestOpenAICompatAdapter:
    def test_images_attached(self, bundle_dir):
        adapter, completions = _compat()
        result = adapter.send(bundle_dir)
        content = completions.requests[0]["messages"][0]["content"]
        assert [part["type"] for part in content] == ["text", "image_url"] * 3 + ["text"]
        assert content[2]["text"] == "Image 2: views/core_coronal.png"
        url = content[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        assert base64.standard_b64decode(url.split(",", 1)[1]) == b"png views/core_axial.png"
        assert result.status == "ok" and result.schema_valid

    def test_iqms_only_sends_no_images(self, bundle_dir):
        adapter, completions = _compat(images=False, acknowledge_data_use=False)
        adapter.send(bundle_dir)
        content = completions.requests[0]["messages"][0]["content"]
        assert [part["type"] for part in content] == ["text"]
        assert NO_IMAGE_SECTION in content[0]["text"]

    def test_schema_requested(self, bundle_dir):
        adapter, completions = _compat()
        adapter.send(bundle_dir)
        request = completions.requests[0]
        assert request["model"] == "llava-onevision" and request["temperature"] == 0
        assert request["response_format"]["type"] == "json_schema"
        assert request["response_format"]["json_schema"]["schema"] == reply_schema()
        assert request["response_format"]["json_schema"]["strict"] is True

    def test_local_endpoint_needs_acknowledgement(self):
        with pytest.raises(DataUseError):
            _compat(base_url="http://localhost:8000/v1", acknowledge_data_use=False)

    def test_endpoint_and_settings_recorded(self, bundle_dir):
        result = _compat()[0].send(bundle_dir)
        assert result.endpoint == GPU_HOST and result.adapter == "openai_compat"
        assert result.settings == {"images": True, "max_tokens": 2048, "temperature": 0, "output": "json_schema"}

    def test_free_text_reply_parsed(self, bundle_dir):
        text = f"Here is my assessment:\n```json\n{json.dumps(REPLY)}\n```\nDone."
        result = _compat(content=text)[0].send(bundle_dir)
        assert result.schema_valid and result.feedback is not None and result.feedback.decision == "fail"

    def test_refusal_recorded_as_error(self, bundle_dir):
        result = _compat(content=None, refusal="I can't help with that.")[0].send(bundle_dir)
        assert result.status == "error" and result.error == "RefusalError: model declined the request: I can't help with that."

    def test_empty_reply_kept_invalid(self, bundle_dir):
        result = _compat(content=None)[0].send(bundle_dir)
        assert result.status == "ok" and not result.schema_valid

    def test_model_id_required(self):
        with pytest.raises(ValueError, match="model id"):
            OpenAICompatAdapter("", base_url=GPU_HOST, acknowledge_data_use=True, client=SimpleNamespace())

    def test_endpoint_required(self, monkeypatch):
        _fake_openai(monkeypatch)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
            OpenAICompatAdapter("m", acknowledge_data_use=True)

    def test_endpoint_and_key_from_environment(self, monkeypatch):
        seen = _fake_openai(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL", GPU_HOST)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        adapter = OpenAICompatAdapter("m", acknowledge_data_use=True)
        assert adapter.endpoint == GPU_HOST
        assert seen == {"base_url": GPU_HOST, "api_key": "sk-test"}

    def test_key_optional(self, monkeypatch):
        seen = _fake_openai(monkeypatch)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        OpenAICompatAdapter("m", base_url=GPU_HOST, acknowledge_data_use=True)
        assert seen == {"base_url": GPU_HOST, "api_key": "EMPTY"}

    def test_injected_client_ignores_environment(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "http://env-host/v1")
        with pytest.raises(ValueError, match="endpoint is required"):
            _compat(base_url=None)

    def test_missing_sdk(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "openai", None)
        with pytest.raises(ImportError, match="uv pip install openai"):
            OpenAICompatAdapter("m", base_url=GPU_HOST, acknowledge_data_use=True)


def _rewrite_bundle(bundle_dir: Path, **changes) -> None:
    bundle = EvidenceBundle.model_validate_json((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    (bundle_dir / "bundle.json").write_text(bundle.model_copy(update=changes).model_dump_json(), encoding="utf-8")


class TestReviewFixes:
    def test_no_views_gets_no_image_section(self, bundle_dir):
        _rewrite_bundle(bundle_dir, views=[])
        adapter = FakeAdapter()
        adapter.send(bundle_dir)
        prompt, images = adapter.calls[0]
        assert images == [] and NO_IMAGE_SECTION in prompt and "attached as images" not in prompt

    def test_unsupported_bundle_not_sent(self, bundle_dir):
        metric = MetricEvidence(
            name="cjv",
            value=0.5,
            display_name="CJV",
            category="noise_and_tissue_contrast",
            direction_of_concern="context_dependent",
            evidence_strength="none",
        )
        _rewrite_bundle(bundle_dir, suffix="PDw", support="unsupported", context_suffix=None, reference=None, metrics=[metric])
        adapter = FakeAdapter()
        result = adapter.send(bundle_dir)
        assert result.status == "skipped_unsupported" and adapter.calls == []

    def test_schema_keeps_property_names(self):
        schema = {"type": "object", "title": "X", "properties": {"title": {"type": "string", "minLength": 1}, "default": {"type": "string"}}}
        assert _clean_schema(schema) == {"type": "object", "properties": {"title": {"type": "string"}, "default": {"type": "string"}}}

    def test_reply_schema_is_a_copy(self):
        reply_schema()["required"].clear()
        assert reply_schema()["required"]

    def test_image_label(self, bundle_dir):
        assert image_label(2, bundle_dir / "views" / "core_coronal.png") == "Image 2: views/core_coronal.png"


def _tree(bundle_dir: Path, tmp_path_factory, names=("sub-01", "sub-02")) -> Path:
    """Copies of the fixture bundle in sibling folders under a fresh root."""
    root = tmp_path_factory.mktemp("bundles")
    for name in names:
        shutil.copytree(bundle_dir, root / name / "anat")
    return root


class CountingAdapter(FakeAdapter):
    """Fails on the bundles whose path contains ``fail_on``."""

    def __init__(self, fail_on: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.fail_on = fail_on

    def complete(self, prompt, images):
        if self.fail_on and any(self.fail_on in str(image) for image in images):
            raise RuntimeError("server unavailable")
        return super().complete(prompt, images)


class TestRunFeedback:
    def test_feedback_written_beside_each_bundle(self, bundle_dir, tmp_path_factory):
        root = _tree(bundle_dir, tmp_path_factory)
        counts = run_feedback.run(root, FakeAdapter())
        assert counts == {"ok": 2}
        assert load_feedback(root / "sub-01" / "anat").schema_valid

    def test_error_recorded_and_run_continues(self, bundle_dir, tmp_path_factory):
        root = _tree(bundle_dir, tmp_path_factory)
        counts = run_feedback.run(root, CountingAdapter(fail_on="sub-01"))
        assert counts == {"error": 1, "ok": 1}
        assert load_feedback(root / "sub-01" / "anat").error == "RuntimeError: server unavailable"
        assert load_feedback(root / "sub-02" / "anat").status == "ok"

    def test_unreadable_bundle_skipped(self, bundle_dir, tmp_path_factory):
        root = _tree(bundle_dir, tmp_path_factory)
        (root / "sub-01" / "anat" / "bundle.json").write_text("{}", encoding="utf-8")
        counts = run_feedback.run(root, FakeAdapter())
        assert counts == {"unreadable": 1, "ok": 1}
        assert not (root / "sub-01" / "anat" / "feedback.json").exists()

    def test_unsupported_bundle_not_sent(self, bundle_dir):
        metric = _metric("cjv").model_copy(update=dict(direction_of_concern="context_dependent", evidence_strength="none"))
        metric = metric.model_copy(update=dict(project_percentile=None, reference_percentile=None, context_category=None))
        _rewrite_bundle(bundle_dir, suffix="PDw", support="unsupported", context_suffix=None, reference=None, metrics=[metric])
        adapter = FakeAdapter()
        assert run_feedback.run(bundle_dir, adapter) == {"skipped_unsupported": 1}
        assert adapter.calls == []
        assert load_feedback(bundle_dir).status == "skipped_unsupported"
        assert run_feedback.run(bundle_dir, adapter) == {"kept": 1}

    def test_fallback_bundle_sent(self, bundle_dir):
        metrics = [_metric("cjv").model_copy(update=dict(reference_percentile=None))]
        _rewrite_bundle(bundle_dir, suffix="FLAIR", support="fallback", context_suffix="T2w", reference=None, metrics=metrics)
        adapter = FakeAdapter(reply=json.dumps({**REPLY, "decision": "pass", "flagged_metrics": [], "recommended_followup": []}))
        run_feedback.run(bundle_dir, adapter)
        result = load_feedback(bundle_dir)
        assert len(adapter.calls) == 1
        assert (result.status, result.support, result.context_suffix) == ("ok", "fallback", "T2w")

    def test_current_feedback_kept(self, bundle_dir):
        adapter = FakeAdapter()
        run_feedback.run(bundle_dir, adapter)
        assert run_feedback.run(bundle_dir, adapter) == {"kept": 1}
        assert len(adapter.calls) == 1

    def test_overwrite_reruns(self, bundle_dir):
        adapter = FakeAdapter()
        run_feedback.run(bundle_dir, adapter)
        assert run_feedback.run(bundle_dir, adapter, overwrite=True) == {"ok": 1}
        assert len(adapter.calls) == 2

    def test_changed_prompt_reruns(self, bundle_dir):
        adapter = FakeAdapter()
        run_feedback.run(bundle_dir, adapter)
        (bundle_dir / "PACKAGE.md").write_text(PACKAGE_TEXT + "\nRevised.\n", encoding="utf-8")
        assert run_feedback.run(bundle_dir, adapter) == {"ok": 1}

    def test_other_model_reruns(self, bundle_dir):
        run_feedback.run(bundle_dir, FakeAdapter())
        other = FakeAdapter()
        other.model_id = "fake-2"
        assert run_feedback.run(bundle_dir, other) == {"ok": 1}

    def test_error_result_retried(self, bundle_dir):
        run_feedback.run(bundle_dir, FakeAdapter(error=RuntimeError("timeout")))
        assert run_feedback.run(bundle_dir, FakeAdapter()) == {"ok": 1}

    def test_cli_refuses_images_without_acknowledgement(self, bundle_dir, monkeypatch):
        seen = _fake_openai(monkeypatch)
        code = run_feedback.main([str(bundle_dir), "--adapter", "openai_compat", "--base_url", "http://localhost:8000/v1", "--model_id", "m"])
        assert code == 2 and seen == {}
        assert not (bundle_dir / "feedback.json").exists()

    def test_cli_builds_adapter(self, monkeypatch):
        seen = _fake_openai(monkeypatch)
        args = run_feedback.parse_args(["x", "--adapter", "openai_compat", "--base_url", GPU_HOST, "--model_id", "m", "--iqms_only"])
        adapter = run_feedback.make_adapter(args)
        assert isinstance(adapter, OpenAICompatAdapter) and adapter.images is False
        assert seen["base_url"] == GPU_HOST

    def test_cli_model_from_environment(self, monkeypatch):
        _fake_sdk(monkeypatch)
        monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5-5")
        args = run_feedback.parse_args(["x", "--adapter", "claude", "--acknowledge_data_use", "--max_tokens", "800"])
        adapter = run_feedback.make_adapter(args)
        assert adapter.model_id == "claude-opus-5-5" and adapter.settings["max_tokens"] == 800

    def test_invalid_reply_retried(self, bundle_dir):
        run_feedback.run(bundle_dir, FakeAdapter(reply='{"decision": "pass", "conf'))
        assert not load_feedback(bundle_dir).schema_valid
        assert run_feedback.run(bundle_dir, FakeAdapter()) == {"ok": 1}

    def test_changed_settings_rerun(self, bundle_dir):
        class TunedAdapter(FakeAdapter):
            @property
            def settings(self):
                return {**super().settings, "max_tokens": 8000}

        run_feedback.run(bundle_dir, FakeAdapter())
        assert run_feedback.run(bundle_dir, TunedAdapter()) == {"ok": 1}
        assert load_feedback(bundle_dir).settings["max_tokens"] == 8000

    def test_unsupported_rewritten_for_other_model(self, bundle_dir):
        metric = _metric("cjv").model_copy(update=dict(direction_of_concern="context_dependent", evidence_strength="none"))
        metric = metric.model_copy(update=dict(project_percentile=None, reference_percentile=None, context_category=None))
        _rewrite_bundle(bundle_dir, suffix="PDw", support="unsupported", context_suffix=None, reference=None, metrics=[metric])
        run_feedback.run(bundle_dir, FakeAdapter())
        other = FakeAdapter()
        other.model_id = "fake-2"
        assert run_feedback.run(bundle_dir, other) == {"skipped_unsupported": 1}
        assert load_feedback(bundle_dir).model_id == "fake-2" and other.calls == []

    def test_unrenderable_package_replaces_old_result(self, bundle_dir):
        run_feedback.run(bundle_dir, FakeAdapter())
        (bundle_dir / "PACKAGE.md").write_bytes(b"\xff\xfe not utf-8")
        assert run_feedback.run(bundle_dir, FakeAdapter()) == {"error": 1}
        assert "UnicodeDecodeError" in load_feedback(bundle_dir).error

    def test_script_imports_without_sandbox_on_path(self):
        script = SANDBOX_DIR / "model_adapters" / "run_feedback.py"
        done = subprocess.run([sys.executable, "-I", str(script), "--help"], capture_output=True, text=True)
        assert done.returncode == 0 and "--adapter" in done.stdout


def test_hash_covers_view_folder(tmp_path):
    for folder in ("views", "other"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "a.png").write_bytes(b"same")
    assert prompt_hash("p", [tmp_path / "views" / "a.png"]) != prompt_hash("p", [tmp_path / "other" / "a.png"])
