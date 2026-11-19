"""Tests for the evaluation runner (``sandbox/evaluation/run_eval.py``), with a fake adapter."""

import csv
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import pytest

from evidence_bundle.feedback import load_feedback
from evidence_bundle.models import DistributionContext, EvidenceBundle, MetricEvidence, ViewRef

SANDBOX_DIR = Path(__file__).resolve().parents[2] / "sandbox"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from model_adapters.base import ModelAdapter  # noqa: E402
from evaluation import run_eval  # noqa: E402
from evaluation.run_eval import VARIANTS  # noqa: E402

VARIANT = {v.name: v for v in VARIANTS}


def _png(width: int, height: int) -> bytes:
    """A valid grey PNG of the given size."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\0" + b"\x80" * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _view(name, kind: Any = "core", plane: Any = "axial", rule=None, control=False):
    return ViewRef(
        path=f"views/{name}.png",
        kind=kind,
        plane=plane,
        slice_positions=[0.0],
        placement="mni",
        window_percentiles=(1.0, 99.0),
        rule=rule,
        control=control,
    )


def _metric(name, flags=()):
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
        context_category="project" if flags else "normal",
    )


def _write_bundle(bundle_dir: Path, bundle: EvidenceBundle) -> None:
    (bundle_dir / "views").mkdir(parents=True)
    for view in bundle.views:
        (bundle_dir / view.path).write_bytes(_png(75, 40))
    (bundle_dir / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    (bundle_dir / "PACKAGE.md").write_text("# exported package\n", encoding="utf-8")


def _bundle(pid: str, flagged: bool) -> EvidenceBundle:
    core = [_view("core_axial"), _view("core_sagittal", plane="sagittal")]
    noise = _view("targeted_noise", kind="targeted", rule="noise", control=not flagged)
    return EvidenceBundle(
        participant_id=pid,
        session_id="ses-01",
        pipeline="mriqc",
        qc_task="anat",
        bids_name=f"{pid}_ses-01_T1w",
        suffix="T1w",
        support="supported",
        context_suffix="T1w",
        project=DistributionContext(n=40),
        reference=DistributionContext(n=1200),
        metrics=[_metric("snr_wm", flags=["project_outlier"] if flagged else []), _metric("cjv")],
        views=[*core, noise],
    )


@pytest.fixture
def bundle_root(tmp_path):
    """Two exported bundles: sub-01 has a flagged SNR and a targeted noise view; sub-02 is clean
    and has the noise view as a control."""
    root = tmp_path / "bundles"
    _write_bundle(root / "sub-01" / "anat", _bundle("sub-01", flagged=True))
    _write_bundle(root / "sub-02" / "anat", _bundle("sub-02", flagged=False))
    return root


class FakeAdapter(ModelAdapter):
    """Flags ``snr_wm`` and fails every scan, so the clean control scan is a false confirmation."""

    name = "fake"

    def __init__(self, **kwargs):
        kwargs.setdefault("acknowledge_data_use", True)
        super().__init__("fake-1", **kwargs)
        self.calls: list[tuple[str, list[Path]]] = []

    def complete(self, prompt, images):
        self.calls.append((prompt, list(images)))
        return json.dumps(
            dict(
                decision="fail",
                confidence="medium",
                summary="Low WM SNR.",
                reasons=["snr_wm is low."],
                flagged_metrics=["snr_wm"],
                recommended_followup=["Inspect the background view."],
            )
        )


def _run(bundle_root, out_dir, adapter, variants=VARIANTS, overwrite=False):
    key = run_eval.model_key(adapter.name, adapter.model_id)
    jobs, unreadable = run_eval.plan(bundle_root, out_dir, key, variants, overwrite=overwrite)
    assert not unreadable
    return run_eval.run(jobs, adapter), key


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class TestVariants:
    def test_view_sets(self):
        bundle = _bundle("sub-01", flagged=True)
        assert run_eval.variant_bundle(bundle, VARIANT["iqms"]).views == []
        assert [v.kind for v in run_eval.variant_bundle(bundle, VARIANT["core"]).views] == ["core", "core"]
        assert len(run_eval.variant_bundle(bundle, VARIANT["core_targeted_stated"]).views) == 3

    def test_stated_reason_names_rule(self):
        text = run_eval.views_text(_bundle("sub-01", flagged=True).views, "stated")
        assert "![targeted axial, rule noise](views/targeted_noise.png)" in text
        assert "![core sagittal](views/core_sagittal.png)" in text

    def test_hidden_reason_drops_rule_and_kind(self):
        text = run_eval.views_text(_bundle("sub-01", flagged=True).views, "hidden")
        assert "noise" not in text.replace("targeted_noise.png", "")
        assert "targeted" not in text.replace("targeted_noise.png", "")
        assert "core" not in text.replace("core_axial.png", "").replace("core_sagittal.png", "")
        assert "![axial view](views/targeted_noise.png)" in text

    def test_staged_views_get_neutral_names(self):
        staged = run_eval.variant_bundle(_bundle("sub-01", flagged=True), VARIANT["core_targeted_hidden"])
        assert [v.path for v in staged.views] == ["views/view_01.png", "views/view_02.png", "views/view_03.png"]
        assert staged.views[2].rule == "noise"  # kept in bundle.json for the evaluation, never in the prompt

    @pytest.mark.parametrize("reason", ["stated", "hidden"])
    def test_control_never_named(self, reason):
        text = run_eval.package_text(_bundle("sub-02", flagged=False), reason)
        assert "control" not in text.lower()

    def test_package_keeps_metrics(self):
        text = run_eval.package_text(_bundle("sub-01", flagged=True), "stated")
        assert "`snr_wm`" in text and "## Rater QC" in text

    def test_model_key_is_filesystem_safe(self):
        key = run_eval.model_key("openai_compat", "org/llava 7b:q4")
        assert key.startswith("openai_compat__org-llava-7b-q4-") and "/" not in key
        assert run_eval.model_key("fake", None).startswith("fake__default-")

    def test_model_key_keeps_similar_ids_apart(self):
        assert run_eval.model_key("openai_compat", "org/model:v1") != run_eval.model_key("openai_compat", "org-model-v1")

    def test_no_images_keeps_only_iqms(self):
        assert [v.name for v in run_eval.variants_for(None, images=False)] == ["iqms"]
        assert [v.name for v in run_eval.variants_for(["core"], images=True)] == ["core"]


class TestRun:
    def test_one_cell_folder_per_bundle_and_variant(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        adapter = FakeAdapter()
        counts, key = _run(bundle_root, out, adapter)
        assert counts == {"ok": 8}
        for variant in VARIANTS:
            cell = out / key / variant.name / "sub-01" / "anat"
            assert load_feedback(cell).status == "ok"
            assert json.loads((cell / "cell.json").read_text())["variant"] == variant.name
        # The exported bundle is left untouched.
        assert not (bundle_root / "sub-01" / "anat" / "feedback.json").exists()

    def test_images_follow_variant(self, bundle_root, tmp_path):
        adapter = FakeAdapter()
        _run(bundle_root, tmp_path / "out", adapter, variants=[VARIANT["iqms"], VARIANT["core"], VARIANT["core_targeted_hidden"]])
        sent = sorted(len(images) for _, images in adapter.calls)
        assert sent == [0, 0, 2, 2, 3, 3]
        assert all("No images are attached" in prompt for prompt, images in adapter.calls if not images)

    def test_prompt_never_names_kind_rule_or_control(self, bundle_root, tmp_path):
        adapter = FakeAdapter()
        _run(bundle_root, tmp_path / "out", adapter, variants=[VARIANT["core_targeted_hidden"]])
        for prompt, images in adapter.calls:
            views = prompt.split("## Views", 1)[1]
            for word in ("targeted", "core", "noise", "control"):
                assert word not in views.lower()
            assert [image.name for image in images] == ["view_01.png", "view_02.png", "view_03.png"]

    def test_failed_cell_is_resent(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        failing = FakeAdapter()
        failing.complete = lambda prompt, images: (_ for _ in ()).throw(TimeoutError("timed out"))
        counts, _ = _run(bundle_root, out, failing, variants=[VARIANT["core"]])
        assert counts == {"error": 2}
        again = FakeAdapter()
        counts, _ = _run(bundle_root, out, again, variants=[VARIANT["core"]])
        assert counts == {"ok": 2} and len(again.calls) == 2

    def test_out_dir_inside_bundle_root_is_not_a_source(self, bundle_root):
        out = bundle_root / "eval"
        _run(bundle_root, out, FakeAdapter())
        jobs, _ = run_eval.plan(bundle_root, out, "fake__x", VARIANTS)
        assert len(jobs) == 8 and all(not run_eval._inside(job.source_dir, out) for job in jobs)

    def test_missing_view_gives_error_row(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        (bundle_root / "sub-01" / "anat" / "views" / "targeted_noise.png").unlink()
        counts, _ = _run(bundle_root, out, FakeAdapter(), variants=[VARIANT["core_targeted_stated"]])
        assert counts == {"ok": 1, "error": 1}
        row = next(r for r in run_eval.collect(out) if r["participant_id"] == "sub-01")
        assert row["status"] == "error" and "staging failed" in row["error"]

    def test_failed_restage_drops_old_result(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _, key = _run(bundle_root, out, FakeAdapter(), variants=[VARIANT["core_targeted_stated"]])
        (bundle_root / "sub-01" / "anat" / "views" / "targeted_noise.png").unlink()
        _run(bundle_root, out, FakeAdapter(), variants=[VARIANT["core_targeted_stated"]], overwrite=True)
        assert load_feedback(out / key / "core_targeted_stated" / "sub-01" / "anat").status == "error"

    def test_variants_have_distinct_prompt_hashes(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _, key = _run(bundle_root, out, FakeAdapter())
        hashes = {load_feedback(out / key / v.name / "sub-01" / "anat").prompt_hash for v in VARIANTS}
        assert len(hashes) == len(VARIANTS)

    def test_existing_feedback_is_read_not_resent(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _run(bundle_root, out, FakeAdapter())
        again = FakeAdapter()
        counts, _ = _run(bundle_root, out, again)
        assert counts == {"kept": 8} and again.calls == []
        counts, _ = _run(bundle_root, out, again, overwrite=True)
        assert counts == {"ok": 8} and len(again.calls) == 8

    def test_unsupported_bundle_is_skipped(self, tmp_path):
        root = tmp_path / "bundles"
        bundle = _bundle("sub-03", flagged=False).model_copy(
            update={
                "support": "unsupported",
                "suffix": "PDw",
                "bids_name": "sub-03_ses-01_PDw",
                "context_suffix": None,
                "reference": None,
                "metrics": [
                    m.model_copy(update={"direction_of_concern": "context_dependent", "evidence_strength": "none", "context_category": None})
                    for m in _bundle("sub-03", False).metrics
                ],
            }
        )
        _write_bundle(root / "sub-03", bundle)
        adapter = FakeAdapter()
        key = run_eval.model_key(adapter.name, adapter.model_id)
        jobs, _ = run_eval.plan(root, tmp_path / "out", key, VARIANTS)
        assert {job.action for job in jobs} == {"skip_unsupported"}
        assert run_eval.run(jobs, adapter) == {"skipped_unsupported": 4}
        assert adapter.calls == []

    def test_unreadable_bundle_reported(self, bundle_root, tmp_path):
        bad = bundle_root / "sub-09"
        bad.mkdir()
        (bad / "bundle.json").write_text("{not json", encoding="utf-8")
        jobs, unreadable = run_eval.plan(bundle_root, tmp_path / "out", "fake__fake-1", VARIANTS)
        assert unreadable == [bad] and len(jobs) == 8


class TestDryRun:
    def test_counts_and_estimate_without_sending(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        jobs, _ = run_eval.plan(bundle_root, out, "fake__fake-1", VARIANTS)
        summary = run_eval.dry_run_summary(jobs, images=True)
        assert summary["bundles"] == 2 and summary["variants"] == 4 and summary["requests"] == 8
        # 2 bundles x (0 + 2 + 3 + 3) images of 75x40 px = 4 tokens each.
        text_only = run_eval.dry_run_summary(jobs, images=False)["input_tokens_estimate"]
        assert summary["input_tokens_estimate"] - text_only == 2 * 8 * 4
        assert not out.exists()

    def test_png_size(self, tmp_path):
        path = tmp_path / "a.png"
        path.write_bytes(_png(75, 40))
        assert run_eval.png_size(path) == (75, 40)
        path.write_bytes(b"not a png")
        assert run_eval.png_size(path) is None
        assert run_eval.image_tokens(path) == run_eval.IMAGE_TOKENS_FALLBACK

    def test_cli_dry_run_prints_and_writes_nothing(self, bundle_root, tmp_path, capsys):
        out = tmp_path / "out"
        code = run_eval.main([str(bundle_root), "--out_dir", str(out), "--adapter", "claude", "--acknowledge_data_use", "--dry_run"])
        assert code == 0
        printed = capsys.readouterr().out
        assert "requests: 8" in printed and "input_tokens_estimate:" in printed
        assert not out.exists()


class TestCollect:
    def test_one_row_per_scan_and_cell(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _, key = _run(bundle_root, out, FakeAdapter())
        rows = run_eval.collect(out)
        assert len(rows) == 8
        row = next(r for r in rows if r["source_bundle"] == "sub-01/anat" and r["variant"] == "core_targeted_stated")
        assert row["cell_id"] == f"{key}/core_targeted_stated"
        assert (row["adapter"], row["model_id"], row["view_set"], row["reason"]) == ("fake", "fake-1", "core_targeted", "stated")
        assert row["prompt_hash"] and row["status"] == "ok" and row["schema_valid"] == "1"
        assert row["consistency_valid"] == "1" and row["decision"] == "fail" and row["n_views"] == "3"
        assert row["control_scan"] == "0" and row["control_confirmed"] == ""

    def test_control_scan_false_confirmation(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _run(bundle_root, out, FakeAdapter())
        rows = {r["variant"]: r for r in run_eval.collect(out) if r["participant_id"] == "sub-02"}
        assert {r["control_scan"] for r in rows.values()} == {"1"}
        for variant in ("core_targeted_stated", "core_targeted_hidden"):
            assert (rows[variant]["control_rules"], rows[variant]["control_confirmed"]) == ("noise", "1")
        # Variants without the control view cannot confirm it.
        for variant in ("iqms", "core"):
            assert (rows[variant]["control_rules"], rows[variant]["control_confirmed"]) == ("", "")
        # The clean scan has no flag, so the model's snr_wm flag breaks consistency.
        assert {r["consistency_valid"] for r in rows.values()} == {"0"}

    def test_control_confirmed_needs_rule_metric(self):
        assert run_eval.control_confirmed(["cjv"], ["noise"]) is False
        assert run_eval.control_confirmed(["snr_gm"], ["noise"]) is True
        assert run_eval.control_confirmed(["snr_gm"], []) is None

    def test_labels_and_agreement(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _run(bundle_root, out, FakeAdapter(), variants=[VARIANT["core"]])
        labels_path = tmp_path / "labels.tsv"
        labels_path.write_text("bids_name\tlabel\toriginal_label\nsub-01_ses-01_T1w\tfail\texclude\nsub-02_ses-01_T1w\tpass\taccept\n")
        rows = {r["participant_id"]: r for r in run_eval.collect(out, run_eval.load_labels(labels_path))}
        assert (rows["sub-01"]["label"], rows["sub-01"]["original_label"], rows["sub-01"]["agreement"]) == ("fail", "exclude", "1")
        assert (rows["sub-02"]["label"], rows["sub-02"]["agreement"]) == ("pass", "0")

    def test_labels_skip_blank_and_reject_duplicates(self, tmp_path):
        path = tmp_path / "labels.tsv"
        path.write_text("bids_name\tlabel\nsub-01_ses-01_T1w\tpass\n\t\n\n")
        assert run_eval.load_labels(path) == {"sub-01_ses-01_T1w": ("pass", "")}
        path.write_text("bids_name\tlabel\nsub-01_ses-01_T1w\tpass\nsub-01_ses-01_T1w\tfail\n")
        with pytest.raises(ValueError, match="duplicate"):
            run_eval.load_labels(path)
        path.write_text("bids_name\tlabel\n\tpass\n")
        with pytest.raises(ValueError, match="empty bids_name"):
            run_eval.load_labels(path)

    def test_bad_label_rejected(self, tmp_path):
        path = tmp_path / "labels.tsv"
        path.write_text("bids_name\tlabel\nsub-01_ses-01_T1w\tdoubtful\n")
        with pytest.raises(ValueError, match="doubtful"):
            run_eval.load_labels(path)

    def test_missing_feedback_row(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _, key = _run(bundle_root, out, FakeAdapter(), variants=[VARIANT["core"]])
        (out / key / "core" / "sub-01" / "anat" / "feedback.json").unlink()
        row = next(r for r in run_eval.collect(out) if r["participant_id"] == "sub-01")
        assert row["status"] == "missing" and row["decision"] == ""

    def test_collect_only_cli_writes_tsv(self, bundle_root, tmp_path):
        out = tmp_path / "out"
        _run(bundle_root, out, FakeAdapter())
        assert run_eval.main(["--collect_only", "--out_dir", str(out)]) == 0
        rows = _rows(out / "results.tsv")
        assert len(rows) == 8 and list(rows[0]) == list(run_eval.ROW_FIELDS)

    def test_cli_needs_adapter_unless_collect_only(self, tmp_path):
        with pytest.raises(SystemExit):
            run_eval.parse_args([str(tmp_path), "--out_dir", str(tmp_path / "out")])
