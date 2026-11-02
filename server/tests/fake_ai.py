"""测试用的假模型网关：按技能返回预设内容，记录每次调用。"""

from collections.abc import Callable

from app.ai.gateway.gateway import ChatResult, Messages

Handler = Callable[[str, Messages], str | Exception]


class FakeChat:
    def __init__(self, handler: Handler):
        self.handler = handler
        self.calls: list[dict] = []

    async def chat(self, skill: str, messages: Messages, *, ctx, **params) -> ChatResult:
        self.calls.append({"skill": skill, "messages": messages, "ctx": ctx, "params": params})
        reply = self.handler(skill, messages)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(reply, "fake", "fake-model", 10, 10, 1)

    def embed_model(self, skill: str) -> None:  # 没有向量模型：资料库检索直接返回空
        return None

    def skills(self) -> list[str]:
        return [c["skill"] for c in self.calls]
