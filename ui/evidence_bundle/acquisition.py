"""Acquisition metadata, protocol signature and the acquisition check.

Metadata comes from the MRIQC JSON (``bids_meta``, ``provenance``), the BIDS sidecar and the
NIfTI header. Only the allowlisted fields of ``models.AcquisitionMetadata`` are kept.
"""

from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union, get_args

import nibabel as nib

from utils.reference_data import normalize_field_strength, normalize_manufacturer

from .constants import SIGNATURE_ROUNDING
from .models import (
    AcquisitionDeviation,
    AcquisitionMetadata,
    GeometryMetadata,
    ProtocolSignature,
    ProvenanceMetadata,
    SignatureField,
)


_FLOAT_FIELDS = (
    "MagneticFieldStrength",
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "PixelBandwidth",
    "ParallelReductionFactorInPlane",
    "PartialFourier",
    "SliceThickness",
    "SpacingBetweenSlices",
)
"""Numeric sidecar fields of the allowlist."""


def _clean_sidecar(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce numeric allowlisted fields; drop nulls and values that are not numbers."""
    cleaned = {k: v for k, v in sidecar.items() if v is not None}
    if "MagneticFieldStrength" in cleaned:
        cleaned["MagneticFieldStrength"] = normalize_field_strength(cleaned["MagneticFieldStrength"])
    for name in set(_FLOAT_FIELDS) & set(cleaned):
        try:
            cleaned[name] = float(cleaned[name])
        except (TypeError, ValueError):
            del cleaned[name]
    return cleaned


def nifti_geometry(path: Union[str, Path]) -> GeometryMetadata:
    """Read shape, voxel size, orientation codes and field of view from a NIfTI header."""
    image = nib.load(str(path))
    shape = tuple(int(n) for n in image.shape)
    zooms = [float(z) for z in image.header.get_zooms()[:3]]
    axcodes = nib.orientations.aff2axcodes(image.affine)
    # Voxel size and field of view in RAS axis order (x = R-L, y = A-P, z = S-I), as MRIQC
    # reports ``spacing_*`` for its RAS-conformed image. Shape and orientation stay as stored.
    world_axis = [int(a) for a in nib.orientations.io_orientation(image.affine)[:, 0]]
    ras_zooms = [0.0, 0.0, 0.0]
    ras_extent = [0.0, 0.0, 0.0]
    for voxel_axis, axis in enumerate(world_axis):
        ras_zooms[axis] = zooms[voxel_axis]
        ras_extent[axis] = shape[voxel_axis] * zooms[voxel_axis]
    return GeometryMetadata.model_validate(
        {
            "shape": shape,
            "voxel_size": tuple(ras_zooms),
            "orientation": tuple(str(c) for c in axcodes),
            "field_of_view": tuple(ras_extent),
        }
    )


def _mriqc_geometry(mriqc: Mapping[str, Any]) -> GeometryMetadata:
    """Geometry from the MRIQC ``size_*`` and ``spacing_*`` IQMs, for when no image is read."""
    axes = ("x", "y", "z")
    try:
        shape = tuple(int(mriqc[f"size_{a}"]) for a in axes)
        voxel_size = tuple(float(mriqc[f"spacing_{a}"]) for a in axes)
    except (KeyError, TypeError, ValueError):
        return GeometryMetadata()
    fov = tuple(n * z for n, z in zip(shape, voxel_size))
    return GeometryMetadata.model_validate({"shape": shape, "voxel_size": voxel_size, "field_of_view": fov})


def extract_acquisition(
    mriqc: Optional[Mapping[str, Any]] = None,
    sidecar: Optional[Mapping[str, Any]] = None,
    nifti_path: Optional[Union[str, Path]] = None,
    site: Optional[str] = None,
) -> AcquisitionMetadata:
    """Build allowlisted acquisition metadata for one scan.

    Valid sidecar values win over the MRIQC ``bids_meta`` copy; a sidecar value that is null or
    not a number does not replace a valid ``bids_meta`` value. Geometry comes from the NIfTI
    header when ``nifti_path`` is given, otherwise from the MRIQC ``size_*``/``spacing_*`` IQMs.
    """
    mriqc = mriqc or {}
    merged = {**_clean_sidecar(mriqc.get("bids_meta") or {}), **_clean_sidecar(sidecar or {})}
    provenance = mriqc.get("provenance") or {}
    geometry = nifti_geometry(nifti_path) if nifti_path is not None else _mriqc_geometry(mriqc)
    return AcquisitionMetadata.from_sidecar(
        merged,
        site=site,
        geometry=geometry,
        provenance=ProvenanceMetadata(mriqc_version=provenance.get("version"), md5sum=provenance.get("md5sum")),
    )


def _round(value: float, step: float) -> float:
    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return round(round(value / step) * step, decimals)


def round_to_step(value: Optional[float], step: float) -> Optional[float]:
    """Round to a multiple of ``step``; the result carries no float noise beyond the step."""
    return None if value is None else _round(value, step)


def protocol_signature(suffix: str, acquisition: AcquisitionMetadata) -> ProtocolSignature:
    """Build the rounded protocol signature of one scan."""
    sequence, scanner = acquisition.sequence, acquisition.scanner
    voxel = acquisition.geometry.voxel_size
    step = SIGNATURE_ROUNDING["VoxelSize"]
    manufacturer = normalize_manufacturer(scanner.Manufacturer)
    return ProtocolSignature(
        suffix=suffix,
        MRAcquisitionType=sequence.MRAcquisitionType,
        MagneticFieldStrength=scanner.MagneticFieldStrength,
        Manufacturer=None if manufacturer == "unknown" else manufacturer,
        RepetitionTime=round_to_step(sequence.RepetitionTime, SIGNATURE_ROUNDING["RepetitionTime"]),
        EchoTime=round_to_step(sequence.EchoTime, SIGNATURE_ROUNDING["EchoTime"]),
        InversionTime=round_to_step(sequence.InversionTime, SIGNATURE_ROUNDING["InversionTime"]),
        FlipAngle=round_to_step(sequence.FlipAngle, SIGNATURE_ROUNDING["FlipAngle"]),
        VoxelSize=None if voxel is None else (_round(voxel[0], step), _round(voxel[1], step), _round(voxel[2], step)),
    )


CHECKED_FIELDS: tuple[SignatureField, ...] = tuple(f for f in get_args(SignatureField) if f != "suffix")


def acquisition_deviations(
    signatures: Sequence[ProtocolSignature],
    sites: Optional[Sequence[Optional[str]]] = None,
) -> list[list[AcquisitionDeviation]]:
    """Compare each scan's signature with the modal values of its suffix (and site) group.

    Returns one list of deviations per scan, in input order. A missing value counts as a value,
    so a null field differs from a non-null mode. Groups of one scan have no deviations. When
    two or more values tie for the most common, the field has no mode and no scan deviates.
    """
    sites = list(sites) if sites is not None else [None] * len(signatures)
    if len(sites) != len(signatures):
        raise ValueError("sites and signatures differ in length")
    groups: dict[tuple[str, Optional[str]], list[int]] = {}
    for index, (signature, site) in enumerate(zip(signatures, sites)):
        groups.setdefault((signature.suffix.lower(), site), []).append(index)

    result: list[list[AcquisitionDeviation]] = [[] for _ in signatures]
    for members in groups.values():
        n = len(members)
        if n < 2:
            continue
        for field in CHECKED_FIELDS:
            values = [getattr(signatures[i], field) for i in members]
            ranked = Counter(values).most_common(2)
            expected, count = ranked[0]
            if len(ranked) > 1 and ranked[1][1] == count:
                continue
            for i, value in zip(members, values):
                if value != expected:
                    result[i].append(AcquisitionDeviation(field=field, value=value, expected=expected, share=count / n, n=n))
    return result
