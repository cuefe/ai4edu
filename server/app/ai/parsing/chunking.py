"""把解析结果切成检索用的片段。

- 一级标题处强制断开；更低级的标题只更新"所在标题"，内容可以和前后合并，避免 PPT 每页一个碎片。
- 片段攒到 TARGET 字左右就断开；单个超长段落按句子切，相邻两块重叠一小段，避免把一句话切断在两处。
- 每个片段记下所在标题和起止页，检索结果和引用里要用。
"""

import re
from dataclasses import dataclass, field

from app.ai.parsing.base import Parsed

TARGET = 600
MAX_LEN = 900
OVERLAP = 80
_SENTENCE = re.compile(r"(?<=[。！？；!?;\n])")


@dataclass
class Chunk:
    text: str
    heading: str  # 所在标题路径，如"第一章 有理数 › 1.2 有理数"
    page_start: int | None
    page_end: int | None

    def embedding_text(self) -> str:
        return f"{self.heading}\n{self.text}" if self.heading else self.text


@dataclass
class _Buffer:
    parts: list[str] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)
    heading: str = ""
    size: int = 0
    has_body: bool = False

    def add(self, text: str, page: int | None, heading: str, *, body: bool) -> None:
        if not self.parts:
            self.heading = heading
        self.parts.append(text)
        if page is not None:
            self.pages.append(page)
        self.size += len(text)
        self.has_body = self.has_body or body


def make_chunks(parsed: Parsed) -> list[Chunk]:
    chunks: list[Chunk] = []
    path: list[tuple[int, str]] = []  # (级别, 标题)
    buf = _Buffer()

    def flush() -> None:
        nonlocal buf
        if buf.has_body:  # 只有标题、没有正文的不算片段
            chunks.append(
                Chunk(
                    text="\n\n".join(buf.parts).strip(),
                    heading=buf.heading,
                    page_start=min(buf.pages) if buf.pages else None,
                    page_end=max(buf.pages) if buf.pages else None,
                )
            )
        buf = _Buffer()

    for page in parsed.pages:
        for block in page.blocks:
            text = block.text.strip()
            if not text:
                continue
            if block.level:
                # 一级标题、或者当前片段已经过半时，在标题处断开
                if block.level == 1 or buf.size >= TARGET // 2:
                    flush()
                path = [(lvl, t) for lvl, t in path if lvl < block.level] + [(block.level, text[:100])]
                if block.level > 1:  # 低级标题也写进正文，合并后的片段里能看出分界
                    buf.add(text, page.number, _join(path[:-1]), body=False)
                continue
            for piece in _split(text):
                if buf.size and buf.size + len(piece) > MAX_LEN:
                    flush()
                buf.add(piece, page.number, _join(path), body=True)
                if buf.size >= TARGET:
                    flush()
    flush()
    return chunks


def _join(path: list[tuple[int, str]]) -> str:
    return " › ".join(t for _, t in path)


def _split(text: str) -> list[str]:
    """按句子切；下一块以上一块的最后一句开头（不超过 OVERLAP 字），不从句子或公式中间截断。"""
    if len(text) <= MAX_LEN:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    for sentence in _SENTENCE.split(text):
        if current and sum(map(len, current)) + len(sentence) > TARGET:
            pieces.append("".join(current))
            current = [current[-1]] if len(current[-1]) <= OVERLAP else []
        current.append(sentence)
        joined = "".join(current)
        while len(joined) > MAX_LEN:  # 没有标点的超长文字，只能硬切
            pieces.append(joined[:MAX_LEN])
            joined = joined[MAX_LEN:]
        current = [joined] if joined else []
    if "".join(current).strip():
        pieces.append("".join(current))
    return pieces
