"""Claude adapter: sends one evidence bundle to the Anthropic Messages API.

The reply is requested through structured output (``output_config.format``) with the
``QCFeedback`` JSON schema. Current Claude models reject forced tool use and a fixed
temperature, so the adapter uses neither and records default sampling in the settings.
A refusal is stored as an error result; no fallback model is used, so each run is one model.
"""

import base64
import os
from pathlib import Path
from typing import Any, Optional, Sequence

from .base import ModelAdapter, Reply, image_label, reply_schema

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_MAX_TOKENS = 16000
BASE_URL_ENV = "ANTHROPIC_BASE_URL"


class RefusalError(RuntimeError):
    """The model declined the request."""


def image_block(path: Path) -> dict[str, Any]:
    """A base64 PNG image content block."""
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


class ClaudeAdapter(ModelAdapter):
    """Send a bundle to Claude; images are attached unless ``images`` is false."""

    name = "claude"

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        images: bool = True,
        acknowledge_data_use: bool = False,
        base_url: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
    ):
        super().__init__(model_id, images=images, acknowledge_data_use=acknowledge_data_use)
        self.max_tokens = max_tokens
        if client is not None:
            # An injected client was built by the caller; record only the endpoint the caller
            # declares, since the environment may not match what that client calls.
            self.base_url = base_url
            self.client = client
        else:
            self.base_url = base_url or os.environ.get(BASE_URL_ENV) or None
            self.client = self._make_client()

    def _make_client(self) -> Any:
        try:
            import anthropic
        except ImportError as err:
            raise ImportError("the Claude adapter needs the 'anthropic' package: uv pip install anthropic") from err
        # Credentials resolve in the SDK: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth` profile.
        return anthropic.Anthropic(base_url=self.base_url)

    @property
    def settings(self) -> dict[str, Any]:
        return {**super().settings, "max_tokens": self.max_tokens, "sampling": "default", "output": "json_schema"}

    @property
    def endpoint(self) -> Optional[str]:
        return self.base_url

    def complete(self, prompt: str, images: Sequence[Path]) -> Reply:
        content: list[dict[str, Any]] = []
        for index, path in enumerate(images, start=1):
            content.append({"type": "text", "text": image_label(index, path)})
            content.append(image_block(path))
        content.append({"type": "text", "text": prompt})
        response = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": reply_schema()}},
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise RefusalError(f"model declined the request (category: {category})")
        return "".join(block.text for block in response.content if block.type == "text")
