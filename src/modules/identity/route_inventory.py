"""Inventory derived from registered HTTP and WebSocket routers."""

from collections.abc import Iterable, Iterator
from typing import Any

from src.modules.identity.authorization import get_access_policy


def registered_routes(
    routes: Iterable[Any], prefix: str = ""
) -> Iterator[tuple[Any, str]]:
    for route in routes:
        # FastAPI >= 0.135 defers include_router expansion.
        original = getattr(route, "original_router", None)
        if original is not None:
            context = route.include_context
            yield from registered_routes(original.routes, prefix + context.prefix)
        elif hasattr(route, "routes"):
            yield from registered_routes(route.routes, prefix + route.path)
        elif hasattr(route, "endpoint"):
            yield route, prefix + route.path


def route_inventory(routes: Iterable[Any]) -> list[dict[str, str]]:
    rows = []
    for route, path in registered_routes(routes):
        policy = get_access_policy(route.endpoint)
        methods = sorted(getattr(route, "methods", None) or {"WEBSOCKET"})
        for method in methods:
            rows.append(
                {
                    "method": method,
                    "path": path,
                    "kind": policy.kind if policy else "MISSING",
                    "permission": (policy.permission or "") if policy else "",
                    "scope": (policy.scope or "") if policy else "",
                    "roles": ",".join(sorted(policy.roles)) if policy else "",
                    "note": policy.note if policy else "",
                }
            )
    return sorted(rows, key=lambda row: (row["path"], row["method"]))
