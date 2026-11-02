"""背诵点抽取：从讲义、教案或老师粘贴的材料里整理背诵卡片（问答卡、挖空卡），输出 JSON。"""

from app.ai.skills.recite_cards.prompt import PROMPT_VERSION, SKILL, build_messages, cloze_blanks, parse_cards
from app.ai.skills.recite_cards.schema import Card, CardKind, ReciteIn

__all__ = [
    "PROMPT_VERSION",
    "SKILL",
    "Card",
    "CardKind",
    "ReciteIn",
    "build_messages",
    "cloze_blanks",
    "parse_cards",
]
