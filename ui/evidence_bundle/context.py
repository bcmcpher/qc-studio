"""Load the IQM interpretation files in ``iqms/``."""

from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .models import MetricContext, MetricContextFile

IQMS_DIR = Path(__file__).parent / "iqms"

MODALITY_FILES = {"t1w": "t1w.json", "bold": "bold.json", "dwi": "dwi.json"}


@lru_cache(maxsize=None)
def load_metric_context(modality: str) -> MetricContextFile:
    """Load and validate the context file for a modality (``T1w``, ``bold`` or ``dwi``)."""
    try:
        filename = MODALITY_FILES[modality.lower()]
    except KeyError:
        raise ValueError(f"no IQM context for modality '{modality}'; known: {sorted(MODALITY_FILES)}") from None
    return MetricContextFile.model_validate_json((IQMS_DIR / filename).read_text())


def lookup_metric(context: MetricContextFile, name: str) -> Optional[MetricContext]:
    """Return the context for one IQM name, or None if the file does not describe it.

    An exact entry in ``metrics`` wins. Otherwise a pattern matches when the name is in its
    ``matches`` list (which may hold globs) or matches the pattern key itself.
    """
    if name in context.metrics:
        return context.metrics[name]
    for key, entry in context.metric_patterns.items():
        if any(fnmatchcase(name, m) for m in entry.matches) or fnmatchcase(name, key):
            return entry
    return None
