"""OpenAI-compatible adapter: sends one evidence bundle to a chat completions endpoint.

Covers any server with the OpenAI chat completions API, for example a self-hosted model
under vLLM on a remote host or a local GPU workstation. The endpoint and the model id are
required. The reply is requested with ``response_format`` (the ``QCFeedback`` JSON schema)
and ``temperature=0``; a server that ignores the format and replies in free text still works,
because ``feedback.py`` extracts the JSON object from the text.
"""

import base64
import os
from pathlib import Path
from typing import Any, Optional, Sequence

from .base import ModelAdapter, RefusalError, Reply, image_label, reply_schema

DEFAULT_MAX_TOKENS = 2048
BASE_URL_ENV = "OPENAI_BASE_URL"
API_KEY_ENV = "OPENAI_API_KEY"
# Self-hosted servers often need no key, but the SDK requires one; this placeholder is sent then.
NO_KEY = "EMPTY"
SCHEMA_NAME = "qc_feedback"


def image_part(path: Path) -> dict[str, Any]:
    """A base64 PNG data-URL image part."""
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


class OpenAICompatAdapter(ModelAdapter):
    """Send a bundle to an OpenAI-compatible endpoint; images are attached unless ``images`` is false."""

    name = "openai_compat"

    def __init__(
        self,
        model_id: str,
        base_url: Optional[str] = None,
        images: bool = True,
        acknowledge_data_use: bool = False,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
    ):
        if not model_id:
            raise ValueError(f"{self.name}: a model id is required (the name the server serves)")
        super().__init__(model_id, images=images, acknowledge_data_use=acknowledge_data_use)
        # As in the Claude adapter, an injected client records only the endpoint the caller declares.
        self.base_url = base_url if client is not None else base_url or os.environ.get(BASE_URL_ENV) or None
        if not self.base_url:
            raise ValueError(f"{self.name}: an endpoint is required: pass base_url or set {BASE_URL_ENV}")
        self.max_tokens = max_tokens
        self.client = client if client is not None else self._make_client()

    def _make_client(self) -> Any:
        try:
            import openai
        except ImportError as err:
            raise ImportError("the OpenAI-compatible adapter needs the 'openai' package: uv pip install openai") from err
        return openai.OpenAI(base_url=self.base_url, api_key=os.environ.get(API_KEY_ENV) or NO_KEY)

    @property
    def settings(self) -> dict[str, Any]:
        return {**super().settings, "max_tokens": self.max_tokens, "temperature": 0, "output": "json_schema"}

    @property
    def endpoint(self) -> Optional[str]:
        return self.base_url

    def complete(self, prompt: str, images: Sequence[Path]) -> Reply:
        content: list[dict[str, Any]] = []
        for index, path in enumerate(images, start=1):
            content.append({"type": "text", "text": image_label(index, path)})
            content.append(image_part(path))
        content.append({"type": "text", "text": prompt})
        response = self.client.chat.completions.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_schema", "json_schema": {"name": SCHEMA_NAME, "schema": reply_schema(), "strict": True}},
        )
        message = response.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise RefusalError(f"model declined the request: {refusal}")
        # A reply cut off at max_tokens is kept; feedback.py marks it invalid with its raw text.
        return message.content or ""
