"""入舱落点指纹：以入舱瞬间的条目键 + 舱码做确定性指纹。"""
from __future__ import annotations

import hashlib


def compute_fingerprint(item_key: str, bin_code: str) -> str:
    raw = f"{item_key or ''}|{bin_code or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]
