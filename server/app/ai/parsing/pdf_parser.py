"""PDF：有文字层的页直接取文字；没有文字层（扫描件、拍照转的 PDF）的页渲染成图片，交给 OCR。"""

import re

import pypdfium2 as pdfium

from app.ai.parsing.base import MAX_PAGES, OCR_IMAGE_EDGE, Block, Page, Parsed, ParseError, to_ocr_jpeg

MIN_TEXT_CHARS = 20  # 文字少于这个数的页当作扫描页
_SENTENCE_END = tuple("。！？；：…!?;:")
_CJK = re.compile(r"[　-〿一-鿿＀-￯]")


def parse(data: bytes) -> Parsed:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise ParseError("PDF 打不开，可能已损坏或设置了密码") from exc
    try:
        if len(pdf) > MAX_PAGES:
            raise ParseError(f"文件超过 {MAX_PAGES} 页，请拆分后再上传")
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            text = page.get_textpage().get_text_range()
            if len(re.sub(r"\s", "", text)) >= MIN_TEXT_CHARS:
                blocks = [Block(text=p) for p in _paragraphs(text)]
            else:
                width, height = page.get_size()
                scale = min(OCR_IMAGE_EDGE / max(width, height, 1), 4.0)
                image = page.render(scale=scale).to_pil()
                blocks = [Block(image=to_ocr_jpeg(image))]
            pages.append(Page(number=i + 1, blocks=blocks))
        return Parsed(pages=pages)
    finally:
        pdf.close()


def _paragraphs(text: str) -> list[str]:
    """PDF 文字按排版折行，这里把同一段的行接起来。

    以"常见行长"为基准（取行长的 60 分位，双栏排版时就是一栏的宽度）：以句末标点结尾且没写满一行、
    或者明显短于常见行长的行，视为段落结束。
    """
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lengths = sorted(len(line) for line in lines if len(line) >= 5)
    typical = lengths[int(len(lengths) * 0.6)] if lengths else 0
    paragraphs: list[str] = []
    current = ""
    for line in lines:
        if not line:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        if current:
            # 中文之间直接相接，英文单词之间补空格
            joiner = "" if _CJK.match(current[-1]) or _CJK.match(line[0]) else " "
            current += joiner + line
        else:
            current = line
        if (line.endswith(_SENTENCE_END) and len(line) < typical * 0.9) or len(line) < typical * 0.5:
            paragraphs.append(current)
            current = ""
    if current:
        paragraphs.append(current)
    return paragraphs
