"""PPT（.pptx）：每页一个标题，正文按视觉位置（从上到下、从左到右）排序。

覆盖 tests/fixtures/pptx 里整理的情况：表格（含合并单元格）、图表、组合图形、演讲者备注、
隐藏页、图片替代文字、图片里的文字（交给 OCR）。
"""

import re
from io import BytesIO

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.ai.parsing.base import Block, Page, Parsed, to_ocr_jpeg

MIN_OCR_SIDE = 80  # 太小的图片（图标、装饰）不识别
MAX_OCR_IMAGES = 40  # 每份课件最多识别的图片数，控制费用和时间
# 没写替代文字时，PowerPoint、WPS 会自动填文件名或"图片 1"，这些不算说明
_DEFAULT_ALT = re.compile(r"^(.+\.(png|jpe?g|gif|bmp|emf|wmf|tiff?|svg)|(图片|picture|image)\s*\d*)$", re.I)


def parse(data: bytes) -> Parsed:
    prs = Presentation(BytesIO(data))
    budget = [MAX_OCR_IMAGES]
    pages = []
    for number, slide in enumerate(prs.slides, start=1):
        blocks: list[Block] = []
        title_shape = slide.shapes.title
        title = (
            title_shape.text_frame.text.strip()
            if title_shape is not None and title_shape.has_text_frame
            else ""
        )
        hidden = slide._element.get("show") == "0"
        heading = f"第 {number} 页" + (f"：{title}" if title else "") + ("（隐藏页）" if hidden else "")
        blocks.append(Block(text=heading, level=2))
        for shape in _sorted(slide.shapes):
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            blocks += _shape_blocks(shape, budget)
        if slide.has_notes_slide:
            notes = (
                slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
            )
            if notes:
                blocks.append(Block(text=f"备注：{notes}"))
        pages.append(Page(number=number, blocks=blocks))
    return Parsed(pages=pages)


def _sorted(shapes):
    # 同一行的框（上边缘相差不到约 0.5 厘米）按从左到右排
    def key(s):
        top, left = s.top or 0, s.left or 0
        return (round(top / 180000), left)

    return sorted(shapes, key=key)


def _shape_blocks(shape, budget: list[int]) -> list[Block]:
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return [b for child in _sorted(shape.shapes) for b in _shape_blocks(child, budget)]
    if getattr(shape, "has_table", False) and shape.has_table:
        return [Block(text=_table_markdown(shape.table))]
    if getattr(shape, "has_chart", False) and shape.has_chart:
        return [Block(text=_chart_text(shape.chart))]
    blocks = []
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or hasattr(shape, "image"):
        alt = [a.strip() for a in shape._element.xpath("./*[1]/p:cNvPr/@descr")]
        if alt and alt[0] and not _DEFAULT_ALT.match(alt[0]):
            blocks.append(Block(text=f"［图片：{alt[0]}］"))
        image = _ocr_image(shape, budget)
        if image:
            blocks.append(Block(image=image))
    if shape.has_text_frame:
        lines = []
        for para in shape.text_frame.paragraphs:
            text = "".join(run.text for run in para.runs).strip() or para.text.strip()
            if text:
                lines.append(("  " * para.level + "- " + text) if para.level else text)
        if lines:
            blocks.append(Block(text="\n".join(lines)))
    return blocks


def _ocr_image(shape, budget: list[int]) -> bytes | None:
    if budget[0] <= 0:
        return None
    try:
        img = Image.open(BytesIO(shape.image.blob))
        if min(img.size) < MIN_OCR_SIDE:
            return None
        data = to_ocr_jpeg(img)
    except Exception:  # WMF/EMF 等矢量图打不开，跳过
        return None
    budget[0] -= 1
    return data


def _table_markdown(table) -> str:
    rows = []
    for row in table.rows:
        # 被合并掉的单元格留空，保持列对齐
        cells = [
            "" if c.is_spanned else c.text.strip().replace("\n", " ").replace("|", "｜") for c in row.cells
        ]
        rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    return "\n".join([rows[0], "|" + " --- |" * len(table.columns), *rows[1:]])


def _chart_text(chart) -> str:
    lines = []
    if chart.has_title and chart.chart_title.has_text_frame:
        lines.append(f"图表：{chart.chart_title.text_frame.text.strip()}")
    try:
        categories = [str(c) for c in chart.plots[0].categories]
        for series in chart.plots[0].series:
            values = "，".join(f"{cat} {val}" for cat, val in zip(categories, series.values, strict=False))
            lines.append(f"{series.name}：{values}")
    except (IndexError, KeyError, ValueError):
        pass
    return "\n".join(lines) or "图表"
