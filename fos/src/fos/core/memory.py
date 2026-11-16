class ShortTermMemory:
    def __init__(self):
        self.history = []

    def append(self, role, content, images=None, audio=None, video=None):
        """Append a message to memory.

        content 可以是 str，或 {"text": str, "images": [url,...]} 形式。
        images 可选，等价于 content dict 里的 images。
        """
        images = images or []
        audio = audio or []
        video = video or []
        if isinstance(content, dict):
            text = content.get("text", "")
            images = content.get("images", images) or []
            audio = content.get("audio", audio) or []
            video = content.get("video", video) or []
        else:
            text = str(content)

        entry = {"role": role, "content": text, "images": images, "audio": audio, "video": video}

        # 仅在都是纯文本且同角色时合并，避免图像信息丢失
        if self.history and self.history[-1]["role"] == role:
            last = self.history[-1]
            if not last.get("images") and not images and not last.get("audio") and not audio and not last.get("video") and not video:
                last["content"] += f"\n{text}"
                return

        self.history.append(entry)

    def get_all(self):
        return self.history

    def clear(self):
        self.history = []

    def serialize(self, dialect="default"):
        if dialect == "default":
            return [
                {
                    "role": msg.get("role"),
                    "content": msg.get("content"),
                    "images": msg.get("images", []),
                    "audio": msg.get("audio", []),
                    "video": msg.get("video", []),
                }
                for msg in self.history
            ]
        else:
            raise NotImplementedError(f"Unknown dialect: {dialect}")

    def searilize(self, dialect="default"):
        return self.serialize(dialect=dialect)

    def __len__(self):
        return len(self.history)
