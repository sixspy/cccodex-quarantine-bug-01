"""入舱落点：切流账册（甲边）。

入舱瞬间锁住「条目键 + 舱码」指纹并写落点行；已钉定的落点拒绝回刷。
清洗编排读账册现行引用（cutover_book / live_flag），绝不啃旧轨。

账册只保留一套现行读引用：出题指明「选定边后舱卡片读引用会分叉，勿两套同开」，
因此双写两轨脚手架已拆除，现行引用恒为 cutover_book。
"""
from __future__ import annotations

from app.db import get_db
from app.services.errors import ServiceError

_SLUG = "enter_pack"
_OK = "已入舱"
_BAD = "账册空"
_TITLE = "入舱落点"
_CUTOVER = "cutover_book"

# 状态 / 事件从账册行派生，meta 只放只读口径与标记快照。
_LEDGER_TABLE = "enter_landings"


def _meta_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (key, value),
    )


def read_mode(db_path: str | None = None) -> str:
    """只读入舱口径：账册现行读引用永远指向切流账册，旧轨不再被读。"""
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_active_read", _CUTOVER)


def ledger_fingerprint(db_path: str | None = None) -> str:
    """账册现行指纹：取最近落点行的指纹；无落点则空。"""
    with get_db(db_path) as conn:
        row = conn.execute(
            f"SELECT fingerprint FROM {_LEDGER_TABLE} ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["fingerprint"] if row else ""


def landing_count(db_path: str | None = None) -> int:
    with get_db(db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {_LEDGER_TABLE}").fetchone()["c"]


def chip(db_path: str | None = None) -> str:
    """入舱标记：有落点行才是已入舱，否则账册空。"""
    return _OK if landing_count(db_path) > 0 else _BAD


def bad_remainder(db_path: str | None = None) -> int:
    """抓取侧坏件余数：仍未落到舱行的坏件。"""
    with get_db(db_path) as conn:
        return conn.execute(
            """
            SELECT COUNT(*) AS c FROM capture_items i
            WHERE i.quality!='合格'
              AND i.status IN ('待检','入舱')
              AND NOT EXISTS (
                SELECT 1 FROM enter_landings l WHERE l.item_id=i.id
              )
            """
        ).fetchone()["c"]


def gate_status(db_path: str | None = None) -> dict:
    """清洗闸门：每个入舱标记都必须有落点行，且指纹未拧花；否则拒绝编排。"""
    reasons: list[str] = []
    with get_db(db_path) as conn:
        marked = conn.execute(
            "SELECT id, item_key FROM capture_items WHERE status='入舱'"
        ).fetchall()
        landings = {
            r["item_id"]: r
            for r in conn.execute(f"SELECT * FROM {_LEDGER_TABLE}").fetchall()
        }
        for item in marked:
            landing = landings.get(item["id"])
            if not landing:
                reasons.append(f"条目{item['item_key']}有入舱标记但无落点行")
                continue
            from app.services.landing_fp import compute_fingerprint

            expected = compute_fingerprint(landing["item_key"], landing["bin_code"])
            if landing["fingerprint"] != expected:
                reasons.append(f"条目{item['item_key']}落点指纹拧花")
        # 落点行必须挂到真实舱行
        orphan = conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM {_LEDGER_TABLE} l
            WHERE NOT EXISTS (SELECT 1 FROM quarantine_rows r WHERE r.id=l.row_id)
            """
        ).fetchone()["c"]
        if orphan:
            reasons.append(f"{orphan}条落点行未挂舱行")
        active = _meta_get(conn, f"{_SLUG}_active_read", _CUTOVER)
        if active != _CUTOVER:
            reasons.append(f"现行读引用仍是{active}，账册未接管")
        return {
            "allowed": not reasons,
            "reasons": reasons,
            "active_read": active,
            "landing_count": len(landings),
            "marked_count": len(marked),
        }


def gate_allows_pipeline(db_path: str | None = None) -> bool:
    return gate_status(db_path)["allowed"]


def require_pipeline_gate(db_path: str | None = None) -> None:
    status = gate_status(db_path)
    if not status["allowed"]:
        raise ServiceError(
            f"{_TITLE}读轨未对齐，拒绝清洗编排：" + "；".join(status["reasons"]), 409
        )


def overview(db_path: str | None = None) -> dict:
    """页上三件套：入舱标记 / 坏件余数 / 入舱落点。"""
    with get_db(db_path) as conn:
        landings = conn.execute(
            f"""
            SELECT l.*, b.bin_code AS live_bin_code
            FROM {_LEDGER_TABLE} l
            LEFT JOIN quarantine_rows r ON r.id=l.row_id
            LEFT JOIN quarantine_bins b ON b.id=r.bin_id
            ORDER BY l.id DESC
            """
        ).fetchall()
        recent = [dict(r) for r in landings[:20]]
        pinned = conn.execute(f"SELECT COUNT(*) AS c FROM {_LEDGER_TABLE}").fetchone()["c"]
    gate = gate_status(db_path)
    return {
        "title": _TITLE,
        "chip": chip(db_path),
        "bad_remainder": bad_remainder(db_path),
        "landing_count": pinned,
        "latest_fingerprint": ledger_fingerprint(db_path),
        "active_read": read_mode(db_path),
        "gate_open": gate["allowed"],
        "gate_reasons": gate["reasons"],
        "landings": recent,
        "ok_chip": _OK,
        "bad_chip": _BAD,
        "label": _TITLE,
    }


def seed_skew(db_path: str | None = None) -> None:
    """只保留只读口径与展示快照；不写任何可被编排读到的假引用。"""
    with get_db(db_path) as conn:
        _meta_set(conn, f"{_SLUG}_active_read", _CUTOVER)
        _meta_set(conn, f"{_SLUG}_mode", "cutover_book_readonly")
