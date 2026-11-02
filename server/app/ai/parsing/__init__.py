"""资料解析：上传的文件 → 按页的文本块 → 检索用的片段。

流程：
1. parse_file：按文件类型提取文字。扫描页、图片里的文字先留成待识别的图片（Block.image）。
2. 调用方用 OCR 填上这些图片的文字（需要调模型，所以不在这里做）。
3. drop_repeated_lines：去掉每页都重复的页眉、页脚、水印。
4. chunking.make_chunks：按标题和长度切成片段，再去向量化。
"""

from app.ai.parsing.base import (
    SUPPORTED_EXTS,
    Block,
    Page,
    Parsed,
    ParseError,
    drop_repeated_lines,
    parse_file,
)
from app.ai.parsing.chunking import Chunk, make_chunks

__all__ = [
    "SUPPORTED_EXTS",
    "Block",
    "Chunk",
    "Page",
    "ParseError",
    "Parsed",
    "drop_repeated_lines",
    "make_chunks",
    "parse_file",
]
