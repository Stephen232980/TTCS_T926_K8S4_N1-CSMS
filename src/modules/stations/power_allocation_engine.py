"""Pure power allocation and preemption engine (S-45 / G2).

Implements AC-2 (Decrease first, increase after) and AC-3 (LIFO preemption
when station power limit is lower than sum of minimum sessions' power).
No database read/write; completely deterministic and pure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class SessionDemand:
    session_id: UUID
    started_at: datetime
    current_w: int
    nominal_w: int
    min_w: int = 1380  # Default minimum charging power: ~6A @ 230V 1-phase


@dataclass(frozen=True)
class AllocationResult:
    to_decrease: dict[UUID, int]  # session_id -> target_w (decrease first)
    to_increase: dict[UUID, int]  # session_id -> target_w (increase after)
    unchanged: dict[UUID, int]  # session_id -> target_w
    to_preempt: list[UUID]  # sessions to be stopped (LIFO order: newest first)
    preemption_reason: str = ""
    allocated_total_w: int = 0
    is_degraded: bool = False


def phan_bo_cong_suat(
    limit_w: int,
    sessions: Sequence[SessionDemand],
) -> AllocationResult:
    """Calculate target power allocation for active sessions under a station limit.

    Rules:
    - If limit_w <= 0: all sessions must be preempted.
    - If sum of min_w > limit_w: preempt sessions in LIFO order (newest started_at first,
      tie-break with higher session_id) until the remaining sessions can receive at least min_w.
    - For remaining sessions: distribute limit_w proportionally or equally, capped at nominal_w.
    - Classify targets into to_decrease (safety first) and to_increase (applied after decrease ACK).
    """
    if not sessions:
        return AllocationResult(
            to_decrease={},
            to_increase={},
            unchanged={},
            to_preempt=[],
            allocated_total_w=0,
            is_degraded=False,
        )

    if limit_w <= 0:
        # Preempt all sessions
        newest_first = sorted(
            sessions,
            key=lambda s: (s.started_at, s.session_id),
            reverse=True,
        )
        return AllocationResult(
            to_decrease={},
            to_increase={},
            unchanged={},
            to_preempt=[s.session_id for s in newest_first],
            preemption_reason="Hạn mức trạm bằng hoặc nhỏ hơn 0W",
            allocated_total_w=0,
            is_degraded=True,
        )

    # 1. Check if preemption is needed (AC-3)
    active = list(sessions)
    preempted: list[UUID] = []

    while active and sum(s.min_w for s in active) > limit_w:
        # Pick the newest session from active to preempt
        candidate_to_drop = max(
            active, key=lambda s: (s.started_at, s.session_id)
        )
        active.remove(candidate_to_drop)
        preempted.append(candidate_to_drop.session_id)

    if not active:
        return AllocationResult(
            to_decrease={},
            to_increase={},
            unchanged={},
            to_preempt=preempted,
            preemption_reason="Hạn mức không đủ duy trì mức sạc tối thiểu cho bất kỳ xe nào",
            allocated_total_w=0,
            is_degraded=True,
        )

    # 2. Distribute power among surviving sessions (Equal share with nominal cap)
    allocated: dict[UUID, int] = {}
    remaining_budget = limit_w
    unassigned = list(active)

    while unassigned and remaining_budget > 0:
        equal_share = remaining_budget // len(unassigned)
        if equal_share == 0:
            for s in unassigned:
                allocated[s.session_id] = allocated.get(s.session_id, 0)
            break

        progress = False
        still_unassigned = []
        for s in unassigned:
            if s.nominal_w <= equal_share:
                # Session is satisfied at nominal cap
                allocated[s.session_id] = s.nominal_w
                remaining_budget -= s.nominal_w
                progress = True
            else:
                still_unassigned.append(s)

        if not progress:
            # All remaining sessions have nominal > equal_share; assign equal_share to each
            for s in still_unassigned:
                allocated[s.session_id] = equal_share
                remaining_budget -= equal_share
            break
        unassigned = still_unassigned

    for s in active:
        if s.session_id not in allocated:
            allocated[s.session_id] = 0

    # 3. Classify into to_decrease and to_increase (AC-2 safety: decrease first)
    to_decrease: dict[UUID, int] = {}
    to_increase: dict[UUID, int] = {}
    unchanged: dict[UUID, int] = {}

    for s in active:
        target = allocated[s.session_id]
        if target < s.current_w:
            to_decrease[s.session_id] = target
        elif target > s.current_w:
            to_increase[s.session_id] = target
        else:
            unchanged[s.session_id] = target

    preemption_reason = ""
    if preempted:
        preemption_reason = (
            f"Dừng {len(preempted)} phiên sạc mới nhất do hạ hạn mức giờ cao điểm "
            f"(hạn mức {limit_w}W không đủ tải tối thiểu)"
        )

    return AllocationResult(
        to_decrease=to_decrease,
        to_increase=to_increase,
        unchanged=unchanged,
        to_preempt=preempted,
        preemption_reason=preemption_reason,
        allocated_total_w=sum(allocated.values()),
        is_degraded=False,
    )
