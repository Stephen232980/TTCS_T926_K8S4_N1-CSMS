from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CurrentActor:
    user_id: UUID
    roles: frozenset[str]
