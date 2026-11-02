"""Word（.docx）：按正文顺序取段落和表格；标题样式转成标题；Word 公式转成线性文本。

暂不识别 Word 里插入的图片（包括 MathType 公式图片），以后按需要加 OCR。
"""

from io import BytesIO

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ai.parsing.base import Block, Page, Parsed

_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def parse(data: bytes) -> Parsed:
    document = docx.Document(BytesIO(data))
    blocks: list[Block] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            text = _paragraph_text(child).strip()
            if text:
                blocks.append(Block(text=text, level=_heading_level(para)))
        elif child.tag == qn("w:tbl"):
            table = _table_markdown(Table(child, document))
            if table:
                blocks.append(Block(text=table))
    return Parsed(pages=[Page(number=None, blocks=blocks)])


def _heading_level(para: Paragraph) -> int:
    name = (para.style.name if para.style is not None else "") or ""
    for prefix in ("Heading ", "标题 ", "标题"):
        if name.startswith(prefix) and name[len(prefix) :].strip().isdigit():
            return min(int(name[len(prefix) :]), 6)
    return 1 if name == "Title" else 0


def _paragraph_text(p) -> str:
    """段落文字，包括其中的公式。python-docx 的 paragraph.text 会漏掉公式。"""
    parts = []
    for el in p.iter():
        if el.tag == qn("w:t") and not _inside_math(el):
            parts.append(el.text or "")
        elif el.tag == qn("w:tab"):
            parts.append("\t")
        elif el.tag in (qn("w:br"), qn("w:cr")):
            parts.append("\n")
        elif el.tag == f"{_M}oMath" and not _inside_math(el):
            parts.append(_math_text(el))
    return "".join(parts)


def _inside_math(el) -> bool:
    parent = el.getparent()
    while parent is not None:
        if parent.tag == f"{_M}oMath":
            return True
        parent = parent.getparent()
    return False


def _math_text(el) -> str:
    """Word 公式（OMML）转成线性文本，如分数写成 (a)/(b)，够检索用。"""
    tag = el.tag.removeprefix(_M)

    def part(name: str) -> str:
        child = el.find(f"{_M}{name}")
        return _math_text(child) if child is not None else ""

    if tag == "t":
        return el.text or ""
    if tag == "f":
        return f"({part('num')})/({part('den')})"
    if tag == "sSup":
        return f"{part('e')}^{part('sup')}"
    if tag == "sSub":
        return f"{part('e')}_{part('sub')}"
    if tag == "rad":
        return f"√({part('e')})"
    if tag == "d":
        props = el.find(f"{_M}dPr")
        beg = props.find(f"{_M}begChr") if props is not None else None
        end = props.find(f"{_M}endChr") if props is not None else None
        b = beg.get(f"{_M}val") if beg is not None else "("
        e = end.get(f"{_M}val") if end is not None else ")"
        inner = ",".join(_math_text(c) for c in el.findall(f"{_M}e"))
        return f"{b}{inner}{e}"
    if tag.endswith("Pr"):
        return ""
    return "".join(_math_text(c) for c in el)


def _table_markdown(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells, last = [], None
        for cell in row.cells:
            if cell._tc is last:  # 横向合并的单元格会重复出现
                continue
            last = cell._tc
            cells.append(" ".join(_paragraph_text(p._p).strip() for p in cell.paragraphs).replace("|", "｜"))
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    width = rows[0].count("|") - 1
    return "\n".join([rows[0], "|" + " --- |" * width, *rows[1:]])
