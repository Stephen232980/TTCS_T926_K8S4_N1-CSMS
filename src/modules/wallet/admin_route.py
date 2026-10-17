"""Preserve wallet error shape without echoing submitted credentials or PII."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.modules.identity.policy_routing import PolicyRoute


class WalletCommandRoute(PolicyRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe(request: Request) -> Response:
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError as error:
                return JSONResponse(
                    status_code=422,
                    headers={"Cache-Control": "no-store"},
                    content={
                        "detail": [
                            {key: entry[key] for key in ["loc", "msg", "type"]}
                            for entry in error.errors()
                        ]
                    },
                )

        return safe
