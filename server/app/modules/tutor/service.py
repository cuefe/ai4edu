"""问一问：学生的 AI 答疑。

每条学生消息：安全分类（关键词＋模型）→ 危机：固定安抚话术和求助电话、生成预警工单，对话不中断
→ 闲聊、不当内容：礼貌拉回学习 → 正常：按模式回答（作业提示模式不流式，先检查有没有泄露答案，泄露就改写）。
"""

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import anyio
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import CallContext, get_gateway
from app.ai.skills import safety, tutor
from app.ai.skills.common import parse_json
from app.core import storage
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.assignment import student as assignments
from app.modules.assignment.models import ItemType, SubmissionStatus
from app.modules.iam.models import User
from app.modules.learning import service as learning
from app.modules.ops import quota
from app.modules.safety import service as safety_service
from app.modules.tutor.models import ChatMessage, ChatSession

log = logging.getLogger(__name__)

HISTORY = 12  # 回答时带上最近几条对话
MAX_IMAGES = 3

Event = tuple[str, dict[str, Any]]


class SessionIn(BaseModel):
    mode: tutor.Mode = "learn"
    assignment_id: uuid.UUID | None = Field(default=None, description="问作业里的某道题时填")
    item_id: uuid.UUID | None = None
    wrong_item_id: uuid.UUID | None = Field(default=None, description="订正错题时填")


class SessionOut(BaseModel):
    id: uuid.UUID
    mode: str
    subject: str
    title: str
    question: dict[str, Any] | None = Field(description="关联的题目（作业提示模式下不含答案）")
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    image_count: int
    style: str | None
    flag: str | None
    created_at: datetime


class SessionDetail(SessionOut):
    messages: list[MessageOut]
    hotlines: list[str] = Field(description="求助电话，危机回复里显示")


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    style: tutor.Style | None = Field(default=None, description="讲解方式：讲简单点 / 举例子 / 编口诀")
    images: list[str] = Field(default_factory=list, max_length=MAX_IMAGES, description="先上传图片拿到的 key")


def session_out(s: ChatSession) -> SessionOut:
    question = None
    if s.context and s.context.get("question"):
        question = dict(s.context["question"])
        if s.mode == "homework":
            question.pop("answer", None)
            question.pop("analysis", None)
    return SessionOut(
        id=s.id,
        mode=s.mode,
        subject=s.subject,
        title=s.title,
        question=question,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def message_out(m: ChatMessage) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        image_count=len(m.images),
        style=m.style,
        flag=m.flag,
        created_at=m.created_at,
    )


# —— 会话 ——


def create_session(db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, body: SessionIn) -> ChatSession:
    mode: str = "learn"
    context = None
    subject = ""
    title = "新的提问"
    if body.assignment_id and body.item_id:
        a, sub = assignments.get(db, tenant_id, student_id, body.assignment_id)
        item = next((i for i in assignments.items_of(db, a.id) if i.id == body.item_id), None)
        if item is None or item.item_type != ItemType.QUESTION:
            raise NotFound("题目不存在")
        if sub.status == SubmissionStatus.TODO and not a.allow_ai:
            raise Forbidden("这份作业老师设置了不能问 AI，先独立完成吧")
        # 作业没提交、或者答案还没公布，都只能给提示
        mode = "learn" if assignments.revealed(a, sub) else "homework"
        context = {
            "type": "assignment_item",
            "id": str(item.id),
            "assignment_id": str(a.id),
            "question": item.content,
        }
        subject = a.subject
        title = f"{a.title} 第 {item.seq + 1} 项"
    elif body.wrong_item_id:
        w = learning.get_wrong(db, tenant_id, student_id, body.wrong_item_id)
        mode = "correction"
        context = {"type": "wrong_item", "id": str(w.id), "question": w.question}
        subject = w.subject
        title = f"订正：{w.question.get('stem', '')[:30]}"
    else:
        blocked = assignments.ai_blocked(db, tenant_id, student_id)
        if blocked:
            raise Forbidden(f"作业「{blocked.title}」老师设置了作业期间不能问 AI，提交后再来问吧")
    s = ChatSession(
        tenant_id=tenant_id,
        student_id=student_id,
        mode=mode,
        subject=subject,
        title=title[:100],
        context=context,
    )
    db.add(s)
    db.flush()
    return s


def get_session(db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, sid: uuid.UUID) -> ChatSession:
    s = db.scalar(
        select(ChatSession).where(
            ChatSession.id == sid, ChatSession.tenant_id == tenant_id, ChatSession.student_id == student_id
        )
    )
    if s is None:
        raise NotFound("会话不存在")
    return s


def list_sessions(db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID) -> list[SessionOut]:
    rows = db.scalars(
        select(ChatSession)
        .where(ChatSession.tenant_id == tenant_id, ChatSession.student_id == student_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(30)
    )
    return [session_out(s) for s in rows]


def messages(db: Session, session_id: uuid.UUID, limit: int = 200) -> list[ChatMessage]:
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.role)
        .limit(limit)
    ).all()
    return list(reversed(rows))


def detail(db: Session, s: ChatSession) -> SessionDetail:
    return SessionDetail(
        **session_out(s).model_dump(),
        messages=[message_out(m) for m in messages(db, s.id)],
        hotlines=get_settings().crisis_hotlines,
    )


# —— 图片 ——


def _image_prefix(tenant_id: uuid.UUID, student_id: uuid.UUID) -> str:
    return f"{tenant_id}/tutor-{student_id}-"


def save_image(tenant_id: uuid.UUID, student_id: uuid.UUID, data: bytes) -> str:
    key = f"{_image_prefix(tenant_id, student_id)}{uuid.uuid4().hex}.jpg"
    storage.put(key, assignments.normalize_image(data))
    return key


def message_image(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, mid: uuid.UUID, index: int
) -> bytes:
    m = db.get(ChatMessage, mid)
    if m is None or m.tenant_id != tenant_id or not 0 <= index < len(m.images):
        raise NotFound("图片不存在")
    get_session(db, tenant_id, student_id, m.session_id)
    return storage.get(m.images[index])


# —— 发消息 ——


async def _classify(ctx: CallContext, text: str) -> safety.SafetyResult:
    keyword = safety.keyword_check(text)
    if not text.strip():
        return safety.combine(keyword, None)
    try:
        result = await get_gateway().chat(
            safety.SKILL,
            safety.build_messages(text),
            ctx=ctx,
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        data = parse_json(result.text)
    except AppError:
        log.warning("安全分类调用失败，只按关键词判断")
        data = None
    return safety.combine(keyword, data)


async def _no_leak(
    ctx: CallContext, question: dict[str, Any] | None, msgs: list, reply: str
) -> tuple[str, bool]:
    """作业提示模式：检查回复有没有直接给答案，有就改写一次，还有就换成通用提示。返回（回复，是否改写过）。"""

    async def leaked(text: str) -> bool:
        try:
            r = await get_gateway().chat(
                tutor.LEAK_SKILL,
                tutor.leak_messages(question, text),
                ctx=ctx,
                temperature=0,
                max_tokens=50,
                response_format={"type": "json_object"},
            )
            return bool(parse_json(r.text).get("leak"))
        except AppError:
            return False  # 检查不了时不拦：系统提示词已经要求不给答案

    if not await leaked(reply):
        return reply, False
    retry = [*msgs, {"role": "assistant", "content": reply}, {"role": "user", "content": tutor.REWRITE_HINT}]
    rewritten = (await get_gateway().chat(tutor.SKILL, retry, ctx=ctx, temperature=0.3, max_tokens=800)).text
    if await leaked(rewritten):
        return tutor.LEAK_FALLBACK, True
    return rewritten, True


def _save_reply(
    tenant_id: uuid.UUID, session_id: uuid.UUID, content: str, flag: str | None, title: str | None
) -> str:
    with session_scope(tenant_id=tenant_id) as db:
        m = ChatMessage(
            tenant_id=tenant_id, session_id=session_id, role="assistant", content=content, flag=flag
        )
        db.add(m)
        s = db.get(ChatSession, session_id)
        if s is not None:
            s.updated_at = datetime.now(UTC)
            if title and s.title == "新的提问":
                s.title = title[:100]
        db.flush()
        return str(m.id)


async def send(
    tenant_id: uuid.UUID, student_id: uuid.UUID, session_id: uuid.UUID, body: MessageIn
) -> AsyncIterator[Event]:
    """处理一条学生消息，按事件返回：notice（危机提示）、delta（回复片段）、done、error。"""
    if not body.text.strip() and not body.images and not body.style:
        raise AppError("请输入问题或者拍一张题目的照片")
    prefix = _image_prefix(tenant_id, student_id)
    if any(not k.startswith(prefix) for k in body.images):
        raise AppError("图片不存在，请重新上传")
    await anyio.to_thread.run_sync(quota.start_tutor_message, tenant_id, student_id)
    ctx = CallContext(tenant_id=tenant_id, user_id=student_id)

    def prepare() -> tuple[ChatSession, list[ChatMessage], User]:
        with session_scope(tenant_id=tenant_id) as db:
            s = get_session(db, tenant_id, student_id, session_id)
            history = messages(db, s.id, HISTORY)
            db.add(
                ChatMessage(
                    tenant_id=tenant_id,
                    session_id=s.id,
                    role="user",
                    content=body.text.strip(),
                    images=body.images,
                    style=body.style,
                )
            )
            student = db.get(User, student_id)
            assert student is not None
            db.flush()  # 先写入学生的消息，再把对象从会话里拿出来给后面用
            db.expunge_all()
            return s, history, student

    s, history, student = await anyio.to_thread.run_sync(prepare)
    title = body.text.strip()[:30] or ("拍照提问" if body.images else "继续提问")
    return _respond(ctx, s, history, student, body, title)


async def _respond(
    ctx: CallContext, s: ChatSession, history: list[ChatMessage], student: User, body: MessageIn, title: str
) -> AsyncIterator[Event]:
    assert ctx.tenant_id is not None
    tenant_id = ctx.tenant_id
    try:
        result = await _classify(ctx, body.text)
        if result.crisis != "none":

            def alert() -> str:
                with session_scope(tenant_id=tenant_id) as db:
                    safety_service.log_moderation(db, tenant_id, student.id, "tutor_input", result, body.text)
                    safety_service.raise_alert(db, tenant_id, student, s.id, result, body.text)
                return _save_reply(tenant_id, s.id, reply, "crisis", "需要关心")

            reply = safety.crisis_reply(get_settings().crisis_hotlines)
            mid = await anyio.to_thread.run_sync(alert)
            yield "notice", {"kind": "crisis", "hotlines": get_settings().crisis_hotlines}
            yield "delta", {"text": reply}
            yield "done", {"id": mid, "flag": "crisis"}
            return
        if result.category in ("chat", "unsafe"):
            reply = safety.OFF_TOPIC_REPLY if result.category == "chat" else safety.UNSAFE_REPLY

            def redirect() -> str:
                with session_scope(tenant_id=tenant_id) as db:
                    safety_service.log_moderation(db, tenant_id, student.id, "tutor_input", result, body.text)
                return _save_reply(tenant_id, s.id, reply, result.category, title)

            mid = await anyio.to_thread.run_sync(redirect)
            yield "delta", {"text": reply}
            yield "done", {"id": mid, "flag": result.category}
            return

        images = [storage.get(k) for k in body.images]
        question = (s.context or {}).get("question")
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": tutor.system_prompt(s.mode, s.subject, question)}
        ]
        msgs += [{"role": m.role, "content": m.content} for m in history if m.content]
        msgs.append({"role": "user", "content": tutor.user_content(body.text, body.style, images)})
        skill = tutor.VISION_SKILL if images else tutor.SKILL

        flag = None
        if s.mode == "homework":
            reply = (await get_gateway().chat(skill, msgs, ctx=ctx, temperature=0.5, max_tokens=800)).text
            reply, rewritten = await _no_leak(ctx, question, msgs, reply)
            flag = "leak" if rewritten else None
            yield "delta", {"text": reply}
        else:
            parts = []
            async for delta in get_gateway().stream(skill, msgs, ctx=ctx, temperature=0.5, max_tokens=1500):
                parts.append(delta)
                yield "delta", {"text": delta}
            reply = "".join(parts)
        mid = await anyio.to_thread.run_sync(_save_reply, tenant_id, s.id, reply, flag, title)
        yield "done", {"id": mid, "flag": flag}
    except Exception as exc:
        message = exc.message if isinstance(exc, AppError) else "AI 老师暂时开小差了，请稍后再问"
        log.exception("问一问回复失败：session=%s", s.id)
        yield "error", {"message": message}
