from io import BytesIO

from PIL import Image, ImageOps

from app.ai.parsing.base import Block, Page, Parsed, to_ocr_jpeg


def parse(data: bytes) -> Parsed:
    img = ImageOps.exif_transpose(Image.open(BytesIO(data)))  # 手机照片按拍摄方向转正
    return Parsed(pages=[Page(number=1, blocks=[Block(image=to_ocr_jpeg(img))])])
