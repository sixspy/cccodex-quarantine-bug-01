
from __future__ import annotations

from app.db import get_db
from app.services.errors import ServiceError


def write_event(
    action: str,
    entity_type: str,
    entity_id: int = 0,
    detail: str = "",
    actor: str = "admin",
    db_path: str | None = None,
    conn=None,
) -> dict:
    """写审计事件；传入 conn 时并入调用方事务，不单独提交。"""
    action = (action or "").strip()
    entity_type = (entity_type or "").strip()
    if not action or not entity_type:
        raise ServiceError("审计动作不完整")
    if conn is not None:
        return _insert_event(conn, action, entity_type, entity_id, detail, actor)
    with get_db(db_path) as own_conn:
        return _insert_event(own_conn, action, entity_type, entity_id, detail, actor)


def _insert_event(conn, action, entity_type, entity_id, detail, actor) -> dict:
    cur = conn.execute(
        """
        INSERT INTO audit_events(actor, action, entity_type, entity_id, detail)
        VALUES (?, ?, ?, ?, ?)
        """,
        (actor or "admin", action, entity_type, int(entity_id or 0), detail or ""),
    )
    row = conn.execute(
        "SELECT * FROM audit_events WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def list_events(limit: int = 100, db_path: str | None = None) -> list[dict]:
    limit = max(1, min(int(limit or 100), 500))
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, actor, action, entity_type, entity_id, detail, created_at
            FROM audit_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def summary(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
        by_action = conn.execute(
            """
            SELECT action, COUNT(*) AS c
            FROM audit_events
            GROUP BY action
            ORDER BY c DESC
            """
        ).fetchall()
        return {
            "total": total,
            "by_action": [dict(r) for r in by_action],
        }
