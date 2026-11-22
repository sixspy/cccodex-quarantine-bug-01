"""入舱落点 / 坏件余数 / 切流账册 / 清洗闸门 的失败用例（先红后绿）。"""
from __future__ import annotations

import importlib.util
import threading

import pytest

from app.db import get_db
from app.services import captures, enter_pack, enter_pack_cutover, policies, quarantine, reconcile
from app.services.errors import ServiceError


def _first_bad_pending(db_path):
    for batch in captures.list_batches(db_path):
        detail = captures.get_batch(batch["id"], db_path)
        for item in detail["items"]:
            if item["quality"] != "合格" and item["status"] == "待检":
                return detail, item
    raise AssertionError("种子数据里找不到待检坏件")


def _open_bin(db_path):
    return next(b for b in quarantine.list_bins(db_path) if b["status"] == "开放")


def _bad_remainder(db_path, batch_id):
    return next(b for b in captures.list_batches(db_path) if b["id"] == batch_id)["bad_count"]


def test_bad_remainder_drops_when_entry_lands(db_path):
    detail, item = _first_bad_pending(db_path)
    bin_row = _open_bin(db_path)
    before = _bad_remainder(db_path, detail["id"])

    row = quarantine.enter_item(item["id"], bin_row["id"], "余数用例", db_path)

    after = _bad_remainder(db_path, detail["id"])
    assert row["status"] == "待复核"
    assert after == before - 1, "入舱后抓取侧坏件余数必须下降"
    refreshed = captures.get_batch(detail["id"], db_path)
    moved = next(i for i in refreshed["items"] if i["id"] == item["id"])
    assert moved["status"] == "入舱"


def test_entry_lands_row_and_locks_item_key_bin_code_fingerprint(db_path):
    _detail, item = _first_bad_pending(db_path)
    bin_row = _open_bin(db_path)

    quarantine.enter_item(item["id"], bin_row["id"], "落点用例", db_path)

    rows = [r for r in enter_pack_cutover.landing_rows(db_path) if r["item_id"] == item["id"]]
    assert len(rows) == 1, "入舱必须落入舱行，不能只亮芯片"
    landing = rows[0]
    assert landing["item_key"] == item["item_key"]
    assert landing["bin_code"] == bin_row["bin_code"]
    assert landing["fingerprint"] == enter_pack_cutover.compute_fingerprint(
        item["item_key"], bin_row["bin_code"]
    )
    with get_db(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM quarantine_rows WHERE item_id=?", (item["id"],)
        ).fetchone()["c"] == 1
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM review_tickets WHERE row_id="
            "(SELECT id FROM quarantine_rows WHERE item_id=?)",
            (item["id"],),
        ).fetchone()["c"] == 1


def test_second_entry_is_rejected_and_cannot_refresh_pinned_point(db_path):
    _detail, item = _first_bad_pending(db_path)
    bin_row = _open_bin(db_path)
    quarantine.enter_item(item["id"], bin_row["id"], "首入", db_path)
    pinned = [r for r in enter_pack_cutover.landing_rows(db_path) if r["item_id"] == item["id"]][0]

    with pytest.raises(ServiceError):
        quarantine.enter_item(item["id"], bin_row["id"], "回刷", db_path)

    rows = [r for r in enter_pack_cutover.landing_rows(db_path) if r["item_id"] == item["id"]]
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == pinned["fingerprint"]
    assert rows[0]["reason"] == pinned["reason"]


def test_entry_failure_rolls_back_whole_record(monkeypatch, db_path):
    detail, item = _first_bad_pending(db_path)
    bin_row = _open_bin(db_path)
    before = _bad_remainder(db_path, detail["id"])

    def boom(*args, **kwargs):
        raise RuntimeError("simulated landing failure")

    monkeypatch.setattr(enter_pack_cutover, "write_landing", boom)

    with pytest.raises(ServiceError) as exc:
        quarantine.enter_item(item["id"], bin_row["id"], "半失败", db_path)
    assert "回滚" in exc.value.message

    with get_db(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM quarantine_rows WHERE item_id=?", (item["id"],)
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM enter_landings WHERE item_id=?", (item["id"],)
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT status FROM capture_items WHERE id=?", (item["id"],)
        ).fetchone()["status"] == "待检"
    assert _bad_remainder(db_path, detail["id"]) == before


def test_gate_fails_when_entry_mark_has_no_landing_row(db_path):
    """只有入舱标记、没有落点行：清洗编排必须被挡住。"""
    detail, item = _first_bad_pending(db_path)
    with get_db(db_path) as conn:
        # 造出“已入舱”标记但没有切流账册行
        conn.execute("UPDATE capture_items SET status='入舱' WHERE id=?", (item["id"],))

    status = enter_pack.gate_status(db_path)
    assert status["allowed"] is False
    with pytest.raises(ServiceError):
        policies.apply_to_batch(detail["id"], db_path)


def test_gate_fails_when_chain_still_eats_old_reference_without_landing(db_path):
    """无落点却仍啃旧引用（离线入舱痕迹）必须失败。"""
    _detail, item = _first_bad_pending(db_path)
    with get_db(db_path) as conn:
        conn.execute("UPDATE capture_items SET status='入舱' WHERE id=?", (item["id"],))
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (f"{enter_pack_cutover._SLUG}_active_read", "old_track"),
        )

    assert enter_pack.gate_allows_pipeline(db_path) is False
    with pytest.raises(ServiceError):
        enter_pack.require_pipeline_gate(db_path)


def test_gate_fails_when_fingerprint_is_mangled(db_path):
    detail, item = _first_bad_pending(db_path)
    bin_row = _open_bin(db_path)
    quarantine.enter_item(item["id"], bin_row["id"], "正常入舱", db_path)
    assert enter_pack.gate_allows_pipeline(db_path) is True

    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE enter_landings SET fingerprint='mangled' WHERE item_id=?",
            (item["id"],),
        )

    status = enter_pack.gate_status(db_path)
    assert status["allowed"] is False
    assert any("指纹" in reason for reason in status["reasons"])
    with pytest.raises(ServiceError):
        enter_pack.require_pipeline_gate(db_path)
    with pytest.raises(ServiceError):
        policies.apply_to_batch(detail["id"], db_path)


def test_pipeline_refuses_drift_items(db_path):
    """清洗编排不得吞下漂件：落点缺失时整批拒绝。"""
    detail, item = _first_bad_pending(db_path)
    # 漂件：状态入舱，但无隔离行、无落点行
    with get_db(db_path) as conn:
        conn.execute("UPDATE capture_items SET status='入舱' WHERE id=?", (item["id"],))
        before_rows = conn.execute("SELECT COUNT(*) AS c FROM quarantine_rows").fetchone()["c"]

    with pytest.raises(ServiceError):
        policies.apply_to_batch(detail["id"], db_path)

    with get_db(db_path) as conn:
        after_rows = conn.execute("SELECT COUNT(*) AS c FROM quarantine_rows").fetchone()["c"]
    assert after_rows == before_rows


def test_concurrent_entry_only_one_wins_and_pin_survives(db_path):
    _detail, item = _first_bad_pending(db_path)
    bin_row = _open_bin(db_path)
    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def attempt(note):
        barrier.wait(timeout=5)
        try:
            quarantine.enter_item(item["id"], bin_row["id"], note, db_path)
            with lock:
                results.append("ok")
        except ServiceError:
            with lock:
                results.append("rejected")

    threads = [threading.Thread(target=attempt, args=(f"争抢{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert sorted(results) == ["ok", "rejected"], "同一坏件并发入舱只允许一侧成功"
    with get_db(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM enter_landings WHERE item_id=?", (item["id"],)
        ).fetchone()["c"] == 1
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM quarantine_rows WHERE item_id=?", (item["id"],)
        ).fetchone()["c"] == 1
    landing = next(r for r in enter_pack_cutover.landing_rows(db_path) if r["item_id"] == item["id"])
    assert landing["fingerprint"] == enter_pack_cutover.compute_fingerprint(
        item["item_key"], bin_row["bin_code"]
    )


def test_bins_and_dashboard_expose_mark_remainder_and_landing(db_path):
    detail, item = _first_bad_pending(db_path)
    bin_row = _open_bin(db_path)
    quarantine.enter_item(item["id"], bin_row["id"], "展示用例", db_path)

    bins = quarantine.list_bins(db_path)
    landed_bin = next(b for b in bins if b["id"] == bin_row["id"])
    assert landed_bin["entry_mark"] == "已入舱"
    assert landed_bin["landing_count"] >= 1

    overview = enter_pack.overview(db_path)
    assert overview["chip"] == "已入舱"
    assert overview["active_read"] == "cutover_book"
    assert overview["landing_count"] >= 1
    assert overview["gate_open"] is True
    assert overview["latest_fingerprint"]

    dash = reconcile.dashboard(db_path)
    assert "entry_landing" in dash
    assert "bad_remainder" in dash["entry_landing"]


def test_reconcile_summary_available_to_review(db_path):
    report = reconcile.run_reconcile(db_path)
    latest = reconcile.latest_report(db_path)
    assert latest["id"] == report["id"]
    assert latest["summary"] == report["summary"]


def test_dualwrite_scaffold_is_removed():
    """未拆除的闲置脚手架不得收工。"""
    assert importlib.util.find_spec("app.services.enter_pack_dualwrite") is None
    assert importlib.util.find_spec("app.services.enter_pack_audit") is None


@pytest.fixture()
def client(db_path):
    from webtest import TestApp

    from app.config import Config
    from app.main import create_app

    testapp = TestApp(create_app())
    testapp.post_json(
        "/api/login",
        {"username": Config.ADMIN_USER, "password": Config.ADMIN_PASS},
    )
    return testapp


def test_commit_endpoint_cannot_paint_chip_without_landing(client, db_path):
    """只改入舱芯片却不落入舱行，必须失败。"""
    before = enter_pack.landing_count(db_path)
    resp = client.post_json("/api/enter_pack/commit", {"ref": 1}, status=400)
    assert "落点" in resp.json["error"]
    assert enter_pack.landing_count(db_path) == before


def test_retired_scaffold_endpoints_are_gone(client):
    assert client.get("/api/enter_pack/snap", status=404)
    assert client.post_json("/api/enter_pack/half", {}, status=404)
    assert client.post_json("/api/enter_pack/dual", {}, status=404)

