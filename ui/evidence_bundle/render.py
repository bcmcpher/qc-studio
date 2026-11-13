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
from .models import Plane, PlacementMethod, ViewKind, ViewRef

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

OVERLAY_RGB = (255, 64, 64)
"""Colour of overlay outlines."""


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


def _load_on_grid(path: Path, volume: Volume, role: str) -> Volume:
    other = load_volume(path)
    if other.data.shape != volume.data.shape or not np.allclose(other.affine, volume.affine, atol=1e-3):
        raise ValueError(f"{path}: {role} grid does not match the image grid")
    return other


def load_mask(path: Path, volume: Volume) -> np.ndarray:
    """Load a mask on the volume's grid; raise ``ValueError`` when the grids differ."""
    return _load_on_grid(path, volume, "mask").data > 0


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


def label_edges(labels: np.ndarray) -> np.ndarray:
    """Pixels whose label differs from a 4-neighbour: the outline of a mask or each parcel."""
    edges = np.zeros(labels.shape, dtype=bool)
    edges[1:, :] |= labels[1:, :] != labels[:-1, :]
    edges[:-1, :] |= labels[:-1, :] != labels[1:, :]
    edges[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    edges[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    return edges


def render_plane(
    volume: Volume,
    plane: str,
    indices: Sequence[int],
    labels: Sequence[str],
    limits: tuple[float, float],
    overlay: Optional[np.ndarray] = None,
) -> Image.Image:
    """Render slices of one plane side by side, with a label under each and side letters.

    With ``overlay`` (an integer label volume on the same grid), the label outlines are drawn
    in ``OVERLAY_RGB`` and the image is RGB; otherwise it is grayscale.
    """
    if len(indices) != len(labels):
        raise ValueError("one label per slice is needed")
    font = _font()
    mode = "L" if overlay is None else "RGB"
    white = 255 if overlay is None else (255, 255, 255)
    gray = SEPARATOR_GRAY if overlay is None else (SEPARATOR_GRAY,) * 3
    canvas = Image.new(mode, (PANEL_SIZE_PX * len(indices), PANEL_SIZE_PX + LABEL_HEIGHT_PX), 0)
    draw = ImageDraw.Draw(canvas)
    left_side, right_side = PLANE_SIDES[plane]
    for n, (index, label) in enumerate(zip(indices, labels)):
        image, row_mm, col_mm = extract_slice(volume, plane, index)
        size = fit_size((image.shape[0], image.shape[1]), row_mm, col_mm, PANEL_SIZE_PX)
        tile = Image.fromarray(_to_uint8(image, limits), mode="L").resize(size, Image.Resampling.BILINEAR)
        if overlay is not None:
            label_slice = np.take(overlay, index, axis=PLANE_AXIS[plane]).T[::-1]
            # Nearest keeps label values; the outline is found at output resolution so it is 1 px.
            resized = np.asarray(Image.fromarray(label_slice.astype(np.int32), mode="I").resize(size, Image.Resampling.NEAREST))
            rgb = np.stack([np.asarray(tile)] * 3, axis=-1)
            rgb[label_edges(resized)] = OVERLAY_RGB
            tile = Image.fromarray(rgb, mode="RGB")
        x0 = n * PANEL_SIZE_PX
        canvas.paste(tile, (x0 + (PANEL_SIZE_PX - size[0]) // 2, (PANEL_SIZE_PX - size[1]) // 2))
        if n > 0:
            draw.line([(x0, 0), (x0, PANEL_SIZE_PX + LABEL_HEIGHT_PX - 1)], fill=gray)
        draw.text((x0 + 3, 2), left_side, fill=white, font=font)
        draw.text((x0 + PANEL_SIZE_PX - 3, 2), right_side, fill=white, font=font, anchor="ra")
        draw.text(
            (x0 + PANEL_SIZE_PX // 2, PANEL_SIZE_PX + LABEL_HEIGHT_PX // 2),
            label,
            fill=white,
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


@dataclass(frozen=True)
class Scene:
    """The volume all views of one scan are drawn from, and how slices are placed in it."""

    volume: Volume
    placement: PlacementMethod
    mask: Optional[np.ndarray]
    """Placement mask for ``bbox_fraction``; ``None`` for ``mni``."""


def prepare_scene(
    image_path: Path,
    *,
    template_image_path: Optional[Path] = None,
    mask_path: Optional[Path] = None,
) -> Scene:
    """Load the volume to draw and choose the slice placement.

    With ``template_image_path`` (an MNI152NLin2009cAsym image of the scan), that image is drawn
    and slices sit at MNI coordinates. Otherwise ``image_path`` is drawn and slices sit at
    fractions of the bounding box of ``mask_path`` (or of a threshold head mask when no mask is
    given). ``mask_path`` is ignored with a template image.
    """
    if template_image_path is not None:
        return Scene(volume=load_volume(template_image_path), placement="mni", mask=None)
    volume = load_volume(image_path)
    mask = load_mask(mask_path, volume) if mask_path is not None else head_mask(volume)
    return Scene(volume=volume, placement="bbox_fraction", mask=mask)


def load_overlay(path: Path, scene: Scene) -> np.ndarray:
    """Load a mask or label image on the scene's grid as integer labels.

    Raises ``ValueError`` when the grids differ.
    """
    overlay = _load_on_grid(path, scene.volume, "overlay")
    return np.rint(np.nan_to_num(overlay.data)).astype(np.int32)


def render_view(
    scene: Scene,
    bundle_dir: Path,
    *,
    name: str,
    kind: ViewKind,
    plane: Plane,
    mni_coords: Sequence[float],
    bbox_fractions: Sequence[float],
    window_percentiles: tuple[float, float],
    rule: Optional[str] = None,
    control: bool = False,
    overlay: Optional[np.ndarray] = None,
) -> ViewRef:
    """Render one view to ``bundle_dir/views/<name>.png`` and return its reference."""
    axis_name = AXIS_NAME[PLANE_AXIS[plane]]
    if scene.mask is None:
        positions = [float(p) for p in mni_coords]
        indices = mni_indices(scene.volume, plane, positions)
        labels = [f"{axis_name}={_format_position(p)} mm" for p in positions]
    else:
        positions = [float(p) for p in bbox_fractions]
        indices = bbox_indices(scene.mask, plane, positions)
        labels = [f"{axis_name} {round(100 * p)}%" for p in positions]
    limits = window_limits(scene.volume.data, window_percentiles)
    relative = Path("views") / f"{name}.png"
    save_png(render_plane(scene.volume, plane, indices, labels, limits, overlay), bundle_dir / relative)
    return ViewRef(
        path=relative.as_posix(),
        kind=kind,
        plane=plane,
        slice_positions=positions,
        placement=scene.placement,
        window_percentiles=window_percentiles,
        rule=rule,
        control=control,
    )


def render_core_views(scene: Scene, bundle_dir: Path) -> list[ViewRef]:
    """Render the core views (one image per plane) and return their references."""
    return [
        render_view(
            scene,
            bundle_dir,
            name=f"core_{plane}",
            kind="core",
            plane=plane,  # type: ignore[arg-type]
            mni_coords=CORE_MNI_COORDS[plane],
            bbox_fractions=CORE_BBOX_FRACTIONS,
            window_percentiles=CORE_WINDOW_PERCENTILES,
        )
        for plane in CORE_PLANES
    ]
