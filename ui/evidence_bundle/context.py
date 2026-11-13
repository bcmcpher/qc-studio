"""Load the IQM interpretation files in ``iqms/`` and resolve a scan's contrast support."""

from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Mapping, NamedTuple, Optional

from .constants import CONTEXT_FILES, DEFAULT_CONTRAST_MAP, FALLBACK_CONTEXT_DEPENDENT
from .models import MetricContext, MetricContextFile, MetricContextOverrideFile, SupportTier

IQMS_DIR = Path(__file__).parent / "iqms"

_SUFFIXES = {suffix.lower(): suffix for suffix in CONTEXT_FILES}


def _canonical_suffix(suffix: str) -> str:
    try:
        return _SUFFIXES[suffix.lower()]
    except KeyError:
        raise ValueError(f"no IQM context for suffix '{suffix}'; known: {sorted(CONTEXT_FILES)}") from None


def _merge(base: MetricContextFile, override: MetricContextOverrideFile) -> MetricContextFile:
    for section in ("metrics", "metric_patterns"):
        unknown = sorted(set(getattr(override, section)) - set(getattr(base, section)))
        if unknown:
            raise ValueError(f"override for {override.modality} names {section} not in the base file: {unknown}")
    return base.model_copy(
        update={
            "modality": override.modality,
            "metrics": {k: (override.metrics[k].apply(v) if k in override.metrics else v) for k, v in base.metrics.items()},
            "metric_patterns": {
                k: (override.metric_patterns[k].apply(v) if k in override.metric_patterns else v) for k, v in base.metric_patterns.items()
            },
        }
    )


def load_metric_context(suffix: str) -> MetricContextFile:
    """Load the context for a suffix with its own context (``T1w``, ``T2w``, ``bold``, ``dwi``).

    The first file in ``CONTEXT_FILES`` is the base; later files are overrides merged in order.
    The lookup is case-insensitive, and ``modality`` of the result is the canonical suffix.
    Each call returns a deep copy, so callers may change the result without changing the cache.
    """
    return _load(_canonical_suffix(suffix)).model_copy(deep=True)


@lru_cache(maxsize=None)
def _load(suffix: str) -> MetricContextFile:
    base_name, *override_names = CONTEXT_FILES[suffix]
    context = MetricContextFile.model_validate_json((IQMS_DIR / base_name).read_text())
    for name in override_names:
        override = MetricContextOverrideFile.model_validate_json((IQMS_DIR / name).read_text())
        if f"{override.base}.json" != base_name:
            raise ValueError(f"{name} overrides '{override.base}', not {base_name}")
        context = _merge(context, override)
    return context.model_copy(update={"modality": suffix})


class ResolvedContext(NamedTuple):
    """How a scan's metrics are interpreted."""

    support: SupportTier
    context_suffix: Optional[str]
    context: Optional[MetricContextFile]
    """Metric context to use; null for ``unsupported``."""


def _force_context_dependent(entry: MetricContext, suffix: str, context_suffix: str) -> MetricContext:
    caveat = f"treated as context_dependent: depends on tissue contrast, and {suffix} is interpreted with {context_suffix} context"
    return entry.model_copy(update={"direction_of_concern": "context_dependent", "caveats": [*entry.caveats, caveat]})


def _is_forced(key: str, entry: MetricContext) -> bool:
    names = [key, *entry.matches]
    return any(fnmatchcase(name, glob) or name == glob for name in names for glob in FALLBACK_CONTEXT_DEPENDENT)


def resolve_context(suffix: str, contrast_map: Optional[Mapping[str, str]] = None) -> ResolvedContext:
    """Return the support tier and metric context for a BIDS suffix.

    A suffix with its own context is ``supported``, whatever the map says. Otherwise the map
    (``DEFAULT_CONTRAST_MAP`` unless ``contrast_map`` replaces it) gives a ``fallback`` context,
    in which ``FALLBACK_CONTEXT_DEPENDENT`` metrics become ``context_dependent``. Any other
    suffix is ``unsupported``. Suffixes and map keys match case-insensitively.
    """
    if suffix.lower() in _SUFFIXES:
        own = _canonical_suffix(suffix)
        return ResolvedContext("supported", own, load_metric_context(own))
    mapping = DEFAULT_CONTRAST_MAP if contrast_map is None else contrast_map
    target = {k.lower(): v for k, v in mapping.items()}.get(suffix.lower())
    if target is None:
        return ResolvedContext("unsupported", None, None)
    context_suffix = _canonical_suffix(target)
    base = load_metric_context(context_suffix)
    context = base.model_copy(
        update={
            "modality": suffix,
            "metrics": {k: (_force_context_dependent(v, suffix, context_suffix) if _is_forced(k, v) else v) for k, v in base.metrics.items()},
            "metric_patterns": {
                k: (_force_context_dependent(v, suffix, context_suffix) if _is_forced(k, v) else v) for k, v in base.metric_patterns.items()
            },
        }
    )
    return ResolvedContext("fallback", context_suffix, context)


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
