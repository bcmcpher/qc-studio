"""Multipage sidebar: one control per subject with QC-done marker (Streamlit app sidebar)."""

import time

import streamlit as st

from constants import (
    MESSAGES,
    PENDING_SIDEBAR_RERUN_KEY,
    SESSION_KEYS,
    SIDEBAR_SEARCH_HOLD_KEY,
    SIDEBAR_SUBJECT_LIST_HEIGHT,
    SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY,
)
from managers.session_manager import SessionManager
from utils.navigation import request_navigation_rerun

_MAX_PID_DISPLAY_LEN = 28
_SUBJECT_SEARCH_WIDGET_KEY = SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY
_NAV_BUTTON_KEYS = ("pag_next", "pag_prev", "autoplay_play", "autoplay_pause")
_LAST_APPLIED_FILTER_KEY = "_sidebar_search_applied_query"


def render_sidebar_cohort_subjects(
    *,
    qc_cohort: list | None = None,
    total_participants: int,
    qc_task: str = "anat_wf_qc",
    qc_tasks: list | None = None,
    entrypoint_rel_path: str | None = None,
    participant_ids: list | None = None,
    session_id: str = "ses-01",
    prepend_navigation: bool = False,
    navigation_kwargs: dict | None = None,
    show_subject_filter: bool = True,
    show_subject_list: bool = True,
) -> None:
    """Add sidebar QC navigation, then a scrollable subject list.

    When ``prepend_navigation`` is True and ``navigation_kwargs`` is set, order is:
    **Navigation** / Page X of Y, Play/Pause, prev–confirm–next / save, then Subjects
    with the filter box directly above the scrollable list. The search widget is
    *created* before those buttons so Streamlit does not reset the filter; it is
    then placed visually above the subject scroller.

    Each subject row is a full-width button: ✅ if QC saved for all active tasks, ⬜ otherwise.
    When ``entrypoint_rel_path`` is set (e.g. ``\"main.py\"``), uses ``st.switch_page``.
    """
    if not SessionManager.is_landing_page_complete():
        return
    if not show_subject_filter and not show_subject_list:
        return

    tasks_eff = list(qc_tasks) if qc_tasks else [qc_task]

    if qc_cohort is None:
        ids = list(participant_ids or [])[: max(int(total_participants), 0)]
        if not ids:
            return
        entries = [{"participant_id": str(pid), "session_id": session_id} for pid in ids]
    else:
        entries = list(qc_cohort or [])[: max(int(total_participants), 0)]
    if not entries:
        return

    with st.sidebar:
        kw = navigation_kwargs if (prepend_navigation and navigation_kwargs) else None

        if kw:
            from components.qc_viewer import (
                _display_qc_pagination_controls,
                _display_qc_pagination_header,
            )

            task_label = "all" if len(tasks_eff) > 1 else (tasks_eff[0] if tasks_eff else qc_task)
            st.caption(f"QC task: {task_label}")
            _display_qc_pagination_header(kw["current_page"], kw["total_participants"])

        if kw:
            _display_qc_pagination_controls(**kw)

        if show_subject_filter:
            st.session_state.setdefault(SESSION_KEYS["sidebar_subject_search"], "")
            current_pid = kw.get("participant_id") if kw else None
            current_sid = kw.get("session_id") if kw else None
            if current_pid is None or current_sid is None:
                current_index = min(max(SessionManager.get_current_page() - 1, 0), max(len(entries) - 1, 0))
                current_entry = entries[current_index] if entries else {}
                current_pid = current_pid or str(current_entry.get("participant_id", "—"))
                current_sid = current_sid or str(current_entry.get("session_id", session_id or "—"))
            st.caption(f"Participant ID: {current_pid or '—'} | Session ID: {current_sid or '—'}")
        else:
            query = get_subject_search_query()

        if show_subject_list:
            _render_subject_list(
                entries=entries,
                session_id=session_id,
                tasks_eff=tasks_eff,
                entrypoint_rel_path=entrypoint_rel_path,
                query=query if not show_subject_filter else "",
                flush_kwargs=kw,
                show_filter=show_subject_filter,
            )

        if st.session_state.get(PENDING_SIDEBAR_RERUN_KEY):
            del st.session_state[PENDING_SIDEBAR_RERUN_KEY]
            st.rerun()
        elif st.session_state.get(SIDEBAR_SEARCH_HOLD_KEY):
            del st.session_state[SIDEBAR_SEARCH_HOLD_KEY]


def _flush_qc_before_forced_navigation(kw: dict | None) -> None:
    """Save the current page's rating/notes before a jump that skips Confirm."""
    if not kw:
        return
    from components.qc_viewer import _record_all_qc_tasks

    _record_all_qc_tasks(kw["participant_id"], kw["session_id"], kw["qc_pipeline"], kw["qc_tasks"])


def get_subject_search_query() -> str:
    """Return the persisted subject-list filter (not the raw widget, which nav can blank)."""
    return str(st.session_state.get(SESSION_KEYS["sidebar_subject_search"], "") or "").strip()


def clear_subject_search() -> None:
    """Clear the subject filter."""
    st.session_state[SESSION_KEYS["sidebar_subject_search"]] = ""
    st.session_state[_SUBJECT_SEARCH_WIDGET_KEY] = ""
    st.session_state.pop(SIDEBAR_SEARCH_HOLD_KEY, None)
    st.session_state.pop(_LAST_APPLIED_FILTER_KEY, None)


def _nav_triggered() -> bool:
    return any(st.session_state.get(key) for key in _NAV_BUTTON_KEYS)


def _hold_search_across_nav() -> None:
    """Keep the filter when Previous/Next/Confirm blank the search widget."""
    persist = str(st.session_state.get(SESSION_KEYS["sidebar_subject_search"], "") or "")
    if _nav_triggered() or st.session_state.get(PENDING_SIDEBAR_RERUN_KEY):
        st.session_state[SIDEBAR_SEARCH_HOLD_KEY] = True
    if st.session_state.get(SIDEBAR_SEARCH_HOLD_KEY):
        st.session_state[_SUBJECT_SEARCH_WIDGET_KEY] = persist


def _matching_subject_entries(entries: list, query: str, session_id: str) -> list[tuple[int, dict]]:
    """Return ``(original_index, entry)`` pairs whose subject or session contains ``query``."""
    needle = (query or "").strip().lower()
    matched: list[tuple[int, dict]] = []
    for i, entry in enumerate(entries):
        pid = str(entry.get("participant_id", ""))
        sid = str(entry.get("session_id", session_id))
        haystack = f"{pid} {sid}".lower()
        if not needle or needle in haystack:
            matched.append((i, entry))
    return matched


def matching_page_numbers(entries: list, query: str, session_id: str) -> list[int]:
    """1-based page numbers that match the current subject filter."""
    return [i + 1 for i, _ in _matching_subject_entries(entries, query, session_id)]


def next_visible_subject_page(entries: list, query: str, session_id: str, current_page: int) -> int | None:
    """Next 1-based page among filter matches, or ``None`` if this is the last match."""
    for page in matching_page_numbers(entries, query, session_id):
        if page > current_page:
            return page
    return None


def prev_visible_subject_page(entries: list, query: str, session_id: str, current_page: int) -> int | None:
    """Previous 1-based page among filter matches, or ``None`` if this is the first match."""
    previous = None
    for page in matching_page_numbers(entries, query, session_id):
        if page < current_page:
            previous = page
        else:
            break
    return previous


def page_if_filter_hides_current(entries: list, query: str, session_id: str, current_page: int) -> int | None:
    """First matching page if ``current_page`` is hidden by the filter; otherwise ``None``."""
    if current_page < 1 or current_page > len(entries):
        return None
    pages = matching_page_numbers(entries, query, session_id)
    if not pages or current_page in pages:
        return None
    return pages[0]


def first_visible_subject_page(entries: list, query: str, session_id: str) -> int | None:
    """1-based page of the first filter match, or ``None`` if nothing matches."""
    pages = matching_page_numbers(entries, query, session_id)
    return pages[0] if pages else None


def _page_after_filter_change(entries: list, query: str, session_id: str, current_page: int) -> int | None:
    """When the filter changes, go to the first visible subject (or if the current page is hidden)."""
    query = (query or "").strip()
    previous = st.session_state.get(_LAST_APPLIED_FILTER_KEY)
    st.session_state[_LAST_APPLIED_FILTER_KEY] = query
    first = first_visible_subject_page(entries, query, session_id)
    if query and previous != query and first is not None and first != current_page:
        return first
    return page_if_filter_hides_current(entries, query, session_id, current_page)


def _render_subject_search() -> str:
    """Render the subject filter within the subject-list panel and persist its value."""
    st.session_state.setdefault(SESSION_KEYS["sidebar_subject_search"], "")
    _hold_search_across_nav()
    query = st.text_input(
        MESSAGES["sidebar_subjects_search"],
        key=_SUBJECT_SEARCH_WIDGET_KEY,
        placeholder=MESSAGES["sidebar_subjects_search_placeholder"],
        label_visibility="collapsed",
    )
    query = "" if query is None else str(query)
    if st.session_state.get(SIDEBAR_SEARCH_HOLD_KEY):
        query = str(st.session_state.get(SESSION_KEYS["sidebar_subject_search"], "") or "")
    else:
        st.session_state[SESSION_KEYS["sidebar_subject_search"]] = query
    return query


def _render_subject_list(
    *,
    entries: list,
    session_id: str,
    tasks_eff: list,
    entrypoint_rel_path: str | None,
    query: str,
    show_filter: bool = True,
    flush_kwargs: dict | None = None,
) -> None:
    """Render the subject buttons inside one fixed-height scroller panel."""
    current_page = SessionManager.get_current_page()
    with st.container(height=SIDEBAR_SUBJECT_LIST_HEIGHT, border=True):
        if show_filter:
            query = _render_subject_search()
            snap_to = _page_after_filter_change(entries, query, session_id, SessionManager.get_current_page())
            if snap_to is not None:
                _flush_qc_before_forced_navigation(flush_kwargs)
                SessionManager.set_current_page(snap_to)
                st.rerun()
        visible = _matching_subject_entries(entries, query, session_id)
        if not visible:
            st.caption(MESSAGES["sidebar_subjects_search_empty"])
            return
        for i, entry in visible:
            page_num = i + 1
            pid = str(entry.get("participant_id", ""))
            sid = str(entry.get("session_id", session_id))
            done = all(SessionManager.participant_has_decided_qc(pid, sid, t) for t in tasks_eff)
            mark = "✅" if done else "⬜"
            display_pid = pid if len(pid) <= _MAX_PID_DISPLAY_LEN else f"{pid[:_MAX_PID_DISPLAY_LEN - 3]}..."
            label_core = f"{display_pid} · {sid}" if sid is not None else display_pid
            suffix = " — current" if page_num == current_page else ""
            label = f"{mark} {label_core}{suffix}"
            if st.button(label, key=f"sidebar_cohort_nav_{i}", width="stretch"):
                if page_num != current_page:
                    _flush_qc_before_forced_navigation(flush_kwargs)
                SessionManager.set_current_page(page_num)
                if SessionManager.is_autoplay_enabled():
                    SessionManager.set_autoplay_start_time(time.time())
                if entrypoint_rel_path:
                    st.switch_page(entrypoint_rel_path)
                else:
                    request_navigation_rerun(st)
