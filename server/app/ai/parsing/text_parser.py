import re

from app.ai.parsing.base import Block, Page, Parsed, ParseError

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


def parse(data: bytes) -> Parsed:
    for encoding in ("utf-8-sig", "gb18030"):  # Windows 记事本的老文件常是 GBK
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError("文本文件的编码无法识别，请另存为 UTF-8")

    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        para = para.strip()
        if not para:
            continue
        m = _HEADING.match(para)
        if m and "\n" not in para:
            blocks.append(Block(text=m.group(2).strip(), level=len(m.group(1))))
        else:
            blocks.append(Block(text=para))
    return Parsed(pages=[Page(number=None, blocks=blocks)])
