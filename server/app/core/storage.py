"""文件存储。业务代码只用 put / get / delete，以后换成 OSS 只改这里。

存储键由服务端生成（机构 ID / 随机 ID + 扩展名），不使用用户上传的文件名，避免路径穿越。
"""

import uuid
from pathlib import Path

from app.core.config import get_settings


def new_key(tenant_id: uuid.UUID, filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    return f"{tenant_id}/{uuid.uuid4().hex}{ext}"


def _path(key: str) -> Path:
    root = get_settings().storage_dir.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"非法的存储键：{key}")
    return path


def put(key: str, data: bytes) -> None:
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get(key: str) -> bytes:
    return _path(key).read_bytes()


def delete(key: str) -> None:
    _path(key).unlink(missing_ok=True)
