"""Tests for evidence bundle core views, on synthetic NIfTI volumes."""

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from PIL import Image

from evidence_bundle.constants import (
    CORE_BBOX_FRACTIONS,
    CORE_MNI_COORDS,
    CORE_PLANES,
    LABEL_HEIGHT_PX,
    PANEL_SIZE_PX,
)
from evidence_bundle.render import (
    Volume,
    bbox_indices,
    extract_slice,
    fit_size,
    load_volume,
    mni_indices,
    prepare_scene,
    render_core_views,
    to_volume,
    window_limits,
)

MNI_RES2_AFFINE = np.array([[2.0, 0, 0, -96.0], [0, 2.0, 0, -132.0], [0, 0, 2.0, -78.0], [0, 0, 0, 1.0]])
"""MNI152NLin2009cAsym ``res-2`` grid (97 x 115 x 97)."""


def _head(shape=(40, 48, 36), seed=0) -> np.ndarray:
    """A noisy ellipsoid on a dark background, with a bright marker at left-anterior-superior."""
    rng = np.random.default_rng(seed)
    grid = np.indices(shape).astype(float)
    centre = [(s - 1) / 2 for s in shape]
    radius = [0.4 * s for s in shape]
    inside = sum(((g - c) / r) ** 2 for g, c, r in zip(grid, centre, radius)) <= 1
    data = rng.normal(5, 1, shape) + inside * 100
    # Low x is subject left in RAS; high y is anterior; high z is superior.
    data[8:14, 30:36, 22:28] = 300
    return data.astype(np.float32)


def _save(data: np.ndarray, affine: np.ndarray, path: Path) -> Path:
    nib.save(nib.Nifti1Image(data, affine), str(path))
    return path


def _core(image, out, **kwargs):
    return render_core_views(prepare_scene(image, **kwargs), out)


def _ras_image(tmp_path: Path, zooms=(1.0, 1.0, 1.0), name="ras.nii.gz") -> Path:
    return _save(_head(), np.diag([*zooms, 1.0]), tmp_path / name)


def _bright_bbox(png: Path, panel: int) -> tuple[int, int, int, int]:
    """Bounding box (left, top, right, bottom) of bright pixels in one panel."""
    # Rows from 20 down skip the side letters at the top of the panel.
    image = np.asarray(Image.open(png))[20:PANEL_SIZE_PX, panel * PANEL_SIZE_PX : (panel + 1) * PANEL_SIZE_PX]
    rows = np.flatnonzero((image > 128).any(axis=1))
    cols = np.flatnonzero((image > 128).any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


class TestDeterminism:
    def test_two_runs_give_identical_bytes(self, tmp_path):
        image = _ras_image(tmp_path)
        _core(image, tmp_path / "a")
        _core(image, tmp_path / "b")
        for plane in CORE_PLANES:
            name = f"views/core_{plane}.png"
            assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()

    def test_fixed_output_size(self, tmp_path):
        small = _save(_head((20, 30, 16)), np.diag([2.0, 1.0, 3.0, 1.0]), tmp_path / "s.nii.gz")
        large = _save(_head((80, 90, 70)), np.eye(4), tmp_path / "l.nii.gz")
        for image, out in ((small, "s"), (large, "l")):
            for view in _core(image, tmp_path / out):
                size = Image.open(tmp_path / out / view.path).size
                assert size == (PANEL_SIZE_PX * len(CORE_BBOX_FRACTIONS), PANEL_SIZE_PX + LABEL_HEIGHT_PX)

    def test_png_has_no_metadata(self, tmp_path):
        _core(_ras_image(tmp_path), tmp_path / "out")
        assert not Image.open(tmp_path / "out/views/core_axial.png").info


class TestOrientation:
    @pytest.mark.parametrize("codes", [("L", "P", "S"), ("P", "I", "R"), ("S", "A", "L")])
    def test_non_ras_volume_matches_ras(self, tmp_path, codes):
        ras = nib.Nifti1Image(_head(), np.eye(4))
        transform = nib.orientations.ornt_transform(nib.orientations.axcodes2ornt(("R", "A", "S")), nib.orientations.axcodes2ornt(codes))
        other = ras.as_reoriented(transform)
        assert nib.aff2axcodes(other.affine) == codes
        nib.save(ras, str(tmp_path / "ras.nii.gz"))
        nib.save(other, str(tmp_path / "other.nii.gz"))
        _core(tmp_path / "ras.nii.gz", tmp_path / "a")
        _core(tmp_path / "other.nii.gz", tmp_path / "b")
        for plane in CORE_PLANES:
            name = f"views/core_{plane}.png"
            assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()

    def test_display_directions(self):
        volume = to_volume(nib.Nifti1Image(_head(), np.eye(4)))
        marker = (11, 33, 25)
        # Axial: subject left on the left, anterior at the top.
        axial, _, _ = extract_slice(volume, "axial", marker[2])
        row, col = np.unravel_index(np.argmax(axial), axial.shape)
        assert col < axial.shape[1] / 2 and row < axial.shape[0] / 2
        # Coronal: subject left on the left, superior at the top.
        coronal, _, _ = extract_slice(volume, "coronal", marker[1])
        row, col = np.unravel_index(np.argmax(coronal), coronal.shape)
        assert col < coronal.shape[1] / 2 and row < coronal.shape[0] / 2
        # Sagittal: anterior on the right, superior at the top.
        sagittal, _, _ = extract_slice(volume, "sagittal", marker[0])
        row, col = np.unravel_index(np.argmax(sagittal), sagittal.shape)
        assert col > sagittal.shape[1] / 2 and row < sagittal.shape[0] / 2

    def test_four_d_is_averaged(self):
        data = np.stack([_head(), _head(seed=1)], axis=3)
        volume = to_volume(nib.Nifti1Image(data, np.eye(4)))
        assert volume.data.shape == data.shape[:3]
        assert np.allclose(volume.data, data.mean(axis=3))


class TestAspect:
    def test_fit_size_keeps_physical_aspect(self):
        assert fit_size((20, 60), row_mm=3.0, col_mm=1.0, panel=240) == (240, 240)
        assert fit_size((60, 60), row_mm=1.0, col_mm=1.0, panel=256) == (256, 256)
        assert fit_size((30, 60), row_mm=1.0, col_mm=1.0, panel=256) == (256, 128)

    def test_anisotropic_cube_renders_square(self, tmp_path):
        # A 30 mm cube in 1 x 1 x 3 mm voxels: 30 x 30 x 10 voxels.
        data = np.zeros((60, 60, 20), dtype=np.float32)
        data[15:45, 15:45, 5:15] = 100
        image = _save(data, np.diag([1.0, 1.0, 3.0, 1.0]), tmp_path / "aniso.nii.gz")
        views = _core(image, tmp_path / "out")
        for view in views:
            if view.plane == "axial":
                continue
            left, top, right, bottom = _bright_bbox(tmp_path / "out" / view.path, panel=1)
            width, height = right - left + 1, bottom - top + 1
            assert abs(width - height) <= 3, (view.plane, width, height)


class TestPlacement:
    def test_fallback_without_template(self, tmp_path):
        views = _core(_ras_image(tmp_path), tmp_path / "out")
        assert [v.plane for v in views] == list(CORE_PLANES)
        for view in views:
            assert view.kind == "core"
            assert view.placement == "bbox_fraction"
            assert view.slice_positions == list(CORE_BBOX_FRACTIONS)
            assert (tmp_path / "out" / view.path).is_file()

    def test_mni_with_template(self, tmp_path):
        rng = np.random.default_rng(0)
        template = _save(rng.normal(100, 10, (97, 115, 97)).astype(np.float32), MNI_RES2_AFFINE, tmp_path / "mni.nii.gz")
        views = _core(tmp_path / "missing.nii.gz", tmp_path / "out", template_image_path=template)
        for view in views:
            assert view.placement == "mni"
            assert view.slice_positions == list(CORE_MNI_COORDS[view.plane])

    def test_mni_indices(self):
        volume = to_volume(nib.Nifti1Image(np.zeros((97, 115, 97), np.float32), MNI_RES2_AFFINE))
        assert mni_indices(volume, "axial", [-20.0, 10.0, 40.0]) == [29, 44, 59]
        assert mni_indices(volume, "sagittal", [0.0]) == [48]
        with pytest.raises(ValueError, match="outside the image"):
            mni_indices(volume, "axial", [500.0])

    def test_bbox_uses_mask(self, tmp_path):
        image = _ras_image(tmp_path)
        mask = np.zeros(_head().shape, dtype=np.uint8)
        mask[10:31, 5:15, 0:11] = 1
        mask_path = _save(mask, np.eye(4), tmp_path / "mask.nii.gz")
        assert bbox_indices(mask > 0, "sagittal", [0.0, 0.5, 1.0]) == [10, 20, 30]
        assert bbox_indices(mask > 0, "axial", [0.3]) == [3]
        _core(image, tmp_path / "masked", mask_path=mask_path)
        _core(image, tmp_path / "unmasked")
        a = (tmp_path / "masked/views/core_axial.png").read_bytes()
        assert a != (tmp_path / "unmasked/views/core_axial.png").read_bytes()

    def test_empty_mask_uses_whole_extent(self):
        assert bbox_indices(np.zeros((11, 5, 5), dtype=bool), "sagittal", [0.0, 0.5, 1.0]) == [0, 5, 10]

    def test_mask_on_another_grid_is_rejected(self, tmp_path):
        image = _ras_image(tmp_path)
        mask = _save(np.ones((10, 10, 10), np.uint8), np.eye(4), tmp_path / "mask.nii.gz")
        with pytest.raises(ValueError, match="does not match"):
            _core(image, tmp_path / "out", mask_path=mask)


class TestWindow:
    def test_percentiles_of_whole_volume(self):
        data = np.arange(1001, dtype=float).reshape(7, 11, 13)[:, :, :]
        assert window_limits(np.arange(1001, dtype=float), (0.5, 99.5)) == (5.0, 995.0)
        low, high = window_limits(data, (0.0, 100.0))
        assert (low, high) == (0.0, float(data.max()))

    def test_constant_and_nan_volumes(self):
        assert window_limits(np.full(10, 7.0), (0.5, 99.5)) == (7.0, 8.0)
        assert window_limits(np.full(10, np.nan), (0.5, 99.5)) == (0.0, 1.0)

    def test_load_volume_zooms(self, tmp_path):
        image = _ras_image(tmp_path, zooms=(1.0, 1.2, 2.5))
        volume = load_volume(image)
        assert isinstance(volume, Volume)
        assert volume.zooms == pytest.approx((1.0, 1.2, 2.5))
