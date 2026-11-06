"""AI 出题：按知识点、题型、难度出题，附答案和解析，输出 JSON。出完自动走 answer_check 校验。"""

from app.ai.skills.question_gen.checks import blanks_out_of_math, choice_letters, normalize, truth_value
from app.ai.skills.question_gen.prompt import PROMPT_VERSION, SKILL, build_messages, parse_questions
from app.ai.skills.question_gen.schema import CHOICE_TYPES, Difficulty, QType, QuestionData, QuestionGenIn

__all__ = [
    "CHOICE_TYPES",
    "PROMPT_VERSION",
    "SKILL",
    "Difficulty",
    "QType",
    "QuestionData",
    "QuestionGenIn",
    "blanks_out_of_math",
    "build_messages",
    "choice_letters",
    "normalize",
    "parse_questions",
    "truth_value",
]
