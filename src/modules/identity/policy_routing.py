"""Route admission is fail closed, independently of router dependency conventions."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute
from starlette.requests import HTTPConnection

from src.modules.identity.authorization import get_access_policy
from src.modules.identity.dependencies import authorize_request


async def require_policy_declaration(request: HTTPConnection) -> None:
    endpoint = request.scope.get("endpoint")
    if not callable(endpoint) or get_access_policy(endpoint) is None:
        raise HTTPException(403, "Không có quyền truy cập")


class PolicyRoute(APIRoute):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        endpoint = kwargs.get("endpoint")
        policy = get_access_policy(endpoint) if callable(endpoint) else None
        if policy is not None and policy.kind == "user":
            kwargs["dependencies"] = [
                *(kwargs.get("dependencies") or []),
                Depends(authorize_request),
            ]
        if policy is not None:
            kwargs["openapi_extra"] = {
                **(kwargs.get("openapi_extra") or {}),
                "x-access-policy": {
                    "kind": policy.kind,
                    "permission": policy.permission,
                    "scope": policy.scope,
                    "roles": sorted(policy.roles),
                },
            }
        super().__init__(*args, **kwargs)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            policy = get_access_policy(self.endpoint)
            if policy is None or policy.kind not in {"user", "public"}:
                # Device/Webhook endpoints must use their respective admission implementation.
                raise HTTPException(403, "Không có quyền truy cập")
            return await original(request)

        return guarded
