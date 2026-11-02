"""TipTap JSON → Word（.docx）。

版式按国内教案的常见习惯：正文宋体小四，标题黑体。公式转成 Word 原生公式，导出后还能在 Word 里编辑；
个别转换失败的公式保留 LaTeX 原文。
"""

import logging
from io import BytesIO
from typing import Any

import docx
import latex2mathml.converter
import mathml2omml
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.table import _Cell
from docx.text.paragraph import Paragraph

log = logging.getLogger(__name__)

Node = dict[str, Any]

_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_INDENT = Cm(0.74)  # 两个汉字宽
_HEADINGS = {1: ("黑体", 16), 2: ("黑体", 14), 3: ("黑体", 12), 4: ("宋体", 12)}


def doc_to_docx(title: str, doc: Node, *, author: str = "") -> bytes:
    writer = _Writer()
    writer.document.core_properties.title = title
    writer.document.core_properties.author = author
    for node in doc.get("content", []):
        writer.block(node, writer.document)
    buf = BytesIO()
    writer.document.save(buf)
    return buf.getvalue()


def _set_fonts(element: Any, east_asia: str, latin: str = "Times New Roman") -> None:
    """同时设置中文和西文字体。默认模板的标题样式用的是主题字体，要先去掉才生效。"""
    rfonts = element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), east_asia)


def _omml(latex: str, *, block: bool) -> Any | None:
    try:
        omml = mathml2omml.convert(latex2mathml.converter.convert(latex))
        el = parse_xml(omml.replace("<m:oMath", f'<m:oMath xmlns:m="{_M_NS}" xmlns:w="{_W_NS}"', 1))
    except Exception:
        log.warning("公式转换失败，保留 LaTeX 原文：%s", latex)
        return None
    if not block:
        return el
    para = parse_xml(f'<m:oMathPara xmlns:m="{_M_NS}"/>')
    para.append(el)
    return para


class _Writer:
    def __init__(self) -> None:
        self.document = docx.Document()
        section = self.document.sections[0]
        section.left_margin = section.right_margin = Cm(2.5)
        section.top_margin = section.bottom_margin = Cm(2.5)

        styles = self.document.styles
        normal = styles["Normal"]
        normal.font.size = Pt(12)
        _set_fonts(normal.element, "宋体")
        normal.paragraph_format.space_after = Pt(4)
        normal.paragraph_format.line_spacing = 1.25
        for level, (font, size) in _HEADINGS.items():
            style = styles[f"Heading {level}"]
            _set_fonts(style.element, font)
            style.font.size = Pt(size)
            style.font.bold = True
            style.font.italic = False
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.paragraph_format.space_before = Pt(12 if level <= 2 else 8)
            style.paragraph_format.space_after = Pt(6)
        styles["Heading 1"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # —— 块级节点 ——

    def block(self, node: Node, container: Any, *, indent: int = 0, bold: bool = False) -> None:
        kind = node["type"]
        content = node.get("content", [])
        if kind == "paragraph":
            p = self._paragraph(container, indent)
            self.inline(p, content, bold=bold)
        elif kind == "heading":
            level = min(int(node.get("attrs", {}).get("level", 1)), 4)
            p = container.add_paragraph(style=f"Heading {level}")
            self.inline(p, content)
        elif kind in ("bulletList", "orderedList"):
            self._list(node, container, indent)
        elif kind == "blockquote":
            for child in content:
                self.block(child, container, indent=indent + 1)
        elif kind == "codeBlock":
            p = self._paragraph(container, indent)
            lines = "".join(c.get("text", "") for c in content).split("\n")
            for i, line in enumerate(lines):
                run = p.add_run(line)
                _set_fonts(run._r, "宋体", "Consolas")
                if i < len(lines) - 1:
                    run.add_break()
        elif kind == "table":
            self._table(node, container)
        elif kind == "blockMath":
            p = self._paragraph(container, indent)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            self._math(p, node.get("attrs", {}).get("latex", ""), block=True)
        elif kind == "horizontalRule":
            self._paragraph(container, indent)
        else:  # 未知节点：尽量保留文字
            for child in content:
                self.block(child, container, indent=indent, bold=bold)

    def _paragraph(self, container: Any, indent: int) -> Paragraph:
        p = container.add_paragraph()
        if indent:
            p.paragraph_format.left_indent = _INDENT * indent
        return p

    def _list(self, node: Node, container: Any, indent: int) -> None:
        ordered = node["type"] == "orderedList"
        start = int(node.get("attrs", {}).get("start") or 1)
        for i, item in enumerate(node.get("content", [])):
            marker = f"{start + i}." if ordered else "•"
            first = True
            for child in item.get("content", []):
                if child["type"] == "paragraph":
                    p = self._paragraph(container, indent + 1)
                    if first:
                        p.paragraph_format.first_line_indent = -_INDENT
                        p.add_run(f"{marker} ")
                    self.inline(p, child.get("content", []))
                elif child["type"] in ("bulletList", "orderedList"):
                    self._list(child, container, indent + 1)
                else:
                    self.block(child, container, indent=indent + 1)
                first = False

    def _table(self, node: Node, container: Any) -> None:
        # 先算出每个单元格在网格中的位置（处理合并单元格），再建表
        occupied: set[tuple[int, int]] = set()
        placed: list[tuple[int, int, int, int, Node]] = []
        for r, row in enumerate(node.get("content", [])):
            c = 0
            for cell in row.get("content", []):
                while (r, c) in occupied:
                    c += 1
                attrs = cell.get("attrs", {})
                rs, cs = max(int(attrs.get("rowspan") or 1), 1), max(int(attrs.get("colspan") or 1), 1)
                occupied.update((r + dr, c + dc) for dr in range(rs) for dc in range(cs))
                placed.append((r, c, rs, cs, cell))
                c += cs
        if not placed:
            return
        n_rows = max(r for r, _ in occupied) + 1
        n_cols = max(c for _, c in occupied) + 1
        table = container.add_table(rows=n_rows, cols=n_cols)
        table.style = "Table Grid"
        for r, c, rs, cs, cell in placed:
            target: _Cell = table.cell(r, c)
            if rs > 1 or cs > 1:
                target = target.merge(table.cell(r + rs - 1, c + cs - 1))
            header = cell["type"] == "tableHeader"
            for child in cell.get("content", []):
                self.block(child, target, bold=header)
            # 新单元格自带一个空段落，内容都追加在它后面；有了别的段落就去掉它
            if len(target.paragraphs) > 1:
                first = target.paragraphs[0]._p
                first.getparent().remove(first)
        if isinstance(container, _Cell):
            return
        # 表格后空一行，避免和下一段贴在一起
        container.add_paragraph()

    # —— 行内节点 ——

    def inline(self, p: Paragraph, nodes: list[Node], *, bold: bool = False) -> None:
        for node in nodes:
            kind = node["type"]
            if kind == "text":
                run = p.add_run(node.get("text", ""))
                marks = {m["type"] for m in node.get("marks", [])}
                run.bold = bold or "bold" in marks or None
                if "italic" in marks:
                    run.italic = True
                if "underline" in marks or "link" in marks:
                    run.underline = True
                if "strike" in marks:
                    run.font.strike = True
                if "link" in marks:
                    run.font.color.rgb = RGBColor(0x2F, 0x6F, 0xED)
                if "code" in marks:
                    _set_fonts(run._r, "宋体", "Consolas")
            elif kind == "hardBreak":
                p.add_run().add_break()
            elif kind == "inlineMath":
                self._math(p, node.get("attrs", {}).get("latex", ""), block=False)

    def _math(self, p: Paragraph, latex: str, *, block: bool) -> None:
        if not latex:
            return
        el = _omml(latex, block=block)
        if el is None:
            p.add_run(f"${latex}$").italic = True
        else:
            p._p.append(el)
