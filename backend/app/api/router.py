from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import ConflictLog, Hall, HallLayoutVersion, SeatHold, Showtime
from app.schemas.schemas import (
    ConflictOut,
    HallOut,
    HoldOut,
    HoldRequest,
    LayoutVersionCreate,
    LayoutVersionOut,
    LayoutVersionUpdate,
    SeatMapCell,
    SeatMapOut,
    ShowtimeBindVersion,
    ShowtimeCreate,
    ShowtimeOut,
)
from app.services import layout_versions as lv
from app.services.bond_engine import (
    HoldSpan,
    SeatCell,
    conflicts_with,
    find_bond_across_rows,
    find_contiguous_block,
)

api_router = APIRouter()


def _hall_out(h: Hall) -> HallOut:
    return HallOut(id=h.id, name=h.name, rows=h.rows, cols=h.cols, aisle_cols=lv.parse_aisles(h.aisle_cols))


def _showtime_out(db: Session, s: Showtime) -> ShowtimeOut:
    hall = db.get(Hall, s.hall_id)
    version = db.get(HallLayoutVersion, s.layout_version_id) if s.layout_version_id else None
    return ShowtimeOut(
        id=s.id,
        hall_id=s.hall_id,
        film_title=s.film_title,
        start_at=s.start_at,
        hall_name=hall.name if hall else None,
        layout_version_id=version.id if version else None,
        layout_version_no=version.version_no if version else None,
    )


def _version_out(db: Session, v: HallLayoutVersion) -> LayoutVersionOut:
    return LayoutVersionOut(
        id=v.id,
        hall_id=v.hall_id,
        version_no=v.version_no,
        rows=v.rows,
        cols=v.cols,
        aisle_cols=lv.parse_aisles(v.aisle_cols),
        frozen=lv.is_version_frozen(db, v.id),
        showtime_count=lv.showtime_count(db, v.id),
        created_at=v.created_at,
    )


def _get_version_or_404(db: Session, version_id: int) -> HallLayoutVersion:
    v = db.get(HallLayoutVersion, version_id)
    if not v:
        raise HTTPException(404, "厅图版本不存在")
    return v


def _validate_layout(rows: int, cols: int, aisle_cols: list[int]) -> None:
    err = lv.validate_layout(rows, cols, aisle_cols)
    if err:
        raise HTTPException(422, err)


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/halls", response_model=list[HallOut])
def list_halls(db: Session = Depends(get_db)):
    return [_hall_out(h) for h in db.scalars(select(Hall).order_by(Hall.id)).all()]


@api_router.get("/halls/{hall_id}/versions", response_model=list[LayoutVersionOut])
def list_layout_versions(hall_id: int, db: Session = Depends(get_db)):
    if not db.get(Hall, hall_id):
        raise HTTPException(404, "影厅不存在")
    versions = db.scalars(
        select(HallLayoutVersion)
        .where(HallLayoutVersion.hall_id == hall_id)
        .order_by(HallLayoutVersion.version_no)
    ).all()
    return [_version_out(db, v) for v in versions]


@api_router.post(
    "/halls/{hall_id}/versions", response_model=LayoutVersionOut, status_code=201
)
def create_layout_version(hall_id: int, body: LayoutVersionCreate, db: Session = Depends(get_db)):
    """Copy-as-new-version: the only way to change layout once the current
    version is frozen. Unspecified fields are inherited from the source."""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "影厅不存在")
    if body.source_version_id is not None:
        src = _get_version_or_404(db, body.source_version_id)
        if src.hall_id != hall_id:
            raise HTTPException(422, "源版本不属于该影厅")
    else:
        src = lv.latest_version(db, hall_id)
    rows = body.rows if body.rows is not None else (src.rows if src else hall.rows)
    cols = body.cols if body.cols is not None else (src.cols if src else hall.cols)
    aisles = (
        body.aisle_cols
        if body.aisle_cols is not None
        else (lv.parse_aisles(src.aisle_cols) if src else lv.parse_aisles(hall.aisle_cols))
    )
    _validate_layout(rows, cols, aisles)
    v = lv.create_version(db, hall, rows=rows, cols=cols, aisle_cols=aisles)
    db.commit()
    db.refresh(v)
    return _version_out(db, v)


@api_router.put("/versions/{version_id}", response_model=LayoutVersionOut)
def update_layout_version(
    version_id: int, body: LayoutVersionUpdate, db: Session = Depends(get_db)
):
    """Edit a version in place — only allowed while no showtime with active
    holds references it. Frozen versions must be copied to a new version."""
    v = _get_version_or_404(db, version_id)
    if lv.is_version_frozen(db, version_id):
        raise HTTPException(
            409,
            f"厅图版本 v{v.version_no} 已被持座场次引用并冻结："
            "禁止修改行列与过道，请复制为新版本供后续场次选用",
        )
    _validate_layout(body.rows, body.cols, body.aisle_cols)
    v.rows = body.rows
    v.cols = body.cols
    v.aisle_cols = lv.dump_aisles(body.aisle_cols)
    latest = lv.latest_version(db, v.hall_id)
    if latest and latest.id == v.id:
        lv.sync_hall_mirror(db, db.get(Hall, v.hall_id), v)  # keep halls.* mirror fresh
    db.commit()
    db.refresh(v)
    return _version_out(db, v)


@api_router.get("/showtimes", response_model=list[ShowtimeOut])
def list_showtimes(db: Session = Depends(get_db)):
    rows = db.scalars(select(Showtime).order_by(Showtime.start_at)).all()
    return [_showtime_out(db, s) for s in rows]


@api_router.post("/showtimes", response_model=ShowtimeOut, status_code=201)
def create_showtime(body: ShowtimeCreate, db: Session = Depends(get_db)):
    """Create a showtime bound to a layout version (default: the hall's latest).
    The binding is permanent for held seats — see the rebind endpoint."""
    hall = db.get(Hall, body.hall_id)
    if not hall:
        raise HTTPException(404, "影厅不存在")
    if body.layout_version_id is not None:
        v = _get_version_or_404(db, body.layout_version_id)
        if v.hall_id != hall.id:
            raise HTTPException(422, "厅图版本不属于该影厅")
    else:
        v = lv.ensure_version(db, hall)
    st = Showtime(
        hall_id=hall.id,
        film_title=body.film_title,
        start_at=body.start_at,
        layout_version_id=v.id,
    )
    db.add(st)
    db.commit()
    db.refresh(st)
    return _showtime_out(db, st)


@api_router.post("/showtimes/{showtime_id}/layout_version", response_model=ShowtimeOut)
def bind_showtime_version(
    showtime_id: int, body: ShowtimeBindVersion, db: Session = Depends(get_db)
):
    """Rebind a showtime to another layout version of the same hall. Refused
    while the showtime has active holds — rebinding would silently rewrite the
    meaning of historical held-seat coordinates."""
    st = db.get(Showtime, showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    v = _get_version_or_404(db, body.layout_version_id)
    if v.hall_id != st.hall_id:
        raise HTTPException(422, "厅图版本不属于该影厅")
    if lv.showtime_has_active_holds(db, showtime_id):
        raise HTTPException(
            409, "场次已存在持有中持座，禁止换绑厅图版本（历史持座坐标语义不可改写）"
        )
    st.layout_version_id = v.id
    db.commit()
    db.refresh(st)
    return _showtime_out(db, st)


@api_router.get("/seatmap/{showtime_id}", response_model=SeatMapOut)
def seatmap(showtime_id: int, db: Session = Depends(get_db)):
    st = db.get(Showtime, showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    hall = db.get(Hall, st.hall_id)
    assert hall
    version = lv.resolve_showtime_version(db, st)
    aisles = set(lv.parse_aisles(version.aisle_cols))
    holds = db.scalars(select(SeatHold).where(SeatHold.showtime_id == showtime_id)).all()
    occupied: set[tuple[int, int]] = set()
    for h in holds:
        for c in range(h.start_col, h.end_col + 1):
            occupied.add((h.row, c))
    cells: list[SeatMapCell] = []
    for r in range(1, version.rows + 1):
        for c in range(1, version.cols + 1):
            occ = (r, c) in occupied
            cells.append(
                SeatMapCell(
                    row=r,
                    col=c,
                    is_aisle=c in aisles,
                    occupied=occ,
                    heat=1.0 if occ else (0.15 if c in aisles else 0.0),
                )
            )
    return SeatMapOut(
        showtime_id=showtime_id,
        hall_name=hall.name,
        rows=version.rows,
        cols=version.cols,
        layout_version_no=version.version_no,
        cells=cells,
    )


@api_router.get("/holds", response_model=list[HoldOut])
def list_holds(db: Session = Depends(get_db)):
    return db.scalars(select(SeatHold).order_by(SeatHold.id.desc())).all()


@api_router.get("/conflicts", response_model=list[ConflictOut])
def list_conflicts(db: Session = Depends(get_db)):
    return db.scalars(select(ConflictLog).order_by(ConflictLog.id.desc())).all()


@api_router.post("/holds", response_model=HoldOut)
def create_hold(body: HoldRequest, db: Session = Depends(get_db)):
    st = db.get(Showtime, body.showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    version = lv.resolve_showtime_version(db, st)
    aisles = set(lv.parse_aisles(version.aisle_cols))
    existing = db.scalars(select(SeatHold).where(SeatHold.showtime_id == body.showtime_id)).all()
    holds = [HoldSpan(row=h.row, start_col=h.start_col, end_col=h.end_col) for h in existing]
    seats_by_row: dict[int, list[SeatCell]] = {}
    for r in range(1, version.rows + 1):
        seats_by_row[r] = [
            SeatCell(row=r, col=c, is_aisle=c in aisles) for c in range(1, version.cols + 1)
        ]

    block = None
    if body.preferred_row:
        block = find_contiguous_block(
            seats_by_row.get(body.preferred_row, []), holds, body.preferred_row, body.party_size
        )
    if block is None:
        block = find_bond_across_rows(seats_by_row, holds, body.party_size)
    if block is None:
        db.add(
            ConflictLog(
                showtime_id=body.showtime_id,
                party_size=body.party_size,
                reason=f"无足够连续空座（人数 {body.party_size}）",
            )
        )
        db.commit()
        raise HTTPException(409, "无足够连续空座")

    hits = conflicts_with(holds, block)
    if hits:
        db.add(
            ConflictLog(
                showtime_id=body.showtime_id,
                party_size=body.party_size,
                reason=f"与既有持座重叠：第{hits[0].row}排 {hits[0].start_col}-{hits[0].end_col}",
            )
        )
        db.commit()
        raise HTTPException(409, "与既有持座冲突")

    code = f"SB-{int(datetime.utcnow().timestamp()) % 100000:05d}"
    hold = SeatHold(
        showtime_id=body.showtime_id,
        order_code=code,
        row=block.row,
        start_col=block.start_col,
        end_col=block.end_col,
        party_size=body.party_size,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    return hold
