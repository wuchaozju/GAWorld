def annotate_low_emotion(context):
    """
    Example hook: flag low-emotion moments in daily logs.
    Phase: on_agent_post_step
    """
    agent = context.get("agent", {})
    daily_logs = context.get("daily_logs")
    if not isinstance(daily_logs, dict):
        return
    state = agent.get("state", {})
    emotion = float(state.get("emotion", 0.5))
    if emotion >= 0.2:
        return
    agent_id = agent.get("id")
    if agent_id is None:
        return
    time_str = context.get("time_str", "")
    note = f"[HookNote] {agent.get('name', agent_id)} @ {time_str}: emotion={emotion:.2f}\n"
    daily_logs[agent_id] = daily_logs.get(agent_id, "") + note


def increase_weekend_mobility(context):
    """
    Example hook: adjust one state variable at day start.
    Phase: on_day_start
    """
    day = int(context.get("day", 0))
    if day % 7 not in (6, 0):
        return
    for agent in context.get("agents", []):
        state = agent.get("state", {})
        mobility = float(state.get("mobility_intent", 0.5))
        state["mobility_intent"] = min(1.0, mobility + 0.05)
