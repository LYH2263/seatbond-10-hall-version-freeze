from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import ConflictLog, Hall, HallLayoutVersion, SeatHold, Showtime


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(Hall.id).limit(1)):
        return
    h1 = Hall(name="一号厅", rows=8, cols=12, aisle_cols="5,6")
    h2 = Hall(name="二号厅", rows=6, cols=10, aisle_cols="4,5")
    db.add_all([h1, h2])
    db.flush()
    # 每个影厅的初始厅图版本 v1；场次创建即绑定版本。
    # 一号厅 v1 将被持座场次引用而冻结：演示「改过道被拒 → 复制新版本 → 新场次绑新版」。
    v1 = HallLayoutVersion(hall_id=h1.id, version_no=1, rows=8, cols=12, aisle_cols="5,6")
    v2 = HallLayoutVersion(hall_id=h2.id, version_no=1, rows=6, cols=10, aisle_cols="4,5")
    db.add_all([v1, v2])
    db.flush()
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    s1 = Showtime(
        hall_id=h1.id, film_title="星际旅人", start_at=now + timedelta(hours=2),
        layout_version_id=v1.id,
    )
    s2 = Showtime(
        hall_id=h1.id, film_title="雾都夜曲", start_at=now + timedelta(hours=5),
        layout_version_id=v1.id,
    )
    s3 = Showtime(
        hall_id=h2.id, film_title="山海经异", start_at=now + timedelta(hours=3),
        layout_version_id=v2.id,
    )
    db.add_all([s1, s2, s3])
    db.flush()
    db.add_all(
        [
            SeatHold(showtime_id=s1.id, order_code="SB-1001", row=3, start_col=2, end_col=4, party_size=3),
            SeatHold(showtime_id=s1.id, order_code="SB-1002", row=5, start_col=7, end_col=9, party_size=3),
            SeatHold(showtime_id=s3.id, order_code="SB-1003", row=2, start_col=1, end_col=2, party_size=2),
        ]
    )
    db.add(ConflictLog(showtime_id=s1.id, party_size=4, reason="与既有持座重叠：第3排 2-4"))
    db.commit()
