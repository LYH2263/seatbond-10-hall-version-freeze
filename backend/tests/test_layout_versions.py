"""厅图版本冻结：冻结拒绝、新版本可用、旧持座坐标不变。"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Hall, HallLayoutVersion, SeatHold, Showtime
from app.services.seed import ensure_layout_versions

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
SessionTest = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_db():
    db = SessionTest()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_db


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionTest()
    yield session
    session.close()


def make_hall(db, name="测试厅", rows=5, cols=8, aisles="4"):
    hall = Hall(name=name, rows=rows, cols=cols, aisle_cols=aisles)
    db.add(hall)
    db.flush()
    v1 = HallLayoutVersion(hall_id=hall.id, version=1, rows=rows, cols=cols, aisle_cols=aisles)
    db.add(v1)
    db.flush()
    return hall, v1


def make_showtime(db, hall, version, title="测试片"):
    st = Showtime(
        hall_id=hall.id,
        film_title=title,
        start_at=datetime(2026, 9, 20, 19, 30),
        layout_version_id=version.id,
    )
    db.add(st)
    db.flush()
    return st


def make_hold(db, showtime, row=2, start_col=1, end_col=2, status="held"):
    hold = SeatHold(
        showtime_id=showtime.id,
        order_code=f"SB-{showtime.id}-{row}-{start_col}",
        row=row,
        start_col=start_col,
        end_col=end_col,
        party_size=end_col - start_col + 1,
        status=status,
    )
    db.add(hold)
    db.flush()
    return hold


# —— 冻结拒绝 ——


def test_frozen_version_rejects_aisle_edit(client, db):
    hall, v1 = make_hall(db)
    st = make_showtime(db, hall, v1)
    make_hold(db, st)
    db.commit()

    resp = client.put(f"/api/layout-versions/{v1.id}", json={"aisle_cols": [2, 3]})
    assert resp.status_code == 409
    assert "冻结" in resp.json()["detail"]

    db.expire_all()
    assert db.get(HallLayoutVersion, v1.id).aisle_cols == "4"


def test_frozen_version_rejects_row_col_edit(client, db):
    hall, v1 = make_hall(db)
    st = make_showtime(db, hall, v1)
    make_hold(db, st)
    db.commit()

    resp = client.put(f"/api/layout-versions/{v1.id}", json={"rows": 6, "cols": 10})
    assert resp.status_code == 409

    db.expire_all()
    v = db.get(HallLayoutVersion, v1.id)
    assert (v.rows, v.cols) == (5, 8)


def test_frozen_status_visible_in_version_list(client, db):
    hall, v1 = make_hall(db)
    st = make_showtime(db, hall, v1)
    make_hold(db, st)
    db.commit()

    versions = client.get(f"/api/halls/{hall.id}/layout-versions").json()
    assert len(versions) == 1
    assert versions[0]["frozen"] is True
    assert versions[0]["bound_showtimes"] == 1

    single = client.get(f"/api/layout-versions/{v1.id}").json()
    assert single["frozen"] is True


def test_unfrozen_version_allows_edit(client, db):
    hall, v1 = make_hall(db)
    make_showtime(db, hall, v1)  # 绑定了场次但无持座 → 未冻结
    db.commit()

    resp = client.put(f"/api/layout-versions/{v1.id}", json={"aisle_cols": [2, 3]})
    assert resp.status_code == 200
    assert resp.json()["aisle_cols"] == [2, 3]

    db.expire_all()
    assert db.get(Hall, hall.id).aisle_cols == "2,3"  # 最新版本镜像到影厅


def test_released_holds_unfreeze_version(client, db):
    hall, v1 = make_hall(db)
    st = make_showtime(db, hall, v1)
    make_hold(db, st, status="released")
    db.commit()

    resp = client.put(f"/api/layout-versions/{v1.id}", json={"rows": 6})
    assert resp.status_code == 200
    assert resp.json()["rows"] == 6


# —— 新版本可用 ——


def test_new_version_usable_for_new_showtime(client, db):
    hall, v1 = make_hall(db)  # 5×8，过道列 4
    st_old = make_showtime(db, hall, v1, "旧片")
    make_hold(db, st_old)
    db.commit()

    # 冻结版本上复制出新版本：去掉过道
    resp = client.post(f"/api/halls/{hall.id}/layout-versions", json={"aisle_cols": []})
    assert resp.status_code == 200
    v2 = resp.json()
    assert v2["version"] == 2
    assert v2["frozen"] is False
    assert v2["aisle_cols"] == []

    # 新场次绑新版本
    resp = client.post(
        "/api/showtimes",
        json={
            "hall_id": hall.id,
            "film_title": "新片",
            "start_at": "2026-09-21T20:00:00",
            "layout_version_id": v2["id"],
        },
    )
    assert resp.status_code == 200
    st_new = resp.json()
    assert st_new["layout_version"] == 2
    assert st_new["layout_frozen"] is False

    # 新场次座图按 v2 渲染：无过道
    sm = client.get(f"/api/seatmap/{st_new['id']}").json()
    assert sm["layout_version"] == 2
    assert not any(c["is_aisle"] for c in sm["cells"])

    # 新过道下锁 4 连座：v2 无过道 → 第1排 1-4；若误用 v1（过道4）只能 5-8
    resp = client.post(
        "/api/holds",
        json={"showtime_id": st_new["id"], "party_size": 4, "preferred_row": 1},
    )
    assert resp.status_code == 200
    hold = resp.json()
    assert (hold["row"], hold["start_col"], hold["end_col"]) == (1, 1, 4)


def test_showtime_create_defaults_to_latest_version(client, db):
    hall, v1 = make_hall(db)
    db.commit()
    v2 = client.post(
        f"/api/halls/{hall.id}/layout-versions", json={"aisle_cols": [2]}
    ).json()

    resp = client.post(
        "/api/showtimes",
        json={"hall_id": hall.id, "film_title": "片", "start_at": "2026-09-22T10:00:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["layout_version"] == v2["version"]


def test_showtime_create_rejects_foreign_version(client, db):
    hall, v1 = make_hall(db)
    other, ov1 = make_hall(db, name="另一厅", rows=4, cols=6, aisles="")
    db.commit()

    resp = client.post(
        "/api/showtimes",
        json={
            "hall_id": hall.id,
            "film_title": "片",
            "start_at": "2026-09-22T12:00:00",
            "layout_version_id": ov1.id,
        },
    )
    assert resp.status_code == 400


# —— 旧持座坐标不变 ——


def test_old_showtime_keeps_version_and_hold_coords(client, db):
    hall, v1 = make_hall(db)  # 过道列 4
    st_old = make_showtime(db, hall, v1)
    make_hold(db, st_old, row=3, start_col=1, end_col=3)
    db.commit()

    # 新版本换过道列 2，并绑给新场次
    v2 = client.post(
        f"/api/halls/{hall.id}/layout-versions", json={"aisle_cols": [2]}
    ).json()
    resp = client.post(
        "/api/showtimes",
        json={
            "hall_id": hall.id,
            "film_title": "新片",
            "start_at": "2026-09-21T20:00:00",
            "layout_version_id": v2["id"],
        },
    )
    assert resp.status_code == 200

    # 旧场次座图仍按 v1 渲染：col4 是过道、col2 不是，持座格位置不变
    sm = client.get(f"/api/seatmap/{st_old.id}").json()
    assert sm["layout_version"] == 1
    cell = {(c["row"], c["col"]): c for c in sm["cells"]}
    assert cell[(1, 4)]["is_aisle"] is True
    assert cell[(1, 2)]["is_aisle"] is False
    assert cell[(3, 1)]["occupied"] and cell[(3, 2)]["occupied"] and cell[(3, 3)]["occupied"]

    # 历史持座坐标未被静默改写
    db.expire_all()
    hold = db.scalar(select(SeatHold).where(SeatHold.showtime_id == st_old.id))
    assert (hold.row, hold.start_col, hold.end_col) == (3, 1, 3)

    # 旧场次锁座仍按 v1 过道：party 3 第1排 → 1-3（v2 过道2 下会是 3-5）
    resp = client.post(
        "/api/holds",
        json={"showtime_id": st_old.id, "party_size": 3, "preferred_row": 1},
    )
    assert resp.status_code == 200
    h2 = resp.json()
    assert (h2["start_col"], h2["end_col"]) == (1, 3)


def test_aisle_out_of_range_rejected(client, db):
    hall, v1 = make_hall(db)
    db.commit()

    resp = client.put(f"/api/layout-versions/{v1.id}", json={"aisle_cols": [9]})
    assert resp.status_code == 400
    assert "超出" in resp.json()["detail"]


# —— 老库回填 ——


def test_ensure_layout_versions_backfills_legacy(db):
    hall = Hall(name="老厅", rows=5, cols=8, aisle_cols="4")
    db.add(hall)
    db.flush()
    st = Showtime(
        hall_id=hall.id,
        film_title="老片",
        start_at=datetime(2026, 9, 20, 18, 0),
        layout_version_id=None,
    )
    db.add(st)
    db.commit()

    ensure_layout_versions(db)
    ensure_layout_versions(db)  # 幂等：重复执行不增生版本

    versions = db.scalars(
        select(HallLayoutVersion).where(HallLayoutVersion.hall_id == hall.id)
    ).all()
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].aisle_cols == "4"

    db.expire_all()
    assert db.get(Showtime, st.id).layout_version_id == versions[0].id
