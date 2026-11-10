"""Tests for session/participant id handling in utils.cohort."""

import pandas as pd
import pytest

from utils.cohort import build_qc_cohort, normalize_session_id_bids, parse_session_list


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1", "ses-1"),
        ("01", "ses-01"),
        ("001", "ses-001"),
        ("ses-01", "ses-01"),
        ("ses-1", "ses-1"),
        ("baseline", "ses-baseline"),
        (" 02 ", "ses-02"),
    ],
)
def test_normalize_session_id_only_adds_prefix(raw, expected):
    assert normalize_session_id_bids(raw) == expected


def test_normalize_session_id_rejects_empty():
    with pytest.raises(ValueError):
        normalize_session_id_bids("  ")


def test_parse_session_list_keeps_labels_as_written():
    assert parse_session_list("1,01,ses-02,1") == ["ses-1", "ses-01", "ses-02"]


def test_build_qc_cohort_from_tsv_keeps_session_labels(tmp_path):
    tsv = tmp_path / "participants.tsv"
    tsv.write_text("participant_id\tsession_id\n" "0001\t1\n" "0001\t01\n" "sub-02\tbaseline\n" "sub-03\t\n")
    df = pd.read_csv(tsv, delimiter="\t", dtype=str, keep_default_na=False)

    cohort = build_qc_cohort(df, session_ids=None)

    assert cohort == [
        {"participant_id": "sub-0001", "session_id": "ses-1"},
        {"participant_id": "sub-0001", "session_id": "ses-01"},
        {"participant_id": "sub-02", "session_id": "ses-baseline"},
        {"participant_id": "sub-03", "session_id": None},
    ]
