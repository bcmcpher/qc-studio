"""Deterministic 2D views of a scan for the evidence bundle.

A volume is reoriented to RAS before slicing. Each plane gets one PNG that holds a few slices
side by side. Every slice is resized so one output pixel covers the same distance in mm along
both image axes, so anisotropic voxels are not distorted. Intensities are windowed with fixed
percentiles of the whole volume, so all slices and planes share one window. Labels are drawn
with Pillow's built-in font; matplotlib is not used.

Slice positions are fixed MNI coordinates when the caller passes a template-space image, and
fractions of the brain-mask bounding box otherwise. Each ``ViewRef`` records the method.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .constants import (
    CORE_BBOX_FRACTIONS,
    CORE_MNI_COORDS,
    CORE_PLANES,
    CORE_WINDOW_PERCENTILES,
    HEAD_MASK_FRACTION,
    LABEL_FONT_SIZE,
    LABEL_HEIGHT_PX,
    PANEL_SIZE_PX,
)
from .models import ViewRef

PLANE_AXIS: dict[str, int] = {"sagittal": 0, "coronal": 1, "axial": 2}
"""RAS array axis that is fixed for each plane."""

AXIS_NAME = ("x", "y", "z")

PLANE_SIDES: dict[str, tuple[str, str]] = {
    "axial": ("L", "R"),
    "coronal": ("L", "R"),
    "sagittal": ("P", "A"),
}
"""Subject direction at the left and right edge of each panel (neurological convention)."""

SEPARATOR_GRAY = 96
"""Gray level of the vertical line between panels."""


@dataclass(frozen=True)
class Volume:
    """A 3D volume in RAS voxel order."""

    data: np.ndarray
    affine: np.ndarray
    zooms: tuple[float, float, float]


def to_volume(img: Any) -> Volume:
    """Reorient an image to the closest RAS orientation; average a 4D image over time."""
    canonical = nib.as_closest_canonical(img)
    data = np.asarray(canonical.dataobj, dtype=np.float64)
    if data.ndim == 4:
        data = data.mean(axis=3)
    if data.ndim != 3:
        raise ValueError(f"expected a 3D or 4D image, got {data.ndim} dimensions")
    zooms = tuple(float(z) for z in canonical.header.get_zooms()[:3])
    return Volume(data=data, affine=np.asarray(canonical.affine), zooms=zooms)  # type: ignore[arg-type]


def load_volume(path: Path) -> Volume:
    """Load a NIfTI file as a RAS volume."""
    return to_volume(nib.load(str(path)))  # type: ignore[arg-type]


def window_limits(data: np.ndarray, percentiles: tuple[float, float]) -> tuple[float, float]:
    """Return the display window: the given percentiles of all finite voxels."""
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0.0, 1.0
    low, high = (float(v) for v in np.percentile(finite, percentiles))
    if high <= low:
        high = low + 1.0
    return low, high


def head_mask(volume: Volume) -> np.ndarray:
    """Threshold mask for when no brain mask is given: voxels above a fraction of the 99th pct."""
    finite = np.isfinite(volume.data)
    if not finite.any():
        return np.zeros(volume.data.shape, dtype=bool)
    level = HEAD_MASK_FRACTION * float(np.percentile(volume.data[finite], 99))
    return finite & (volume.data > level)


def load_mask(path: Path, volume: Volume) -> np.ndarray:
    """Load a mask on the volume's grid; raise ``ValueError`` when the grids differ."""
    mask = load_volume(path)
    if mask.data.shape != volume.data.shape or not np.allclose(mask.affine, volume.affine, atol=1e-3):
        raise ValueError(f"{path}: mask grid does not match the image grid")
    return mask.data > 0


def bbox_indices(mask: np.ndarray, plane: str, fractions: Sequence[float]) -> list[int]:
    """Slice indices at fractions of the mask's bounding box along the plane's axis.

    An empty mask uses the whole volume extent.
    """
    axis = PLANE_AXIS[plane]
    other = tuple(a for a in range(3) if a != axis)
    present = np.flatnonzero(mask.any(axis=other))
    if present.size == 0:
        low, high = 0, mask.shape[axis] - 1
    else:
        low, high = int(present[0]), int(present[-1])
    return [int(round(low + f * (high - low))) for f in fractions]


def mni_indices(volume: Volume, plane: str, coords: Sequence[float]) -> list[int]:
    """Slice indices of world coordinates (mm) along the plane's axis.

    The volume must be in template space. Raises ``ValueError`` for a coordinate outside it.
    """
    axis = PLANE_AXIS[plane]
    inverse = np.linalg.inv(volume.affine)
    indices = []
    for coord in coords:
        world = np.zeros(4)
        world[axis] = coord
        world[3] = 1.0
        index = int(round(float((inverse @ world)[axis])))
        if not 0 <= index < volume.data.shape[axis]:
            raise ValueError(f"{plane} {AXIS_NAME[axis]}={coord} mm lies outside the image")
        indices.append(index)
    return indices


def extract_slice(volume: Volume, plane: str, index: int) -> tuple[np.ndarray, float, float]:
    """Return one slice for display and its row and column spacing in mm.

    Rows run from superior (or anterior, for axial) at the top; columns run from subject left
    (or posterior, for sagittal) at the left.
    """
    axis = PLANE_AXIS[plane]
    cols_axis, rows_axis = (a for a in range(3) if a != axis)
    plane_data = np.take(volume.data, index, axis=axis)
    image = plane_data.T[::-1]
    return image, volume.zooms[rows_axis], volume.zooms[cols_axis]


def fit_size(shape: tuple[int, int], row_mm: float, col_mm: float, panel: int) -> tuple[int, int]:
    """Width and height in pixels that fit a slice in the panel at its physical aspect."""
    height_mm = shape[0] * row_mm
    width_mm = shape[1] * col_mm
    scale = panel / max(height_mm, width_mm)
    return max(1, int(round(width_mm * scale))), max(1, int(round(height_mm * scale)))


def _to_uint8(image: np.ndarray, limits: tuple[float, float]) -> np.ndarray:
    low, high = limits
    scaled = (np.nan_to_num(image, nan=low) - low) / (high - low)
    return np.round(np.clip(scaled, 0.0, 1.0) * 255.0).astype(np.uint8)


def _font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=LABEL_FONT_SIZE)


def render_plane(
    volume: Volume,
    plane: str,
    indices: Sequence[int],
    labels: Sequence[str],
    limits: tuple[float, float],
) -> Image.Image:
    """Render slices of one plane side by side, with a label under each and side letters."""
    if len(indices) != len(labels):
        raise ValueError("one label per slice is needed")
    font = _font()
    canvas = Image.new("L", (PANEL_SIZE_PX * len(indices), PANEL_SIZE_PX + LABEL_HEIGHT_PX), 0)
    draw = ImageDraw.Draw(canvas)
    left_side, right_side = PLANE_SIDES[plane]
    for n, (index, label) in enumerate(zip(indices, labels)):
        image, row_mm, col_mm = extract_slice(volume, plane, index)
        size = fit_size((image.shape[0], image.shape[1]), row_mm, col_mm, PANEL_SIZE_PX)
        tile = Image.fromarray(_to_uint8(image, limits), mode="L").resize(size, Image.Resampling.BILINEAR)
        x0 = n * PANEL_SIZE_PX
        canvas.paste(tile, (x0 + (PANEL_SIZE_PX - size[0]) // 2, (PANEL_SIZE_PX - size[1]) // 2))
        if n > 0:
            draw.line([(x0, 0), (x0, PANEL_SIZE_PX + LABEL_HEIGHT_PX - 1)], fill=SEPARATOR_GRAY)
        draw.text((x0 + 3, 2), left_side, fill=255, font=font)
        draw.text((x0 + PANEL_SIZE_PX - 3, 2), right_side, fill=255, font=font, anchor="ra")
        draw.text(
            (x0 + PANEL_SIZE_PX // 2, PANEL_SIZE_PX + LABEL_HEIGHT_PX // 2),
            label,
            fill=255,
            font=font,
            anchor="mm",
        )
    return canvas


def save_png(image: Image.Image, path: Path) -> None:
    """Write a PNG with no metadata, so identical images give identical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False)


def _format_position(value: float) -> str:
    return f"{value:g}"


def render_core_views(
    image_path: Path,
    bundle_dir: Path,
    *,
    template_image_path: Optional[Path] = None,
    mask_path: Optional[Path] = None,
) -> list[ViewRef]:
    """Render the core views into ``bundle_dir/views`` and return their references.

    With ``template_image_path`` (an MNI152NLin2009cAsym image of the scan), that image is
    rendered at ``CORE_MNI_COORDS`` and positions are recorded in mm. Otherwise ``image_path``
    is rendered at ``CORE_BBOX_FRACTIONS`` of the bounding box of ``mask_path`` (or of a
    threshold head mask when no mask is given), and positions are recorded as fractions.
    """
    if template_image_path is not None:
        volume = load_volume(template_image_path)
        placement = "mni"
        mask = None
    else:
        volume = load_volume(image_path)
        placement = "bbox_fraction"
        mask = load_mask(mask_path, volume) if mask_path is not None else head_mask(volume)

    limits = window_limits(volume.data, CORE_WINDOW_PERCENTILES)
    views = []
    for plane in CORE_PLANES:
        axis_name = AXIS_NAME[PLANE_AXIS[plane]]
        if mask is None:
            positions = list(CORE_MNI_COORDS[plane])
            indices = mni_indices(volume, plane, positions)
            labels = [f"{axis_name}={_format_position(p)} mm" for p in positions]
        else:
            positions = list(CORE_BBOX_FRACTIONS)
            indices = bbox_indices(mask, plane, positions)
            labels = [f"{axis_name} {round(100 * p)}%" for p in positions]
        relative = Path("views") / f"core_{plane}.png"
        save_png(render_plane(volume, plane, indices, labels, limits), bundle_dir / relative)
        views.append(
            ViewRef(
                path=relative.as_posix(),
                kind="core",
                plane=plane,  # type: ignore[arg-type]
                slice_positions=positions,
                placement=placement,  # type: ignore[arg-type]
                window_percentiles=CORE_WINDOW_PERCENTILES,
            )
        )
    return views
