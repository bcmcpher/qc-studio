"""Tests for the sandbox model adapters (``sandbox/model_adapters``), with fake model clients."""

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from evidence_bundle.models import DistributionContext, EvidenceBundle, MetricEvidence, ViewRef

SANDBOX_DIR = Path(__file__).resolve().parents[2] / "sandbox"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from model_adapters.base import (  # noqa: E402
    NO_IMAGE_SECTION,
    DataUseError,
    ModelAdapter,
    prompt_hash,
    render_prompt,
)
from model_adapters.claude import DEFAULT_MODEL, ClaudeAdapter  # noqa: E402

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


class TestClaudeAdapter:
    def test_images_attached(self, bundle_dir):
        adapter, messages = _claude()
        result = adapter.send(bundle_dir)
        content = messages.requests[0]["messages"][0]["content"]
        assert [block["type"] for block in content] == ["image", "image", "image", "text"]
        assert content[0]["source"]["media_type"] == "image/png"
        assert base64.standard_b64decode(content[0]["source"]["data"]) == b"png views/core_axial.png"
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

    def test_base_url_from_environment(self, bundle_dir, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env.example.org")
        assert _claude()[0].send(bundle_dir).endpoint == "https://env.example.org"

    def test_base_url_passed_to_client(self, monkeypatch):
        seen = {}

        class FakeAnthropic:
            def __init__(self, **kwargs):
                seen.update(kwargs)

        monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))
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
