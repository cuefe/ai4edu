"""背诵卡片：从讲义、教案或粘贴的材料里抽取，老师修改后保存。卡片组只有创建的老师能看到。"""

import uuid

import anyio
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import CallContext, get_gateway
from app.ai.skills import recite_cards
from app.ai.skills.common import parse_json
from app.core.db import session_scope
from app.core.errors import AppError, NotFound
from app.modules.content import service as content
from app.modules.content.markdown import doc_to_markdown
from app.modules.recite.models import ReciteCard, ReciteDeck
from app.modules.recite.schemas import CardOut, DeckBrief, DeckOut

MAX_MATERIAL = 20000  # 送给模型的材料最多多少字


def list_decks(db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> list[DeckBrief]:
    decks = db.scalars(
        select(ReciteDeck)
        .where(ReciteDeck.tenant_id == tenant_id, ReciteDeck.owner_id == owner_id)
        .order_by(ReciteDeck.updated_at.desc())
    )
    return [DeckBrief.model_validate(d, from_attributes=True) for d in decks]


def get_deck(db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID, deck_id: uuid.UUID) -> ReciteDeck:
    deck = db.scalar(
        select(ReciteDeck).where(
            ReciteDeck.id == deck_id, ReciteDeck.tenant_id == tenant_id, ReciteDeck.owner_id == owner_id
        )
    )
    if deck is None:
        raise NotFound("卡片组不存在")
    return deck


def to_out(db: Session, deck: ReciteDeck) -> DeckOut:
    cards = db.scalars(select(ReciteCard).where(ReciteCard.deck_id == deck.id).order_by(ReciteCard.seq))
    return DeckOut(
        **DeckBrief.model_validate(deck, from_attributes=True).model_dump(),
        cards=[CardOut.model_validate(c, from_attributes=True) for c in cards],
        warnings=deck.params.get("warnings", []),
    )


def replace_cards(db: Session, deck: ReciteDeck, cards: list[recite_cards.Card]) -> None:
    db.execute(delete(ReciteCard).where(ReciteCard.deck_id == deck.id))
    db.add_all(
        ReciteCard(tenant_id=deck.tenant_id, deck_id=deck.id, seq=i, kind=c.kind, front=c.front, back=c.back)
        for i, c in enumerate(cards)
    )
    deck.card_count = len(cards)


def _material(tenant_id: uuid.UUID, owner_id: uuid.UUID, p: recite_cards.ReciteIn) -> str:
    if p.doc_id:
        with session_scope(tenant_id=tenant_id) as db:
            doc = content.get_ready_document(db, tenant_id, owner_id, p.doc_id)
            return doc_to_markdown(doc.content or {})
    return p.text or ""


async def generate(ctx: CallContext, p: recite_cards.ReciteIn) -> uuid.UUID:
    """抽取背诵点并保存为新的卡片组，返回卡片组 ID。模型一次输出全部卡片，几十秒内返回。"""
    assert ctx.tenant_id is not None and ctx.user_id is not None
    tenant_id, owner_id = ctx.tenant_id, ctx.user_id
    material = (await anyio.to_thread.run_sync(_material, tenant_id, owner_id, p)).strip()
    if not material:
        raise AppError("请选择一份讲义或教案，或者粘贴要整理的内容")
    warnings = []
    if len(material) > MAX_MATERIAL:
        material = material[:MAX_MATERIAL]
        warnings.append(f"材料太长，只整理了前 {MAX_MATERIAL} 字")

    result = await get_gateway().chat(
        recite_cards.SKILL,
        recite_cards.build_messages(p, material),
        ctx=ctx,
        temperature=0.3,
        max_tokens=6000,
        response_format={"type": "json_object"},
    )
    cards, dropped = recite_cards.parse_cards(parse_json(result.text), p.max_cards)
    if not cards:
        raise AppError("没有从材料里找到需要背诵的内容，可以换一份材料或补充要求后重试")
    if dropped:
        warnings.append(f"有 {dropped} 张卡片格式不对或重复，已经去掉")

    def save() -> uuid.UUID:
        with session_scope(tenant_id=tenant_id) as db:
            deck = ReciteDeck(
                tenant_id=tenant_id,
                owner_id=owner_id,
                title=p.title,
                subject=p.subject,
                grade=p.grade,
                source_doc_id=p.doc_id,
                params={
                    **p.model_dump(mode="json", exclude={"text"}),
                    "prompt_version": recite_cards.PROMPT_VERSION,
                    "model": f"{result.provider}/{result.model}",
                    "warnings": warnings,
                },
                generated=[c.model_dump() for c in cards],
            )
            db.add(deck)
            db.flush()
            replace_cards(db, deck, cards)
            return deck.id

    return await anyio.to_thread.run_sync(save)
