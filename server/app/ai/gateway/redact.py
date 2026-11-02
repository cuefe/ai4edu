"""发给模型前去掉明显的个人信息。

这里只处理能用规则识别的手机号、身份证号；学生姓名由调用方在组装 prompt 时用代号替换。
"""

import re
from typing import Any

_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_MOBILE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def redact_text(text: str) -> str:
    text = _ID_CARD.sub("[身份证号]", text)
    return _MOBILE.sub("[手机号]", text)


def redact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            msg = {**msg, "content": redact_text(content)}
        elif isinstance(content, list):  # 多模态消息：只处理文本部分
            msg = {
                **msg,
                "content": [
                    {**part, "text": redact_text(part["text"])} if part.get("type") == "text" else part
                    for part in content
                ],
            }
        result.append(msg)
    return result
