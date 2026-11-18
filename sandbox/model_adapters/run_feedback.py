"""Batch CLI: run one model adapter over a tree of evidence bundles.

Each folder that holds a ``bundle.json`` gets a ``feedback.json`` beside it. Per-bundle
failures are recorded in that bundle's ``feedback.json`` and the run continues.

Usage (from the repo root)::

    .venv/bin/python sandbox/model_adapters/run_feedback.py BUNDLE_ROOT --adapter claude --acknowledge_data_use
    .venv/bin/python sandbox/model_adapters/run_feedback.py BUNDLE_ROOT --adapter openai_compat \\
        --base_url http://gpu-host:8000/v1 --model_id llava-onevision --iqms_only
"""

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    # Run as a script: make ``model_adapters`` importable from the sandbox folder.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_adapters.base import BUNDLE_FILE, DataUseError, ModelAdapter, load_bundle  # noqa: E402
from evidence_bundle.feedback import FEEDBACK_FILE, FeedbackResult, load_feedback, skipped_result, write_feedback  # noqa: E402

LOG = logging.getLogger("run_feedback")

ADAPTERS = ("claude", "openai_compat")
MODEL_ENV = {"claude": "CLAUDE_MODEL", "openai_compat": "OPENAI_MODEL"}


def find_bundles(root: Path) -> list[Path]:
    """Every bundle folder under ``root`` (a folder holding ``bundle.json``), in sorted order."""
    return sorted(path.parent for path in Path(root).rglob(BUNDLE_FILE))


def _existing(bundle_dir: Path) -> Optional[FeedbackResult]:
    if not (bundle_dir / FEEDBACK_FILE).exists():
        return None
    try:
        return load_feedback(bundle_dir)
    except (OSError, ValueError) as err:
        LOG.warning("%s: unreadable %s is replaced: %s", bundle_dir, FEEDBACK_FILE, err)
        return None


def is_current(existing: Optional[FeedbackResult], adapter: ModelAdapter, prompt_hash: Optional[str]) -> bool:
    """True when ``existing`` came from this adapter and model with the same request.

    Error results are never current, so a rerun retries them.
    """
    if existing is None or existing.status == "error":
        return False
    same_model = (existing.adapter, existing.model_id) == (adapter.name, adapter.model_id)
    return same_model and existing.prompt_hash == prompt_hash


def process(bundle_dir: Path, adapter: ModelAdapter, overwrite: bool = False) -> str:
    """Write ``feedback.json`` for one bundle; return what happened (a result status or ``kept``).

    Raises only when ``bundle.json`` is unreadable, since no result can describe that bundle.
    """
    bundle = load_bundle(bundle_dir)
    existing = None if overwrite else _existing(bundle_dir)
    if bundle.support == "unsupported":
        # Never sent; the panel reads the skipped result to say why there is no feedback.
        if existing is not None and existing.status == "skipped_unsupported":
            return "kept"
        result = skipped_result(bundle, adapter=adapter.name, model_id=adapter.model_id)
    else:
        if existing is not None:
            try:
                prompt_hash = adapter.request(bundle_dir, bundle)[2]
            except OSError:
                prompt_hash = None  # a missing PACKAGE.md or view: send() records the error
            if prompt_hash is not None and is_current(existing, adapter, prompt_hash):
                return "kept"
        result = adapter.send(bundle_dir)
    write_feedback(bundle_dir, result)
    return result.status


def run(root: Path, adapter: ModelAdapter, overwrite: bool = False) -> Counter:
    """Process every bundle under ``root``; return a count of outcomes (``unreadable`` for failures)."""
    counts: Counter = Counter()
    bundles = find_bundles(root)
    LOG.info("%d bundles under %s", len(bundles), root)
    for bundle_dir in bundles:
        try:
            outcome = process(bundle_dir, adapter, overwrite=overwrite)
        except Exception as err:  # noqa: BLE001 - one bad bundle must not stop the run
            LOG.error("%s: %s: %s", bundle_dir, type(err).__name__, err)
            outcome = "unreadable"
        LOG.info("%s: %s", bundle_dir, outcome)
        counts[outcome] += 1
    return counts


def make_adapter(args: argparse.Namespace) -> ModelAdapter:
    """Build the adapter the arguments name. Raises ``DataUseError`` or ``ValueError`` on bad options."""
    model_id = args.model_id or os.environ.get(MODEL_ENV[args.adapter])
    common = dict(images=not args.iqms_only, acknowledge_data_use=args.acknowledge_data_use, base_url=args.base_url)
    if args.max_tokens is not None:
        common["max_tokens"] = args.max_tokens
    if args.adapter == "claude":
        from model_adapters.claude import DEFAULT_MODEL, ClaudeAdapter

        return ClaudeAdapter(model_id or DEFAULT_MODEL, **common)
    from model_adapters.openai_compat import OpenAICompatAdapter

    return OpenAICompatAdapter(model_id, **common)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write feedback.json for every evidence bundle under a folder.")
    parser.add_argument("bundle_root", type=Path, help="folder searched recursively for bundle.json files")
    parser.add_argument("--adapter", choices=ADAPTERS, required=True)
    parser.add_argument("--model_id", help="model id; default from CLAUDE_MODEL / OPENAI_MODEL, or the Claude default")
    parser.add_argument("--base_url", help="endpoint URL; default from ANTHROPIC_BASE_URL / OPENAI_BASE_URL")
    parser.add_argument("--iqms_only", action="store_true", help="send no images, only the metrics text")
    parser.add_argument(
        "--acknowledge_data_use",
        action="store_true",
        help="confirm that sending MRI views to this endpoint is allowed by your data-use agreement",
    )
    parser.add_argument("--max_tokens", type=int, help="reply token limit; default per adapter")
    parser.add_argument("--overwrite", action="store_true", help="rerun bundles that already have current feedback")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.bundle_root.is_dir():
        LOG.error("not a folder: %s", args.bundle_root)
        return 2
    try:
        adapter = make_adapter(args)
    except (DataUseError, ValueError, ImportError) as err:
        LOG.error("%s", err)
        return 2
    counts = run(args.bundle_root, adapter, overwrite=args.overwrite)
    LOG.info("done: %s", ", ".join(f"{key} {value}" for key, value in sorted(counts.items())) or "no bundles")
    return 1 if counts["unreadable"] else 0


if __name__ == "__main__":
    sys.exit(main())
