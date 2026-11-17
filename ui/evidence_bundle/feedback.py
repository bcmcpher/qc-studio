"""Structured model feedback for an evidence bundle.

A model adapter sends a bundle to a model and stores the reply as a ``FeedbackResult`` in
``feedback.json`` beside ``bundle.json``. This module holds the reply schema, the consistency
check of a reply against its bundle, and the file I/O. It has no model dependencies, so the UI
can read and validate feedback without them.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Union

from pydantic import Field, ValidationError, model_validator

from .constants import MAX_REASONS, MIN_REASONS
from .models import EvidenceBundle, SupportTier, _Strict

FEEDBACK_FILE = "feedback.json"

Decision = Literal["pass", "fail", "uncertain"]
Confidence = Literal["high", "medium", "low"]
FeedbackStatus = Literal["ok", "error", "skipped_unsupported"]
"""``ok``: a reply was received (valid or not); ``error``: the run failed; ``skipped_unsupported``: no model call."""

_FENCE = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.DOTALL)


class QCFeedback(_Strict):
    """A model's reply about one bundle."""

    decision: Decision
    confidence: Confidence
    summary: str = Field(min_length=1)
    reasons: list[str]
    flagged_metrics: list[str]
    recommended_followup: list[str]
    image_observations: list[str] = Field(default_factory=list)
    """What the model saw in the views; empty for an IQMs-only run."""


class FeedbackResult(_Strict):
    """One model run over one bundle, written as ``feedback.json``."""

    status: FeedbackStatus
    adapter: str
    model_id: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    """Generation settings (temperature, max tokens, decoding, image mode)."""
    endpoint: Optional[str] = None
    """API endpoint used by a cloud adapter; null for the default endpoint or a local model."""
    prompt_hash: Optional[str] = None
    bundle_schema_version: str
    support: SupportTier
    context_suffix: Optional[str]
    timestamp: str
    raw_reply: Optional[str] = None
    schema_valid: bool = False
    schema_errors: list[str] = Field(default_factory=list)
    consistency_errors: list[str] = Field(default_factory=list)
    feedback: Optional[QCFeedback] = None
    error: Optional[str] = None

    @model_validator(mode="after")
    def _check_status(self):
        if self.schema_valid != (self.feedback is not None):
            raise ValueError("schema_valid is true exactly when the parsed feedback is present")
        if self.consistency_errors and self.feedback is None:
            raise ValueError("consistency errors need parsed feedback")
        if self.status == "ok":
            if self.raw_reply is None:
                raise ValueError("an 'ok' result holds the raw reply")
            if not self.schema_valid and not self.schema_errors:
                raise ValueError("an invalid reply records its schema errors")
        elif self.feedback is not None:
            raise ValueError(f"a '{self.status}' result has no parsed feedback")
        if self.status == "error" and not self.error:
            raise ValueError("an 'error' result records the error")
        if self.status == "skipped_unsupported":
            if self.support != "unsupported":
                raise ValueError(f"only unsupported bundles are skipped, not '{self.support}'")
            if self.raw_reply is not None:
                raise ValueError("a skipped bundle has no reply")
        return self


def extract_json(raw: str) -> Any:
    """Return the first JSON object in ``raw``, after removing a Markdown code fence."""
    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    value, _ = json.JSONDecoder().raw_decode(text, start)
    return value


def parse_reply(raw: Union[str, Mapping[str, Any]]) -> tuple[Optional[QCFeedback], list[str]]:
    """Validate a reply against ``QCFeedback``; return the feedback or the validation errors.

    ``raw`` is reply text (free text or fenced JSON) or an already-parsed object (tool input).
    """
    try:
        data = dict(raw) if isinstance(raw, Mapping) else extract_json(raw)
    except ValueError as err:
        return None, [f"reply is not JSON: {err}"]
    try:
        return QCFeedback.model_validate(data), []
    except ValidationError as err:
        return None, [f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}" for e in err.errors()]


def _filled(items: list[str]) -> list[str]:
    return [item for item in items if item.strip()]


def check_consistency(feedback: QCFeedback, bundle: EvidenceBundle, min_reasons: int = MIN_REASONS, max_reasons: int = MAX_REASONS) -> list[str]:
    """Return every rule the reply breaks against its bundle; empty when consistent."""
    errors = []
    bundle_flags = set(bundle.flagged_metrics())
    for metric in feedback.flagged_metrics:
        if metric not in bundle_flags:
            errors.append(f"flagged metric '{metric}' is not flagged in the bundle")
    reasons = _filled(feedback.reasons)
    text = " ".join(reasons).lower()
    for metric in feedback.flagged_metrics:
        if metric.lower() not in text:
            errors.append(f"flagged metric '{metric}' is not named in any reason")
    if not min_reasons <= len(reasons) <= max_reasons:
        errors.append(f"{len(reasons)} reasons; expected {min_reasons} to {max_reasons}")
    if feedback.decision != "pass" and not _filled(feedback.recommended_followup):
        errors.append(f"decision '{feedback.decision}' needs a recommended follow-up")
    return errors


def _bundle_fields(bundle: EvidenceBundle) -> dict[str, Any]:
    return dict(
        bundle_schema_version=bundle.schema_version,
        support=bundle.support,
        context_suffix=bundle.context_suffix,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def reply_result(
    bundle: EvidenceBundle,
    raw: Union[str, Mapping[str, Any]],
    *,
    adapter: str,
    model_id: Optional[str],
    settings: Optional[Mapping[str, Any]] = None,
    prompt_hash: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> FeedbackResult:
    """Validate a reply and its consistency with ``bundle``; keep the raw reply either way."""
    feedback, schema_errors = parse_reply(raw)
    return FeedbackResult(
        status="ok",
        adapter=adapter,
        model_id=model_id,
        settings=dict(settings or {}),
        endpoint=endpoint,
        prompt_hash=prompt_hash,
        raw_reply=raw if isinstance(raw, str) else json.dumps(dict(raw)),
        schema_valid=feedback is not None,
        schema_errors=schema_errors,
        consistency_errors=check_consistency(feedback, bundle) if feedback is not None else [],
        feedback=feedback,
        **_bundle_fields(bundle),
    )


def error_result(
    bundle: EvidenceBundle,
    error: str,
    *,
    adapter: str,
    model_id: Optional[str],
    settings: Optional[Mapping[str, Any]] = None,
    prompt_hash: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> FeedbackResult:
    """A run that failed before a reply arrived."""
    return FeedbackResult(
        status="error",
        adapter=adapter,
        model_id=model_id,
        settings=dict(settings or {}),
        endpoint=endpoint,
        prompt_hash=prompt_hash,
        error=error,
        **_bundle_fields(bundle),
    )


def skipped_result(bundle: EvidenceBundle, *, adapter: str, model_id: Optional[str]) -> FeedbackResult:
    """An unsupported bundle that was not sent to the model."""
    return FeedbackResult(status="skipped_unsupported", adapter=adapter, model_id=model_id, **_bundle_fields(bundle))


def load_feedback(path: Union[str, Path]) -> FeedbackResult:
    """Read a ``feedback.json`` file, or a bundle folder that holds one."""
    path = Path(path)
    if path.is_dir():
        path = path / FEEDBACK_FILE
    return FeedbackResult.model_validate_json(path.read_text(encoding="utf-8"))


def write_feedback(path: Union[str, Path], result: FeedbackResult) -> Path:
    """Write ``result`` to ``path`` (a file, or a bundle folder) and replace any earlier result.

    The file is written to a temporary name first, so a failed write leaves the earlier result intact.
    """
    path = Path(path)
    if path.is_dir():
        path = path / FEEDBACK_FILE
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".feedback-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(result.model_dump_json(indent=2))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
