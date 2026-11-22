"""入舱落点切流账册：入舱瞬间锁定条目键 + 舱码指纹，落点行拒回刷。

甲边形态：入舱与落点同行同事务写入，账册钉住当刻指纹；任何二次入舱
（回刷）都因已钉定落点而失败，不会覆盖钉点。
"""
from __future__ import annotations

from app.db import get_db
from app.services.landing_fp import compute_fingerprint

_SLUG = "enter_pack"
_TITLE = "入舱落点"


def write_landing(
    conn,
    *,
    item_id: int,
    row_id: int,
    item_key: str,
    bin_code: str,
    reason: str,
) -> dict:
    """在调用方事务内写入落点行并钉定指纹。

    由 quarantine.enter_item 在同一事务里调用，保证「整次写完」；
    若本函数抛错，外层连接回滚，入舱行与坏件余数一并复原。
    """
    fingerprint = compute_fingerprint(item_key, bin_code)
    cur = conn.execute(
        """
        INSERT INTO enter_landings(item_id, row_id, item_key, bin_code, fingerprint, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_id, row_id, item_key, bin_code, fingerprint, reason or ""),
    )
    return {
        "id": cur.lastrowid,
        "item_id": item_id,
        "row_id": row_id,
        "item_key": item_key,
        "bin_code": bin_code,
        "fingerprint": fingerprint,
        "reason": reason or "",
    }


def landing_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM enter_landings ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def board(db_path: str | None = None) -> dict:
    """舱卡片 + 抓取侧共用的切流账册面板。"""
    from app.services import enter_pack

    overview = enter_pack.overview(db_path)
    return {
        **overview,
        "landing_rows": landing_rows(db_path),
        "fate": "cutover_book",
        "label": _TITLE,
    }
