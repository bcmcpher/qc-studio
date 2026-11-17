"""Constants for the evidence bundle."""

CONTEXT_FILES: dict[str, tuple[str, ...]] = {
    "T1w": ("anat.json",),
    "T2w": ("anat.json", "t2w.json"),
    "bold": ("bold.json",),
    "dwi": ("dwi.json",),
}
"""Context files per BIDS suffix: a base file, then override files applied in order.

A suffix listed here has its own metric context and gets the ``supported`` tier.
"""

DEFAULT_CONTRAST_MAP: dict[str, str] = {"FLAIR": "T2w", "T2starw": "T2w"}
"""Suffixes without their own context, mapped to the suffix whose context they use (``fallback``).

Suffixes in neither ``CONTEXT_FILES`` nor this map are ``unsupported``. ``PDw`` is unmapped
because its contrast is close to neither T1w nor T2w.
"""

FALLBACK_CONTEXT_DEPENDENT: tuple[str, ...] = ("wm2max", "cjv", "tpm_overlap_*", "icvs_*", "rpve_*")
"""IQM names or globs that become ``context_dependent`` in a ``fallback`` context.

These depend on tissue contrast, so the mapped suffix's direction does not transfer.
"""

SIGNATURE_ROUNDING: dict[str, float] = {
    "RepetitionTime": 0.001,
    "EchoTime": 0.0001,
    "InversionTime": 0.01,
    "FlipAngle": 1.0,
    "VoxelSize": 0.1,
}
"""Rounding step per protocol-signature field, in sidecar units (seconds, degrees; voxel size mm).

TR rounds to 1 ms so short-TR gradient-echo protocols (for example 6.95 ms and 8.2 ms) stay
apart; echo time rounds to 0.1 ms because anatomical echo times are a few ms.
"""

SIGNATURE_FALLBACK_ORDER: tuple[str, ...] = (
    "FlipAngle",
    "InversionTime",
    "EchoTime",
    "RepetitionTime",
    "VoxelSize",
    "Manufacturer",
)
"""Signature fields dropped, in this order, while a stratum is below the minimum size."""

SIGNATURE_FIXED: tuple[str, ...] = ("suffix", "MRAcquisitionType", "MagneticFieldStrength")
"""Signature fields that are never dropped from a stratum."""

REFERENCE_SIGNATURE_FIELDS: tuple[str, ...] = ("MagneticFieldStrength", "Manufacturer", "VoxelSize")
"""Signature fields the MRIQC reference data holds (``spacing_*`` columns hold the voxel size).

``MagneticFieldStrength`` is never dropped; the others are dropped in ``SIGNATURE_FALLBACK_ORDER``.
"""

MAD_SCALE = 1.4826
"""Scales the median absolute deviation to the standard deviation of a normal distribution."""

OUTLIER_TOP_CONTRIBUTORS = 3
"""Number of metrics listed as the main contributors to the outlier score."""

OUTLIER_WINSOR_Z = 5.0
"""Robust z-scores of stratum members are clipped to this magnitude before the covariance."""

DEFAULT_MIN_STRATUM_SIZE = 10
DEFAULT_PROJECT_Z_THRESHOLD = 3.0
DEFAULT_REFERENCE_PERCENTILE_LOW = 2.5
DEFAULT_REFERENCE_PERCENTILE_HIGH = 97.5
"""Defaults for ``models.StatsConfig``; a project can change them per export."""

CORE_PLANES: tuple[str, ...] = ("axial", "coronal", "sagittal")
"""Planes of the core views, one image each, in this order."""

CORE_MNI_COORDS: dict[str, tuple[float, ...]] = {
    "axial": (-20.0, 10.0, 40.0),
    "coronal": (-60.0, -15.0, 20.0),
    "sagittal": (-35.0, 0.0, 35.0),
}
"""Core slice positions in MNI152NLin2009cAsym mm (z, y and x), three per image.

The number and positions are tuned in ``add-feedback-evaluation``.
"""

CORE_BBOX_FRACTIONS: tuple[float, ...] = (0.3, 0.5, 0.7)
"""Core slice positions as fractions of the mask's bounding box along the plane's axis."""

CORE_WINDOW_PERCENTILES: tuple[float, float] = (0.5, 99.5)
"""Display window: these percentiles of all finite voxels of the volume."""

HEAD_MASK_FRACTION = 0.1
"""Without a mask, voxels above this fraction of the 99th percentile form the head mask."""

PANEL_SIZE_PX = 256
"""Width and height of one slice panel; the slice is fitted inside it at its physical aspect."""

LABEL_HEIGHT_PX = 20
"""Height of the text strip under the panels."""

LABEL_FONT_SIZE = 12
"""Size of Pillow's built-in font for the labels."""

TEMPLATE_SPACE = "MNI152NLin2009cAsym"
"""Template space of the ``mni`` placement; its images are found by the ``space-`` entity."""

DERIVED_ENTITIES: tuple[str, ...] = ("space", "res", "desc")
"""BIDS entities a pipeline adds to a scan's name; removed to get the name MRIQC used."""

BASE_CATALOG_SUFFIX: dict[str, str] = {"anat": "T1w", "func": "bold", "dwi": "dwi"}
"""Per BIDS datatype, the suffix whose context names the metrics of an ``unsupported`` scan.

``T1w`` loads ``anat.json`` without overrides, the base catalog of anatomical scans.
"""
