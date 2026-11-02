import json
import re
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.ai.parsing import Block, Page, Parsed, ParseError, drop_repeated_lines, make_chunks, parse_file
from app.ai.parsing.chunking import MAX_LEN
from app.modules.content.docx_export import doc_to_docx
from app.modules.content.markdown import markdown_to_doc
from tests.pdf_utils import make_pdf

PPTX_DIR = Path(__file__).parent / "fixtures" / "pptx"
MANIFEST = json.loads((PPTX_DIR / "manifest.json").read_text(encoding="utf-8"))


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _all_text(parsed: Parsed) -> str:
    return "\n".join(b.text for p in parsed.pages for b in p.blocks)


@pytest.mark.parametrize("name", sorted(MANIFEST))
def test_pptx_fixtures(name):
    """按 tests/fixtures/pptx/manifest.json 验收 PPT 解析（图片里的文字要靠 OCR，这里只检查交给了 OCR）。"""
    expect = MANIFEST[name]
    parsed = parse_file(name, (PPTX_DIR / name).read_bytes())
    drop_repeated_lines(parsed)
    text = _squash(_all_text(parsed))

    assert len(parsed.pages) == expect["slides"]
    for s in expect["must_contain"] + expect["alt_texts"] + expect["notes_contain"] + expect["hidden_text"]:
        assert _squash(s) in text, s
    for s in expect["noise"]:
        assert _squash(s) not in text, s
    for i in expect["hidden_slides"]:
        assert "隐藏页" in parsed.pages[i].blocks[0].text
    if expect["only_in_images"]:
        assert parsed.ocr_blocks, "图片应当交给 OCR"
    for page, order in expect["reading_order"].items():
        page_text = _squash("\n".join(b.text for b in parsed.pages[int(page)].blocks))
        positions = [page_text.index(_squash(s)) for s in order]
        assert positions == sorted(positions), order


def test_pptx_tables_keep_rows():
    parsed = parse_file("x.pptx", (PPTX_DIR / "02-tables-chart.pptx").read_bytes())
    tables = [b.text for p in parsed.pages for b in p.blocks if b.text.startswith("|")]
    assert len(tables) == 2
    assert all("| --- |" in t for t in tables)
    assert "图表：一周最低气温（℃）" in _all_text(parsed)


def test_pptx_ignores_default_alt_text():
    """没写替代文字的图片，PowerPoint 会自动填文件名，不能当成图片说明。"""
    text = _all_text(parse_file("x.pptx", (PPTX_DIR / "03-images.pptx").read_bytes()))
    assert "［图片：数轴示意图" in text
    assert "image.png" not in text


def test_docx_headings_tables_and_math():
    content = markdown_to_doc(
        "# 有理数\n\n## 一、概念\n\n分数如 $\\frac{1}{4}$。\n\n| 整数 | 分数 |\n| --- | --- |\n| 0 | 1/2 |\n"
    )
    parsed = parse_file("教案.docx", doc_to_docx("有理数", content))
    blocks = parsed.pages[0].blocks
    assert [(b.level, b.text) for b in blocks[:2]] == [(1, "有理数"), (2, "一、概念")]
    assert "(1)/(4)" in blocks[2].text  # Word 公式转成线性文字
    assert blocks[3].text.splitlines()[0] == "| 整数 | 分数 |"


def test_pdf_text_and_scanned_pages():
    pdf = make_pdf(
        [
            ["Rational numbers include integers", "and fractions. Zero is an integer."],
            None,  # 扫描页：没有文字层
        ]
    )
    parsed = parse_file("a.pdf", pdf)
    assert [p.number for p in parsed.pages] == [1, 2]
    assert "Rational numbers include integers and fractions." in parsed.pages[0].blocks[0].text
    [scan] = parsed.ocr_blocks
    assert scan is parsed.pages[1].blocks[0]
    assert Image.open(BytesIO(scan.image)).format == "JPEG"


def test_images_and_text_files():
    buf = BytesIO()
    Image.new("RGBA", (3000, 1000), (255, 0, 0, 128)).save(buf, "PNG")
    [block] = parse_file("photo.png", buf.getvalue()).ocr_blocks
    assert max(Image.open(BytesIO(block.image)).size) == 2000  # 缩小后再送去识别

    parsed = parse_file("note.txt", "# 标题\n\n第一段\n第一段续\n\n第二段".encode("gb18030"))
    assert [(b.level, b.text) for b in parsed.pages[0].blocks] == [
        (1, "标题"),
        (0, "第一段\n第一段续"),
        (0, "第二段"),
    ]


def test_unsupported_files():
    with pytest.raises(ParseError, match="另存为 .docx"):
        parse_file("old.doc", b"x")
    with pytest.raises(ParseError, match="不支持 .exe"):
        parse_file("a.exe", b"x")
    with pytest.raises(ParseError, match="打不开"):
        parse_file("broken.pptx", b"not a zip")


def test_drop_repeated_lines():
    pages = [
        Page(n, [Block(text=f"正文第 {n} 页\n某校数学组 · 内部资料"), Block(text="某校数学组 · 内部资料")])
        for n in range(1, 6)
    ]
    parsed = Parsed(pages)
    drop_repeated_lines(parsed)
    assert [[b.text for b in p.blocks] for p in parsed.pages][0] == ["正文第 1 页"]
    # 页数太少不处理
    few = Parsed([Page(1, [Block(text="页脚")]), Page(2, [Block(text="页脚")])])
    drop_repeated_lines(few)
    assert few.pages[0].blocks[0].text == "页脚"


def test_chunking():
    long_para = "有理数包括整数和分数。" * 200  # 2000 字，要按句子切开
    parsed = Parsed(
        [
            Page(
                1,
                [
                    Block(text="第一章 有理数", level=1),
                    Block(text="1.1 正数和负数", level=2),
                    Block(text="正数大于 0。"),
                ],
            ),
            Page(2, [Block(text="1.2 有理数", level=2), Block(text=long_para)]),
            Page(3, [Block(text="第二章 整式", level=1), Block(text="只有标题", level=2)]),
        ]
    )
    chunks = make_chunks(parsed)
    assert chunks[0].heading == "第一章 有理数"
    assert chunks[0].text.startswith("1.1 正数和负数")
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)  # 短内容跨页合并
    assert all(len(c.text) <= MAX_LEN + 50 for c in chunks)
    assert sum(c.text.count("有理数包括整数和分数") for c in chunks) >= 200  # 没丢内容（重叠部分会多算）
    assert all("只有标题" not in c.text for c in chunks)  # 没有正文的标题不单独成片段
    assert all(c.text.startswith("有理数包括") for c in chunks[1:])  # 重叠部分从整句开始
    assert chunks[-1].embedding_text().startswith(chunks[-1].heading)
