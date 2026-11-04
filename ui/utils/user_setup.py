"""Validate a multi-user QC-Studio setup before launch and summarize it for the admin.

``validate_users_setup`` checks everything a rater needs to sign in and work:

* their users-config entry is valid (see :mod:`utils.user_config`)
* their ``rater_dir`` exists
* their participant list is a readable TSV with a ``participant_id`` column and,
  optionally, a ``session_id`` column, with no blank or duplicate rows
* sessions are defined (``session_id`` column, per-user or CLI ``session_list``)
* their output folder exists and is writable, or can be created

It also checks how identity is configured (Cloudflare JWT vs. trusted header vs. the
dev-only override). Nothing is modified unless ``create_output_dirs`` is called.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from utils.user_config import UsersConfigError, load_users_config
from utils.cohort import parse_session_list

ERROR = "error"
WARNING = "warning"

STATUS_READY = "READY"
STATUS_CREATE = "READY*"  # ready once the output folder is created
STATUS_NOT_READY = "NOT READY"
STATUS_INVALID = "INVALID"

NO_SESSIONS_MSG = "no sessions defined: pass --session_list (e.g. ses-BL), set session_list for this rater, or add a session_id column"


@dataclass
class UserSetup:
    email: str
    rater_id: str = ""
    rater_dir: str = ""
    participant_list: str = ""
    out_dir: str = ""
    n_participants: int = 0
    n_pages: int = 0
    sessions: list[str] = field(default_factory=list)
    output_exists: bool = False
    n_saved_files: int = 0
    issues: list[tuple[str, str]] = field(default_factory=list)  # (level, message)
    config_valid: bool = True

    @property
    def errors(self) -> list[str]:
        return [m for lvl, m in self.issues if lvl == ERROR]

    @property
    def warnings(self) -> list[str]:
        return [m for lvl, m in self.issues if lvl == WARNING]

    @property
    def status(self) -> str:
        if not self.config_valid:
            return STATUS_INVALID
        if self.errors:
            return STATUS_NOT_READY
        return STATUS_READY if self.output_exists else STATUS_CREATE

    @property
    def ready(self) -> bool:
        return self.status in (STATUS_READY, STATUS_CREATE)


@dataclass
class SetupReport:
    config_path: str
    users: list[UserSetup] = field(default_factory=list)
    global_issues: list[tuple[str, str]] = field(default_factory=list)
    identity_mode: str = ""
    rater_root: str = ""

    @property
    def fatal(self) -> bool:
        return any(lvl == ERROR for lvl, _ in self.global_issues)

    @property
    def ready_users(self) -> list[UserSetup]:
        return [u for u in self.users if u.ready]

    @property
    def users_to_create(self) -> list[UserSetup]:
        return [u for u in self.users if u.status == STATUS_CREATE]


def _nearest_existing_parent(path: Path) -> Path:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def _blank(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "")


def _check_participant_list(u: UserSetup, session_list: str | None) -> None:
    path = Path(u.participant_list)
    if not path.is_file():
        u.issues.append((ERROR, f"participant list not found: {path}"))
        return
    try:
        df = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, na_values=[""])
    except Exception as exc:  # pandas raises many types for malformed files
        u.issues.append((ERROR, f"cannot read participant list as TSV: {exc}"))
        return
    df.columns = [str(c).strip() for c in df.columns]
    if "participant_id" not in df.columns:
        found = ", ".join(df.columns) or "none"
        hint = " (is the file comma-separated? it must be tab-separated)" if len(df.columns) == 1 and "," in df.columns[0] else ""
        u.issues.append((ERROR, f"participant list has no 'participant_id' column (found: {found}){hint}"))
        return
    if df.empty:
        u.issues.append((ERROR, "participant list has no rows"))
        return

    blank_pid = _blank(df["participant_id"])
    if blank_pid.any():
        rows = ", ".join(str(i + 2) for i in df.index[blank_pid][:5])
        u.issues.append((ERROR, f"{int(blank_pid.sum())} row(s) with blank participant_id (line {rows})"))

    has_session_col = "session_id" in df.columns
    if has_session_col:
        blank_sid = _blank(df["session_id"])
        if blank_sid.any():
            rows = ", ".join(str(i + 2) for i in df.index[blank_sid][:5])
            u.issues.append((ERROR, f"{int(blank_sid.sum())} row(s) with blank session_id (line {rows}); fill them or drop the column"))
        u.sessions = sorted(df.loc[~blank_sid, "session_id"].astype(str).str.strip().unique().tolist())
        if session_list:
            u.issues.append((WARNING, f"session_id column overrides session_list {session_list!r}"))
        keys = ["participant_id", "session_id"]
        u.n_pages = len(df)
    else:
        keys = ["participant_id"]
        if not session_list:
            u.issues.append((ERROR, NO_SESSIONS_MSG))
            u.n_pages = len(df)
        else:
            sessions = parse_session_list(session_list)  # None = dataset has no session level
            u.sessions = sessions or ["(no session level)"]
            u.n_pages = len(df) * len(sessions or [None])

    dups = df.duplicated(subset=keys)
    if dups.any():
        u.issues.append((WARNING, f"{int(dups.sum())} duplicate row(s) by {'+'.join(keys)} (each is shown as a separate page)"))

    u.n_participants = int(df.loc[~blank_pid, "participant_id"].astype(str).str.strip().nunique())


def _check_output_dir(u: UserSetup) -> None:
    out = Path(u.out_dir)
    if out.exists():
        if not out.is_dir():
            u.issues.append((ERROR, f"output path exists but is not a directory: {out}"))
            return
        if not os.access(out, os.W_OK | os.X_OK):
            u.issues.append((ERROR, f"output directory is not writable: {out}"))
            return
        u.output_exists = True
        u.n_saved_files = sum(1 for _ in out.glob("*.tsv")) + sum(1 for _ in (out / "checkpoints").glob("*.tsv"))
        return
    parent = _nearest_existing_parent(out)
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        u.issues.append((ERROR, f"output directory does not exist and cannot be created (no write access to {parent})"))


def check_identity_env(env: dict | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Describe how users will be identified; flag unsafe or broken settings."""
    env = os.environ if env is None else env
    issues: list[tuple[str, str]] = []
    if str(env.get("QC_STUDIO_DEV_USER_EMAIL", "")).strip():
        issues.append((ERROR, "QC_STUDIO_DEV_USER_EMAIL is set: everyone without a Cloudflare header would be treated as that user. Unset it."))
    team = str(env.get("CF_ACCESS_TEAM_DOMAIN", "")).strip()
    aud = str(env.get("CF_ACCESS_AUD", "")).strip()
    if team and aud:
        try:
            import jwt  # noqa: F401

            mode = f"verified Cloudflare Access JWT (team {team})"
        except ImportError:
            mode = "JWT verification configured but PyJWT is missing"
            issues.append((ERROR, "PyJWT is not installed: pip install 'PyJWT[crypto]'"))
    elif team or aud:
        mode = "misconfigured"
        issues.append((ERROR, "set BOTH CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD (only one is set)"))
    else:
        mode = "trusted Cf-Access-Authenticated-User-Email header (no JWT verification)"
        issues.append((WARNING, "identities are not cryptographically verified; set CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD in .env"))
    return mode, issues


def validate_users_setup(config_path: str | Path, session_list: str | None = None, env: dict | None = None) -> SetupReport:
    """Check every rater in the users config without changing anything.

    ``session_list`` is the CLI value the app will be launched with (per-user
    ``session_list`` entries take precedence).
    """
    report = SetupReport(config_path=str(Path(config_path).expanduser().resolve()))
    report.identity_mode, report.global_issues = check_identity_env(env)
    try:
        cfg = load_users_config(config_path)
    except UsersConfigError as exc:
        report.global_issues.insert(0, (ERROR, str(exc)))
        return report
    report.rater_root = str(cfg.rater_root)
    if not cfg.rater_root.is_dir():
        report.global_issues.insert(0, (ERROR, f"rater_root does not exist: {cfg.rater_root}"))

    for email, u in sorted(cfg.users.items()):
        us = UserSetup(
            email=email,
            rater_id=u["rater_id"],
            rater_dir=u["rater_dir"],
            participant_list=u["participant_list"],
            out_dir=u["out_dir"],
        )
        if not Path(us.rater_dir).is_dir():
            us.issues.append((ERROR, f"rater_dir does not exist: {us.rater_dir}"))
        _check_participant_list(us, u.get("session_list") or session_list)
        _check_output_dir(us)
        report.users.append(us)

    for email, reasons in sorted(cfg.rejected.items()):
        us = UserSetup(email=email, config_valid=False, issues=[(ERROR, r) for r in reasons])
        report.users.append(us)

    if not cfg.users and not cfg.rejected:
        report.global_issues.append((ERROR, "no users defined"))
    elif not report.ready_users:
        if not session_list and any(NO_SESSIONS_MSG in u.errors for u in report.users):
            report.global_issues.append(
                (ERROR, "no rater is ready because no sessions are defined: re-run with --session_list (the launcher uses ses-BL)")
            )
        else:
            report.global_issues.append((ERROR, "no rater is ready; nobody would be able to use QC-Studio"))
    return report


def create_output_dirs(report: SetupReport) -> list[str]:
    """Create missing output folders for ready users; returns the folders created."""
    created = []
    for u in report.users_to_create:
        Path(u.out_dir).mkdir(parents=True, exist_ok=True)
        u.output_exists = True
        created.append(u.out_dir)
    return created


def format_report(report: SetupReport) -> str:
    """Human-readable admin summary."""
    lines = [f"QC-Studio multi-user setup: {report.config_path}"]
    if report.rater_root:
        lines.append(f"Rater root: {report.rater_root}")
    lines += [f"Identity: {report.identity_mode}", ""]
    if report.users:
        w_email = max(len("EMAIL"), *(len(u.email) for u in report.users))
        w_rater = max(len("RATER"), *(len(u.rater_id) for u in report.users))
        header = f"{'STATUS':<10} {'EMAIL':<{w_email}} {'RATER':<{w_rater}} {'SUBJ':>5} {'PAGES':>5} {'SAVED':>5}  SESSIONS"
        lines += [header, "-" * len(header)]
        for u in report.users:
            sessions = ",".join(u.sessions[:4]) + (" ..." if len(u.sessions) > 4 else "") if u.sessions else "-"
            nums = (u.n_participants, u.n_pages, u.n_saved_files) if u.config_valid else ("-", "-", "-")
            lines.append(f"{u.status:<10} {u.email:<{w_email}} {u.rater_id or '-':<{w_rater}} {nums[0]:>5} {nums[1]:>5} {nums[2]:>5}  {sessions}")
        lines.append("")
        lines.append("SUBJ = unique participants, PAGES = review pages, SAVED = existing status/checkpoint TSVs")
        lines.append("READY* = ready; output folder will be created at launch")

    detail = [u for u in report.users if u.issues or u.status == STATUS_CREATE]
    if detail:
        lines += ["", "Details:"]
        for u in detail:
            lines.append(f"  {u.email} [{u.status}]")
            if u.config_valid:
                lines.append(f"      participants: {u.participant_list}")
                note = "" if u.output_exists else ("  (will be created)" if u.status == STATUS_CREATE else "  (missing)")
                lines.append(f"      output:       {u.out_dir}{note}")
            for lvl, msg in u.issues:
                lines.append(f"      {'✗' if lvl == ERROR else '!'} {msg}")

    if report.global_issues:
        lines += ["", "General:"]
        lines += [f"  {'✗' if lvl == ERROR else '!'} {msg}" for lvl, msg in report.global_issues]

    n_ready = len(report.ready_users)
    n_bad = len(report.users) - n_ready
    lines += ["", f"Summary: {n_ready} ready, {n_bad} not ready (refused at sign-in), {len(report.users_to_create)} output folder(s) to create."]
    return "\n".join(lines)
