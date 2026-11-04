"""Tests for utils.user_setup (pre-launch validation of a multi-user setup)."""

import json

import pytest

from utils.user_setup import (
    STATUS_CREATE,
    STATUS_INVALID,
    STATUS_NOT_READY,
    STATUS_READY,
    check_identity_env,
    create_output_dirs,
    format_report,
    validate_users_setup,
)

SAFE_ENV = {"CF_ACCESS_TEAM_DOMAIN": "", "CF_ACCESS_AUD": ""}


@pytest.fixture
def raters(tmp_path):
    """users.json in tmp_path with one rater dir per (rater_id, tsv content) pair."""

    def make(spec, extra_users=None):
        users = {}
        for rid, tsv in spec.items():
            if tsv is not None:
                (tmp_path / rid).mkdir()
                (tmp_path / rid / f"{rid}.tsv").write_text(tsv)
            users[f"{rid}@x.org"] = {"rater_id": rid, "rater_dir": rid, "participant_list": f"{rid}.tsv"}
        users.update(extra_users or {})
        cfg = tmp_path / "users.json"
        cfg.write_text(json.dumps({"users": users}))
        return cfg

    return make


def _by_rater(report):
    return {u.rater_id or u.email: u for u in report.users}


def test_statuses(raters, tmp_path):
    cfg = raters(
        {
            "ok": "participant_id\nsub-01\nsub-02\n",
            "nodir": None,
            "nocol": "subject\nsub-01\n",
            "csv": "participant_id,session_id\nsub-01,ses-BL\n",
        },
        extra_users={"bad-email": {"participant_list": "x.tsv"}},
    )
    (tmp_path / "ok" / "qc-output").mkdir()
    report = validate_users_setup(cfg, session_list="ses-BL", env=SAFE_ENV)
    u = _by_rater(report)

    assert u["ok"].status == STATUS_READY and u["ok"].n_participants == 2 and u["ok"].n_pages == 2
    assert u["nodir"].status == STATUS_NOT_READY
    assert any("rater_dir does not exist" in m for m in u["nodir"].errors)
    assert any("no 'participant_id' column" in m for m in u["nocol"].errors)
    assert any("tab-separated" in m for m in u["csv"].errors)
    assert u["bad-email"].status == STATUS_INVALID
    assert not report.fatal  # one rater is ready


def test_output_dir_created_only_for_ready_users(raters, tmp_path):
    cfg = raters({"new": "participant_id\nsub-01\n", "broken": "participant_id\n"})
    report = validate_users_setup(cfg, session_list="ses-BL", env=SAFE_ENV)
    u = _by_rater(report)
    assert u["new"].status == STATUS_CREATE
    assert u["broken"].status == STATUS_NOT_READY  # no rows
    assert not (tmp_path / "new" / "qc-output").exists()  # validation changes nothing

    created = create_output_dirs(report)
    assert created == [str((tmp_path / "new" / "qc-output").resolve())]
    assert (tmp_path / "new" / "qc-output").is_dir()
    assert not (tmp_path / "broken" / "qc-output").exists()


def test_session_checks(raters):
    cfg = raters(
        {
            "col": "participant_id\tsession_id\nsub-01\tses-BL\nsub-01\tses-M12\n",
            "blank": "participant_id\tsession_id\nsub-01\tses-BL\nsub-02\t\n",
            "dup": "participant_id\nsub-01\nsub-01\n",
        }
    )
    u = _by_rater(validate_users_setup(cfg, session_list="ses-BL", env=SAFE_ENV))
    assert u["col"].sessions == ["ses-BL", "ses-M12"] and u["col"].n_pages == 2 and u["col"].n_participants == 1
    assert any("overrides session_list" in m for m in u["col"].warnings)
    assert any("blank session_id" in m for m in u["blank"].errors)
    assert any("duplicate" in m for m in u["dup"].warnings) and u["dup"].ready


def test_missing_sessions_is_an_error(raters):
    cfg = raters({"a": "participant_id\nsub-01\n"})
    u = _by_rater(validate_users_setup(cfg, session_list=None, env=SAFE_ENV))
    assert any("no sessions defined" in m for m in u["a"].errors)


def test_no_ready_users_is_fatal(raters):
    cfg = raters({"a": None})
    report = validate_users_setup(cfg, session_list="ses-BL", env=SAFE_ENV)
    assert report.fatal


def test_unreadable_config_is_fatal(tmp_path):
    cfg = tmp_path / "users.json"
    cfg.write_text("{")
    report = validate_users_setup(cfg, env=SAFE_ENV)
    assert report.fatal and "Invalid JSON" in format_report(report)


@pytest.mark.parametrize(
    "env, fatal",
    [
        ({}, False),
        ({"QC_STUDIO_DEV_USER_EMAIL": "x@y.org"}, True),
        ({"CF_ACCESS_AUD": "aud"}, True),
        ({"CF_ACCESS_TEAM_DOMAIN": "t.cloudflareaccess.com", "CF_ACCESS_AUD": "aud"}, False),
    ],
)
def test_identity_env(env, fatal):
    _, issues = check_identity_env(env)
    assert any(lvl == "error" for lvl, _ in issues) is fatal


def test_format_report_mentions_every_user(raters):
    cfg = raters({"a": "participant_id\nsub-01\n", "b": None})
    text = format_report(validate_users_setup(cfg, session_list="ses-BL", env=SAFE_ENV))
    assert "a@x.org" in text and "b@x.org" in text and "1 ready, 1 not ready" in text


def test_missing_rater_root_is_fatal(tmp_path):
    cfg = tmp_path / "users.json"
    cfg.write_text(json.dumps({"rater_root": "nope", "users": {"a@x.org": {"participant_list": "a.tsv"}}}))
    report = validate_users_setup(cfg, session_list="ses-BL", env=SAFE_ENV)
    assert report.fatal
    text = format_report(report)
    assert "rater_root does not exist" in text and f"Rater root: {(tmp_path / 'nope').resolve()}" in text


class TestCheckUsersSetupCli:
    @pytest.fixture
    def cfg(self, raters, monkeypatch):
        for var in ("QC_STUDIO_DEV_USER_EMAIL", "CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD"):
            monkeypatch.delenv(var, raising=False)
        return raters({"a": "participant_id\nsub-01\n", "b": "participant_id\nsub-02\n"})

    def _run(self, cfg, tmp_path, *extra):
        import check_users_setup

        return check_users_setup.main([str(cfg), "--env-file", str(tmp_path / "no.env"), *extra])

    def test_creates_output_dirs(self, cfg, tmp_path, capsys):
        assert self._run(cfg, tmp_path, "--session_list", "ses-BL", "--create-output-dirs") == 0
        assert (tmp_path / "a" / "qc-output").is_dir() and (tmp_path / "b" / "qc-output").is_dir()
        assert capsys.readouterr().out.count("📁 created") == 2

    def test_explains_nothing_created_without_session_list(self, cfg, tmp_path, capsys):
        assert self._run(cfg, tmp_path, "--create-output-dirs") == 2
        out = capsys.readouterr().out
        assert "re-run with --session_list" in out and "No output folders were created" in out
        assert not (tmp_path / "a" / "qc-output").exists()

    def test_reports_when_nothing_left_to_create(self, cfg, tmp_path, capsys):
        self._run(cfg, tmp_path, "--session_list", "ses-BL", "--create-output-dirs")
        capsys.readouterr()
        assert self._run(cfg, tmp_path, "--session_list", "ses-BL", "--create-output-dirs") == 0
        assert "No output folders to create" in capsys.readouterr().out
