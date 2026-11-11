from types import SimpleNamespace

from gaworld.apps import roommate_engagement as engagement


def session(hour=12, activities=("看电视", "喝茶")):
    return SimpleNamespace(
        virtual_clock_minutes=hour * 60,
        opening_clock_minutes=8 * 60,
        events=[],
        engagement_last_attempt=0,
        pending_tick=None,
        residents=[
            SimpleNamespace(agent_id=1, activity=activities[0], room="living"),
            SimpleNamespace(agent_id=2, activity=activities[1], room="balcony"),
        ],
    )


def test_long_idle_invitation_is_bounded_and_does_not_move_residents():
    s = session()
    result = engagement.invite(s)
    assert result and [r.room for r in s.residents] == ["living", "balcony"]
    assert engagement.invite(s) is None


def test_sleep_and_busy_time_do_not_force_conversation():
    assert engagement.invite(session(3)) is None
    assert engagement.invite(session(12, ("睡觉", "处理工作邮件"))) is None
