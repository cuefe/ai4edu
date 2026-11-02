"""学生消息的安全分类：是不是学习相关、有没有危机信号（自伤、轻生、被欺凌等）。

关键词和模型两路一起判断，取更严重的结果：危机识别宁可多报，不能漏报。
关键词命中时即使模型说没事也按低风险处理；模型调用失败时只看关键词。
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.ai.gateway.gateway import Messages

SKILL = "safety_classify"
PROMPT_VERSION = "2026-11-03.1"

Category = Literal["study", "chat", "unsafe"]
Crisis = Literal["none", "low", "high"]

# 明确的自伤、轻生表达：命中直接按高风险
_HIGH = [
    "自杀", "轻生", "不想活", "活不下去", "想去死", "我想死", "结束生命", "结束自己", "割腕", "跳楼", "跳河",
    "吃安眠药", "上吊", "自残", "伤害自己", "了结自己", "不如死了", "死了算了", "遗书",
]  # fmt: skip
# 需要关注的消极表达、被伤害的信号：命中至少按低风险
# 学生口头常说的“崩溃”“好想哭”不放进来，交给模型结合上下文判断，免得预警太多老师反而不看
_LOW = [
    "活着没意思", "活着好累", "活着没有意义", "没人在乎我", "消失就好了", "想消失", "撑不下去",
    "被欺负", "被霸凌", "被打", "被孤立", "没有朋友", "讨厌自己", "恨自己", "绝望",
]  # fmt: skip
# 学习里常见的夸张说法，不算危机
_BENIGN = re.compile(r"(难|累|笑|热|冷|饿|困|烦|吓|气|急)死|死记硬背|死循环|死胡同|死角|生死")

_SYSTEM = """你是中小学 AI 学习助手的安全审核员。判断一条学生发来的消息，输出 JSON。

category（话题）：
- study：和学习有关，包括学科问题、作业、考试、学习方法、学习压力和情绪
- chat：和学习无关的闲聊，如游戏、明星、八卦、恋爱、购物
- unsafe：不适合未成年人的内容，如色情、暴力、赌博、违法、辱骂他人

crisis（危机信号，宁可多报，不能漏报）：
- high：明确表达想自杀、自伤、不想活，或者正在遭受严重伤害（被打、被虐待、被性侵）
- low：情绪很低落、绝望、觉得活着没意思、被欺负、被孤立，需要大人关注
- none：没有以上信号。“这题难死了”“累死了”这类口头夸张不算

只输出 JSON：{"category": "study|chat|unsafe", "crisis": "none|low|high", "reason": "一句话理由"}"""


@dataclass
class SafetyResult:
    category: Category
    crisis: Crisis
    reason: str
    by_keyword: bool = False


def keyword_check(text: str) -> Crisis:
    s = re.sub(r"\s+", "", _BENIGN.sub("", text))
    if any(k in s for k in _HIGH):
        return "high"
    if any(k in s for k in _LOW):
        return "low"
    return "none"


def build_messages(text: str) -> Messages:
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text[:2000]}]


_LEVEL = {"none": 0, "low": 1, "high": 2}


def combine(keyword: Crisis, data: dict[str, Any] | None) -> SafetyResult:
    """合并关键词和模型的结论，危机等级取更高的。"""
    category: Category = "study"
    crisis: Crisis = "none"
    reason = ""
    if data:
        if data.get("category") in ("study", "chat", "unsafe"):
            category = data["category"]
        if data.get("crisis") in _LEVEL:
            crisis = data["crisis"]
        reason = str(data.get("reason") or "")[:200]
    by_keyword = _LEVEL[keyword] > _LEVEL[crisis]
    if by_keyword:
        crisis = keyword
        reason = reason or "命中危机关键词"
    if crisis != "none":
        category = "study"  # 有危机信号时不按闲聊拉回，而是给出关心和求助方式
    return SafetyResult(category=category, crisis=crisis, reason=reason, by_keyword=by_keyword)


def crisis_reply(hotlines: list[str]) -> str:
    """危机回复用固定话术和配置里的号码，不让模型自己编。"""
    lines = "\n".join(f"- {h}" for h in hotlines)
    return (
        "我听到了，你现在一定很难受。愿意说出来，已经很勇敢了。你不是一个人，身边有人愿意帮你。\n\n"
        "请现在就找一位你信任的大人聊一聊——爸爸妈妈、班主任，或者学校的心理老师。"
        "也可以打下面的电话，会有专业的人认真听你说：\n\n"
        f"{lines}\n\n"
        "老师也会来关心你。你愿意的话，可以继续跟我说说发生了什么。"
    )


OFF_TOPIC_REPLY = (
    "我是你的学习小助手，这个话题我们先放一放。学习上有不懂的随时问我，比如哪道题没思路、哪个知识点没弄明白。"
)
UNSAFE_REPLY = "这个话题我不能聊。我们说说学习吧：有哪道题或者哪个知识点需要我帮忙吗？"
