"""Tests for utils.user_config (per-user participant lists and output dirs)."""

import json
import os

import pytest

from utils.user_config import UsersConfigError, load_users_config, resolve_user_run_overrides, slugify_rater_id


def _write(path, users):
    path.write_text(json.dumps({"users": users}))
    return path


def test_rater_dir_layout(tmp_path):
    cfg = _write(
        tmp_path / "users.json",
        {"Alice@McGill.ca": {"rater_id": "alice", "rater_dir": "alice_dir", "participant_list": "alice.tsv"}},
    )
    ov = resolve_user_run_overrides("alice@mcgill.ca", cfg)
    assert ov["rater_dir"] == str((tmp_path / "alice_dir").resolve())
    assert ov["participant_list"] == str((tmp_path / "alice_dir" / "alice.tsv").resolve())
    assert ov["out_dir"] == str((tmp_path / "alice_dir" / "qc-output").resolve())
    assert ov["session_list"] is None


def test_defaults_rater_id_and_rater_dir(tmp_path):
    cfg = _write(tmp_path / "users.json", {"Alice.Smith@McGill.ca": {"participant_list": "p.tsv"}})
    ov = resolve_user_run_overrides("alice.smith@mcgill.ca", cfg)
    assert ov["rater_id"] == "alice.smith"
    assert ov["rater_dir"] == str((tmp_path / "alice.smith").resolve())


def test_explicit_overrides(tmp_path):
    cfg = _write(
        tmp_path / "users.json",
        {"bob@mcgill.ca": {"rater_id": "Bob", "participant_list": "/abs/bob.tsv", "session_list": "ses-BL", "output_dir": "/abs/out"}},
    )
    ov = resolve_user_run_overrides("BOB@mcgill.ca", cfg)
    assert ov["rater_id"] == "bob"
    assert ov["participant_list"] == "/abs/bob.tsv"
    assert ov["session_list"] == "ses-BL"
    assert ov["out_dir"] == "/abs/out"


def test_unknown_user_returns_none(tmp_path):
    cfg = _write(tmp_path / "users.json", {"alice@mcgill.ca": {"participant_list": "a.tsv"}})
    assert resolve_user_run_overrides("eve@mcgill.ca", cfg) is None


def test_bad_entry_does_not_lock_out_others(tmp_path):
    cfg = _write(
        tmp_path / "users.json",
        {
            "alice@mcgill.ca": {"participant_list": "a.tsv"},
            "nikhil.bhagwat.mcgill.ca": {"participant_list": "n.tsv"},
            "bob@mcgill.ca": {"participant_list": "b.tsv", "typo_key": 1},
        },
    )
    loaded = load_users_config(cfg)
    assert set(loaded.users) == {"alice@mcgill.ca"}
    assert "not a valid email" in loaded.rejected["nikhil.bhagwat.mcgill.ca"][0]
    assert "unknown key 'typo_key'" in loaded.rejected["bob@mcgill.ca"][0]


def test_duplicate_rater_id_rejects_both(tmp_path):
    cfg = _write(
        tmp_path / "users.json",
        {"alice@a.org": {"participant_list": "a.tsv"}, "alice@b.org": {"participant_list": "b.tsv"}, "c@c.org": {"participant_list": "c.tsv"}},
    )
    loaded = load_users_config(cfg)
    assert set(loaded.users) == {"c@c.org"}
    assert "alice@b.org" in loaded.rejected["alice@a.org"][0]


def test_shared_output_dir_rejects_both(tmp_path):
    cfg = _write(
        tmp_path / "users.json",
        {
            "a@x.org": {"participant_list": "a.tsv", "output_dir": "/shared"},
            "b@x.org": {"participant_list": "b.tsv", "output_dir": "/shared"},
        },
    )
    loaded = load_users_config(cfg)
    assert loaded.users == {}
    assert "output_dir" in loaded.rejected["b@x.org"][0]


def test_duplicate_email_keys_rejected(tmp_path):
    cfg = tmp_path / "users.json"
    cfg.write_text('{"users": {"a@x.org": {"participant_list": "1.tsv"}, "A@x.org": {"participant_list": "2.tsv"}}}')
    loaded = load_users_config(cfg)
    assert loaded.users == {}
    assert "listed 2 times" in loaded.rejected["a@x.org"][0]


def test_invalid_rater_id_rejected(tmp_path):
    cfg = _write(tmp_path / "users.json", {"alice@x.org": {"participant_list": "a.tsv", "rater_id": "../etc"}})
    assert "alice@x.org" in load_users_config(cfg).rejected


@pytest.mark.parametrize("content", ["not json", '{"people": {}}', '{"users": []}', '{"users": {}, "extra": 1}'])
def test_file_level_errors_raise(tmp_path, content):
    cfg = tmp_path / "users.json"
    cfg.write_text(content)
    with pytest.raises(UsersConfigError):
        load_users_config(cfg)


def test_missing_file(tmp_path):
    with pytest.raises(UsersConfigError, match="not found"):
        load_users_config(tmp_path / "nope.json")


def test_reloads_when_file_changes(tmp_path):
    cfg = _write(tmp_path / "users.json", {"alice@x.org": {"participant_list": "a.tsv"}})
    assert resolve_user_run_overrides("bob@x.org", cfg) is None
    _write(cfg, {"alice@x.org": {"participant_list": "a.tsv"}, "bob@x.org": {"participant_list": "b.tsv"}})
    st_ = cfg.stat()
    os.utime(cfg, ns=(st_.st_atime_ns, st_.st_mtime_ns + 1_000_000_000))
    assert resolve_user_run_overrides("bob@x.org", cfg)["rater_id"] == "bob"


def test_slugify_rater_id():
    assert slugify_rater_id(" Jane Doe+qc ") == "jane_doe_qc"


def test_rater_root_absolute(tmp_path):
    root = tmp_path / "data" / "raters"
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg = cfg_dir / "users.json"
    cfg.write_text(json.dumps({"rater_root": str(root), "users": {"a@x.org": {"rater_id": "a", "participant_list": "a.tsv"}}}))
    loaded = load_users_config(cfg)
    assert loaded.rater_root == root.resolve()
    assert loaded.users["a@x.org"]["participant_list"] == str((root / "a" / "a.tsv").resolve())
    assert loaded.users["a@x.org"]["out_dir"] == str((root / "a" / "qc-output").resolve())


def test_rater_root_relative_to_config(tmp_path):
    cfg = tmp_path / "users.json"
    cfg.write_text(json.dumps({"rater_root": "raters", "users": {"a@x.org": {"rater_dir": "dir_a", "participant_list": "a.tsv"}}}))
    assert load_users_config(cfg).users["a@x.org"]["rater_dir"] == str((tmp_path / "raters" / "dir_a").resolve())


def test_rater_root_defaults_to_config_folder(tmp_path):
    cfg = _write(tmp_path / "users.json", {"a@x.org": {"participant_list": "a.tsv"}})
    assert load_users_config(cfg).rater_root == tmp_path.resolve()


def test_absolute_rater_dir_ignores_rater_root(tmp_path):
    cfg = tmp_path / "users.json"
    cfg.write_text(json.dumps({"rater_root": "/elsewhere", "users": {"a@x.org": {"rater_dir": str(tmp_path / "abs"), "participant_list": "a.tsv"}}}))
    assert load_users_config(cfg).users["a@x.org"]["rater_dir"] == str((tmp_path / "abs").resolve())


@pytest.mark.parametrize("root", ["", "   ", 5, ["a"]])
def test_invalid_rater_root_raises(tmp_path, root):
    cfg = tmp_path / "users.json"
    cfg.write_text(json.dumps({"rater_root": root, "users": {}}))
    with pytest.raises(UsersConfigError, match="rater_root"):
        load_users_config(cfg)
