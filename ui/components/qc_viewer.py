"""QC viewer component for displaying MRI, montage, and metrics panels."""

import base64
import binascii
import glob
import math
import re
from typing import Any
import pandas as pd
import streamlit as st
import time
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from constants import (
    MONTAGE_HEIGHT,
    MESSAGES,
    ERROR_MESSAGES,
    SUCCESS_MESSAGES,
    INFO_MESSAGES,
    QC_RATINGS,
    VIEW_MODES,
    OVERLAY_COLORMAPS,
    RATING_FACET_COLUMNS,
    DEFAULT_QC_RATING_NONE,
)
from utils.data_loaders import load_montage_data as _load_montage_data_uncached
from utils.config import parse_qc_config
from utils.navigation import request_navigation_rerun
from utils.path_helpers import sanitize_qc_task_slug
from utils.export import build_qc_results_dataframe, save_qc_results_to_csv, normalize_note_value
from managers.niivue_viewer_manager import NiivueViewerManager, NiivueViewerConfig
from managers.session_manager import SessionManager
from models import QCRecord
from components.iqm_viewer import _display_iqm_panel as display_iqm_distribution_panel

AUTOPLAY_RUN_CTX_KEY = "_autoplay_run_ctx"
PENDING_QC_SAVE_MSG_KEY = "pending_qc_save_msg"

# Extra wait past the configured autoplay duration before advancing, so a rating click
# made right at the boundary has time to reach the server and self-save via on_change
# before the poll treats the interval as elapsed.
AUTOPLAY_ADVANCE_GRACE_SECONDS = 0.3


def _clean_filename(filename: str) -> str:
    """Return a compact tab label from an internal image key."""
    # Functional-style names: ses/task/run are the most informative tokens.
    pattern = r"((?:ses-[^_]+_)?(?:task-[^_]+_?)?(?:run-[^_]+)?)"
    match = re.search(pattern, filename)
    if match and match.group(1):
        clean_label = match.group(1).strip("_")
        if clean_label:
            return clean_label

    # Remove extension suffix added during key construction.
    clean = re.sub(r"_(svg|png|jpeg)$", "", filename)
    # For anatomy-like keys, strip subject-prefixed path fragments.
    if "sub-" in clean:
        clean = re.sub(r"^.*sub-[^_]+_", "", clean)
    return clean or filename


def _pause_autoplay_for_notes_edit() -> None:
    """Stop autoplay when the user explicitly starts editing notes."""
    SessionManager.set_autoplay_enabled(False)
    SessionManager.set_autoplay_start_time(0.0)


def _notes_edit_mode_key(qc_task: str) -> str:
    return f"_notes_edit_mode_{qc_task}"


def _toggle_notes_editing_for_task(qc_task: str) -> None:
    """Reveal the notes box and pause autoplay until the user is done."""
    st.session_state[_notes_edit_mode_key(qc_task)] = True
    _pause_autoplay_for_notes_edit()


def _save_and_toggle_notes_editing_for_task(
    participant_id: str | None,
    session_id: str | None,
    qc_pipeline: str | None,
    qc_task: str,
    rver: int,
    nver: int,
    rating_config: dict[str, Any] | None = None,
) -> None:
    """Persist the current task state before enabling note editing."""
    _on_rating_change(participant_id, session_id, qc_pipeline, qc_task, rver, nver, rating_config)
    _toggle_notes_editing_for_task(qc_task)


def _save_and_start_autoplay(
    participant_id: str | None,
    session_id: str | None,
    qc_pipeline: str | None,
    qc_tasks: list,
) -> None:
    """Persist the current page before enabling autoplay."""
    _save_current_page_qc_state(participant_id, session_id, qc_pipeline, qc_tasks)
    SessionManager.set_autoplay_enabled(True)
    SessionManager.set_autoplay_start_time(time.time())


def _save_current_page_qc_state(
    participant_id: str | None,
    session_id: str | None,
    qc_pipeline: str | None,
    qc_tasks: list,
) -> None:
    """Flush the current page widgets into session records without changing navigation."""
    _record_all_qc_tasks(participant_id, session_id, qc_pipeline, qc_tasks)


def _unique_montage_tab_names(image_keys: list[str]) -> list[str]:
    """Ensure each montage tab label is unique even when several image keys normalize to the same cleaned basename."""
    labels: list[str] = []
    counts: dict[str, int] = {}
    for key in image_keys:
        label = _clean_filename(key)
        count = counts.get(label, 0)
        counts[label] = count + 1
        if count == 0:
            labels.append(label)
        else:
            labels.append(f"{label} ({count + 1})")
    return labels


def try_autoplay_advance_if_due(
    participant_id: str | None,
    session_id: str | None,
    qc_pipeline: str | None,
    qc_task: str | None,
    qc_tasks: list | None,
    total_participants: int | None,
    qc_cohort: list | None = None,
    participant_ids: list | None = None,
) -> None:
    """If autoplay interval elapsed, save ratings and go to next page (or stop at end).

    Called from the autoplay sidebar fragment. Uses ``st.rerun()`` when it advances or
    stops so the full app reloads on a new cohort row.
    """
    if participant_id is None or not total_participants:
        return
    if not SessionManager.is_autoplay_enabled():
        return
    start_time = SessionManager.get_autoplay_start_time()
    if start_time <= 0:
        return
    elapsed = time.time() - start_time
    duration = SessionManager.get_autoplay_duration()
    if elapsed < duration + AUTOPLAY_ADVANCE_GRACE_SECONDS:
        return
    tasks = list(qc_tasks or [])
    if not tasks:
        tasks = [qc_task] if qc_task else ["anat_wf_qc"]

    current_page = SessionManager.get_current_page()
    _, next_page = _filtered_adjacent_pages(
        current_page=current_page, total_participants=total_participants, participant_ids=participant_ids, qc_cohort=qc_cohort, session_id=session_id
    )

    if next_page is not None:
        _record_all_qc_tasks(participant_id, session_id, qc_pipeline, tasks)
        SessionManager.set_current_page(next_page)
        SessionManager.set_autoplay_start_time(time.time())
    else:
        _record_all_qc_tasks(participant_id, session_id, qc_pipeline, tasks)
        if _has_active_subject_filter() and not _filtered_cohort_complete_for_tasks(
            tasks, qc_cohort, participant_ids, session_id, total_participants
        ):
            msg = "⚠️ Some subjects remain unrated. Remove the filter to continue autoplay through the remaining subjects."
            st.info(msg)
            st.session_state["_pending_incomplete_cohort_msg"] = msg
        elif not _has_active_subject_filter() and (
            qc_cohort
            and SessionManager.all_qc_cohort_pages_complete_for_tasks(tasks, qc_cohort)
            or not qc_cohort
            and participant_ids
            and session_id
            and _cohort_entries_for_filter(qc_cohort, participant_ids, session_id, total_participants)
            and SessionManager.all_qc_cohort_pages_complete_for_tasks(
                tasks, _cohort_entries_for_filter(qc_cohort, participant_ids, session_id, total_participants)
            )
        ):
            SessionManager.set_current_page(total_participants + 1)
        SessionManager.set_autoplay_enabled(False)
        SessionManager.set_autoplay_start_time(0.0)
    request_navigation_rerun(st)


def _render_autoplay_countdown_main_banner() -> None:
    """Large, visible countdown above the QC viewer (client-side ticks; no fragment redraw)."""
    if not SessionManager.is_autoplay_enabled():
        return
    t0 = SessionManager.get_autoplay_start_time()
    if t0 <= 0:
        return
    duration = float(SessionManager.get_autoplay_duration())
    deadline_ms = int((t0 + duration) * 1000)
    secs_now = max(0, int(math.ceil(duration - (time.time() - t0) - 1e-9)))
    st.iframe(
        f"""
		<div style="font-family:system-ui,sans-serif;padding:10px 14px;background:#153448;
		  color:#f8fafc;border-radius:10px;margin:0 0 12px 0;display:flex;align-items:center;
		  gap:10px;flex-wrap:wrap;">
		  <span style="font-size:1.35rem;">⏱️</span>
		  <span style="opacity:0.95;">Next page in</span>
		  <span id="qc_autoplay_sec" style="font-size:1.75rem;font-weight:700;min-width:2ch;
		    text-align:center;">{secs_now}</span>
		  <span style="opacity:0.95;">s</span>
		</div>
		<script>
		(function() {{
		  const deadline = {deadline_ms};
		  const el = document.getElementById("qc_autoplay_sec");
		  function tick() {{
		    if (!el) return;
		    const sec = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
		    el.textContent = sec;
		  }}
		  tick();
		  setInterval(tick, 150);
		}})();
		</script>
		""",
        height=76,
    )


@st.fragment(run_every=timedelta(milliseconds=400))
def _autoplay_fragment_advance_only() -> None:
    """Periodic server check to advance when the interval elapses (sidebar; no countdown UI here)."""
    ctx = st.session_state.get(AUTOPLAY_RUN_CTX_KEY)
    if not ctx or not SessionManager.is_autoplay_enabled():
        return
    try_autoplay_advance_if_due(
        participant_id=ctx.get("participant_id"),
        session_id=ctx.get("session_id"),
        qc_pipeline=ctx.get("qc_pipeline"),
        qc_task=ctx.get("qc_task"),
        qc_tasks=ctx.get("qc_tasks"),
        total_participants=ctx.get("total_participants"),
        qc_cohort=ctx.get("qc_cohort"),
        participant_ids=ctx.get("participant_ids"),
    )


def display_qc_viewers(
    dataset_dir,
    qc_config_path: str,
    substitution_values: dict,
    participant_id: str = None,
    session_id: str = None,
    qc_pipeline: str = None,
    qc_task: str = None,
    qc_tasks: list | None = None,
    total_participants: int = None,
    participant_ids: list | None = None,
    qc_cohort: list | None = None,
) -> None:
    """Display QC viewers (Niivue, MONTAGE, IQM) for one or more tasks from ``qc.json``."""
    cohort_eff = qc_cohort
    if cohort_eff is None and participant_ids:
        sid = session_id or "ses-01"
        cohort_eff = []
        for p in participant_ids:
            ps = str(p).strip()
            if not ps.startswith("sub-"):
                ps = f"sub-{ps}"
            cohort_eff.append({"participant_id": ps, "session_id": sid})

    tasks = list(qc_tasks or [])
    if not tasks:
        tasks = [qc_task] if qc_task else ["anat_wf_qc"]

    multi_task = len(tasks) > 1

    selected_panels = SessionManager.get_selected_panels()
    selected_panels = {
        "niivue": selected_panels.get("niivue_col", selected_panels.get("niivue", True)),
        "montage": selected_panels.get("montage_col", selected_panels.get("montage", True)),
        "iqm": selected_panels.get("iqm_col", selected_panels.get("iqm", False)),
    }

    show_niivue = selected_panels.get("niivue", True)
    show_montage = selected_panels.get("montage", True)
    show_iqm = selected_panels.get("iqm", False)

    _render_autoplay_countdown_main_banner()

    # st.markdown(f"**{compact_session_label(participant_id, session_id)}**")

    for i, tname in enumerate(tasks):
        qc_config = parse_qc_config(qc_config_path, tname, substitution_values)
        display_label = qc_config.get("display_name") or tname
        rating_cfg = _task_rating_config(qc_config.get("rating"))
        task_has_data_sources = _task_has_data_sources(qc_config, dataset_dir)
        st.session_state.setdefault("_qc_rating_cfg_by_task", {})[tname] = rating_cfg
        if multi_task and i > 0:
            st.divider()
        task_has_niivue = (
            show_niivue
            and bool(qc_config.get("base_mri_image_path"))
            and _path_spec_has_existing_file(qc_config.get("base_mri_image_path"), dataset_dir)
        )
        if task_has_niivue and show_montage and show_iqm:
            _display_niivue_with_secondary_panel(
                dataset_dir,
                selected_panels,
                qc_config,
                participant_id,
                session_id,
                tname,
                qc_config_path=qc_config_path,
            )
        elif task_has_niivue and show_montage:
            _display_niivue_with_secondary_panel(
                dataset_dir, selected_panels, qc_config, participant_id, session_id, tname, qc_config_path=qc_config_path
            )
        elif task_has_niivue and show_iqm:
            _display_niivue_with_secondary_panel(
                dataset_dir, selected_panels, qc_config, participant_id, session_id, tname, qc_config_path=qc_config_path
            )
        elif task_has_niivue:
            _display_niivue_full_width(dataset_dir, qc_config, participant_id, session_id, tname)
        elif show_montage and show_iqm:
            _display_montage_panel(dataset_dir, qc_config)
            st.divider()
            display_iqm_distribution_panel(
                qc_config,
                qc_config_path,
                participant_id,
                session_id,
                dataset_dir,
            )
        elif show_montage:
            _display_montage_panel(dataset_dir, qc_config)
        elif show_iqm:
            display_iqm_distribution_panel(
                qc_config,
                qc_config_path,
                participant_id,
                session_id,
                dataset_dir,
            )

        _display_qc_rating_for_task(
            participant_id=participant_id,
            session_id=session_id,
            qc_pipeline=qc_pipeline,
            qc_task=tname,
            display_label=display_label,
            notes_height=88 if multi_task else 120,
            rating_config=rating_cfg,
            task_has_data_sources=task_has_data_sources,
        )


def _display_niivue_with_secondary_panel(
    dataset_dir,
    selected_panels: dict,
    qc_config,
    participant_id: str = None,
    session_id: str = None,
    task_suffix: str = "",
    qc_config_path: str = None,
) -> None:
    """Display 3-column layout: Niivue with hidden controls | Secondary panel.

    Niivue controls are hidden in an expander attached to the Niivue viewer column.
    Used when Niivue is selected with either montage or IQM panel.

    Args:
        dataset_dir: Root dataset directory
        selected_panels: Dictionary of selected panels
        qc_config: QC configuration object
        participant_id: Current participant ID
        session_id: Current session ID
        qc_config_path: Path to the QC configuration file (needed to resolve IQM source paths)
    """
    viewer_col, panel_col = st.columns([0.3, 0.7], gap="small")

    # Left column: Niivue viewer with hidden controls at bottom
    with viewer_col:
        st.caption(MESSAGES["niivue_header"])
        # Get niivue config from session state or render_controls_panel
        niivue_config = _get_or_render_niivue_config(
            task_suffix,
            has_overlay=bool(qc_config.get("overlay_mri_image_path")),
        )

        # Render viewer at top
        NiivueViewerManager.render_viewer(dataset_dir, qc_config, niivue_config, participant_id, session_id, task_suffix=task_suffix)

        # Render controls in expander at bottom
        with st.expander("🎮 Niivue Controls", expanded=False):
            NiivueViewerManager.render_controls_panel(state_suffix=task_suffix)

    # Right column: Montage or IQM panel
    with panel_col:
        if selected_panels.get("montage", False):
            _display_montage_panel(dataset_dir, qc_config)
        if selected_panels.get("iqm", False):
            if selected_panels.get("montage", False):
                st.divider()
            display_iqm_distribution_panel(
                qc_config,
                qc_config_path,
                participant_id,
                session_id,
                dataset_dir,
            )


def _display_niivue_full_width(dataset_dir, qc_config, participant_id: str = None, session_id: str = None, task_suffix: str = "") -> None:
    """Display Niivue in full width with hidden controls in an expander at bottom.

    Args:
            dataset_dir: Root dataset directory
            qc_config: QC configuration object
            participant_id: Current participant ID
            session_id: Current session ID
    """
    # Get niivue config from session state or render_controls_panel
    niivue_config = _get_or_render_niivue_config(
        task_suffix,
        has_overlay=bool(qc_config.get("overlay_mri_image_path")),
    )

    st.subheader(MESSAGES["niivue_header"])

    # Render viewer at top
    NiivueViewerManager.render_viewer(dataset_dir, qc_config, niivue_config, participant_id, session_id, task_suffix=task_suffix)

    # Render controls in expander at bottom
    with st.expander("🎮 Niivue Controls", expanded=False):
        NiivueViewerManager.render_controls_panel(state_suffix=task_suffix)


def _get_or_render_niivue_config(state_suffix: str = "", has_overlay: bool = False):
    """Return NiivueViewerConfig; use per-task session state when ``state_suffix`` is set."""
    state_key = "niivue_config" if not state_suffix else f"niivue_config_{state_suffix}"
    if state_key not in st.session_state:
        default_config = NiivueViewerConfig(
            view_mode=VIEW_MODES[0],
            overlay_colormap=OVERLAY_COLORMAPS[0],
            show_crosshair=False,
            radiological=False,
            show_colorbar=True,
            interpolation=True,
            show_overlay=has_overlay,
        )
        st.session_state[state_key] = default_config

    return st.session_state[state_key]


@st.cache_data(show_spinner=False, max_entries=128)
def _load_montage_data_cached(dataset_dir, qc_config, max_montage_rows, max_montage_cols):
    """Cached wrapper around ``data_loaders.load_montage_data``."""
    return _load_montage_data_uncached(dataset_dir, qc_config, max_montage_rows, max_montage_cols)


def _display_montage_panel(dataset_dir, qc_config) -> None:
    """Display SVG/PNG/JPEG montage panel with tabs for multiple images.

    If multiple image files are available, renders them as separate tabs.
    If only one image file is available, displays it directly.

    Supports:
    - SVG: Rendered as HTML
    - PNG/JPEG: Displayed as images using st.image()

    Args:
            dataset_dir: Root dataset directory
            qc_config: QC configuration object
    """
    st.caption(MESSAGES["montage_header"])

    # Get montage grid settings from session manager
    max_montage_rows = SessionManager.get_montage_max_rows()
    max_montage_cols = SessionManager.get_montage_max_cols()

    image_data = _load_montage_data_cached(dataset_dir, qc_config, max_montage_rows, max_montage_cols)

    if image_data:
        ordered_items = list(image_data.items())
        if len(image_data) > 1 and "montage" in image_data:
            overview_entry = ("montage", image_data["montage"])
            individual_entries = [(key, value) for key, value in ordered_items if key != "montage"]
            ordered_items = [overview_entry, *individual_entries]

        if len(ordered_items) > 1:
            tab_names = []
            iter_items = ordered_items
            if "montage" in image_data:
                tab_names.append("Overview")
                iter_items = [("montage", image_data["montage"])] + [item for item in ordered_items if item[0] != "montage"]
                remaining_keys = [key for key, _ in iter_items[1:]]
            else:
                remaining_keys = [key for key, _ in ordered_items]
            tab_names.extend(_unique_montage_tab_names(remaining_keys))
            tabs = st.tabs(tab_names)
            for tab, (filename, data) in zip(tabs, iter_items):
                with tab:
                    _render_image(data, filename)
        else:
            # Single image - display directly
            filename, data = ordered_items[0]
            _render_image(data, filename)
    else:
        st.info(ERROR_MESSAGES["montage_not_found"])


def _render_image(image_data: dict, filename: str) -> None:
    """Render a single image (SVG, PNG, or JPEG) in Streamlit.

    Args:
            image_data: Dict with keys 'type' and 'content'
            filename: Name of the image file for display
    """
    image_type = image_data.get("type")
    content = image_data.get("content")

    if image_type == "svg":
        # Render SVG as HTML
        st.iframe(content, height="content")
    elif image_type in ["png", "jpeg"]:
        # Display PNG/JPEG as image
        st.image(content, width="stretch", caption=filename)
    else:
        st.warning(f"Unsupported image type: {image_type}")


def _rating_widget_key(qc_task: str, rver: int) -> str:
    return f"qc_rating_{qc_task}_{rver}"


def _facet_rating_widget_key(qc_task: str, facet: str, rver: int) -> str:
    facet_raw = str(facet).strip()
    facet_token = base64.urlsafe_b64encode(facet_raw.encode("utf-8")).decode("ascii").rstrip("=") or "ZmFjZXQ"
    return f"qc_rating_{qc_task}_facetb64_{facet_token}_{rver}"


def _multifacet_bulk_widget_key(qc_task: str, rver: int) -> str:
    return f"qc_rating_{qc_task}_allfacets_{rver}"


def _multifacet_bulk_index_and_sync(bulk_key: str, uniform_value: str | None, options: list[str]) -> int | None:
    """Return the bulk radio default index while keeping mixed facet state unselected.

    Streamlit warns when a widget gets both an explicit default and a Session State
    value in the same run. For the bulk control, only provide an explicit default
    when no Session State value exists; if facets are mixed, force the bulk widget
    value to ``None`` so stale selections cannot be reapplied.
    """
    if uniform_value in options:
        return None if bulk_key in st.session_state else options.index(uniform_value)

    st.session_state[bulk_key] = None
    return None


def _decode_facet_token(token: str) -> str | None:
    """Decode a base64 facet token used in widget keys."""
    if not token:
        return None
    padded = token + ("=" * ((4 - (len(token) % 4)) % 4))
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError):
        return None
    return decoded or None


def _notes_widget_key(qc_task: str, nver: int) -> str:
    return f"qc_notes_{qc_task}_{nver}"


def _task_rating_config(rating_config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = rating_config if isinstance(rating_config, dict) else {}
    mode = str(cfg.get("type") or "single").strip().lower()
    mode = mode if mode in {"single", "multi"} else "single"

    raw_scale = cfg.get("scale")
    if isinstance(raw_scale, (list, tuple)):
        scale = [str(v).strip() for v in raw_scale if str(v).strip()]
    else:
        raw_single = str(raw_scale).strip() if raw_scale is not None else ""
        scale = [raw_single] if raw_single else []
    if not scale:
        scale = list(QC_RATINGS)

    raw_facets = cfg.get("facets")
    if isinstance(raw_facets, (list, tuple)):
        facets = [str(v).strip() for v in raw_facets if str(v).strip()]
    else:
        facets = []

    if mode == "multi" and not facets:
        # Fallback to single mode if facets are not defined.
        mode = "single"

    return {"type": mode, "scale": scale, "facets": facets}


def _path_spec_has_existing_file(path_spec: Any, dataset_dir: str | Path | None = None) -> bool:
    """Return True when a configured source resolves to at least one existing file."""
    if path_spec in (None, ""):
        return False

    specs = path_spec if isinstance(path_spec, (list, tuple)) else [path_spec]
    base_root = Path(dataset_dir) if dataset_dir else Path()

    for spec in specs:
        if spec in (None, ""):
            continue
        candidate = Path(spec)
        if not candidate.is_absolute():
            candidate = base_root / candidate
        if candidate.is_file():
            return True
        if "*" in str(spec):
            # Path.glob rejects absolute patterns, so use glob.glob on a fully resolved pattern.
            pattern = str(spec) if Path(spec).is_absolute() else str(Path(glob.escape(str(base_root))) / str(spec))
            if any(Path(p).is_file() for p in glob.glob(pattern)):
                return True
    return False


def _task_has_data_sources(qc_config: dict[str, Any] | None, dataset_dir: str | Path | None = None) -> bool:
    """True when at least one configured QC source resolves to an actual file."""
    if not isinstance(qc_config, dict):
        return False
    return any(
        _path_spec_has_existing_file(spec, dataset_dir)
        for spec in (
            qc_config.get("base_mri_image_path"),
            qc_config.get("overlay_mri_image_path"),
            qc_config.get("montage_path"),
            qc_config.get("iqm_path"),
        )
    )


def _latest_widget_version_for_task(qc_task: str, prefix: str, fallback: int | None = 0) -> int:
    """Prefer the newest versioned widget key still resident in session state."""
    latest = int(fallback or 0)
    task_prefix = f"{prefix}{qc_task}_"
    for key in list(st.session_state.keys()):
        if not isinstance(key, str) or not key.startswith(task_prefix):
            continue
        suffix = key[len(task_prefix) :]
        if not suffix:
            continue
        last_token = suffix.rsplit("_", 1)[-1]
        if last_token.isdigit():
            latest = max(latest, int(last_token))
    return latest


def _collect_task_rating_payload(qc_task: str, rver: int, rating_config: dict[str, Any] | None) -> tuple[str | None, dict[str, str | None] | None]:
    cfg = _task_rating_config(rating_config)
    effective_rver = _latest_widget_version_for_task(qc_task, "qc_rating_", rver)
    if cfg["type"] == "single":
        return st.session_state.get(_rating_widget_key(qc_task, effective_rver)), None

    ratings: dict[str, str | None] = {}
    for facet in cfg["facets"]:
        ratings[facet] = st.session_state.get(_facet_rating_widget_key(qc_task, facet, effective_rver))
    return None, ratings


def _is_stale_widget_callback(rver: int, nver: int) -> bool:
    """True when a callback belongs to an older participant/page widget generation."""
    return int(rver) != SessionManager.get_rating_version() or int(nver) != SessionManager.get_notes_version()


def _fallback_rating_config_for_task(
    participant_id: str,
    session_id: str,
    qc_task: str,
    rver: int,
) -> dict[str, Any] | None:
    """Best-effort config inference for save paths invoked before viewer render.

    Sidebar actions (Play/Checkpoint) run before the main viewer on each rerun.
    If ``_qc_rating_cfg_by_task`` is not populated yet, infer multi-facet shape
    from the latest saved record or from reversible facet names in live widget keys
    so current page edits are not dropped.
    """
    existing = SessionManager.get_qc_record_for_participant(participant_id, session_id, qc_task)
    if existing is not None:
        existing_ratings = existing.ratings if hasattr(existing, "ratings") else existing.get("ratings")
        if isinstance(existing_ratings, dict) and existing_ratings:
            facets = [str(f).strip() for f in existing_ratings.keys() if str(f).strip()]
            if facets:
                return {"type": "multi", "scale": list(QC_RATINGS), "facets": facets}

    effective_rver = _latest_widget_version_for_task(qc_task, "qc_rating_", rver)
    prefix = f"qc_rating_{qc_task}_"
    facets: list[str] = []
    for key in list(st.session_state.keys()):
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        suffix = key[len(prefix) :]
        if suffix == str(effective_rver):
            # Single-scale key: qc_rating_<task>_<version>
            continue
        tail = f"_{effective_rver}"
        if suffix.endswith(tail):
            token = suffix[: -len(tail)].strip()
            if not token.startswith("facetb64_"):
                continue
            facet_name = _decode_facet_token(token[len("facetb64_") :])
            if facet_name and facet_name not in facets:
                facets.append(facet_name)

    if facets:
        return {"type": "multi", "scale": list(QC_RATINGS), "facets": facets}
    return None


def _on_rating_change(participant_id, session_id, qc_pipeline, qc_task, rver, nver, rating_config=None):
    """Save rating and notes as soon as either widget changes.

    Used by both the rating radio and the notes box so a later forced page jump
    (sidebar search, autoplay, subject-list click) cannot drop unsaved notes.
    """
    if _is_stale_widget_callback(rver, nver):
        return
    rating, ratings = _collect_task_rating_payload(qc_task, rver, rating_config)
    notes = st.session_state.get(_notes_widget_key(qc_task, nver), "")
    _record_qc_for_current_participant(participant_id, session_id, qc_pipeline, qc_task, rating, notes, ratings=ratings)


def _on_notes_change(participant_id, session_id, qc_pipeline, qc_task, rver, nver, rating_config=None):
    """Same save path as ``_on_rating_change``; named for the notes widget callback."""
    if _is_stale_widget_callback(rver, nver):
        return
    if SessionManager.is_autoplay_enabled():
        _pause_autoplay_for_notes_edit()
    _on_rating_change(participant_id, session_id, qc_pipeline, qc_task, rver, nver, rating_config)


def _on_multifacet_bulk_change(participant_id, session_id, qc_pipeline, qc_task, rver, nver, rating_config=None):
    """Apply one selected value to every facet, then persist immediately."""
    if _is_stale_widget_callback(rver, nver):
        return

    cfg = _task_rating_config(rating_config)
    if cfg["type"] != "multi":
        return

    selected = st.session_state.get(_multifacet_bulk_widget_key(qc_task, rver))
    if selected not in cfg["scale"]:
        return

    for facet in cfg["facets"]:
        st.session_state[_facet_rating_widget_key(qc_task, facet, rver)] = selected

    _on_rating_change(participant_id, session_id, qc_pipeline, qc_task, rver, nver, cfg)


def _display_qc_rating_for_task(
    participant_id: str | None,
    session_id: str | None,
    qc_pipeline: str | None,
    qc_task: str,
    *,
    display_label: str | None = None,
    notes_height: int = 120,
    rating_config: dict[str, Any] | None = None,
    task_has_data_sources: bool = True,
) -> None:
    """PASS/FAIL/UNCERTAIN and notes for one task (shown under that task's viewers)."""
    label = (display_label or qc_task).strip()
    cfg = _task_rating_config(rating_config)
    st.markdown(f"#### 📊 Rate **{label}**")
    rver = SessionManager.get_rating_version()
    nver = SessionManager.get_notes_version()
    default_rating = SessionManager.get_default_qc_rating()
    default_is_unrated = str(default_rating).strip().lower() == str(DEFAULT_QC_RATING_NONE).lower()
    existing_record = SessionManager.get_qc_record_for_participant(participant_id, session_id, qc_task)
    if existing_record:
        existing_rating = existing_record.final_qc if hasattr(existing_record, "final_qc") else existing_record.get("final_qc")
        initial_rating = existing_rating if existing_rating in cfg["scale"] else None
        existing_ratings = existing_record.ratings if hasattr(existing_record, "ratings") else existing_record.get("ratings")
        existing_ratings = existing_ratings if isinstance(existing_ratings, dict) else {}
        initial_notes = existing_record.notes if hasattr(existing_record, "notes") else existing_record.get("notes", "")
        initial_notes = initial_notes or ""
    else:
        if not task_has_data_sources:
            initial_rating = None
        elif default_is_unrated:
            initial_rating = None
        else:
            initial_rating = default_rating if default_rating in cfg["scale"] else cfg["scale"][0]
        existing_ratings = {}
        initial_notes = ""

    if cfg["type"] == "single":
        options = cfg["scale"]
        single_key = _rating_widget_key(qc_task, rver)
        st.radio(
            " ",
            options=options,
            index=None if single_key in st.session_state else (options.index(initial_rating) if initial_rating in options else None),
            key=single_key,
            label_visibility="collapsed",
            on_change=_on_rating_change,
            args=(participant_id, session_id, qc_pipeline, qc_task, rver, nver, cfg),
        )
    else:
        options = cfg["scale"]
        facet_initial_values: dict[str, str | None] = {}
        for facet in cfg["facets"]:
            facet_key = _facet_rating_widget_key(qc_task, facet, rver)
            state_value = st.session_state.get(facet_key)
            if state_value in options:
                facet_initial_values[facet] = state_value
                continue

            if not existing_ratings:
                if not task_has_data_sources or default_is_unrated:
                    facet_initial_values[facet] = None
                else:
                    facet_initial_values[facet] = default_rating if default_rating in options else options[0]
                continue

            facet_initial = existing_ratings.get(facet)
            if facet_initial not in options:
                if not task_has_data_sources or default_is_unrated:
                    facet_initial = None
                else:
                    facet_initial = default_rating if default_rating in options else options[0]
            facet_initial_values[facet] = facet_initial

        facet_values = [facet_initial_values.get(facet) for facet in cfg["facets"]]
        uniform_value = None
        if facet_values and all(v in options for v in facet_values) and len(set(facet_values)) == 1:
            uniform_value = facet_values[0]

        bulk_key = _multifacet_bulk_widget_key(qc_task, rver)
        bulk_index = _multifacet_bulk_index_and_sync(bulk_key, uniform_value, options)

        st.radio(
            "Apply same rating to all facets",
            options=options,
            index=bulk_index,
            key=bulk_key,
            horizontal=True,
            on_change=_on_multifacet_bulk_change,
            args=(participant_id, session_id, qc_pipeline, qc_task, rver, nver, cfg),
        )

        # Render each facet in its own column, wrapping to new rows as needed
        num_facets = len(cfg["facets"])

        for i in range(0, num_facets, RATING_FACET_COLUMNS):
            cols = st.columns(RATING_FACET_COLUMNS)
            for j in range(RATING_FACET_COLUMNS):
                if i + j < num_facets:
                    facet = cfg["facets"][i + j]
                    facet_key = _facet_rating_widget_key(qc_task, facet, rver)
                    facet_initial = facet_initial_values.get(facet)

                    with cols[j]:
                        st.radio(
                            facet,
                            options=options,
                            index=None if facet_key in st.session_state else (options.index(facet_initial) if facet_initial in options else None),
                            key=facet_key,
                            on_change=_on_rating_change,
                            args=(participant_id, session_id, qc_pipeline, qc_task, rver, nver, cfg),
                        )

    notes_editable = st.session_state.get(_notes_edit_mode_key(qc_task), False)
    action_col, notes_col = st.columns([2, 6])
    with action_col:
        st.caption("Autoplay will be paused when you add notes. Notes are saved when you continue with rating or navigation.")
        if st.button("Add notes" if not notes_editable else "Edit notes", key=f"_toggle_notes_{qc_task}_{nver}", use_container_width=True):
            _save_and_toggle_notes_editing_for_task(participant_id, session_id, qc_pipeline, qc_task, rver, nver, cfg)
            st.rerun()

    with notes_col:
        st.text_area(
            MESSAGES["qc_notes_prompt"],
            value=initial_notes,
            key=_notes_widget_key(qc_task, nver),
            height=notes_height,
            disabled=not notes_editable,
            on_change=_on_notes_change,
            args=(participant_id, session_id, qc_pipeline, qc_task, rver, nver, cfg),
        )


def _record_all_qc_tasks(participant_id: str, session_id: str, qc_pipeline: str, qc_tasks: list) -> None:
    rver = SessionManager.get_rating_version()
    nver = SessionManager.get_notes_version()
    rating_cfg_by_task = st.session_state.get("_qc_rating_cfg_by_task", {})
    for t in qc_tasks:
        rating_cfg = rating_cfg_by_task.get(t)
        if rating_cfg is None:
            rating_cfg = _fallback_rating_config_for_task(participant_id, session_id, t, rver)
        rating, ratings = _collect_task_rating_payload(t, rver, rating_cfg)
        latest_nver = _latest_widget_version_for_task(t, "qc_notes_", nver)
        notes = st.session_state.get(_notes_widget_key(t, latest_nver), "")
        _record_qc_for_current_participant(participant_id, session_id, qc_pipeline, t, rating, notes, ratings=ratings)


def _cohort_entries_for_filter(
    qc_cohort: list | None,
    participant_ids: list | None,
    session_id: str,
    total_participants: int,
) -> list:
    limit = max(int(total_participants), 0)
    if qc_cohort is not None:
        return list(qc_cohort)[:limit]
    return [{"participant_id": str(pid), "session_id": session_id} for pid in list(participant_ids or [])][:limit]


def _cohort_entries_for_active_filter(
    qc_cohort: list | None,
    participant_ids: list | None,
    session_id: str,
    total_participants: int,
) -> list:
    """Return the currently visible cohort subset under the active sidebar filter, if any."""
    from views.sidebar_cohort_nav import _matching_subject_entries, get_subject_search_query

    entries = _cohort_entries_for_filter(qc_cohort, participant_ids, session_id, total_participants)
    query = get_subject_search_query()
    if not query:
        return entries
    return [entry for _, entry in _matching_subject_entries(entries, query, session_id)]


def _has_active_subject_filter() -> bool:
    """True when a sidebar subject filter is currently active."""
    from views.sidebar_cohort_nav import get_subject_search_query

    return bool(get_subject_search_query())


def _filtered_cohort_complete_for_tasks(
    qc_tasks: list,
    qc_cohort: list | None,
    participant_ids: list | None,
    session_id: str,
    total_participants: int,
) -> bool:
    """True when the visible subset under the active filter is finished for all tasks."""
    active_entries = _cohort_entries_for_active_filter(qc_cohort, participant_ids, session_id, total_participants)
    if not active_entries:
        return False
    return SessionManager.all_qc_cohort_pages_complete_for_tasks(qc_tasks, active_entries)


def _filtered_adjacent_pages(
    current_page: int,
    total_participants: int,
    participant_ids: list | None,
    qc_cohort: list | None,
    session_id: str,
) -> tuple[int | None, int | None]:
    """Previous/next pages that match the subject filter. Empty filter → full cohort order."""
    from views.sidebar_cohort_nav import get_subject_search_query, next_visible_subject_page, prev_visible_subject_page

    entries = _cohort_entries_for_filter(qc_cohort, participant_ids, session_id, total_participants)
    # Fallback for direct calls (e.g., tests) where cohort data is not provided.
    # In that case, use simple contiguous pagination bounds.
    if not entries:
        prev_page = current_page - 1 if current_page > 1 else None
        next_page = current_page + 1 if current_page < total_participants else None
        return prev_page, next_page
    query = get_subject_search_query()
    return (
        prev_visible_subject_page(entries, query, session_id, current_page),
        next_visible_subject_page(entries, query, session_id, current_page),
    )


def _sanitize_qc_task_slug(qc_task: str | None) -> str:
    """Build a filepath-safe QC task slug; ``all`` stays explicit in the filename."""
    return sanitize_qc_task_slug(qc_task)


def _sanitize_pipeline_slug(qc_pipeline: str | None) -> str:
    pipe = str(qc_pipeline or "").strip()
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", pipe).strip("_").lower() or "qc"


def _default_qc_status_filename(rater_id: str | None, qc_pipeline: str | None, qc_task: str | None) -> str:
    """Stable status filename grouped by rater, pipeline, and task."""
    rid = str(rater_id or "rater").strip().lower() or "rater"
    pipe_slug = _sanitize_pipeline_slug(qc_pipeline)
    task_slug = _sanitize_qc_task_slug(qc_task)
    return f"{rid}_{pipe_slug}_{task_slug}_qc_status.tsv"


def _build_qc_session_label(
    rater_id: str,
    qc_pipeline: str | None,
    qc_task: str | None,
    qc_session_id: str | None = None,
) -> str:
    """Human-readable QC session label for file naming and UI state."""
    rid = str(rater_id or "rater").strip().lower() or "rater"
    pipe = str(qc_pipeline or "qc").strip().lower() or "qc"
    task_slug = _sanitize_qc_task_slug(qc_task)
    if qc_session_id and str(qc_session_id).strip():
        return f"{rid}_{pipe}_{task_slug}_{str(qc_session_id).strip()}"
    return f"{rid}_{pipe}_{task_slug}"


def _resolve_output_base_dir(out_dir: str | None) -> Path:
    """Resolve the CLI output directory to a stable absolute path regardless of cwd."""
    base_dir = Path(str(out_dir).strip()).expanduser() if out_dir and str(out_dir).strip() else Path(".").expanduser()
    return base_dir.resolve() if base_dir.is_absolute() else (Path.cwd() / base_dir).resolve()


def _default_qc_save_path(
    out_dir: str | None,
    qc_pipeline: str | None = None,
    qc_task: str | None = None,
    qc_session_id: str | None = None,
) -> str:
    """Default save path shown to users in the sidebar."""
    base_dir = _resolve_output_base_dir(out_dir)
    filename = _default_qc_status_filename(SessionManager.get_rater_id(), qc_pipeline, qc_task)
    return str((base_dir / filename).resolve())


def _checkpoint_dir_for_session(out_dir: str | None) -> Path:
    """Directory for timestamped checkpoint snapshots associated with a QC session."""
    if out_dir and str(out_dir).strip():
        base_dir = _resolve_output_base_dir(out_dir)
        checkpoint_dir = base_dir / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return checkpoint_dir.resolve()

    session_dir = SessionManager.get_qc_session_checkpoint_dir()
    if session_dir:
        checkpoint_dir = Path(session_dir).expanduser().resolve()
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return checkpoint_dir

    base_dir = _resolve_output_base_dir(None)
    checkpoint_dir = base_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return checkpoint_dir.resolve()


def _default_qc_checkpoint_path(
    out_dir: str | None,
    qc_pipeline: str | None = None,
    qc_task: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Single-timestamp checkpoint snapshot filename for the current QC session."""
    stamp = str(timestamp or datetime.now().strftime("%Y%m%dT%H%M%SZ"))
    rater_id = str(SessionManager.get_rater_id() or "rater").strip().lower() or "rater"
    pipe_slug = _sanitize_pipeline_slug(qc_pipeline)
    task_slug = _sanitize_qc_task_slug(qc_task)
    checkpoint_dir = _checkpoint_dir_for_session(out_dir)
    return str((checkpoint_dir / f"{rater_id}_{pipe_slug}_{task_slug}_checkpoint_{stamp}.tsv").resolve())


def _checkpoint_frame_for_records(records: list) -> pd.DataFrame:
    """Normalize QC records to the checkpoint TSV schema before comparison or export."""
    return build_qc_results_dataframe(records)


def _latest_checkpoint_path_for_session(
    out_dir: str | None,
    qc_pipeline: str | None = None,
    qc_task: str | None = None,
) -> Path | None:
    """Latest checkpoint file for the active session, optionally filtered by pipeline/task."""
    checkpoint_dir = _checkpoint_dir_for_session(out_dir)
    checkpoint_files = [p for p in checkpoint_dir.glob("*.tsv") if p.is_file()]
    if qc_pipeline is not None and qc_task is not None:
        rid = str(SessionManager.get_rater_id() or "rater").strip().lower() or "rater"
        prefix = f"{rid}_{_sanitize_pipeline_slug(qc_pipeline)}_{_sanitize_qc_task_slug(qc_task)}_checkpoint_"
        checkpoint_files = [p for p in checkpoint_files if p.name.startswith(prefix)]
    if not checkpoint_files:
        return None
    checkpoint_files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return checkpoint_files[0]


def _checkpoint_contents_match_records(
    records: list,
    out_dir: str | None,
    qc_pipeline: str | None = None,
    qc_task: str | None = None,
) -> bool:
    """True when the current QC records are unchanged from the most recent checkpoint.

    Pass ``qc_pipeline``/``qc_task`` with the same values given to ``_create_qc_checkpoint``
    so the lookup matches the checkpoint file name; otherwise they are inferred from records.
    """
    pipelines = {str((r.pipeline if hasattr(r, "pipeline") else r.get("pipeline", "")) or "").strip() for r in records or []}
    tasks = {str((r.qc_task if hasattr(r, "qc_task") else r.get("qc_task", "")) or "").strip() for r in records or []}
    pipelines = {p for p in pipelines if p}
    tasks = {t for t in tasks if t}
    if qc_pipeline is not None and qc_task is not None:
        filter_pipeline = qc_pipeline
        filter_task = qc_task
    elif SessionManager.is_all_tasks_mode_locked():
        filter_pipeline = _sanitize_pipeline_slug(next(iter(pipelines)) if len(pipelines) == 1 else "qc")
        filter_task = "all"
    else:
        filter_pipeline = next(iter(pipelines)) if len(pipelines) == 1 else None
        filter_task = next(iter(tasks)) if len(tasks) == 1 else None

    latest_path = _latest_checkpoint_path_for_session(
        out_dir,
        qc_pipeline=filter_pipeline,
        qc_task=filter_task,
    )
    if latest_path is None:
        return False
    try:
        latest_df = pd.read_csv(latest_path, sep="\t", dtype=str)
    except Exception:
        return False
    comparison_columns = [
        "pipeline",
        "qc_task",
        "participant_id",
        "session_id",
        "task_id",
        "run_id",
        "rater_id",
        "rater_experience",
        "rater_fatigue",
        "rater_screen_size",
        "final_qc",
        "facet",
        "rating_value",
        "notes",
    ]
    current_df = _checkpoint_frame_for_records(records).reindex(columns=comparison_columns, fill_value="")
    latest_df = latest_df.reindex(columns=comparison_columns, fill_value="")
    for col in comparison_columns:
        if col == "notes":
            current_df[col] = current_df[col].map(normalize_note_value)
            latest_df[col] = latest_df[col].map(normalize_note_value)
        else:
            current_df[col] = current_df[col].fillna("").astype(str)
            latest_df[col] = latest_df[col].fillna("").astype(str)
    current_df = current_df.sort_values(by=["pipeline", "participant_id", "session_id", "qc_task", "facet"], kind="mergesort").reset_index(drop=True)
    latest_df = latest_df.sort_values(by=["pipeline", "participant_id", "session_id", "qc_task", "facet"], kind="mergesort").reset_index(drop=True)
    return current_df.equals(latest_df)


def _create_qc_checkpoint(
    records: list,
    out_dir: str | None,
    qc_pipeline: str | None,
    qc_task: str | None,
    *,
    timestamp: str | None = None,
) -> Path:
    """Create a time-stamped checkpoint file for the current QC session; does not overwrite prior checkpoints."""
    checkpoint_path = Path(
        _default_qc_checkpoint_path(
            out_dir,
            qc_pipeline=qc_pipeline,
            qc_task=qc_task,
            timestamp=timestamp,
        )
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    df = _checkpoint_frame_for_records(records)
    df.to_csv(checkpoint_path, sep="\t", index=False)
    return checkpoint_path


def _require_overwrite_confirmation(file_path: str | Path, label: str) -> bool:
    """Require a second explicit click before overwriting an existing export file."""
    target = Path(str(file_path)).expanduser()
    if not target.exists():
        st.session_state.pop("_pending_overwrite_path", None)
        return True
    current = st.session_state.get("_pending_overwrite_path")
    if current == str(target):
        st.session_state.pop("_pending_overwrite_path", None)
        return True
    st.session_state["_pending_overwrite_path"] = str(target)
    st.warning(f"⚠️ {label} will overwrite the existing file: {target}")
    return False


def _resolve_qc_save_file_path(out_dir: str | None, save_file_path: str | None, qc_pipeline: str | None = None, qc_task: str | None = None) -> Path:
    """Resolve the final export path from optional user input.

    If the user provides a directory-like path (no suffix), append the default file name.
    """
    if save_file_path and str(save_file_path).strip():
        candidate = Path(str(save_file_path).strip()).expanduser()
        if candidate.suffix:
            return candidate
        task_name = qc_task or "all_tasks"
        return candidate / _default_qc_status_filename(SessionManager.get_rater_id(), qc_pipeline, task_name)
    return Path(_default_qc_save_path(out_dir, qc_pipeline=qc_pipeline, qc_task=qc_task, qc_session_id=SessionManager.get_qc_session_id()))


def _render_sidebar_status_banner(kind: str, msg: str) -> None:
    """Render a full-width sidebar status banner for save/checkpoint feedback."""
    palette = {
        "success": ("rgba(34, 197, 94, 0.12)", "#16a34a", "#166534"),
        "info": ("rgba(59, 130, 246, 0.10)", "#3b82f6", "#1d4ed8"),
    }
    bg, accent, text = palette.get(kind, palette["info"])
    safe_text = escape(str(msg)).replace("\n", "<br>")
    st.markdown(
        f"""
        <div style="width:100%; box-sizing:border-box; display:block; background:{bg};
        border:1px solid {accent}; border-left:4px solid {accent}; border-radius:8px;
        color:{text}; padding:0.75rem 0.9rem; margin:0.5rem 0; line-height:1.4; white-space:normal;">
            {safe_text}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_previous_page_button(target_page: int) -> None:
    """Sidebar Previous control; no-ops visually when omitted by the caller."""
    if st.button(
        MESSAGES["previous_button"],
        width="stretch",
        key="pag_prev",
        help=MESSAGES["nav_tooltip_previous"],
    ):
        SessionManager.set_current_page(target_page)
        if SessionManager.is_autoplay_enabled():
            SessionManager.set_autoplay_start_time(time.time())
        request_navigation_rerun(st)


def _render_next_page_button(
    target_page: int | None,
    *,
    participant_id: str,
    session_id: str,
    qc_pipeline: str,
    qc_tasks: list,
    participant_ids: list | None = None,
    qc_cohort: list | None = None,
    total_participants: int | None = None,
) -> None:
    """Sidebar Next control: save current page, then advance only when the page transition is allowed."""
    if st.button(
        MESSAGES["next_button"],
        width="stretch",
        key="pag_next",
        help=MESSAGES["nav_tooltip_next"],
    ):
        _record_all_qc_tasks(participant_id, session_id, qc_pipeline, qc_tasks)

        if target_page is not None:
            SessionManager.set_current_page(target_page)
        elif (
            qc_cohort
            and SessionManager.all_qc_cohort_pages_complete_for_tasks(qc_tasks, qc_cohort)
            or not qc_cohort
            and participant_ids
            and session_id
            and _cohort_entries_for_filter(qc_cohort, participant_ids, session_id, total_participants or 0)
            and SessionManager.all_qc_cohort_pages_complete_for_tasks(
                qc_tasks, _cohort_entries_for_filter(qc_cohort, participant_ids, session_id, total_participants or 0)
            )
        ):
            SessionManager.set_current_page((total_participants or 0) + 1)
        elif _has_active_subject_filter() and _filtered_cohort_complete_for_tasks(
            qc_tasks, qc_cohort, participant_ids, session_id, total_participants or 0
        ):
            msg = "✅ The active filtered subject list is fully rated. Remove the filter to continue rating any remaining unrated subjects."
            st.info(msg)
            st.session_state["_pending_filtered_subject_msg"] = msg
        else:
            msg = "⚠️ Some subjects remain unrated. Complete all required ratings before moving to the final page."
            st.session_state["_pending_incomplete_cohort_msg"] = msg

        if SessionManager.is_autoplay_enabled():
            SessionManager.set_autoplay_start_time(time.time())
        request_navigation_rerun(st)


def _display_qc_pagination_header(current_page: int, total_participants: int) -> None:
    """Sidebar: page counter only; kept compact to save space."""
    st.write(f"**Page {current_page} of {total_participants}**")


def _display_qc_pagination_controls(
    current_page: int,
    total_participants: int,
    participant_id: str,
    session_id: str,
    qc_pipeline: str,
    qc_tasks: list,
    participant_ids: list | None = None,
    qc_cohort: list | None = None,
    out_dir: str | None = None,
    drop_duplicates: bool = True,
) -> None:
    """Sidebar: autoplay, page buttons, save CSV (call inside ``with st.sidebar:``)."""
    autoplay_col1, autoplay_col2 = st.columns([1, 1])
    with autoplay_col1:
        if st.button(MESSAGES["play_button"], width="stretch", key="autoplay_play"):
            _save_and_start_autoplay(participant_id, session_id, qc_pipeline, qc_tasks)
            request_navigation_rerun(st)

    with autoplay_col2:
        if st.button(MESSAGES["pause_button"], width="stretch", key="autoplay_pause"):
            SessionManager.set_autoplay_enabled(False)
            SessionManager.set_autoplay_start_time(0.0)
            request_navigation_rerun(st)

    if SessionManager.is_autoplay_enabled():
        if SessionManager.get_autoplay_start_time() > 0:
            _autoplay_fragment_advance_only()
        else:
            st.caption("Autoplay on — countdown starts on **Play**.")

    if pending := st.session_state.pop("_pending_filtered_subject_msg", None):
        st.info(pending)

    if pending := st.session_state.pop("_pending_incomplete_cohort_msg", None):
        st.warning(pending)

    prev_page, next_page = _filtered_adjacent_pages(
        current_page=current_page,
        total_participants=total_participants,
        participant_ids=participant_ids,
        qc_cohort=qc_cohort,
        session_id=session_id,
    )

    _render_next_page_button(
        next_page,
        participant_id=participant_id,
        session_id=session_id,
        qc_pipeline=qc_pipeline,
        qc_tasks=qc_tasks,
        participant_ids=participant_ids,
        qc_cohort=qc_cohort,
        total_participants=total_participants,
    )

    if prev_page is not None:
        _render_previous_page_button(prev_page)

    active_task_label = "all" if len(qc_tasks) > 1 else (qc_tasks[0] if qc_tasks else qc_pipeline)

    resolved_out_dir = Path(out_dir).expanduser().resolve() if out_dir else Path.cwd().resolve()
    st.caption(f"Output dir: {resolved_out_dir}")

    if st.button(
        MESSAGES["create_checkpoint_button"],
        width="stretch",
        key="create_checkpoint",
        help=MESSAGES["create_checkpoint_help"],
    ):
        _save_current_page_qc_state(participant_id, session_id, qc_pipeline, qc_tasks)
        records = SessionManager.get_latest_qc_records_for_task_set(qc_tasks)
        if not records:
            st.session_state["_pending_checkpoint_msg"] = ("info", INFO_MESSAGES["no_export_records"])
        elif _checkpoint_contents_match_records(records, out_dir, qc_pipeline=qc_pipeline, qc_task=active_task_label):
            st.session_state["_pending_checkpoint_msg"] = ("info", INFO_MESSAGES["checkpoint_unchanged"])
        else:
            checkpoint_path = _create_qc_checkpoint(
                records=records,
                out_dir=out_dir,
                qc_pipeline=qc_pipeline,
                qc_task=active_task_label,
            )
            st.session_state["_pending_checkpoint_msg"] = ("success", SUCCESS_MESSAGES["checkpoint_saved"].format(path=checkpoint_path))

    if pending := st.session_state.pop("_pending_checkpoint_msg", None):
        kind, msg = pending
        _render_sidebar_status_banner(kind, msg)


def _display_qc_pagination(
    current_page: int,
    total_participants: int,
    participant_id: str,
    session_id: str,
    qc_pipeline: str,
    qc_tasks: list,
    participant_ids: list | None = None,
    qc_cohort: list | None = None,
) -> None:
    """Full navigation block (header + playback / page controls)."""
    _display_qc_pagination_header(current_page, total_participants)
    st.divider()
    _display_qc_pagination_controls(
        current_page=current_page,
        total_participants=total_participants,
        participant_id=participant_id,
        session_id=session_id,
        qc_pipeline=qc_pipeline,
        qc_tasks=qc_tasks,
        participant_ids=participant_ids,
        qc_cohort=qc_cohort,
    )


def _save_qc_record(
    participant_id: str,
    session_id: str,
    qc_pipeline: str,
    qc_tasks: list,
    total_participants: int,
    participant_ids: list | None = None,
    qc_cohort: list | None = None,
    out_dir: str | None = None,
    drop_duplicates: bool = True,
    save_file_path: str | None = None,
    allow_overwrite: bool = False,
    trigger_rerun: bool = True,
    allow_completion_navigation: bool = True,
) -> str | None:
    _record_all_qc_tasks(participant_id, session_id, qc_pipeline, qc_tasks)

    export_rows = SessionManager.get_latest_qc_records_for_task_set(qc_tasks)
    if export_rows:
        saved_paths: list[Path] = []
        if SessionManager.is_all_tasks_mode_locked() and len(qc_tasks or []) > 1:
            out_file = _resolve_qc_save_file_path(out_dir, save_file_path, qc_pipeline=qc_pipeline, qc_task="all")
            saved_path, dropped, _ = save_qc_results_to_csv(out_file, export_rows, drop_duplicates)
            _ = dropped
            saved_paths.append(Path(saved_path))
        else:
            rows_by_task: dict[str, list] = {}
            for row in export_rows:
                task_name = str((row.qc_task if hasattr(row, "qc_task") else row.get("qc_task", "")) or "").strip() or "unknown_task"
                rows_by_task.setdefault(task_name, []).append(row)

            for task_name in sorted(rows_by_task.keys()):
                task_rows = rows_by_task[task_name]
                if save_file_path and len(rows_by_task) == 1:
                    out_file = _resolve_qc_save_file_path(out_dir, save_file_path, qc_pipeline=qc_pipeline, qc_task=task_name)
                elif save_file_path and len(rows_by_task) > 1:
                    user_target = Path(str(save_file_path).strip()).expanduser()
                    user_dir = user_target.parent if user_target.suffix else user_target
                    out_file = _resolve_qc_save_file_path(str(user_dir), None, qc_pipeline=qc_pipeline, qc_task=task_name)
                else:
                    out_file = _resolve_qc_save_file_path(out_dir, None, qc_pipeline=qc_pipeline, qc_task=task_name)
                saved_path, dropped, _ = save_qc_results_to_csv(out_file, task_rows, drop_duplicates)
                _ = dropped
                saved_paths.append(Path(saved_path))

        record_count = len(export_rows)
        unique_participants = len({str(r.participant_id if hasattr(r, "participant_id") else r.get("participant_id", "")) for r in export_rows})
        if len(saved_paths) == 1:
            path_label = saved_paths[0].name
        else:
            path_label = ", ".join(p.name for p in saved_paths)
        msg = SUCCESS_MESSAGES["records_saved"].format(path=path_label)
        msg += f"\n\nSaved {record_count} record(s) across {unique_participants} unique participant(s)."
        kind = "success"
    else:
        msg = INFO_MESSAGES["no_export_records"]
        kind = "info"

    st.session_state[PENDING_QC_SAVE_MSG_KEY] = (kind, msg)

    cohort_is_complete = False
    if qc_cohort:
        cohort_is_complete = SessionManager.all_qc_cohort_pages_complete_for_tasks(qc_tasks, qc_cohort)
    elif participant_ids and session_id:
        temp_cohort = []
        for pid in participant_ids:
            p = str(pid).strip()
            if not p.startswith("sub-"):
                p = f"sub-{p}"
            temp_cohort.append({"participant_id": p, "session_id": session_id})
        cohort_is_complete = SessionManager.all_qc_cohort_pages_complete_for_tasks(qc_tasks, temp_cohort)

    if cohort_is_complete and allow_completion_navigation:
        SessionManager.set_current_page(total_participants + 1)
        if trigger_rerun:
            request_navigation_rerun(st)
        return msg

    if trigger_rerun:
        request_navigation_rerun(st)
    return msg


def _record_qc_for_current_participant(
    participant_id: str,
    session_id: str,
    qc_pipeline: str,
    qc_task: str,
    rating: str | None,
    notes: str,
    *,
    ratings: dict[str, str | None] | None = None,
) -> None:
    """Save a QC record for the current participant without navigating."""
    # A stale/rotated widget key (e.g. the autoplay poll reading a key from before the
    # page advanced) reads back None; ignore it instead of overwriting a saved rating.
    single_rating_present = str(rating).strip().lower() not in {"", "none", "nan"} if rating is not None else False
    facet_rating_present = False
    if isinstance(ratings, dict):
        facet_rating_present = any(str(v).strip().lower() not in {"", "none", "nan"} for v in ratings.values())

    if not single_rating_present and not facet_rating_present:
        return

    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    record = QCRecord(
        participant_id=participant_id,
        session_id=session_id,
        qc_task=qc_task,
        pipeline=qc_pipeline,
        timestamp=timestamp,
        rater_id=SessionManager.get_rater_id(),
        rater_experience=SessionManager.get_rater_experience(),
        rater_fatigue=SessionManager.get_rater_fatigue(),
        rater_screen_size=SessionManager.get_rater_screen_size(),
        final_qc=rating if rating is not None else SessionManager.derive_multifacet_final_qc(ratings),
        ratings=ratings,
        notes=notes,
    )
    SessionManager.add_qc_record(record)
