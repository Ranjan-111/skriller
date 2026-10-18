"""Context-owned source routing over the copied Agent-Reach registry."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import AdapterBinding, ConnectorRegistry, OperationVerification, RouteSelection

__all__ = ["AdapterBinding", "ConnectorRegistry", "OperationVerification", "RouteSelection"]


def __getattr__(name):
    # Keep the reviewed standalone workers free of orchestration dependencies.
    # This mirrors the lazy export pattern in the copied Scrapling package.
    if name in __all__:
        return getattr(import_module(".registry", __name__), name)
    raise AttributeError(name)
