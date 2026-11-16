def _fmt_time_prefix(time_val):
    if time_val is None:
        return ""
    minutes = int(time_val)
    hours = minutes // 60
    mins = minutes % 60
    return f"[{hours}:{mins:02d}] "


class Event:
    def to_string(self, time=None):
        raise NotImplementedError

    def get_sender(self):
        return None


class MessageEvent(Event):
    def __init__(self, sender, message):
        self.sender = sender
        self.message = message

    def to_string(self, time=None):
        time_str = _fmt_time_prefix(time)
        return f"{time_str}[Message] {self.sender}: {self.message}"

    def get_sender(self):
        return self.sender


class PublicEvent(Event):
    def __init__(self, content, prefix="Public Event", images=None, audio=None, video=None):
        self.content = content
        self.prefix = prefix
        self.images = images or []
        self.audio = audio or []
        self.video = video or []
        self.code = "public_event"
        self.params = {
            "content": content,
            "prefix": prefix,
            "images": self.images,
            "audio": self.audio,
            "video": self.video,
        }

    def to_string(self, time=None):
        time_str = _fmt_time_prefix(time)
        return f"{time_str}{self.prefix}: {self.content}"


class NewsEvent(Event):
    def __init__(self, content):
        self.content = content

    def to_string(self, time=None):
        time_str = _fmt_time_prefix(time)
        return f"{time_str}[NEWS] {self.content}"


class StatusEvent(Event):
    def __init__(self, status_data):
        self.status_data = status_data

    def to_string(self, time=None):
        time_str = _fmt_time_prefix(time)
        return f"{time_str}Status: {self.status_data}"


class SpeakEvent(Event):
    def __init__(self, sender, message):
        self.sender = sender
        self.message = message

    def to_string(self, time=None):
        # Natural transcript style: "[time] Alice: message"
        time_str = _fmt_time_prefix(time)
        return f"{time_str}{self.sender}: {self.message}"

    def get_sender(self):
        return self.sender


class TalkToEvent(Event):
    def __init__(self, sender, recipient, message):
        self.sender = sender
        self.recipient = recipient
        self.message = message

    def to_string(self, time=None):
        time_str = _fmt_time_prefix(time)
        return f"{time_str}{self.sender} to {self.recipient}: {self.message}"

    def get_sender(self):
        return self.sender


class EnvironmentEvent(Event):
    """Environmental events like weather, emergencies, notifications, public opinion."""

    def __init__(self, event_type: str, description: str, severity: str = "mild"):
        self.event_type = event_type  # "weather", "emergency", "notification", "opinion"
        self.description = description
        self.severity = severity  # "mild", "moderate", "severe"
        self.code = "environment_event"
        self.params = {
            "event_type": event_type,
            "description": description,
            "severity": severity,
        }

    def to_string(self, time=None):
        time_str = _fmt_time_prefix(time)
        prefix_map = {
            "weather": "WEATHER",
            "emergency": "EMERGENCY",
            "notification": "NOTIFICATION",
            "opinion": "PUBLIC OPINION",
        }
        prefix = prefix_map.get(self.event_type, "ENVIRONMENT")
        return f"{time_str}[{prefix}] {self.description}"
