"""S-07 in-memory pending CALL registry for matching OCPP responses."""

import asyncio

from src.modules.ocpp.messages import CallError, CallResult


class OcppCallFailed(RuntimeError):
    """S-07 error raised to the sender when a charge point returns CALLERROR."""

    def __init__(self, response: CallError) -> None:
        super().__init__(f"OCPP CALL failed: {response.code}: {response.description}")
        self.response = response


class PendingCallRegistry:
    """S-07 store outbound CALLs until their matching response arrives."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[CallResult]] = {}
        self._lock = asyncio.Lock()

    async def add(self, message_id: str) -> asyncio.Future[CallResult]:
        """Store a unique outbound message ID before the CALL is sent."""
        async with self._lock:
            if message_id in self._pending:
                raise ValueError(
                    f"Pending OCPP message ID already exists: {message_id}"
                )
            response = asyncio.get_running_loop().create_future()
            self._pending[message_id] = response
            return response

    async def resolve(self, response: CallResult) -> bool:
        """Complete the matching pending CALLRESULT and report whether it existed."""
        async with self._lock:
            pending = self._pending.pop(response.message_id, None)
        if pending is None:
            return False
        if not pending.done():
            pending.set_result(response)
        return True

    async def reject(self, response: CallError) -> bool:
        """Fail the matching pending CALL when a charge point returns CALLERROR."""
        async with self._lock:
            pending = self._pending.pop(response.message_id, None)
        if pending is None:
            return False
        if not pending.done():
            pending.set_exception(OcppCallFailed(response))
        return True

    async def discard(self, message_id: str) -> None:
        """Remove a pending CALL when writing it to the socket fails."""
        async with self._lock:
            self._pending.pop(message_id, None)
