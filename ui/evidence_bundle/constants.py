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
