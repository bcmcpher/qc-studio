"""Tests for the targeted-view rule table, on synthetic metrics and volumes."""

import json
from fnmatch import fnmatchcase
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from PIL import Image

from evidence_bundle.constants import CORE_PLANES
from evidence_bundle.models import MetricEvidence
from evidence_bundle.render import prepare_scene
from evidence_bundle.view_rules import (
    FLAG_RULES,
    MASK_OVERLAY_RULE,
    fired_rules,
    render_targeted_views,
    rule_applies,
    rule_fires,
)

IQMS_DIR = Path(__file__).resolve().parents[1] / "evidence_bundle" / "iqms"

RULE_EXAMPLES = {"motion": ["fd_mean", "fd_num", "fd_perc"], "noise": ["snr", "snr_total", "efc", "fber", "qi_1", "gsr_x"]}
"""One or more metric names per rule; each must fire that rule and no other."""


def _metric(name: str, flagged: bool = True) -> MetricEvidence:
    return MetricEvidence(
        name=name,
        value=1.0,
        display_name=name,
        category="test",
        direction_of_concern="higher_worse",
        evidence_strength="high",
        flags=["project_outlier"] if flagged else [],
        context_category="project" if flagged else "normal",
    )


def _catalog_names() -> set[str]:
    names = set()
    for path in IQMS_DIR.glob("*.json"):
        data = json.loads(path.read_text())
        names.update(data.get("metrics", {}))
        for key, entry in data.get("metric_patterns", {}).items():
            # lookup_metric matches a pattern's key as well as its matches list.
            names.update([key, *entry.get("matches", [])])
    return names


def _volume(tmp_path: Path, shape=(40, 48, 36)) -> tuple[Path, Path]:
    rng = np.random.default_rng(0)
    grid = np.indices(shape).astype(float)
    inside = np.asarray(sum(((g - (s - 1) / 2) / (0.4 * s)) ** 2 for g, s in zip(grid, shape)) <= 1)
    data = (rng.normal(5, 1, shape) + inside * 100).astype(np.float32)
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(tmp_path / "img.nii.gz"))
    nib.save(nib.Nifti1Image(inside.astype(np.uint8), np.eye(4)), str(tmp_path / "mask.nii.gz"))
    return tmp_path / "img.nii.gz", tmp_path / "mask.nii.gz"


class TestRuleTable:
    def test_examples_cover_every_rule(self):
        assert set(RULE_EXAMPLES) == {rule.name for rule in FLAG_RULES}

    @pytest.mark.parametrize("rule_name,metric", [(r, m) for r, ms in RULE_EXAMPLES.items() for m in ms])
    def test_rule_fires_on_its_flag_only(self, rule_name, metric):
        fired = [rule.name for rule, _ in fired_rules([_metric(metric)])]
        assert fired == [rule_name]

    def test_motion_flag_adds_motion_view_not_noise(self):
        metrics = [_metric("fd_mean"), _metric("efc", flagged=False), _metric("snr_total", flagged=False)]
        assert [rule.name for rule, _ in fired_rules(metrics)] == ["motion"]

    @pytest.mark.parametrize("metric", ["cjv", "inu_med", "wm2max", "tsnr", "dvars_std", "cnr"])
    def test_other_flags_fire_nothing(self, metric):
        assert fired_rules([_metric(metric)]) == []

    def test_unflagged_trigger_fires_nothing(self):
        assert fired_rules([_metric("fd_mean", flagged=False), _metric("efc", flagged=False)]) == []

    def test_both_rules_fire_in_table_order(self):
        fired = fired_rules([_metric("efc"), _metric("fd_mean")])
        assert [(rule.name, control) for rule, control in fired] == [("motion", False), ("noise", False)]

    def test_every_trigger_matches_a_catalog_metric(self):
        names = _catalog_names()
        for rule in FLAG_RULES:
            for pattern in rule.metrics:
                assert any(fnmatchcase(n, pattern) for n in names), (rule.name, pattern)

    def test_no_metric_triggers_two_rules(self):
        for name in _catalog_names():
            assert sum(rule_fires(rule, [_metric(name)]) for rule in FLAG_RULES) <= 1, name


class TestControlMode:
    def test_clean_bold_scan_gets_every_rule_as_control(self):
        metrics = [_metric("fd_mean", flagged=False), _metric("gsr_x", flagged=False)]
        fired = fired_rules(metrics, control=True)
        assert [(rule.name, control) for rule, control in fired] == [(r.name, True) for r in FLAG_RULES]

    def test_clean_anatomical_scan_gets_no_motion_control(self):
        metrics = [_metric("cjv", flagged=False), _metric("efc", flagged=False)]
        fired = fired_rules(metrics, control=True)
        assert [(rule.name, control) for rule, control in fired] == [("noise", True)]

    def test_rule_applies(self):
        motion = next(r for r in FLAG_RULES if r.name == "motion")
        assert rule_applies(motion, [_metric("fd_perc", flagged=False)])
        assert not rule_applies(motion, [_metric("cjv")])

    def test_flagged_scan_gets_no_controls(self):
        fired = fired_rules([_metric("efc")], control=True)
        assert [(rule.name, control) for rule, control in fired] == [("noise", False)]

    def test_control_off_clean_scan_gets_nothing(self):
        assert fired_rules([_metric("efc", flagged=False)]) == []

    def test_rendered_controls_are_marked(self, tmp_path):
        image, mask = _volume(tmp_path)
        scene = prepare_scene(image, mask_path=mask)
        metrics = [_metric("fd_mean", flagged=False), _metric("efc", flagged=False)]
        views = render_targeted_views(scene, tmp_path / "out", metrics, control=True)
        assert [(v.rule, v.kind, v.control) for v in views] == [(r.name, "targeted", True) for r in FLAG_RULES]
        for view in views:
            assert (tmp_path / "out" / view.path).is_file()


class TestRenderTargeted:
    def test_views_follow_the_rule(self, tmp_path):
        image, mask = _volume(tmp_path)
        scene = prepare_scene(image, mask_path=mask)
        views = render_targeted_views(scene, tmp_path / "out", [_metric("fd_mean"), _metric("snr_total")])
        by_rule = {v.rule: v for v in views}
        motion, noise = (next(r for r in FLAG_RULES if r.name == n) for n in ("motion", "noise"))
        assert by_rule["motion"].plane == "sagittal"
        assert by_rule["motion"].slice_positions == list(motion.bbox_fractions)
        assert by_rule["noise"].window_percentiles == noise.window_percentiles
        assert by_rule["noise"].path == "views/targeted_noise.png"
        assert all(not v.control for v in views)

    def test_no_flags_no_overlay_no_views(self, tmp_path):
        image, mask = _volume(tmp_path)
        scene = prepare_scene(image, mask_path=mask)
        assert render_targeted_views(scene, tmp_path / "out", [_metric("fd_mean", flagged=False)]) == []
        assert not (tmp_path / "out").exists()

    def test_mask_overlay_without_flags(self, tmp_path):
        image, mask = _volume(tmp_path)
        scene = prepare_scene(image, mask_path=mask)
        views = render_targeted_views(scene, tmp_path / "out", [], overlay_path=mask)
        assert [v.plane for v in views] == list(CORE_PLANES)
        assert all(v.rule == MASK_OVERLAY_RULE and not v.control for v in views)
        rgb = np.asarray(Image.open(tmp_path / "out" / views[0].path))
        assert rgb.ndim == 3
        assert ((rgb[..., 0] == 255) & (rgb[..., 1] == 64)).any()

    def test_overlay_on_another_grid_is_rejected(self, tmp_path):
        image, mask = _volume(tmp_path)
        scene = prepare_scene(image, mask_path=mask)
        other = tmp_path / "other.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((10, 10, 10), np.uint8), np.eye(4)), str(other))
        with pytest.raises(ValueError, match="overlay grid"):
            render_targeted_views(scene, tmp_path / "out", [], overlay_path=other)

    def test_deterministic(self, tmp_path):
        image, mask = _volume(tmp_path)
        scene = prepare_scene(image, mask_path=mask)
        metrics = [_metric("fd_mean"), _metric("efc")]
        a = render_targeted_views(scene, tmp_path / "a", metrics, overlay_path=mask)
        render_targeted_views(scene, tmp_path / "b", metrics, overlay_path=mask)
        for view in a:
            assert (tmp_path / "a" / view.path).read_bytes() == (tmp_path / "b" / view.path).read_bytes()

    def test_noise_view_uses_background_scene(self, tmp_path):
        image, mask = _volume(tmp_path)
        scene = prepare_scene(image, mask_path=mask)
        # A skull-stripped stand-in: zero outside the mask, so its background is empty.
        stripped = tmp_path / "stripped.nii.gz"
        data = np.asarray(nib.load(str(image)).dataobj) * np.asarray(nib.load(str(mask)).dataobj)
        nib.save(nib.Nifti1Image(data.astype(np.float32), np.eye(4)), str(stripped))
        stripped_scene = prepare_scene(stripped, mask_path=mask)
        metrics = [_metric("efc"), _metric("fd_mean")]
        render_targeted_views(stripped_scene, tmp_path / "a", metrics, background_scene=scene)
        render_targeted_views(scene, tmp_path / "native", metrics)
        render_targeted_views(stripped_scene, tmp_path / "stripped", metrics)
        noise, motion = "views/targeted_noise.png", "views/targeted_motion.png"
        assert (tmp_path / "a" / noise).read_bytes() == (tmp_path / "native" / noise).read_bytes()
        assert (tmp_path / "a" / motion).read_bytes() == (tmp_path / "stripped" / motion).read_bytes()

    def test_mask_overlay_on_mni_scene(self, tmp_path):
        affine = np.array([[2.0, 0, 0, -96.0], [0, 2.0, 0, -132.0], [0, 0, 2.0, -78.0], [0, 0, 0, 1.0]])
        shape = (97, 115, 97)
        data = np.random.default_rng(0).normal(100, 10, shape).astype(np.float32)
        mask = np.zeros(shape, np.uint8)
        mask[20:77, 20:95, 15:80] = 1
        nib.save(nib.Nifti1Image(data, affine), str(tmp_path / "mni.nii.gz"))
        nib.save(nib.Nifti1Image(mask, affine), str(tmp_path / "mni_mask.nii.gz"))
        scene = prepare_scene(tmp_path / "unused.nii.gz", template_image_path=tmp_path / "mni.nii.gz")
        views = render_targeted_views(scene, tmp_path / "out", [], overlay_path=tmp_path / "mni_mask.nii.gz")
        assert [(v.rule, v.placement) for v in views] == [(MASK_OVERLAY_RULE, "mni")] * 3
