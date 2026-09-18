"""厅图版本冻结：冻结拒绝、新版本可用、旧持座坐标不变。

种子路径：场次已有持座 → 改当前版本过道被拒 → 复制为新版本 →
新场次绑新版本可用新过道；旧场次座位图仍按旧版本渲染。
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Hall, HallLayoutVersion, SeatHold, Showtime
from app.services.layout_versions import backfill_all


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


def _seed_frozen_scenario():
    """一号厅 v1（8×12，过道 5,6）；场次绑 v1 且存在持有中持座 → v1 冻结。"""
    db = SessionLocal()
    try:
        hall = Hall(name="一号厅", rows=8, cols=12, aisle_cols="5,6")
        db.add(hall)
        db.flush()
        v1 = HallLayoutVersion(
            hall_id=hall.id, version_no=1, rows=8, cols=12, aisle_cols="5,6"
        )
        db.add(v1)
        db.flush()
        st = Showtime(
            hall_id=hall.id,
            film_title="星际旅人",
            start_at=datetime.utcnow() + timedelta(hours=2),
            layout_version_id=v1.id,
        )
        db.add(st)
        db.flush()
        hold = SeatHold(
            showtime_id=st.id, order_code="SB-1001",
            row=3, start_col=2, end_col=4, party_size=3,
        )
        db.add(hold)
        db.commit()
        return hall.id, v1.id, st.id, hold.id
    finally:
        db.close()


def _new_showtime(client, hall_id, title="新片", version_id=None, hours=8):
    body = {
        "hall_id": hall_id,
        "film_title": title,
        "start_at": (datetime.utcnow() + timedelta(hours=hours)).isoformat(),
    }
    if version_id is not None:
        body["layout_version_id"] = version_id
    r = client.post("/api/showtimes", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# —— 冻结拒绝 ——


def test_frozen_version_rejects_layout_edit(client):
    hall_id, v1_id, _st_id, _hold_id = _seed_frozen_scenario()

    vs = client.get(f"/api/halls/{hall_id}/versions").json()
    assert len(vs) == 1
    assert vs[0]["version_no"] == 1
    assert vs[0]["frozen"] is True
    assert vs[0]["showtime_count"] == 1

    # 改过道被拒，且提示可读
    r = client.put(f"/api/versions/{v1_id}", json={"rows": 8, "cols": 12, "aisle_cols": [7]})
    assert r.status_code == 409
    assert "冻结" in r.json()["detail"]
    assert "复制为新版本" in r.json()["detail"]

    # 改行列同样被拒
    r = client.put(f"/api/versions/{v1_id}", json={"rows": 9, "cols": 12, "aisle_cols": [5, 6]})
    assert r.status_code == 409

    # 版本内容未被偷改
    v = client.get(f"/api/halls/{hall_id}/versions").json()[0]
    assert (v["rows"], v["cols"], v["aisle_cols"]) == (8, 12, [5, 6])


def test_version_unfreezes_when_holds_released(client):
    _hall_id, v1_id, _st_id, hold_id = _seed_frozen_scenario()
    db = SessionLocal()
    db.get(SeatHold, hold_id).status = "released"
    db.commit()
    db.close()

    r = client.put(f"/api/versions/{v1_id}", json={"rows": 8, "cols": 12, "aisle_cols": [7]})
    assert r.status_code == 200
    assert r.json()["frozen"] is False
    assert r.json()["aisle_cols"] == [7]


def test_layout_validation_rejects_out_of_range_aisle(client):
    hall_id, _v1_id, _st_id, _hold_id = _seed_frozen_scenario()
    v2 = client.post(f"/api/halls/{hall_id}/versions", json={}).json()  # 未冻结
    r = client.put(
        f"/api/versions/{v2['id']}", json={"rows": 8, "cols": 12, "aisle_cols": [13]}
    )
    assert r.status_code == 422
    assert "过道列" in r.json()["detail"]


# —— 复制为新版本 → 新场次绑新版本可用新过道 ——


def test_new_version_usable_for_new_showtime(client):
    hall_id, _v1_id, _st_id, _hold_id = _seed_frozen_scenario()

    # 复制为新版本：无过道
    r = client.post(f"/api/halls/{hall_id}/versions", json={"aisle_cols": []})
    assert r.status_code == 201
    v2 = r.json()
    assert v2["version_no"] == 2
    assert v2["frozen"] is False
    assert v2["aisle_cols"] == []

    # 冻结状态列表：v1 冻结、v2 可编辑
    vs = client.get(f"/api/halls/{hall_id}/versions").json()
    assert [(v["version_no"], v["frozen"]) for v in vs] == [(1, True), (2, False)]

    # 新场次显式绑 v2
    st2 = _new_showtime(client, hall_id, version_id=v2["id"])
    assert st2["layout_version_no"] == 2

    # 新座位图按 v2 渲染：无过道
    m = client.get(f"/api/seatmap/{st2['id']}").json()
    assert m["layout_version_no"] == 2
    assert not any(c["is_aisle"] for c in m["cells"])

    # 新版本可用：无过道时 12 人连座可成行（旧版本过道 5,6 下不可能）
    r = client.post("/api/holds", json={"showtime_id": st2["id"], "party_size": 12})
    assert r.status_code == 200
    hold = r.json()
    assert (hold["row"], hold["start_col"], hold["end_col"]) == (1, 1, 12)


def test_showtime_defaults_to_latest_version(client):
    hall_id, _v1_id, _st_id, _hold_id = _seed_frozen_scenario()
    v2 = client.post(f"/api/halls/{hall_id}/versions", json={}).json()
    st = _new_showtime(client, hall_id)  # 未指定版本 → 绑最新 v2
    assert st["layout_version_no"] == v2["version_no"]


def test_showtime_rejects_version_of_other_hall(client):
    hall_id, v1_id, _st_id, _hold_id = _seed_frozen_scenario()
    db = SessionLocal()
    other = Hall(name="二号厅", rows=6, cols=10, aisle_cols="")
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()

    r = client.post(
        "/api/showtimes",
        json={
            "hall_id": other_id,
            "film_title": "串厅",
            "start_at": datetime.utcnow().isoformat(),
            "layout_version_id": v1_id,
        },
    )
    assert r.status_code == 422
    assert "不属于" in r.json()["detail"]


def test_rebind_refused_while_holds_active(client):
    hall_id, v1_id, st_id, _hold_id = _seed_frozen_scenario()
    v2 = client.post(f"/api/halls/{hall_id}/versions", json={}).json()

    # 有持座的场次禁止换绑
    r = client.post(
        f"/api/showtimes/{st_id}/layout_version", json={"layout_version_id": v2["id"]}
    )
    assert r.status_code == 409
    assert "持座" in r.json()["detail"]

    # 无持座的场次可以换绑
    st3 = _new_showtime(client, hall_id, title="空场", version_id=v2["id"])
    r = client.post(
        f"/api/showtimes/{st3['id']}/layout_version", json={"layout_version_id": v1_id}
    )
    assert r.status_code == 200
    assert r.json()["layout_version_no"] == 1


# —— 旧持座坐标不变、旧场次仍按旧版本渲染 ——


def test_old_showtime_keeps_old_layout_and_hold_coords(client):
    hall_id, _v1_id, st_id, _hold_id = _seed_frozen_scenario()

    before = {h["id"]: h for h in client.get("/api/holds").json()}

    # 复制 v2（不同行列、无过道）并绑新场次
    r = client.post(
        f"/api/halls/{hall_id}/versions", json={"rows": 10, "cols": 14, "aisle_cols": []}
    )
    v2 = r.json()
    _new_showtime(client, hall_id, version_id=v2["id"])

    # 旧场次座位图仍按 v1 渲染：8×12、过道 5,6
    m = client.get(f"/api/seatmap/{st_id}").json()
    assert (m["rows"], m["cols"], m["layout_version_no"]) == (8, 12, 1)
    assert {c["col"] for c in m["cells"] if c["is_aisle"]} == {5, 6}
    occ = {(c["row"], c["col"]) for c in m["cells"] if c["occupied"]}
    assert occ == {(3, 2), (3, 3), (3, 4)}

    # 历史持座坐标未被静默改写
    after = client.get("/api/holds").json()
    assert len(after) == len(before)
    for h in after:
        o = before[h["id"]]
        assert (h["row"], h["start_col"], h["end_col"]) == (
            o["row"],
            o["start_col"],
            o["end_col"],
        )

    # 旧场次锁座仍受旧版本约束：过道 5,6 断行，12 人连座放不下
    r = client.post("/api/holds", json={"showtime_id": st_id, "party_size": 12})
    assert r.status_code == 409


# —— 旧库迁移回填 ——


def test_backfill_binds_legacy_showtimes(client):
    db = SessionLocal()
    try:
        hall = Hall(name="老厅", rows=5, cols=8, aisle_cols="4")
        db.add(hall)
        db.flush()
        st = Showtime(
            hall_id=hall.id,
            film_title="老片",
            start_at=datetime.utcnow(),
            layout_version_id=None,  # 版本机制上线前的遗留数据
        )
        db.add(st)
        db.commit()
        st_id = st.id

        backfill_all(db)

        db.refresh(st)
        assert st.layout_version_id is not None
        v = db.get(HallLayoutVersion, st.layout_version_id)
        assert (v.version_no, v.rows, v.cols, v.aisle_cols) == (1, 5, 8, "4")
    finally:
        db.close()

    m = client.get(f"/api/seatmap/{st_id}").json()
    assert (m["rows"], m["cols"], m["layout_version_no"]) == (5, 8, 1)
    assert {c["col"] for c in m["cells"] if c["is_aisle"]} == {4}
