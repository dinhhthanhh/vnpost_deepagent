"""Domain module: VNPost postal services catalog, tracking, and terminology."""

from app.domain.postal_services import (
    lookup_postal_office,
    track_postal_item,
)
from app.domain.terminology import (
    build_terminology_hint,
    find_matched_terminology,
    load_terminology,
    postprocess_func,
)

__all__ = [
    "lookup_postal_office",
    "track_postal_item",
    "build_terminology_hint",
    "find_matched_terminology",
    "load_terminology",
    "postprocess_func",
]
