import re
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

MAX_PAGES = 300
OCR_IMAGE_EDGE = 2000  # 送去识别的图片长边上限（像素），太大既慢又贵


class ParseError(Exception):
    """文件本身的问题（格式不支持、损坏、太大），message 直接展示给老师。"""


@dataclass
class Block:
    text: str = ""
    level: int = 0  # 大于 0 表示标题级别
    image: bytes | None = None  # 待 OCR 的图片（JPEG）；识别后文字写回 text


@dataclass
class Page:
    number: int | None  # 页码 / 幻灯片序号，从 1 开始；Word、纯文本没有页码
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Parsed:
    pages: list[Page]

    @property
    def ocr_blocks(self) -> list[Block]:
        return [b for p in self.pages for b in p.blocks if b.image is not None]


def parse_file(filename: str, data: bytes) -> Parsed:
    from app.ai.parsing import docx_parser, image_parser, pdf_parser, pptx_parser, text_parser

    parsers = {
        ".pdf": pdf_parser.parse,
        ".docx": docx_parser.parse,
        ".pptx": pptx_parser.parse,
        ".txt": text_parser.parse,
        ".md": text_parser.parse,
        ".jpg": image_parser.parse,
        ".jpeg": image_parser.parse,
        ".png": image_parser.parse,
        ".webp": image_parser.parse,
    }
    ext = Path(filename).suffix.lower()
    if ext in (".doc", ".ppt"):
        raise ParseError(f"暂不支持老版本的 {ext} 文件，请用 Office 或 WPS 另存为 {ext}x 后再上传")
    if ext not in parsers:
        raise ParseError(f"不支持 {ext or '无扩展名'} 文件，支持：{'、'.join(SUPPORTED_EXTS)}")
    try:
        parsed = parsers[ext](data)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("文件打不开，可能已损坏或被加密") from exc
    if len(parsed.pages) > MAX_PAGES:
        raise ParseError(f"文件超过 {MAX_PAGES} 页，请拆分后再上传")
    return parsed


SUPPORTED_EXTS = [".pdf", ".docx", ".pptx", ".jpg", ".png", ".txt", ".md"]


def to_ocr_jpeg(img: Image.Image) -> bytes:
    """转成适合识别的 JPEG：透明背景铺白，长边缩到 OCR_IMAGE_EDGE 以内。"""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((OCR_IMAGE_EDGE, OCR_IMAGE_EDGE))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


_SPACES = re.compile(r"\s+")


def _norm(line: str) -> str:
    return _SPACES.sub("", line)


def drop_repeated_lines(parsed: Parsed, *, min_pages: int = 4, ratio: float = 0.5, max_len: int = 40) -> None:
    """去掉在多数页面上重复出现的短行：页眉、页脚、水印、"内部资料"之类。

    页数太少时不处理，避免把正常内容误删；页码这类每页不同的行不受影响。
    """
    numbered = [p for p in parsed.pages if p.blocks]
    if len(numbered) < min_pages:
        return
    seen: Counter[str] = Counter()
    for page in numbered:
        lines = {_norm(line) for b in page.blocks if b.level == 0 for line in b.text.splitlines()}
        seen.update(line for line in lines if line and len(line) <= max_len)
    noise = {line for line, n in seen.items() if n >= max(2, len(numbered) * ratio)}
    if not noise:
        return
    for page in numbered:
        kept = []
        for b in page.blocks:
            if b.level == 0:
                b.text = "\n".join(line for line in b.text.splitlines() if _norm(line) not in noise)
            if b.text.strip() or b.image is not None:
                kept.append(b)
        page.blocks = kept
