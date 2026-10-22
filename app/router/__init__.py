"""Router module: adaptive 4-tier query classification and fastpath rules."""

import sys

from app.router import classifier as _classifier
from app.router.classifier import (
    Route,
    RouterDecision,
    _parse_semantic_response,
    _semantic_route,
    classify_query,
    classify_query_adaptive,
    is_pure_arithmetic,
    rule_based_decision,
)
from app.router.fastpath import (
    LocalAnswer,
    local_answer,
    try_arithmetic,
)


class _RouterModule(sys.modules[__name__].__class__):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name != "__class__":
            setattr(_classifier, name, value)


sys.modules[__name__].__class__ = _RouterModule

__all__ = [
    "Route",
    "RouterDecision",
    "classify_query",
    "classify_query_adaptive",
    "rule_based_decision",
    "is_pure_arithmetic",
    "_parse_semantic_response",
    "_semantic_route",
    "LocalAnswer",
    "local_answer",
    "try_arithmetic",
]
