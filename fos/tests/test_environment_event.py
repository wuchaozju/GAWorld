from fos.core.event import EnvironmentEvent


def test_environment_event_creation():
    event = EnvironmentEvent("weather", "Heavy rain begins to fall.", "moderate")
    assert event.event_type == "weather"
    assert event.description == "Heavy rain begins to fall."
    assert event.severity == "moderate"


def test_environment_event_to_string():
    event = EnvironmentEvent("emergency", "A small fire has been reported in the district.", "severe")
    result = event.to_string(time=120)  # 2:00
    assert "[2:00]" in result
    assert "EMERGENCY" in result
    assert "small fire" in result


def test_environment_event_serialization():
    event = EnvironmentEvent("notification", "Town hall meeting at 3 PM.", "mild")
    assert hasattr(event, "code")
    assert hasattr(event, "params")
    assert event.code == "environment_event"
    assert event.params["event_type"] == "notification"
