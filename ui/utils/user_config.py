"""Per-user run configuration for multi-user QC-Studio deployments.

A users config JSON maps authenticated emails to each rater's setup::

    {
      "rater_root": "/data/qc-datasets/qc-raters",
      "users": {
        "alice@mcgill.ca": {
          "rater_id": "alice",
          "rater_dir": "alice",
          "participant_list": "alice_primary_participant_list.tsv"
        },
        "bob@mcgill.ca": {
          "participant_list": "bob.tsv",
          "session_list": "ses-BL",
          "output_dir": "/data/qc-output/bob"
        }
      }
    }

Path rules:

* ``rater_root`` (optional, top level) is the folder holding the rater folders. It may be
  absolute or relative to the users config; it defaults to the users config's folder.
* ``rater_dir`` resolves against ``rater_root`` (default: ``<rater_id>``); an absolute
  ``rater_dir`` ignores ``rater_root``.
* ``participant_list`` and ``output_dir`` resolve against ``rater_dir``.
* ``output_dir`` defaults to ``<rater_dir>/qc-output``.

Other rules:

* Email keys are case-insensitive. ``rater_id`` defaults to the sanitized part of the
  email before the ``@``.
* Invalid entries are **rejected individually**, so one typo never locks out the other
  raters. Rejected users are refused at sign-in. Duplicate emails, rater IDs or output
  folders reject every entry involved, so raters can never overwrite each other's files.
* Only file-level problems (missing file, invalid JSON, no ``users`` object, invalid
  ``rater_root``) raise :class:`UsersConfigError`.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

DEFAULT_OUTPUT_SUBDIR = "qc-output"
_RATER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def slugify_rater_id(value: str) -> str:
    """Lower-case, filename-safe rater id (used for directory and file names)."""
    return re.sub(r"[^a-z0-9._-]+", "_", str(value or "").strip().lower()).strip("._-")


class UserEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_list: str
    rater_id: str | None = None
    rater_dir: str | None = None
    session_list: str | None = None
    output_dir: str | None = None

    @field_validator("rater_id")
    @classmethod
    def _check_rater_id(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if not _RATER_ID_RE.match(v):
            raise ValueError(f"rater_id {v!r} must contain only lowercase letters, digits, '.', '_' or '-'")
        return v

    @field_validator("participant_list")
    @classmethod
    def _check_participant_list(cls, v):
        if not str(v).strip():
            raise ValueError("participant_list must not be empty")
        return v


class UsersConfigError(ValueError):
    """Raised for a users config that cannot be used at all (file-level problem)."""


@dataclass
class UsersConfig:
    """Parsed users config: valid users plus the reasons any entries were rejected."""

    path: Path
    rater_root: Path | None = None
    users: dict[str, dict] = field(default_factory=dict)
    rejected: dict[str, list[str]] = field(default_factory=dict)


def _resolve_path(value: str, base_dir: Path) -> Path:
    p = Path(str(value).strip()).expanduser()
    return (p if p.is_absolute() else base_dir / p).resolve()


def _format_validation_error(exc: ValidationError) -> list[str]:
    msgs = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ())) or "entry"
        if err.get("type") == "extra_forbidden":
            msgs.append(f"unknown key {loc!r} (allowed: {', '.join(UserEntry.model_fields)})")
        else:
            msgs.append(f"{loc}: {err.get('msg', 'invalid')}".replace("Value error, ", ""))
    return msgs


def _parse_raw(path: Path) -> tuple[object, list[tuple[str, object]]]:
    """Return ``(rater_root, users)``; users as (key, value) pairs, keeping duplicate keys."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsersConfigError(f"Cannot read users config {str(path)!r}: {exc}") from exc

    def _pairs(pairs):
        return {"__pairs__": pairs}

    try:
        root = json.loads(text, object_pairs_hook=_pairs)
    except json.JSONDecodeError as exc:
        raise UsersConfigError(f"Invalid JSON in {str(path)!r}: {exc}") from exc
    top = dict(root.get("__pairs__", [])) if isinstance(root, dict) else None
    if not top or "users" not in top:
        raise UsersConfigError(f'{str(path)!r} must be a JSON object with a top-level "users" object')
    unknown = sorted(set(top) - {"users", "rater_root"})
    if unknown:
        raise UsersConfigError(f"Unknown top-level key(s) in {str(path)!r}: {', '.join(unknown)}")
    users = top["users"]
    if not isinstance(users, dict) or "__pairs__" not in users:
        raise UsersConfigError(f'"users" in {str(path)!r} must be an object mapping emails to settings')

    def _plain(obj):
        if isinstance(obj, dict) and "__pairs__" in obj:
            return {k: _plain(v) for k, v in obj["__pairs__"]}
        return obj

    return top.get("rater_root"), [(k, _plain(v)) for k, v in users["__pairs__"]]


def _build_config(path: Path) -> UsersConfig:
    config_dir = path.parent.resolve()
    raw_root, entries = _parse_raw(path)
    if raw_root is None:
        rater_root = config_dir
    elif isinstance(raw_root, str) and raw_root.strip():
        rater_root = _resolve_path(raw_root, config_dir)
    else:
        raise UsersConfigError(f'"rater_root" in {str(path)!r} must be a non-empty path string')
    cfg = UsersConfig(path=path, rater_root=rater_root)
    candidates: dict[str, dict] = {}

    def reject(email: str, msg: str):
        cfg.rejected.setdefault(email, []).append(msg)

    email_counts = Counter(str(k).strip().lower() for k, _ in entries)
    for raw_email, raw_entry in entries:
        email = str(raw_email).strip().lower()
        if email_counts[email] > 1:
            if email not in cfg.rejected:
                reject(email, f"email listed {email_counts[email]} times")
            continue
        if not _EMAIL_RE.match(email):
            reject(email, f"{raw_email!r} is not a valid email address")
            continue
        if not isinstance(raw_entry, dict):
            reject(email, "settings must be a JSON object")
            continue
        try:
            entry = UserEntry.model_validate(raw_entry)
        except ValidationError as exc:
            for msg in _format_validation_error(exc):
                reject(email, msg)
            continue
        rater_id = entry.rater_id or slugify_rater_id(email.split("@", 1)[0])
        if not rater_id:
            reject(email, "could not derive a rater_id from the email; set one explicitly")
            continue
        rater_dir = _resolve_path(entry.rater_dir or rater_id, rater_root)
        out_dir = _resolve_path(entry.output_dir, rater_dir) if entry.output_dir else rater_dir / DEFAULT_OUTPUT_SUBDIR
        candidates[email] = {
            "email": email,
            "rater_id": rater_id,
            "rater_dir": str(rater_dir),
            "participant_list": str(_resolve_path(entry.participant_list, rater_dir)),
            "session_list": entry.session_list,
            "out_dir": str(out_dir),
        }

    # Uniqueness: any clash rejects every entry involved (fail closed).
    for key, label in (("rater_id", "rater_id"), ("out_dir", "output_dir")):
        owners: dict[str, list[str]] = {}
        for email, u in candidates.items():
            owners.setdefault(u[key], []).append(email)
        for value, emails in owners.items():
            if len(emails) > 1:
                for email in emails:
                    others = ", ".join(e for e in emails if e != email)
                    reject(email, f"{label} {value!r} is also used by {others}")

    cfg.users = {e: u for e, u in candidates.items() if e not in cfg.rejected}
    return cfg


@lru_cache(maxsize=8)
def _load_cached(path_str: str, mtime_ns: int) -> UsersConfig:
    return _build_config(Path(path_str))


def load_users_config(path: str | Path) -> UsersConfig:
    """Load the users config; re-read automatically when the file changes."""
    p = Path(path).expanduser().resolve()
    try:
        mtime_ns = p.stat().st_mtime_ns
    except OSError as exc:
        raise UsersConfigError(f"Users config not found: {str(p)!r}") from exc
    return _load_cached(str(p), mtime_ns)


def resolve_user_run_overrides(email: str, users_config_path: str | Path) -> dict | None:
    """Run-context overrides for ``email``; ``None`` when the user is unknown or rejected.

    Returned keys: ``email``, ``rater_id``, ``rater_dir``, ``participant_list``,
    ``session_list`` (``None`` = keep the CLI value) and ``out_dir``.
    """
    entry = load_users_config(users_config_path).users.get(str(email or "").strip().lower())
    return dict(entry) if entry else None
