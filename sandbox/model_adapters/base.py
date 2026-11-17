"""Shared model adapter interface and helpers.

An adapter sends one evidence bundle to a model and returns a ``FeedbackResult``. Every
adapter renders the same prompt template around the bundle's ``PACKAGE.md``, hashes the
request, and validates the reply through ``ui/evidence_bundle/feedback.py``.
"""

import hashlib
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from string import Template
from typing import Any, Mapping, Optional, Sequence, Union

_UI_DIR = Path(__file__).resolve().parents[2] / "ui"
if str(_UI_DIR) not in sys.path:
    sys.path.insert(0, str(_UI_DIR))

from evidence_bundle.constants import MAX_REASONS, MIN_REASONS  # noqa: E402
from evidence_bundle.feedback import FeedbackResult, error_result, reply_result  # noqa: E402
from evidence_bundle.models import EvidenceBundle  # noqa: E402

BUNDLE_FILE = "bundle.json"
PACKAGE_FILE = "PACKAGE.md"
PROMPT_TEMPLATE = Path(__file__).with_name("prompt.md")

IMAGE_SECTION = (
    'The views listed under "Views" are attached as images, in the order listed. Describe what '
    "they show in `image_observations`; use them alongside the metrics, not instead of them."
)
NO_IMAGE_SECTION = "No images are attached. Leave `image_observations` empty and do not cite image evidence."

Reply = Union[str, Mapping[str, Any]]


class DataUseError(RuntimeError):
    """Images would be sent without the data-use acknowledgement."""


def load_bundle(bundle_dir: Path) -> EvidenceBundle:
    """Read ``bundle.json`` from a bundle folder."""
    return EvidenceBundle.model_validate_json((Path(bundle_dir) / BUNDLE_FILE).read_text(encoding="utf-8"))


def view_paths(bundle_dir: Path, bundle: EvidenceBundle) -> list[Path]:
    """The bundle's view images, in bundle order (core views first)."""
    return [Path(bundle_dir) / view.path for view in bundle.views]


def render_prompt(bundle_dir: Path, images: bool, template: Path = PROMPT_TEMPLATE) -> str:
    """The full prompt: the template with ``PACKAGE.md`` and the image instructions inserted."""
    package = (Path(bundle_dir) / PACKAGE_FILE).read_text(encoding="utf-8")
    return Template(template.read_text(encoding="utf-8")).substitute(
        package=package.strip(),
        image_section=IMAGE_SECTION if images else NO_IMAGE_SECTION,
        min_reasons=MIN_REASONS,
        max_reasons=MAX_REASONS,
    )


def prompt_hash(prompt: str, images: Sequence[Path] = ()) -> str:
    """SHA-256 of the prompt text and of each attached image's name and bytes.

    A changed template, ``PACKAGE.md`` or view gives a new hash, so earlier feedback is stale.
    """
    digest = hashlib.sha256(prompt.encode("utf-8"))
    for image in images:
        digest.update(b"\0" + image.name.encode("utf-8") + b"\0")
        digest.update(image.read_bytes())
    return digest.hexdigest()


class ModelAdapter(ABC):
    """Interface for every model adapter: ``send(bundle_dir) -> FeedbackResult``.

    Subclasses set ``name`` and implement ``complete``. ``send`` builds the prompt, calls
    ``complete`` and stores the reply, or the error, as a ``FeedbackResult``.
    """

    name: str = "adapter"

    def __init__(self, model_id: Optional[str], images: bool = True, acknowledge_data_use: bool = False):
        if images and not acknowledge_data_use:
            raise DataUseError(
                f"{self.name}: sending MRI views to a model endpoint can breach data-use agreements; "
                "set the data-use acknowledgement to send images, or use the IQMs-only mode"
            )
        self.model_id = model_id
        self.images = images

    @property
    def settings(self) -> dict[str, Any]:
        """Generation settings recorded in the result."""
        return {"images": self.images}

    @property
    def endpoint(self) -> Optional[str]:
        """Endpoint recorded in the result; null for the default endpoint."""
        return None

    @abstractmethod
    def complete(self, prompt: str, images: Sequence[Path]) -> Reply:
        """Send one request; return the reply text, or the parsed object for structured output."""

    def request(self, bundle_dir: Path, bundle: EvidenceBundle) -> tuple[str, list[Path], str]:
        """The prompt, attached images and prompt hash for one request, without sending it."""
        prompt = render_prompt(bundle_dir, self.images)
        images = view_paths(bundle_dir, bundle) if self.images else []
        return prompt, images, prompt_hash(prompt, images)

    def send(self, bundle_dir: Path) -> FeedbackResult:
        """Send one bundle.

        An unreadable ``bundle.json`` raises, since no result can describe it. Any later failure
        (missing ``PACKAGE.md`` or view, model or transport error) is recorded in the result.
        """
        bundle = load_bundle(bundle_dir)
        meta: dict[str, Any] = dict(adapter=self.name, model_id=self.model_id, settings=self.settings, endpoint=self.endpoint)
        try:
            prompt, images, meta["prompt_hash"] = self.request(bundle_dir, bundle)
            reply = self.complete(prompt, images)
        except Exception as err:  # noqa: BLE001 - any adapter failure is stored for the evaluation
            return error_result(bundle, f"{type(err).__name__}: {err}", **meta)
        return reply_result(bundle, reply, **meta)
