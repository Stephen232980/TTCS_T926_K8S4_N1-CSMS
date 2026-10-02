"""In-process registry for active OCPP sockets. S-06 owns replacement semantics."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from fastapi import WebSocket

from src.modules.ocpp.frames import Frame, encode_frame


@dataclass(slots=True)
class OcppConnection:
    charge_point_id: UUID
    station_id: UUID
    charge_point_code: str
    station_status: str
    websocket: WebSocket
    connected_at: datetime
    boot_accepted: bool = False
    pending: dict[str, asyncio.Future[Frame]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, raw: str) -> None:
        async with self.send_lock:
            await self.websocket.send_text(raw)

    async def call(
        self, action: str, payload: dict[str, object], timeout: float = 30
    ) -> Frame:
        from uuid import uuid4

        message_id = str(uuid4())
        future: asyncio.Future[Frame] = asyncio.get_running_loop().create_future()
        self.pending[message_id] = future
        try:
            await self.send(encode_frame(Frame(2, message_id, payload, action=action)))
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(message_id, None)

    def cancel_pending(self) -> None:
        for future in self.pending.values():
            if not future.done():
                future.cancel()

    @property
    def can_start_session(self) -> bool:
        """S-06: only an active station may be used to start a session.

        Session handlers must re-check the current database status before each
        StartTransaction because this connection snapshot can become stale.
        """
        return self.station_status == "active"


class OcppConnectionRegistry:
    """Track one active socket per charge point within this application process."""

    def __init__(self) -> None:
        self._connections: dict[str, OcppConnection] = {}
        self._lock = asyncio.Lock()

    async def replace(self, connection: OcppConnection) -> None:
        """S-06: replace an older socket for the same code with the new socket."""
        async with self._lock:
            previous = self._connections.get(connection.charge_point_code)
            self._connections[connection.charge_point_code] = connection

        if previous is not None and previous.websocket is not connection.websocket:
            previous.cancel_pending()
            try:
                await previous.websocket.close(
                    code=1000,
                    reason="Replaced by a newer charge point connection.",
                )
            except (OSError, RuntimeError):
                # The prior socket may have disconnected while it was replaced.
                pass

    async def remove(self, charge_point_code: str, websocket: WebSocket) -> None:
        """Remove a socket only if it is still current for that charge point."""
        async with self._lock:
            current = self._connections.get(charge_point_code)
            if current is not None and current.websocket is websocket:
                del self._connections[charge_point_code]

    async def get(self, charge_point_code: str) -> OcppConnection | None:
        async with self._lock:
            return self._connections.get(charge_point_code)

    async def snapshot(self) -> dict[UUID, OcppConnection]:
        async with self._lock:
            return {
                connection.charge_point_id: connection
                for connection in self._connections.values()
            }


ocpp_connections = OcppConnectionRegistry()
