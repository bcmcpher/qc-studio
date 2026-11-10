"""Data loading utilities for QC-Studio.

This module loads MRI files, montages, scanner metadata, IQM metrics, and
reference IQM tables from dataset and pipeline outputs.
"""

import json
import re
import pandas as pd

from pathlib import Path

from typing import Optional, Union, Tuple

from constants import NIIVUE_MAX_FILE_BYTES


def _resolve_all_under_dataset(base_root: Path, rel_path: Union[str, Path, None]) -> list[Path]:
    """Resolve a dataset-relative path to zero or more files (globs return all sorted matches)."""
    if rel_path is None:
        return []
    rel = Path(rel_path)
    direct = base_root / rel
    if "*" in str(rel):
        matches = sorted(p for p in base_root.glob(str(rel)) if p.is_file())
        if matches:
            return matches
    if direct.is_file():
        return [direct]
    no_ses_name = re.sub(r"_ses-[^_]+", "", direct.name)
    fallback = direct.parent / no_ses_name
    if fallback.is_file():
        return [fallback]
    return []


def _expand_dataset_paths(base_root: Path, paths_value: Union[str, Path, list, None]) -> list[Path]:
    """Expand path specs to concrete files; globs include every match."""
    if paths_value is None:
        return []
    specs = paths_value if isinstance(paths_value, list) else [paths_value]
    expanded: list[Path] = []
    seen: set[Path] = set()
    for spec in specs:
        for path in _resolve_all_under_dataset(base_root, spec):
            if path not in seen:
                seen.add(path)
                expanded.append(path)
    return expanded


def _resolve_under_dataset(base_root: Path, rel_path: Union[str, Path, None]) -> Optional[Path]:
    """Resolve a single dataset-relative file (first glob match when multiple exist)."""
    matches = _resolve_all_under_dataset(base_root, rel_path)
    return matches[0] if matches else None


def _nifti_volume_to_bytes(img, vol_index: int = 0) -> bytes:
    """Serialize one 3D volume from a NIfTI image (handles 4D via mmap slice)."""
    import numpy as np
    import nibabel as nib

    shape = img.shape
    if len(shape) == 4:
        vol = np.asanyarray(img.dataobj[..., vol_index])
    elif len(shape) == 3:
        vol = np.asanyarray(img.dataobj)
    else:
        raise ValueError(f"Unsupported NIfTI rank for Niivue preview: {len(shape)}")
    hdr = img.header.copy()
    hdr.set_data_shape(vol.shape)
    out = nib.Nifti1Image(vol, img.affine, hdr)
    return out.to_bytes()


def _read_nifti_bytes_for_niivue(path: Path) -> Tuple[Optional[bytes], bool, Optional[str]]:
    """Load NIfTI bytes for Niivue; reduce 4D / oversize files to the first volume."""
    size = path.stat().st_size
    try:
        import nibabel as nib
    except ImportError:
        if size > NIIVUE_MAX_FILE_BYTES:
            return None, False, "oversize"
        return path.read_bytes(), False, None

    try:
        img = nib.load(str(path))
        reduce = size > NIIVUE_MAX_FILE_BYTES or len(img.shape) == 4
        if reduce:
            vol_bytes = _nifti_volume_to_bytes(img, vol_index=0)
            if len(vol_bytes) > NIIVUE_MAX_FILE_BYTES:
                return None, True, "oversize"
            return vol_bytes, True, None
        if size > NIIVUE_MAX_FILE_BYTES:
            return None, False, "oversize"
        return path.read_bytes(), False, None
    except Exception:
        if size <= NIIVUE_MAX_FILE_BYTES:
            return path.read_bytes(), False, None
        return None, False, "oversize"


def _attach_nifti_bytes(file_bytes_dict: dict, path: Path, prefix: str) -> None:
    """Read NIfTI bytes for Niivue (first BOLD volume when 4D or file is large)."""
    nbytes, reduced, err = _read_nifti_bytes_for_niivue(path)
    file_bytes_dict[f"{prefix}_mri_image_path"] = path
    if nbytes is not None:
        file_bytes_dict[f"{prefix}_mri_image_bytes"] = nbytes
        if reduced:
            file_bytes_dict[f"{prefix}_mri_preview_reduced"] = True
        return
    if err == "oversize":
        file_bytes_dict[f"{prefix}_mri_oversize"] = True
        file_bytes_dict[f"{prefix}_mri_size_bytes"] = path.stat().st_size


def load_mri_data(
    dataset_dir: Union[str, Path, dict],
    path_dict: Optional[dict] = None,
) -> dict:
    """Load base and overlay MRI image files as bytes.

    Supports ``load_mri_data(dataset_dir, path_dict)`` (paths relative to
    ``dataset_dir``) and ``load_mri_data(path_dict)`` (paths already absolute
    or cwd-relative).

    Args:
            dataset_dir: Root directory containing the dataset, or a path_dict if
                    ``path_dict`` is omitted.
            path_dict: Dictionary with keys 'base_mri_image_path' and 'overlay_mri_image_path'

    Returns:
            dict with keys: 'base_mri_image_bytes', 'base_mri_image_path',
            'overlay_mri_image_bytes', 'overlay_mri_image_path'
            Returns empty dict if files don't exist
    """
    if path_dict is None:
        if not isinstance(dataset_dir, dict):
            raise TypeError("load_mri_data: pass either path_dict only or (dataset_dir, path_dict)")
        path_dict = dataset_dir
        dataset_dir = ""

    base_root = Path(dataset_dir) if dataset_dir else Path()
    base_mri_path = _resolve_under_dataset(base_root, path_dict.get("base_mri_image_path"))
    overlay_mri_path = _resolve_under_dataset(base_root, path_dict.get("overlay_mri_image_path"))

    file_bytes_dict = {}

    if base_mri_path is not None and base_mri_path.is_file():
        _attach_nifti_bytes(file_bytes_dict, base_mri_path, "base")

    if overlay_mri_path is not None and overlay_mri_path.is_file():
        _attach_nifti_bytes(file_bytes_dict, overlay_mri_path, "overlay")

    return file_bytes_dict


def load_iqm_data(path_dict: dict) -> Optional[dict]:
    """Load IQM metrics from a JSON file referenced by ``path_dict['iqm_path']``.

    Returns ``None`` if the path is missing, the file does not exist, or JSON is invalid.
    """
    iqm_ref = path_dict.get("iqm_path")
    if not iqm_ref:
        return None
    iqm_path = Path(iqm_ref)
    if not iqm_path.is_file():
        return None
    try:
        return json.loads(iqm_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_montage_paths(montage_paths_value):
    """Normalize montage paths to a list of Path objects."""

    if isinstance(montage_paths_value, (str, Path)):
        return [Path(montage_paths_value)]

    if isinstance(montage_paths_value, list):
        normalized_paths = []
        for p in montage_paths_value:
            if p is None:
                continue
            try:
                normalized_paths.append(Path(p))
            except TypeError:
                # Ignore malformed path entries and keep loading valid montage files.
                continue
        return normalized_paths

    return None


def load_montage_data(dataset_dir, path_dict: dict, max_montage_rows=None, max_montage_cols=None) -> Optional[dict]:
    """Normalize montage paths from a QC config and return display data.

    Delegates file reads and montage creation to ``_build_montage_display_data``.
    Uncached; see ``qc_viewer._load_montage_data_cached``.

    Args:
            dataset_dir: Base directory path for resolving relative paths.
            path_dict: Dictionary containing 'montage_path' key with:
                    - None (no montage)
                    - Single Path/str object
                    - List of Path/str objects
            max_montage_rows: Maximum rows for grid montage.
            max_montage_cols: Maximum columns for grid montage.

    Returns:
            Display data from ``_build_montage_display_data``, or None if no
            montage paths are configured.
    """
    montage_paths_value = path_dict.get("montage_path")
    if not montage_paths_value:
        return None

    # Normalize to list of paths
    montage_paths_value = _normalize_montage_paths(montage_paths_value)

    if not montage_paths_value:
        return None

    base_root = Path(dataset_dir) if dataset_dir else Path()
    resolved_paths = _expand_dataset_paths(base_root, montage_paths_value)
    if not resolved_paths:
        return None

    return _build_montage_display_data(
        tuple(str(path) for path in resolved_paths),
        max_montage_rows,
        max_montage_cols,
    )


def _create_unique_id_from_path(file_path: Path) -> str:
    """Create a unique identifier from the last 2-3 components of a file path.

    Args:
            file_path: Path object for the file.

    Returns:
            Unique identifier string based on the last 2-3 path components.
    """
    path_parts = file_path.parts

    if len(path_parts) >= 3:
        # Use last 3 path components (grandparent dir + parent dir + stem)
        grandparent = path_parts[-3]
        parent = path_parts[-2]
        stem = file_path.stem
        return f"{grandparent}_{parent}_{stem}"
    elif len(path_parts) >= 2:
        # Fallback: use parent dir + stem
        parent = path_parts[-2]
        stem = file_path.stem
        return f"{parent}_{stem}"
    else:
        return file_path.stem


def _load_montage_entry(full_path: Path, unique_id: str):
    try:
        with open(full_path, encoding="utf-8") as f:
            montage_content = f.read()

        filename = f"{unique_id}_svg"
        data_content = {
            "type": "svg",
            "content": montage_content,
        }

        # Convert SVG to image for montage (optional - if conversion fails, SVG is still available as string)
        try:
            pil_img = _load_image_from_file(full_path)
        except Exception:
            # SVG conversion not critical; skip but keep the SVG string version for rendering
            pil_img = None

        return filename, data_content, pil_img

    except Exception as e:
        print(f"Failed to load Montage file {full_path}: {e}")
        return None


def _load_raster_entry(full_path: Path, unique_id: str, raster_type: str):
    try:
        pil_img = _load_image_from_file(full_path)

        filename = f"{unique_id}_{raster_type}"
        data_content = {"type": raster_type, "content": pil_img}
        return filename, data_content, pil_img

    except ValueError:
        return None


def _add_montage_if_available(
    image_data_dict: dict,
    images_for_montage: list,
    max_montage_rows=None,
    max_montage_cols=None,
) -> dict:
    if len(images_for_montage) <= 1:
        # Keep individual images for single-image montages, without injecting a
        # synthetic combined montage tab.
        return image_data_dict

    try:
        from .image_processing import create_grid_montage

        montage_img = create_grid_montage(
            images_for_montage,
            max_rows=max_montage_rows,
            max_cols=max_montage_cols,
        )
        result_dict = {"montage": {"type": "png", "content": montage_img}}
        result_dict.update(image_data_dict)
        return result_dict
    except Exception:
        return image_data_dict


def _build_montage_display_data(montage_paths: tuple, max_montage_rows=None, max_montage_cols=None) -> Optional[dict]:
    """Load montage image files and build display data. Uncached; see ``load_montage_data``.

    Args:
            montage_paths: Tuple of SVG/PNG/JPEG paths to load.
            max_montage_rows: Maximum rows for grid montage.
            max_montage_cols: Maximum columns for grid montage.

    Returns:
            Dict with image keys mapped to ``{"type": ..., "content": ...}``.
            SVG content is returned as a string; PNG/JPEG content is returned as a
            PIL Image. If multiple images can be converted for montage display, a
            ``"montage"`` entry is inserted first. Returns None if no valid image
            files are found.

    Notes:
            - Unsupported formats are silently skipped.
            - SVG-to-image conversion is optional; if conversion fails, the SVG text
              is still returned for direct rendering.
    """
    image_data_dict = {}
    images_for_montage = []  # Collect PIL Images for montage creation

    for montage_path in montage_paths:
        full_path = Path(montage_path)
        if not full_path.is_file():
            continue
        file_ext = full_path.suffix.lower()

        # Create unique identifier using last 3 path components to avoid collisions
        # E.g., "screenshots/sub-CMH0001/sub-CMH0001.png" -> "screenshots_sub-CMH0001_sub"
        unique_id = _create_unique_id_from_path(full_path)

        if file_ext == ".svg":
            # Return SVG as string content (use open() so tests can mock builtins.open)
            loaded_entry = _load_montage_entry(full_path, unique_id)
            if loaded_entry is None:
                continue
            filename, data_content, pil_img = loaded_entry
            image_data_dict[filename] = data_content
            if pil_img is not None:
                images_for_montage.append(pil_img)

        elif file_ext in [".png", ".jpg", ".jpeg"]:
            # Return PNG/JPEG as PIL Image
            raster_type = "jpeg" if file_ext in (".jpg", ".jpeg") else file_ext.lstrip(".")
            loaded_entry = _load_raster_entry(full_path, unique_id, raster_type)
            if loaded_entry is None:
                continue
            filename, data_content, pil_img = loaded_entry
            image_data_dict[filename] = data_content
            images_for_montage.append(pil_img)

    if not image_data_dict:
        return None

    return _add_montage_if_available(
        image_data_dict,
        images_for_montage,
        max_montage_rows=max_montage_rows,
        max_montage_cols=max_montage_cols,
    )


def _load_image_from_file(file_path, dpi=96):
    """Load image from file path, supporting both raster and SVG formats.

    Args:
            file_path: Path to image file (SVG, PNG, JPG, JPEG)
            dpi: DPI for Montage rendering (default: 96)

    Returns:
            PIL.Image: Image object in RGB mode

    Raises:
            ValueError: If file format is not supported or conversion fails
    """
    from io import BytesIO
    from PIL import Image

    file_path = Path(file_path)
    file_ext = file_path.suffix.lower()

    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")

    if file_ext == ".svg":
        try:
            import cairosvg

            # Convert SVG to PNG in memory
            png_data = cairosvg.svg2png(bytestring=file_path.read_bytes(), dpi=dpi)
            img = Image.open(BytesIO(png_data))
        except ImportError:
            raise ValueError("cairosvg library required for SVG support. " "Install it with: pip install cairosvg")
        except Exception as e:
            raise ValueError(f"Failed to convert SVG file {file_path}: {e}")
    elif file_ext in [".png", ".jpg", ".jpeg"]:
        try:
            img = Image.open(file_path)
        except Exception as e:
            raise ValueError(f"Failed to load image file {file_path}: {e}")
    else:
        raise ValueError(f"Unsupported image format: {file_ext}. " f"Supported formats: SVG, PNG, JPG, JPEG")

    # Ensure image is in RGB mode
    if img.mode != "RGB":
        img = img.convert("RGB")

    return img


def _resolve_metadata_path(image_path: Union[Path, str]) -> Path:
    """Returning the JSON sidecar path for a BIDS image file."""
    if not image_path:
        return None
    image_path = Path(image_path)
    image_name = image_path.name
    if image_name.endswith(".nii.gz"):
        json_name = image_name.replace(".nii.gz", ".json")
    elif image_name.endswith(".nii"):
        json_name = image_name.replace(".nii", ".json")
    else:
        return None

    return image_path.parent / json_name


def _infer_bids_ids_from_path(image_path: Union[Path, str]) -> tuple:
    """Infer BIDS participant/session IDs from a file path string."""
    if not image_path:
        return None, None

    path_str = str(image_path)
    participant_match = re.search(r"(sub-[A-Za-z0-9]+)", path_str)
    session_match = re.search(r"(ses-[A-Za-z0-9]+)", path_str)

    participant_id = participant_match.group(1) if participant_match else None
    session_id = session_match.group(1) if session_match else None
    return participant_id, session_id


def _infer_dataset_root_from_path(image_path: Union[Path, str]) -> Optional[Path]:
    """Infer dataset root from a path containing BIDS-like folders."""
    if not image_path:
        return None

    path_obj = Path(image_path)
    parts = path_obj.parts

    if "derivatives" in parts:
        idx = parts.index("derivatives")
        return Path(*parts[:idx]) if idx > 0 else Path(".")

    if "bids" in parts:
        idx = parts.index("bids")
        return Path(*parts[:idx]) if idx > 0 else Path(".")

    return None


# Folder + filename-suffix to search for, per BIDS modality.
MODALITY_SIDECAR_HINTS = {
    "anat": ("anat", "T1w"),
    "t1w": ("anat", "T1w"),
    "func": ("func", "bold"),
    "bold": ("func", "bold"),
    "dwi": ("dwi", "dwi"),
    "diffusion": ("dwi", "dwi"),
}


def _infer_bids_folder_from_path(path: Union[Path, str]) -> Optional[str]:
    """Infer a BIDS modality folder from a path or filename."""
    if not path:
        return None

    path_str = str(path).lower()
    name = Path(path).name.lower()

    if "/func/" in path_str or re.search(r"_(bold|sbref)\.", path_str) or "bold" in name:
        return "func"
    if "/dwi/" in path_str or re.search(r"_dwi\.", path_str) or "dwi" in name:
        return "dwi"
    if "/anat/" in path_str or "t1w" in name:
        return "anat"
    return None


def _find_bids_metadata_sidecar(
    dataset_root: Union[Path, str],
    participant_id: str = None,
    session_id: str = None,
    modality: str = "anat",
) -> Optional[Path]:
    """Find a likely scanner-metadata sidecar for a participant."""
    if not dataset_root or not participant_id:
        return None

    dataset_root = Path(dataset_root)
    folder, suffix = MODALITY_SIDECAR_HINTS.get(str(modality).lower(), ("anat", "T1w"))

    if not participant_id.startswith("sub-"):
        participant_id = f"sub-{participant_id}"
    if session_id and not session_id.startswith("ses-"):
        session_id = f"ses-{session_id}"

    def _patterns_for(prefix: str) -> list:
        patterns = []
        if session_id:
            patterns.extend(
                [
                    f"{prefix}{participant_id}/{session_id}/{folder}/*{suffix}*.json",
                    f"{prefix}{participant_id}/{session_id}/{folder}/*.json",
                    f"{prefix}{participant_id}/{session_id}/**/*{suffix}*.json",
                ]
            )
        patterns.extend(
            [
                f"{prefix}{participant_id}/**/*{suffix}*.json",
                f"{prefix}{participant_id}/**/{folder}/*.json",
            ]
        )
        return patterns

    # Raw BIDS sidecars are the authoritative source when present.
    bids_root = dataset_root / "bids"
    if not bids_root.is_dir():
        bids_root = dataset_root
    search_roots = [(bids_root, "")]

    # Fall back to derivative sidecars when raw BIDS metadata is unavailable.
    derivatives_root = dataset_root / "derivatives"
    if derivatives_root.is_dir():
        search_roots.append((derivatives_root, "**/"))

    for root, prefix in search_roots:
        for pattern in _patterns_for(prefix):
            matches = sorted(root.glob(pattern))
            for match in matches:
                if match.is_file():
                    return match

    return None


def load_scanner_metadata(
    image_path: Union[Path, str], participant_id: str = None, session_id: str = None, modality: str = None, dataset_dir: Union[Path, str] = None
) -> dict:
    """Load scanner metadata from the JSON sidecar of a BIDS image file.

    If the direct sidecar is unavailable, look for a participant/session sidecar
    under raw BIDS or derivatives and fall back to "Unknown" values.
    """
    if dataset_dir and image_path:
        image_path = Path(dataset_dir) / image_path

    json_path = _resolve_metadata_path(image_path)
    dataset_root = _infer_dataset_root_from_path(image_path)

    # Prefer IDs inferred from image path when explicit IDs are not provided.
    inferred_participant, inferred_session = _infer_bids_ids_from_path(image_path)
    participant_id = participant_id or inferred_participant
    session_id = session_id or inferred_session
    modality = modality or _infer_bids_folder_from_path(image_path) or "anat"

    if not json_path or not Path(json_path).is_file():
        json_path = _find_bids_metadata_sidecar(dataset_root, participant_id, session_id, modality=modality)

    # Metadata sidecar may be absent for derivative images. Fall back to
    # unknown values instead of failing the whole IQM panel.
    if not json_path or not Path(json_path).is_file():
        return {
            "Manufacturer": "Unknown",
            "MagneticFieldStrength": "Unknown",
            "ProtocolName": "Unknown",
        }

    with open(json_path, "r") as f:
        metadata = json.load(f)

    # MRIQC sidecars may nest original BIDS metadata under "bids_meta".
    bids_meta = metadata.get("bids_meta") or {}

    return {
        "Manufacturer": metadata.get("Manufacturer") or bids_meta.get("Manufacturer", "Unknown"),
        "MagneticFieldStrength": metadata.get("MagneticFieldStrength") or bids_meta.get("MagneticFieldStrength", "Unknown"),
        "ProtocolName": metadata.get("ProtocolName") or bids_meta.get("ProtocolName", "Unknown"),
    }


def resolve_iqm_data_path(
    modality_path: str,
    qc_config_path: str = None,
    dataset_dir: str = None,
) -> Path:
    """Resolve an IQM dataset TSV path across common runtime contexts."""
    path = Path(modality_path)

    if path.is_absolute() and path.is_file():
        return path

    candidates = [Path.cwd() / path]

    if dataset_dir:
        candidates.append(Path(dataset_dir) / path)

    if qc_config_path:
        candidates.append(Path(qc_config_path).parent / path)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    # Return original path so callers can surface it in error messages.
    return path


def load_iqm_distribution_table(resolved_path) -> pd.DataFrame:
    """Load a TSV/CSV distribution table and return a DataFrame. Raises on failure -
    the caller decides how to surface that. Uncached; see
    ``iqm_viewer._load_iqm_distribution_table_cached``."""

    suffix = resolved_path.suffix.lower()
    return pd.read_csv(resolved_path, sep="," if suffix == ".csv" else "\t")


def load_parquet_table(resolved_path) -> pd.DataFrame:
    """Read a local Parquet file into a DataFrame. Raises on failure."""
    return pd.read_parquet(resolved_path, engine="pyarrow")


def load_iqm_metrics_subject_level(resolved_path) -> dict:
    """Read a single per-subject IQM metrics file. Raises on failure."""
    return json.loads(Path(resolved_path).read_text(encoding="utf-8"))
