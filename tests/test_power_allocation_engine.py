from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from src.modules.stations.power_allocation_engine import (
    SessionDemand,
    phan_bo_cong_suat,
)


def test_empty_sessions():
    result = phan_bo_cong_suat(50000, [])
    assert result.allocated_total_w == 0
    assert result.to_preempt == []
    assert not result.is_degraded


def test_normal_unconstrained_allocation():
    now = datetime.now(UTC)
    s1 = SessionDemand(
        session_id=uuid4(),
        started_at=now,
        current_w=10000,
        nominal_w=11000,
        min_w=1380,
    )
    s2 = SessionDemand(
        session_id=uuid4(),
        started_at=now,
        current_w=5000,
        nominal_w=22000,
        min_w=1380,
    )
    # Total limit is 50kW, both can reach full nominal
    result = phan_bo_cong_suat(50000, [s1, s2])
    assert result.to_preempt == []
    assert result.to_increase[s1.session_id] == 11000
    assert result.to_increase[s2.session_id] == 22000
    assert result.allocated_total_w == 33000


def test_decrease_first_and_increase_after():
    now = datetime.now(UTC)
    s1 = SessionDemand(
        session_id=uuid4(),
        started_at=now,
        current_w=20000,
        nominal_w=22000,
        min_w=1380,
    )
    s2 = SessionDemand(
        session_id=uuid4(),
        started_at=now,
        current_w=5000,
        nominal_w=22000,
        min_w=1380,
    )
    # Total limit 20kW -> equal share 10kW each
    # s1 decreases from 20kW to 10kW
    # s2 increases from 5kW to 10kW
    result = phan_bo_cong_suat(20000, [s1, s2])
    assert result.to_preempt == []
    assert s1.session_id in result.to_decrease
    assert result.to_decrease[s1.session_id] == 10000
    assert s2.session_id in result.to_increase
    assert result.to_increase[s2.session_id] == 10000


def test_lifo_preemption_drops_newest_session():
    """AC-3: If limit is lower than total minimum demands, drop newest session (started_at LIFO)."""
    t0 = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=15)
    t2 = t0 + timedelta(minutes=30)

    # 3 sessions each need at least 4kW (min_w = 4000)
    s_oldest = SessionDemand(
        session_id=uuid4(), started_at=t0, current_w=7000, nominal_w=11000, min_w=4000
    )
    s_middle = SessionDemand(
        session_id=uuid4(), started_at=t1, current_w=7000, nominal_w=11000, min_w=4000
    )
    s_newest = SessionDemand(
        session_id=uuid4(), started_at=t2, current_w=7000, nominal_w=11000, min_w=4000
    )

    # Total min required for 3 cars is 12kW.
    # At 22:00, station drops limit to 10kW -> cannot support 3 cars!
    result = phan_bo_cong_suat(10000, [s_oldest, s_middle, s_newest])

    # S_newest MUST be preempted!
    assert result.to_preempt == [s_newest.session_id]
    assert s_oldest.session_id not in result.to_preempt
    assert s_middle.session_id not in result.to_preempt
    assert s_oldest.session_id in result.to_decrease
    assert s_middle.session_id in result.to_decrease
    assert "giờ cao điểm" in result.preemption_reason


def test_lifo_tie_break_by_session_id():
    """AC-3: If started_at is identical, break ties by session_id descending."""
    now = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    id1 = UUID("00000000-0000-0000-0000-000000000001")
    id2 = UUID("00000000-0000-0000-0000-000000000002")

    s1 = SessionDemand(
        session_id=id1, started_at=now, current_w=5000, nominal_w=7000, min_w=4000
    )
    s2 = SessionDemand(
        session_id=id2, started_at=now, current_w=5000, nominal_w=7000, min_w=4000
    )

    # Limit 5kW: can only keep 1 car (min_w = 4000)
    result = phan_bo_cong_suat(5000, [s1, s2])
    # id2 is greater than id1, so s2 is preempted
    assert result.to_preempt == [id2]


def test_zero_or_negative_limit_preempts_all():
    now = datetime.now(UTC)
    s1 = SessionDemand(
        session_id=uuid4(), started_at=now, current_w=5000, nominal_w=7000, min_w=1380
    )
    s2 = SessionDemand(
        session_id=uuid4(), started_at=now, current_w=5000, nominal_w=7000, min_w=1380
    )
    result = phan_bo_cong_suat(0, [s1, s2])
    assert len(result.to_preempt) == 2
    assert result.is_degraded
