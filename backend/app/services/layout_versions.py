"""Hall layout versioning: freeze rules, version resolution, and backfill.

A layout version is frozen once any showtime bound to it still has holds in
status "held". Frozen versions reject rows/cols/aisle_cols changes; callers
must copy a new version instead. Showtimes always resolve their layout from
the version they were bound to, so historical holds keep their meaning even
after newer versions exist.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Hall, HallLayoutVersion, SeatHold, Showtime

ACTIVE_HOLD_STATUS = "held"


def parse_aisles(raw: str) -> list[int]:
    if not raw or not raw.strip():
        return []
    return [int(x) for x in raw.split(",") if x.strip()]


def dump_aisles(cols: list[int]) -> str:
    """Normalize aisle cols: unique, ascending, comma-separated."""
    return ",".join(str(c) for c in sorted(set(cols)))


def validate_layout(rows: int, cols: int, aisle_cols: list[int]) -> str | None:
    """Return an error message if the layout is invalid, else None."""
    if rows < 1 or cols < 1:
        return "行数与列数必须为正整数"
    bad = [c for c in aisle_cols if c < 1 or c > cols]
    if bad:
        return f"过道列 {bad} 超出 1..{cols} 范围"
    return None


def latest_version(db: Session, hall_id: int) -> HallLayoutVersion | None:
    return db.scalars(
        select(HallLayoutVersion)
        .where(HallLayoutVersion.hall_id == hall_id)
        .order_by(HallLayoutVersion.version_no.desc())
        .limit(1)
    ).first()


def ensure_version(db: Session, hall: Hall) -> HallLayoutVersion:
    """Return the hall's latest version, creating v1 from the hall mirror if none."""
    v = latest_version(db, hall.id)
    if v is None:
        v = HallLayoutVersion(
            hall_id=hall.id,
            version_no=1,
            rows=hall.rows,
            cols=hall.cols,
            aisle_cols=dump_aisles(parse_aisles(hall.aisle_cols)),
        )
        db.add(v)
        db.flush()
    return v


def create_version(
    db: Session,
    hall: Hall,
    rows: int,
    cols: int,
    aisle_cols: list[int],
) -> HallLayoutVersion:
    """Append a new version (version_no = max + 1) and move the hall mirror to it."""
    latest = latest_version(db, hall.id)
    next_no = (latest.version_no + 1) if latest else 1
    v = HallLayoutVersion(
        hall_id=hall.id,
        version_no=next_no,
        rows=rows,
        cols=cols,
        aisle_cols=dump_aisles(aisle_cols),
    )
    db.add(v)
    db.flush()
    sync_hall_mirror(db, hall, v)
    return v


def sync_hall_mirror(db: Session, hall: Hall, version: HallLayoutVersion) -> None:
    """Keep halls.rows/cols/aisle_cols mirroring the latest version (legacy readers)."""
    hall.rows = version.rows
    hall.cols = version.cols
    hall.aisle_cols = version.aisle_cols
    db.flush()


def is_version_frozen(db: Session, version_id: int) -> bool:
    """Frozen iff a showtime bound to this version still has a held hold."""
    stmt = (
        select(SeatHold.id)
        .join(Showtime, Showtime.id == SeatHold.showtime_id)
        .where(
            Showtime.layout_version_id == version_id,
            SeatHold.status == ACTIVE_HOLD_STATUS,
        )
        .limit(1)
    )
    return db.scalar(stmt) is not None


def showtime_count(db: Session, version_id: int) -> int:
    return db.scalar(
        select(func.count(Showtime.id)).where(Showtime.layout_version_id == version_id)
    ) or 0


def showtime_has_active_holds(db: Session, showtime_id: int) -> bool:
    stmt = (
        select(SeatHold.id)
        .where(
            SeatHold.showtime_id == showtime_id,
            SeatHold.status == ACTIVE_HOLD_STATUS,
        )
        .limit(1)
    )
    return db.scalar(stmt) is not None


def resolve_showtime_version(db: Session, showtime: Showtime) -> HallLayoutVersion:
    """The layout version governing a showtime (bound version; legacy fallback: latest)."""
    if showtime.layout_version_id is not None:
        v = db.get(HallLayoutVersion, showtime.layout_version_id)
        if v is not None:
            return v
    hall = db.get(Hall, showtime.hall_id)
    assert hall
    return ensure_version(db, hall)


def backfill_all(db: Session) -> None:
    """Idempotent upgrade for pre-versioning data: give every hall a v1 and bind
    every unbound showtime to its hall's latest version."""
    halls = db.scalars(select(Hall).order_by(Hall.id)).all()
    for hall in halls:
        ensure_version(db, hall)
    db.flush()
    unbound = db.scalars(select(Showtime).where(Showtime.layout_version_id.is_(None))).all()
    for st in unbound:
        v = latest_version(db, st.hall_id)
        if v is not None:
            st.layout_version_id = v.id
    db.commit()
