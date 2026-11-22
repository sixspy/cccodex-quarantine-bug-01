from __future__ import annotations

from app.db import get_db
from app.services import audit as audit_svc
from app.services import captures as captures_svc
from app.services import enter_pack_cutover
from app.services import settings as settings_svc
from app.services.errors import ServiceError


def list_bins(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT b.*,
              (SELECT COUNT(*) FROM quarantine_rows r WHERE r.bin_id=b.id AND r.status='待复核') AS pending_count,
              (SELECT COUNT(*) FROM quarantine_rows r WHERE r.bin_id=b.id) AS row_count,
              (SELECT COUNT(*) FROM enter_landings l
                 JOIN quarantine_rows r ON r.id=l.row_id
                 WHERE r.bin_id=b.id) AS landing_count
            FROM quarantine_bins b ORDER BY b.id
            """
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["entry_mark"] = "已入舱" if item["landing_count"] > 0 else "账册空"
            out.append(item)
        return out


def list_rows(bin_id: int | None = None, db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if bin_id:
            rows = conn.execute(
                """
                SELECT r.*, i.item_key, i.quality, i.batch_id, b.bin_code, b.title AS bin_title,
                       l.fingerprint, l.id AS landing_id
                FROM quarantine_rows r
                JOIN capture_items i ON i.id=r.item_id
                JOIN quarantine_bins b ON b.id=r.bin_id
                LEFT JOIN enter_landings l ON l.item_id=i.id
                WHERE r.bin_id=?
                ORDER BY r.id DESC
                """,
                (bin_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT r.*, i.item_key, i.quality, i.batch_id, b.bin_code, b.title AS bin_title,
                       l.fingerprint, l.id AS landing_id
                FROM quarantine_rows r
                JOIN capture_items i ON i.id=r.item_id
                JOIN quarantine_bins b ON b.id=r.bin_id
                LEFT JOIN enter_landings l ON l.item_id=i.id
                ORDER BY r.id DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]


def enter_item(item_id: int, bin_id: int, reason: str, db_path: str | None = None) -> dict:
    """入舱：单事务写完 隔离行 + 条目状态 + 复核单 + 落点行。

    甲边：同一事务内钉定「条目键 + 舱码」指纹，落点行唯一，二次入舱即回刷，必拒。
    失败回滚整次写入，坏件余数维持原样，错误回中随即用短句说明。
    """
    reason = (reason or "").strip() or "质量异常入舱"
    try:
        with get_db(db_path, immediate=True) as conn:
            item = conn.execute(
                "SELECT * FROM capture_items WHERE id=?", (item_id,)
            ).fetchone()
            if not item:
                raise ServiceError("条目不存在", 404)
            if item["status"] == "入舱":
                raise ServiceError("条目已入舱，落点已钉定不可回刷", 409)
            if item["status"] != "待检":
                raise ServiceError("仅待检条目可入舱")
            if item["quality"] == "合格":
                raise ServiceError("合格条目不应入舱")
            pinned = conn.execute(
                "SELECT id FROM enter_landings WHERE item_id=?", (item_id,)
            ).fetchone()
            if pinned:
                raise ServiceError("条目落点已钉定，拒绝回刷", 409)
            bin_row = conn.execute(
                "SELECT * FROM quarantine_bins WHERE id=?", (bin_id,)
            ).fetchone()
            if not bin_row:
                raise ServiceError("隔离舱不存在", 404)
            if bin_row["status"] != "开放":
                raise ServiceError("隔离舱未开放")
            open_bins = conn.execute(
                "SELECT COUNT(*) AS c FROM quarantine_bins WHERE status='开放'"
            ).fetchone()["c"]
            max_open = int(settings_svc.get_value("max_bin_open", "3", db_path) or "3")
            if open_bins > max_open:
                raise ServiceError("开放隔离舱超过上限")
            occupied = conn.execute(
                "SELECT COUNT(*) AS c FROM quarantine_rows WHERE bin_id=? AND status IN ('待复核','回炉中')",
                (bin_id,),
            ).fetchone()["c"]
            if occupied >= bin_row["capacity"]:
                raise ServiceError("隔离舱已满")
            exists = conn.execute(
                "SELECT id FROM quarantine_rows WHERE item_id=?", (item_id,)
            ).fetchone()
            if exists:
                raise ServiceError("条目已在隔离舱")
            cur = conn.execute(
                """
                INSERT INTO quarantine_rows(bin_id, item_id, reason, status)
                VALUES (?, ?, ?, '待复核')
                """,
                (bin_id, item_id, reason),
            )
            row_id = cur.lastrowid
            conn.execute(
                "UPDATE capture_items SET status='入舱' WHERE id=?", (item_id,)
            )
            n = conn.execute("SELECT COUNT(*) AS c FROM review_tickets").fetchone()["c"] + 1
            conn.execute(
                """
                INSERT INTO review_tickets(ticket_code, row_id, decision, comment)
                VALUES (?, ?, '待决', ?)
                """,
                (f"REV-{n:04d}", row_id, "入舱自动开复核单"),
            )
            # 落点行与入舱行同事务写入；指纹在此刻钉定。
            enter_pack_cutover.write_landing(
                conn,
                item_id=item_id,
                row_id=row_id,
                item_key=item["item_key"],
                bin_code=bin_row["bin_code"],
                reason=reason,
            )
            row = conn.execute(
                """
                SELECT r.*, i.item_key, i.quality, b.bin_code, l.fingerprint
                FROM quarantine_rows r
                JOIN capture_items i ON i.id=r.item_id
                JOIN quarantine_bins b ON b.id=r.bin_id
                JOIN enter_landings l ON l.item_id=i.id
                WHERE r.id=?
                """,
                (row_id,),
            ).fetchone()
            # 余数与审计与入舱同一次写完，半途失败一并回滚。
            captures_svc.refresh_bad_count(item["batch_id"], conn=conn)
            audit_svc.write_event(
                "入舱", "quarantine_row", row_id, reason, db_path=db_path, conn=conn
            )
    except ServiceError:
        raise
    except Exception as exc:  # 半失败：整次回滚并回中短句
        raise ServiceError(f"入舱整次写入失败已回滚：{exc}", 500) from exc
    out = dict(row)
    out["chip"] = "已入舱"
    out["active_read"] = "cutover_book"
    return out


def auto_enter_bad(batch_id: int, bin_id: int, db_path: str | None = None) -> dict:
    auto = settings_svc.get_value("auto_enter_bad", "1", db_path)
    if auto != "1":
        raise ServiceError("未开启自动入舱")
    with get_db(db_path) as conn:
        items = conn.execute(
            """
            SELECT id FROM capture_items
            WHERE batch_id=? AND quality!='合格' AND status='待检'
            """,
            (batch_id,),
        ).fetchall()
    entered = []
    for it in items:
        entered.append(enter_item(it["id"], bin_id, "批内自动入舱", db_path))
    return {"entered": len(entered), "rows": entered}
