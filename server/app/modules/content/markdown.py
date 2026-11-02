"""Markdown → TipTap（ProseMirror）JSON。

模型输出 Markdown，编辑器和 Word 导出都用 TipTap JSON。支持：标题、段落、加粗、斜体、删除线、行内代码、
链接、列表、引用、代码块、分割线、表格、LaTeX 公式（$…$ 行内，$$…$$ 独立成行）。
节点名和前端编辑器的扩展一一对应（StarterKit、Table、Mathematics）。
"""

import re
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin

Node = dict[str, Any]

MAX_HEADING_LEVEL = 4  # 编辑器只开放 1～4 级标题

_md = (
    MarkdownIt("commonmark", {"html": True})
    .enable(["table", "strikethrough"])
    .use(dollarmath_plugin, double_inline=True)
)

_BLOCKS = {
    "paragraph": "paragraph",
    "heading": "heading",
    "bullet_list": "bulletList",
    "ordered_list": "orderedList",
    "list_item": "listItem",
    "blockquote": "blockquote",
    "table": "table",
    "tr": "tableRow",
    "th": "tableHeader",
    "td": "tableCell",
}
_MARKS = {"strong": "bold", "em": "italic", "s": "strike"}
_CELLS = {"tableCell", "tableHeader"}
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")


def markdown_to_doc(text: str) -> Node:
    root: Node = {"type": "doc", "content": []}
    stack = [root]
    for tok in _md.parse(text):
        kind = tok.type
        if kind.endswith("_open") and kind[:-5] in _BLOCKS:
            node = _open_block(tok)
            _append(stack[-1], node)
            stack.append(node)
        elif kind.endswith("_close") and kind[:-6] in _BLOCKS:
            stack.pop()
        elif kind == "inline":
            parent = stack[-1]
            inline = _inline(tok.children or [])
            if parent["type"] in _CELLS:
                _append(parent, _paragraph(inline))
            else:
                for node in inline:
                    _append(parent, node)
        elif kind in ("fence", "code_block"):
            code = tok.content.rstrip("\n")
            _append(stack[-1], {"type": "codeBlock", "content": [_text(code)] if code else []})
        elif kind == "hr":
            _append(stack[-1], {"type": "horizontalRule"})
        elif kind in ("math_block", "math_block_label"):
            _append(stack[-1], {"type": "blockMath", "attrs": {"latex": tok.content.strip()}})
        elif kind == "html_block":
            plain = _TAG.sub("", _BR.sub("\n", tok.content)).strip()
            if plain:
                _append(stack[-1], _paragraph([_text(plain)]))
    _normalize(root)
    if not root.get("content"):
        root["content"] = [{"type": "paragraph"}]
    return root


def _open_block(tok: Token) -> Node:
    kind = _BLOCKS[tok.type[:-5]]
    if kind == "heading":
        return {"type": kind, "attrs": {"level": min(int(tok.tag[1]), MAX_HEADING_LEVEL)}}
    if kind == "orderedList":
        return {"type": kind, "attrs": {"start": int(tok.attrGet("start") or 1)}}
    if kind in _CELLS:
        return {"type": kind, "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None}}
    return {"type": kind}


def _inline(children: list[Token]) -> list[Node]:
    out: list[Node] = []
    marks: list[Node] = []
    for c in children:
        kind = c.type
        if kind == "text":
            _push_text(out, c.content, marks)
        elif kind == "code_inline":
            _push_text(out, c.content, [{"type": "code"}])  # code 标记不能和其他标记叠加
        elif kind in ("softbreak", "hardbreak"):
            # 中文没有"软换行变空格"的习惯，模型逐行写的内容按原样换行
            out.append({"type": "hardBreak"})
        elif kind.endswith("_open") and kind[:-5] in _MARKS:
            marks.append({"type": _MARKS[kind[:-5]]})
        elif kind.endswith("_close") and kind[:-6] in _MARKS:
            _pop_mark(marks, _MARKS[kind[:-6]])
        elif kind == "link_open":
            marks.append({"type": "link", "attrs": {"href": c.attrGet("href") or ""}})
        elif kind == "link_close":
            _pop_mark(marks, "link")
        elif kind in ("math_inline", "math_inline_double"):
            out.append({"type": "inlineMath", "attrs": {"latex": c.content.strip()}})
        elif kind == "image":
            _push_text(out, c.content, marks)  # 先保留图片说明文字，图片上传做好后再支持
        elif kind == "html_inline" and _BR.fullmatch(c.content.strip()):  # 其他 HTML 标签直接丢掉
            out.append({"type": "hardBreak"})
    while out and out[0]["type"] == "hardBreak":
        out.pop(0)
    while out and out[-1]["type"] == "hardBreak":
        out.pop()
    return out


def _push_text(out: list[Node], text: str, marks: list[Node]) -> None:
    if text:
        out.append(_text(text, marks))


def _text(text: str, marks: list[Node] | None = None) -> Node:
    node: Node = {"type": "text", "text": text}
    if marks:
        node["marks"] = [dict(m) for m in marks]
    return node


def _pop_mark(marks: list[Node], kind: str) -> None:
    for i in range(len(marks) - 1, -1, -1):
        if marks[i]["type"] == kind:
            del marks[i]
            return


def _paragraph(inline: list[Node]) -> Node:
    return {"type": "paragraph", "content": inline} if inline else {"type": "paragraph"}


def _append(parent: Node, node: Node) -> None:
    parent.setdefault("content", []).append(node)


def doc_to_markdown(doc: Node) -> str:
    """TipTap JSON → Markdown，给模型读老师改过的文档用（如从讲义抽背诵点）。只求内容完整，不求格式还原。"""
    return "\n\n".join(b for b in (_block_md(n) for n in doc.get("content", [])) if b).strip()


def _block_md(node: Node, indent: str = "") -> str:
    kind = node.get("type")
    children = node.get("content", [])
    if kind == "heading":
        return "#" * int(node.get("attrs", {}).get("level", 2)) + " " + _inline_md(children)
    if kind == "paragraph":
        return _inline_md(children)
    if kind in ("bulletList", "orderedList"):
        start = int(node.get("attrs", {}).get("start") or 1)
        lines = []
        for i, item in enumerate(children):
            marker = f"{start + i}." if kind == "orderedList" else "-"
            body = [_block_md(c, indent + "  ") for c in item.get("content", [])]
            lines.append(f"{indent}{marker} " + f"\n{indent}  ".join(b for b in body if b))
        return "\n".join(lines)
    if kind == "blockquote":
        return "\n".join(f"> {line}" for b in children for line in _block_md(b).splitlines())
    if kind == "table":
        rows = [
            "| " + " | ".join(_block_md(c).replace("\n", " ") for c in row.get("content", [])) + " |"
            for row in children
        ]
        return "\n".join(rows)
    if kind == "tableHeader" or kind == "tableCell":
        return " ".join(_block_md(c) for c in children)
    if kind == "codeBlock":
        return "```\n" + _inline_md(children) + "\n```"
    if kind == "blockMath":
        return f"$${node.get('attrs', {}).get('latex', '')}$$"
    return ""


def _inline_md(nodes: list[Node]) -> str:
    out = []
    for n in nodes:
        kind = n.get("type")
        if kind == "text":
            text = n.get("text", "")
            if any(m.get("type") == "bold" for m in n.get("marks", [])):
                text = f"**{text}**"
            out.append(text)
        elif kind == "inlineMath":
            out.append(f"${n.get('attrs', {}).get('latex', '')}$")
        elif kind == "hardBreak":
            out.append("\n")
    return "".join(out)


def _normalize(node: Node) -> None:
    """补齐编辑器 schema 要求的结构：列表项以段落开头，表格单元格、引用不能为空。"""
    children = node.get("content")
    if children is not None and not children:
        del node["content"]
    for child in node.get("content", []):
        _normalize(child)
    kind = node["type"]
    content = node.get("content", [])
    if kind == "listItem" and (not content or content[0]["type"] != "paragraph"):
        node["content"] = [{"type": "paragraph"}, *content]
    elif kind in (*_CELLS, "blockquote") and not content:
        node["content"] = [{"type": "paragraph"}]
