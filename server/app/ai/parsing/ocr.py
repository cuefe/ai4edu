"""图片转文字：调用多模态 OCR 模型（技能 ocr）。"""

import base64
import re

from app.ai.gateway.gateway import AIGateway, CallContext

SKILL = "ocr"
PROMPT = (
    "识别图片中的全部文字，按阅读顺序输出。保留段落结构，表格用 Markdown 表格，"
    "数学公式用 LaTeX（行内用 $...$）。只输出识别出的文字，不要解释，不要补充图片里没有的内容。"
    "图片里没有文字时什么都不输出。"
)
_FENCE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


async def ocr_image(gateway: AIGateway, image: bytes, ctx: CallContext) -> str:
    url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": PROMPT}],
        }
    ]
    result = await gateway.chat(SKILL, messages, ctx=ctx)
    return _FENCE.sub("", result.text.strip()).strip()
