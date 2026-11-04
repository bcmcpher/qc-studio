"""Multi-user mode: get_cli_run_context resolves cohort/output per authenticated user."""

import json
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

import main
from utils import identity
from utils.identity import UserIdentity


class _Stopped(Exception):
    pass


@pytest.fixture
def setup(monkeypatch, tmp_path):
    qc_json = tmp_path / "qc.json"
    qc_json.write_text(json.dumps({"anat_wf_qc": {}}))
    for rid, pids in {"alice": ["sub-01", "sub-02"], "bobby": ["sub-03"]}.items():
        (tmp_path / rid).mkdir()
        pd.DataFrame({"participant_id": pids}).to_csv(tmp_path / rid / f"{rid}.tsv", sep="\t", index=False)
    users = tmp_path / "users.json"
    users.write_text(
        json.dumps(
            {
                "users": {
                    "alice@mcgill.ca": {"participant_list": "alice.tsv"},
                    "bob@mcgill.ca": {"participant_list": "bobby.tsv", "rater_id": "bobby"},
                    "carol@mcgill.ca": {"participant_list": "carol.tsv"},
                    "broken.mcgill.ca": {"participant_list": "x.tsv"},
                }
            }
        )
    )
    st_mock = MagicMock()
    st_mock.stop.side_effect = _Stopped
    monkeypatch.setattr(main, "st", st_mock)
    monkeypatch.setattr(main.SessionManager, "get_qc_cohort_order", lambda: None)
    argv = ["main.py", "--dataset_dir", str(tmp_path), "--session_list", "ses-01", "--qc_pipeline", "fmriprep"]
    argv += ["--qc_task", "anat_wf_qc", "--qc_json", str(qc_json), "--users_config", str(users)]
    monkeypatch.setattr(sys, "argv", argv)
    return tmp_path, st_mock


def _as_user(monkeypatch, email):
    monkeypatch.setattr(identity, "get_current_user", lambda: UserIdentity(email=email, source="header") if email else None)


def test_each_user_gets_own_cohort_and_output(monkeypatch, setup):
    tmp_path, _ = setup
    _as_user(monkeypatch, "alice@mcgill.ca")
    alice = main.get_cli_run_context()
    _as_user(monkeypatch, "bob@mcgill.ca")
    bob = main.get_cli_run_context()

    assert alice["multi_user"] and alice["user_email"] == "alice@mcgill.ca"
    assert alice["participant_ids"] == ["sub-01", "sub-02"]
    assert alice["rater_id"] == "alice"
    assert alice["out_dir"] == str((tmp_path / "alice" / "qc-output").resolve())

    assert bob["participant_ids"] == ["sub-03"]
    assert bob["rater_id"] == "bobby"
    assert bob["out_dir"] == str((tmp_path / "bobby" / "qc-output").resolve())


def test_unknown_user_is_denied(monkeypatch, setup):
    _, st_mock = setup
    _as_user(monkeypatch, "eve@mcgill.ca")
    with pytest.raises(_Stopped):
        main.get_cli_run_context()
    assert "not assigned" in st_mock.error.call_args[0][0]


def test_user_without_participant_list_is_denied(monkeypatch, setup):
    _, st_mock = setup
    _as_user(monkeypatch, "carol@mcgill.ca")  # carol/ was never created
    with pytest.raises(_Stopped):
        main.get_cli_run_context()
    assert "No participant list" in st_mock.error.call_args[0][0]


def test_rejected_entry_does_not_block_others(monkeypatch, setup):
    _, st_mock = setup
    _as_user(monkeypatch, "broken.mcgill.ca")
    with pytest.raises(_Stopped):
        main.get_cli_run_context()
    assert "has a problem" in st_mock.error.call_args[0][0]
    _as_user(monkeypatch, "alice@mcgill.ca")
    assert main.get_cli_run_context()["rater_id"] == "alice"


def test_unidentified_user_is_denied(monkeypatch, setup):
    _, st_mock = setup
    _as_user(monkeypatch, None)
    with pytest.raises(_Stopped):
        main.get_cli_run_context()
    assert "Could not determine" in st_mock.error.call_args[0][0]


def test_participant_list_and_output_dir_required_without_users_config():
    base = ["--dataset_dir", "d", "--qc_pipeline", "p", "--qc_task", "t", "--qc_json", "q"]
    with pytest.raises(SystemExit):
        main.parse_args(base + ["--output_dir", "o"])
    with pytest.raises(SystemExit):
        main.parse_args(base + ["--participant_list", "p.tsv"])
    assert main.parse_args(base + ["--users_config", "u.json"]).out_dir is None


def test_single_user_mode_unchanged(monkeypatch, tmp_path):
    qc_json = tmp_path / "qc.json"
    qc_json.write_text(json.dumps({"anat_wf_qc": {}}))
    plist = tmp_path / "p.tsv"
    pd.DataFrame({"participant_id": ["sub-01"]}).to_csv(plist, sep="\t", index=False)
    monkeypatch.setattr(main.SessionManager, "get_qc_cohort_order", lambda: None)
    argv = ["main.py", "--dataset_dir", str(tmp_path), "--participant_list", str(plist), "--session_list", "ses-01"]
    argv += ["--qc_pipeline", "fmriprep", "--qc_task", "anat_wf_qc", "--output_dir", str(tmp_path / "out"), "--qc_json", str(qc_json)]
    monkeypatch.setattr(sys, "argv", argv)
    ctx = main.get_cli_run_context()
    assert ctx["multi_user"] is False and ctx["user_email"] is None
    assert ctx["out_dir"] == str((tmp_path / "out").resolve())
