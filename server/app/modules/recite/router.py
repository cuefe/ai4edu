import uuid

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import CallContext
from app.ai.skills.recite_cards import ReciteIn
from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.modules.iam.models import Role, User
from app.modules.iam.schemas import OkOut
from app.modules.ops.service import audit
from app.modules.recite import service
from app.modules.recite.schemas import DeckBrief, DeckOut, DeckUpdate

router = APIRouter(prefix="/teacher/recite-decks", tags=["背诵卡片"])

Teacher = Depends(require_roles(Role.TEACHER))


@router.get("", response_model=list[DeckBrief], summary="我的背诵卡片组")
def list_decks(user: User = Teacher, db: Session = Depends(get_db)):
    return service.list_decks(db, tenant_of(user), user.id)


@router.post("/generate", response_model=DeckOut, summary="AI 抽取背诵点", description="大约需要半分钟")
async def generate(body: ReciteIn, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    deck_id = await service.generate(CallContext(tenant_id=tenant_id, user_id=user.id), body)
    return await run_in_threadpool(
        lambda: service.to_out(db, service.get_deck(db, tenant_id, user.id, deck_id))
    )


@router.get("/{deck_id}", response_model=DeckOut)
def get_deck(deck_id: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    return service.to_out(db, service.get_deck(db, tenant_of(user), user.id, deck_id))


@router.put("/{deck_id}", response_model=DeckOut, summary="保存卡片组（整组替换）")
def update_deck(deck_id: uuid.UUID, body: DeckUpdate, user: User = Teacher, db: Session = Depends(get_db)):
    deck = service.get_deck(db, tenant_of(user), user.id, deck_id)
    deck.title = body.title
    service.replace_cards(db, deck, body.cards)
    db.commit()
    return service.to_out(db, deck)


@router.delete("/{deck_id}", response_model=OkOut)
def delete_deck(deck_id: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    deck = service.get_deck(db, tenant_of(user), user.id, deck_id)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="delete_recite_deck",
        target_type="recite_deck",
        target_id=deck.id,
        title=deck.title,
    )
    db.delete(deck)
    db.commit()
    return OkOut()
