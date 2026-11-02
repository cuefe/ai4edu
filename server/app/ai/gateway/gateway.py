"""模型网关：业务代码统一从这里调用大模型。

职责：按技能选模型、失败切换备用模型、去除个人信息、记录每次调用的用量和费用。
三家供应商（豆包 / DeepSeek / 通义）都提供 OpenAI 兼容接口，所以统一用 openai SDK 调用。
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

import anyio
from openai import AsyncOpenAI

from app.ai.gateway.config import MOCK, Candidate, GatewayConfig
from app.ai.gateway.redact import redact_messages
from app.core.config import SERVER_DIR, get_settings
from app.core.errors import AppError

log = logging.getLogger(__name__)

Messages = list[dict[str, Any]]


@dataclass(frozen=True)
class CallContext:
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass
class UsageRecord:
    ctx: CallContext
    skill: str
    candidate: Candidate
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    ok: bool = True
    error: str | None = None
    cost: Decimal | None = field(default=None)


class UsageSink(Protocol):
    async def record(self, rec: UsageRecord) -> None: ...


class DbUsageSink:
    """写入 ai_usage 表。用独立会话，不影响调用方的事务。"""

    async def record(self, rec: UsageRecord) -> None:
        await anyio.to_thread.run_sync(self._write, rec)

    @staticmethod
    def _write(rec: UsageRecord) -> None:
        # 从 app.models 导入：要注册全部表，ai_usage 的外键（tenant、user_account）才能解析。
        # 只导入 AiUsage 时，在 API 进程之外（Celery Worker、脚本）写入会失败
        from app.core.db import session_scope
        from app.models import AiUsage

        try:
            with session_scope(tenant_id=rec.ctx.tenant_id, bypass=rec.ctx.tenant_id is None) as db:
                db.add(
                    AiUsage(
                        tenant_id=rec.ctx.tenant_id,
                        user_id=rec.ctx.user_id,
                        skill=rec.skill,
                        provider=rec.candidate.provider,
                        model=rec.candidate.model,
                        prompt_tokens=rec.prompt_tokens,
                        completion_tokens=rec.completion_tokens,
                        cost_yuan=rec.cost,
                        latency_ms=rec.latency_ms,
                        ok=rec.ok,
                        error=rec.error,
                    )
                )
        except Exception:  # 记账失败不能影响业务
            log.exception("写入 AI 用量失败")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)


def _last_user_text(messages: Messages) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content
            return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return ""


class AIGateway:
    def __init__(self, config: GatewayConfig, *, sink: UsageSink | None = None, allow_mock: bool = False):
        self.config = config
        self.sink = sink
        self.allow_mock = allow_mock
        self._clients: dict[str, AsyncOpenAI] = {}

    def candidates(self, skill: str) -> list[Candidate]:
        found = self.config.candidates(skill)
        if not found and self.allow_mock:
            return [MOCK]
        return found

    def _client(self, c: Candidate) -> AsyncOpenAI:
        if c.provider not in self._clients:
            self._clients[c.provider] = AsyncOpenAI(
                api_key=c.api_key, base_url=c.base_url, timeout=60, max_retries=1
            )
        return self._clients[c.provider]

    async def _record(self, rec: UsageRecord) -> None:
        rec.cost = rec.candidate.cost(rec.prompt_tokens, rec.completion_tokens)
        if self.sink:
            await self.sink.record(rec)

    async def chat(self, skill: str, messages: Messages, *, ctx: CallContext, **params: Any) -> ChatResult:
        messages = redact_messages(messages)
        candidates = self.candidates(skill)
        for c in candidates:
            started = time.monotonic()
            try:
                if c is MOCK:
                    text = f"[mock:{skill}] {_last_user_text(messages)}"
                    pt, ct = (
                        sum(_estimate_tokens(str(m.get("content", ""))) for m in messages),
                        _estimate_tokens(text),
                    )
                else:
                    resp = await self._client(c).chat.completions.create(
                        model=c.model, messages=messages, **params
                    )
                    text = resp.choices[0].message.content or ""
                    pt = resp.usage.prompt_tokens if resp.usage else 0
                    ct = resp.usage.completion_tokens if resp.usage else 0
            except Exception as exc:
                latency = int((time.monotonic() - started) * 1000)
                log.warning(
                    "模型调用失败，切换下一个：skill=%s provider=%s model=%s err=%r",
                    skill,
                    c.provider,
                    c.model,
                    exc,
                )
                await self._record(
                    UsageRecord(ctx, skill, c, latency_ms=latency, ok=False, error=repr(exc)[:500])
                )
                continue
            latency = int((time.monotonic() - started) * 1000)
            await self._record(UsageRecord(ctx, skill, c, pt, ct, latency))
            return ChatResult(text, c.provider, c.model, pt, ct, latency)
        raise AppError("AI 服务暂时不可用，请稍后再试", code="ai_unavailable", status=503)

    async def stream(
        self, skill: str, messages: Messages, *, ctx: CallContext, **params: Any
    ) -> AsyncIterator[str]:
        """流式输出。只在第一段内容返回前切换备用模型；开始输出后出错直接抛出。"""
        messages = redact_messages(messages)
        for c in self.candidates(skill):
            started = time.monotonic()
            chunks: list[str] = []
            pt = ct = 0
            try:
                if c is MOCK:
                    source = self._mock_stream(skill, messages)
                else:
                    source = await self._client(c).chat.completions.create(
                        model=c.model,
                        messages=messages,
                        stream=True,
                        stream_options={"include_usage": True},
                        **params,
                    )
                iterator = aiter(source)
                first = await anext(iterator, None)
            except Exception as exc:
                latency = int((time.monotonic() - started) * 1000)
                log.warning("流式调用失败，切换下一个：skill=%s provider=%s err=%r", skill, c.provider, exc)
                await self._record(
                    UsageRecord(ctx, skill, c, latency_ms=latency, ok=False, error=repr(exc)[:500])
                )
                continue

            ok, error = True, None
            try:
                chunk = first
                while chunk is not None:
                    if isinstance(chunk, str):
                        delta = chunk
                    else:
                        if chunk.usage:
                            pt, ct = chunk.usage.prompt_tokens, chunk.usage.completion_tokens
                        delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        chunks.append(delta)
                        yield delta
                    chunk = await anext(iterator, None)
            except Exception as exc:
                ok, error = False, repr(exc)[:500]
                raise
            finally:
                if not pt:
                    pt = sum(_estimate_tokens(str(m.get("content", ""))) for m in messages)
                    ct = _estimate_tokens("".join(chunks))
                latency = int((time.monotonic() - started) * 1000)
                await self._record(UsageRecord(ctx, skill, c, pt, ct, latency, ok, error))
            return
        raise AppError("AI 服务暂时不可用，请稍后再试", code="ai_unavailable", status=503)

    @staticmethod
    async def _mock_stream(skill: str, messages: Messages) -> AsyncIterator[str]:
        text = f"[mock:{skill}] {_last_user_text(messages)}"
        for i in range(0, len(text), 8):
            yield text[i : i + 8]


@lru_cache
def get_gateway() -> AIGateway:
    settings = get_settings()
    # 测试时不读 .env，避免开发者本地配置的真实 Key 被测试调用
    env_file = None if settings.env == "test" else SERVER_DIR / ".env"
    config = GatewayConfig.load(settings.ai_config_path, env_file)
    return AIGateway(config, sink=DbUsageSink(), allow_mock=settings.ai_allow_mock and not settings.is_prod)
