from app.modules.content.markdown import markdown_to_doc


def _text(node) -> str:
    if node["type"] == "text":
        return node["text"]
    if node["type"] == "inlineMath":
        return f"${node['attrs']['latex']}$"
    return "".join(_text(c) for c in node.get("content", []))


def test_headings_paragraphs_and_marks():
    doc = markdown_to_doc("# 有理数\n\n## 一、教材分析\n\n本节是**重点**，也是*难点*，~~删掉~~，`code`。\n")
    h1, h2, p = doc["content"]
    assert h1 == {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "有理数"}]}
    assert h2["attrs"]["level"] == 2
    marks = {n["text"]: [m["type"] for m in n.get("marks", [])] for n in p["content"]}
    assert marks == {
        "本节是": [],
        "重点": ["bold"],
        "，也是": [],
        "难点": ["italic"],
        "，": [],
        "删掉": ["strike"],
        "code": ["code"],
        "。": [],
    }


def test_soft_line_breaks_are_kept():
    doc = markdown_to_doc("**教师活动**：提问\n**学生活动**：回答\n")
    para = doc["content"][0]
    assert [n["type"] for n in para["content"]] == ["text", "text", "hardBreak", "text", "text"]


def test_nested_lists():
    doc = markdown_to_doc("1. 第一\n   - 甲\n   - 乙\n2. 第二\n\n3) 不同分隔符\n")
    ol = doc["content"][0]
    assert ol["type"] == "orderedList" and ol["attrs"]["start"] == 1
    first = ol["content"][0]
    assert [c["type"] for c in first["content"]] == ["paragraph", "bulletList"]
    assert _text(first["content"][1]) == "甲乙"
    assert doc["content"][1]["attrs"]["start"] == 3


def test_table_cells_wrap_paragraphs():
    doc = markdown_to_doc("| 环节 | 时长 |\n| --- | --- |\n| 导入 | 5 分钟 |\n| 新授 |  |\n")
    table = doc["content"][0]
    header, row, empty_row = table["content"]
    assert [c["type"] for c in header["content"]] == ["tableHeader", "tableHeader"]
    cell = row["content"][0]
    assert cell["attrs"] == {"colspan": 1, "rowspan": 1, "colwidth": None}
    assert cell["content"][0]["type"] == "paragraph" and _text(cell) == "导入"
    # 空单元格也要有一个段落，编辑器才能放光标
    assert empty_row["content"][1]["content"] == [{"type": "paragraph"}]


def test_math():
    doc = markdown_to_doc("解方程 $3x+5=20$，得\n\n$$\nx = \\frac{15}{3} = 5\n$$\n")
    para, block = doc["content"]
    assert para["content"][1] == {"type": "inlineMath", "attrs": {"latex": "3x+5=20"}}
    assert block == {"type": "blockMath", "attrs": {"latex": "x = \\frac{15}{3} = 5"}}


def test_html_and_edge_cases():
    doc = markdown_to_doc(
        "| a |\n| --- |\n| 第一行<br>第二行 |\n\n<div>说明</div>\n\n---\n\n```\nx = 1\n```\n"
    )
    table, html, hr, code = doc["content"]
    cell_para = table["content"][1]["content"][0]["content"][0]
    assert [n["type"] for n in cell_para["content"]] == ["text", "hardBreak", "text"]
    assert _text(html) == "说明"
    assert hr == {"type": "horizontalRule"}
    assert code == {"type": "codeBlock", "content": [{"type": "text", "text": "x = 1"}]}


def test_empty_and_deep_headings():
    assert markdown_to_doc("") == {"type": "doc", "content": [{"type": "paragraph"}]}
    assert markdown_to_doc("###### 很深")["content"][0]["attrs"]["level"] == 4
