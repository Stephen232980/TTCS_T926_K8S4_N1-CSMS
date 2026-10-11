"""Bounded, aggregate-only telemetry. No database I/O on the OCPP reply path."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

INTERVAL_SECONDS = 30
RETENTION_HOURS = 25


def bucket_time(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(
        second=value.second // INTERVAL_SECONDS * INTERVAL_SECONDS, microsecond=0
    )


@dataclass
class Bucket:
    timestamp: datetime
    error_count: int = 0
    response_count: int = 0
    latency_total_ms: float = 0
    complete: bool = False
    version: int = 0


class TelemetryBuffer:
    def __init__(self, started_at: datetime | None = None) -> None:
        self.worker_id: UUID = uuid4()
        self.started_at = started_at or datetime.now(UTC)
        self._coverage_cursor = bucket_time(self.started_at) + timedelta(seconds=30)
        self._buckets: dict[datetime, Bucket] = {}
        self._dirty: set[datetime] = set()
        self._lock = Lock()

    def record(
        self, *, error: bool, latency_ms: float | None, at: datetime | None = None
    ) -> None:
        if not error and latency_ms is None:
            return
        timestamp = bucket_time(at or datetime.now(UTC))
        with self._lock:
            bucket = self._buckets.setdefault(timestamp, Bucket(timestamp))
            bucket.error_count += int(error)
            if latency_ms is not None:
                bucket.response_count += 1
                bucket.latency_total_ms += max(0, latency_ms)
            bucket.version += 1
            self._dirty.add(timestamp)

    def snapshot(self, now: datetime) -> list[Bucket]:
        boundary = bucket_time(now)
        cutoff = boundary - timedelta(hours=RETENTION_HOURS)
        with self._lock:
            # Alive but quiet intervals are measured zero, not missing data.
            cursor = max(self._coverage_cursor, cutoff)
            while cursor < boundary:
                bucket = self._buckets.setdefault(cursor, Bucket(cursor))
                bucket.complete = True
                bucket.version += 1
                self._dirty.add(cursor)
                cursor += timedelta(seconds=30)
            self._coverage_cursor = max(self._coverage_cursor, boundary)
            for key in list(self._buckets):
                if key < cutoff:
                    self._buckets.pop(key)
                    self._dirty.discard(key)
            return [replace(self._buckets[t]) for t in sorted(self._dirty)]

    def acknowledge(self, buckets: list[Bucket]) -> None:
        with self._lock:
            for saved in buckets:
                current = self._buckets.get(saved.timestamp)
                if current and current.version == saved.version:
                    self._dirty.discard(saved.timestamp)


ocpp_telemetry = TelemetryBuffer()
