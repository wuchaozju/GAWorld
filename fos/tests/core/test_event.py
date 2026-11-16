"""
Tests for fos.core.event — event classes used in simulation output.

Verifies to_string formatting, time formatting, and get_sender
for all event types: MessageEvent, PublicEvent, NewsEvent,
StatusEvent, SpeakEvent, TalkToEvent, EnvironmentEvent.

Contains: test_fmt_time_prefix, test_message_event,
          test_public_event, test_news_event, test_status_event,
          test_speak_event, test_talk_to_event,
          test_environment_event_all_types
"""
import pytest

from fos.core.event import (
    EnvironmentEvent,
    Event,
    MessageEvent,
    NewsEvent,
    PublicEvent,
    SpeakEvent,
    StatusEvent,
    TalkToEvent,
    _fmt_time_prefix,
)


# ── _fmt_time_prefix ──────────────────────────────────────────────────────

def test_fmt_time_returns_empty_when_none():
    assert _fmt_time_prefix(None) == ""


def test_fmt_time_formats_hours_and_minutes():
    assert _fmt_time_prefix(0) == "[0:00] "
    assert _fmt_time_prefix(65) == "[1:05] "
    assert _fmt_time_prefix(125) == "[2:05] "


def test_fmt_time_formats_large_values():
    assert _fmt_time_prefix(600) == "[10:00] "


# ── Event base class ──────────────────────────────────────────────────────

def test_event_base_raises_not_implemented():
    e = Event()
    with pytest.raises(NotImplementedError):
        e.to_string()


def test_event_base_get_sender_returns_none():
    assert Event().get_sender() is None


# ── MessageEvent ──────────────────────────────────────────────────────────

def test_message_event_formats_without_time():
    e = MessageEvent("Alice", "Hello world")
    assert e.to_string() == "[Message] Alice: Hello world"


def test_message_event_formats_with_time():
    e = MessageEvent("Bob", "Hi")
    assert e.to_string(time=10) == "[0:10] [Message] Bob: Hi"


def test_message_event_get_sender():
    assert MessageEvent("Alice", "x").get_sender() == "Alice"


# ── PublicEvent ───────────────────────────────────────────────────────────

def test_public_event_default_prefix():
    e = PublicEvent("Breaking news")
    assert e.to_string() == "Public Event: Breaking news"


def test_public_event_custom_prefix():
    e = PublicEvent("Storm incoming", prefix="WEATHER")
    assert e.to_string() == "WEATHER: Storm incoming"


def test_public_event_with_time():
    e = PublicEvent("Content", prefix="P")
    assert e.to_string(time=30) == "[0:30] P: Content"


def test_public_event_stores_multimedia():
    e = PublicEvent("c", images=["img.png"], audio=["a.wav"], video=["v.mp4"])
    assert e.images == ["img.png"]
    assert e.audio == ["a.wav"]
    assert e.video == ["v.mp4"]
    assert e.params["images"] == ["img.png"]


def test_public_event_defaults_empty_media():
    e = PublicEvent("c")
    assert e.images == []
    assert e.audio == []
    assert e.video == []


# ── NewsEvent ─────────────────────────────────────────────────────────────

def test_news_event_without_time():
    e = NewsEvent("Markets crashed")
    assert e.to_string() == "[NEWS] Markets crashed"


def test_news_event_with_time():
    e = NewsEvent("Markets up")
    assert e.to_string(time=120) == "[2:00] [NEWS] Markets up"


# ── StatusEvent ───────────────────────────────────────────────────────────

def test_status_event_without_time():
    e = StatusEvent({"hp": 80})
    assert e.to_string() == "Status: {'hp': 80}"


def test_status_event_with_time():
    e = StatusEvent("idle")
    assert e.to_string(time=5) == "[0:05] Status: idle"


# ── SpeakEvent ────────────────────────────────────────────────────────────

def test_speak_event_without_time():
    e = SpeakEvent("Alice", "I agree")
    assert e.to_string() == "Alice: I agree"


def test_speak_event_with_time():
    e = SpeakEvent("Bob", "No way")
    assert e.to_string(time=45) == "[0:45] Bob: No way"


def test_speak_event_get_sender():
    assert SpeakEvent("Alice", "x").get_sender() == "Alice"


# ── TalkToEvent ───────────────────────────────────────────────────────────

def test_talk_to_event_without_time():
    e = TalkToEvent("Alice", "Bob", "Secret")
    assert e.to_string() == "Alice to Bob: Secret"


def test_talk_to_event_with_time():
    e = TalkToEvent("A", "B", "Hi")
    assert e.to_string(time=90) == "[1:30] A to B: Hi"


def test_talk_to_event_get_sender():
    assert TalkToEvent("Alice", "Bob", "x").get_sender() == "Alice"


# ── EnvironmentEvent ──────────────────────────────────────────────────────

class TestEnvironmentEvent:
    def test_weather_prefix(self):
        e = EnvironmentEvent("weather", "Rainy day")
        assert e.to_string() == "[WEATHER] Rainy day"

    def test_emergency_prefix(self):
        e = EnvironmentEvent("emergency", "Fire alarm")
        assert e.to_string() == "[EMERGENCY] Fire alarm"

    def test_notification_prefix(self):
        e = EnvironmentEvent("notification", "Update available")
        assert e.to_string() == "[NOTIFICATION] Update available"

    def test_opinion_prefix(self):
        e = EnvironmentEvent("opinion", "Public angry")
        assert e.to_string() == "[PUBLIC OPINION] Public angry"

    def test_unknown_type_uses_generic_prefix(self):
        e = EnvironmentEvent("earthquake", "Rumble")
        assert e.to_string() == "[ENVIRONMENT] Rumble"

    def test_with_time(self):
        e = EnvironmentEvent("weather", "Sunny")
        assert e.to_string(time=15) == "[0:15] [WEATHER] Sunny"

    def test_params_stored(self):
        e = EnvironmentEvent("weather", "Snow", severity="severe")
        assert e.params == {
            "event_type": "weather",
            "description": "Snow",
            "severity": "severe",
        }
