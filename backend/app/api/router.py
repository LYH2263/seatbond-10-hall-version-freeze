from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
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
    ShowtimeCreate,
    ShowtimeOut,
)
from app.services.bond_engine import (
    HoldSpan,
    SeatCell,
    conflicts_with,
    find_bond_across_rows,
    find_contiguous_block,
)

api_router = APIRouter()


def _parse_aisles(raw: str) -> list[int]:
    if not raw.strip():
        return []
    return [int(x) for x in raw.split(",") if x.strip()]


def _normalize_aisles(aisles: list[int], cols: int) -> str:
    xs = sorted(set(aisles))
    bad = [a for a in xs if a < 1 or a > cols]
    if bad:
        raise HTTPException(400, f"过道列超出 1-{cols} 范围：{bad}")
    return ",".join(str(a) for a in xs)


def _latest_version(db: Session, hall_id: int) -> HallLayoutVersion | None:
    return db.scalars(
        select(HallLayoutVersion)
        .where(HallLayoutVersion.hall_id == hall_id)
        .order_by(HallLayoutVersion.version.desc())
        .limit(1)
    ).first()


def _version_frozen(db: Session, version_id: int) -> bool:
    """冻结 = 有场次绑定该版本，且该场次仍存在持有中持座。"""
    stmt = (
        select(SeatHold.id)
        .join(Showtime, Showtime.id == SeatHold.showtime_id)
        .where(Showtime.layout_version_id == version_id, SeatHold.status == "held")
        .limit(1)
    )
    return db.scalar(stmt) is not None


def _version_out(db: Session, v: HallLayoutVersion) -> LayoutVersionOut:
    bound = db.scalar(
        select(func.count(Showtime.id)).where(Showtime.layout_version_id == v.id)
    ) or 0
    return LayoutVersionOut(
        id=v.id,
        hall_id=v.hall_id,
        version=v.version,
        rows=v.rows,
        cols=v.cols,
        aisle_cols=_parse_aisles(v.aisle_cols),
        frozen=_version_frozen(db, v.id),
        bound_showtimes=bound,
        created_at=v.created_at,
    )


def _resolve_version(db: Session, st: Showtime) -> HallLayoutVersion:
    """场次渲染/锁座一律走其绑定版本；历史未绑定的回退到本厅最新版本。"""
    if st.layout_version_id is not None:
        v = db.get(HallLayoutVersion, st.layout_version_id)
        if v:
            return v
    v = _latest_version(db, st.hall_id)
    if not v:
        raise HTTPException(500, "影厅缺少厅图版本")
    return v


def _hall_out(db: Session, h: Hall) -> HallOut:
    latest = _latest_version(db, h.id)
    return HallOut(
        id=h.id,
        name=h.name,
        rows=h.rows,
        cols=h.cols,
        aisle_cols=_parse_aisles(h.aisle_cols),
        current_version=latest.version if latest else None,
        current_version_frozen=_version_frozen(db, latest.id) if latest else False,
    )


def _showtime_out(db: Session, s: Showtime) -> ShowtimeOut:
    hall = db.get(Hall, s.hall_id)
    v = db.get(HallLayoutVersion, s.layout_version_id) if s.layout_version_id else None
    return ShowtimeOut(
        id=s.id,
        hall_id=s.hall_id,
        film_title=s.film_title,
        start_at=s.start_at,
        hall_name=hall.name if hall else None,
        layout_version_id=s.layout_version_id,
        layout_version=v.version if v else None,
        layout_frozen=_version_frozen(db, v.id) if v else False,
    )


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/halls", response_model=list[HallOut])
def list_halls(db: Session = Depends(get_db)):
    return [_hall_out(db, h) for h in db.scalars(select(Hall).order_by(Hall.id)).all()]


@api_router.get("/halls/{hall_id}/layout-versions", response_model=list[LayoutVersionOut])
def list_layout_versions(hall_id: int, db: Session = Depends(get_db)):
    if not db.get(Hall, hall_id):
        raise HTTPException(404, "影厅不存在")
    versions = db.scalars(
        select(HallLayoutVersion)
        .where(HallLayoutVersion.hall_id == hall_id)
        .order_by(HallLayoutVersion.version)
    ).all()
    return [_version_out(db, v) for v in versions]


@api_router.get("/layout-versions/{version_id}", response_model=LayoutVersionOut)
def get_layout_version(version_id: int, db: Session = Depends(get_db)):
    v = db.get(HallLayoutVersion, version_id)
    if not v:
        raise HTTPException(404, "厅图版本不存在")
    return _version_out(db, v)


@api_router.post("/halls/{hall_id}/layout-versions", response_model=LayoutVersionOut)
def create_layout_version(hall_id: int, body: LayoutVersionCreate, db: Session = Depends(get_db)):
    """复制/新建厅图版本：缺省以本厅最新版本为底，可覆盖行列与过道。"""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "影厅不存在")
    if body.base_version_id is not None:
        base = db.get(HallLayoutVersion, body.base_version_id)
        if not base or base.hall_id != hall_id:
            raise HTTPException(400, "基准版本不属于该影厅")
    else:
        base = _latest_version(db, hall_id)
    rows = body.rows if body.rows is not None else (base.rows if base else hall.rows)
    cols = body.cols if body.cols is not None else (base.cols if base else hall.cols)
    aisles = (
        body.aisle_cols
        if body.aisle_cols is not None
        else _parse_aisles(base.aisle_cols if base else hall.aisle_cols)
    )
    aisle_str = _normalize_aisles(aisles, cols)
    next_no = (
        db.scalar(
            select(func.max(HallLayoutVersion.version)).where(HallLayoutVersion.hall_id == hall_id)
        )
        or 0
    ) + 1
    v = HallLayoutVersion(
        hall_id=hall_id, version=next_no, rows=rows, cols=cols, aisle_cols=aisle_str
    )
    db.add(v)
    # 影厅表镜像最新版本，供列表展示
    hall.rows, hall.cols, hall.aisle_cols = rows, cols, aisle_str
    db.commit()
    db.refresh(v)
    return _version_out(db, v)


@api_router.put("/layout-versions/{version_id}", response_model=LayoutVersionOut)
def update_layout_version(
    version_id: int, body: LayoutVersionUpdate, db: Session = Depends(get_db)
):
    """原地修改版本：仅未冻结版本允许；冻结版本必须复制为新版本。"""
    v = db.get(HallLayoutVersion, version_id)
    if not v:
        raise HTTPException(404, "厅图版本不存在")
    if _version_frozen(db, v.id):
        raise HTTPException(
            409,
            f"厅图版本 v{v.version} 已被场次引用且存在持有中持座，已冻结："
            "禁止修改行列与过道，请复制为新版本供后续场次选用",
        )
    rows = body.rows if body.rows is not None else v.rows
    cols = body.cols if body.cols is not None else v.cols
    aisles = body.aisle_cols if body.aisle_cols is not None else _parse_aisles(v.aisle_cols)
    v.rows, v.cols = rows, cols
    v.aisle_cols = _normalize_aisles(aisles, cols)
    latest = _latest_version(db, v.hall_id)
    hall = db.get(Hall, v.hall_id)
    if latest and latest.id == v.id and hall:
        hall.rows, hall.cols, hall.aisle_cols = v.rows, v.cols, v.aisle_cols
    db.commit()
    db.refresh(v)
    return _version_out(db, v)


@api_router.get("/showtimes", response_model=list[ShowtimeOut])
def list_showtimes(db: Session = Depends(get_db)):
    rows = db.scalars(select(Showtime).order_by(Showtime.start_at)).all()
    return [_showtime_out(db, s) for s in rows]


@api_router.post("/showtimes", response_model=ShowtimeOut)
def create_showtime(body: ShowtimeCreate, db: Session = Depends(get_db)):
    hall = db.get(Hall, body.hall_id)
    if not hall:
        raise HTTPException(404, "影厅不存在")
    if body.layout_version_id is not None:
        v = db.get(HallLayoutVersion, body.layout_version_id)
        if not v:
            raise HTTPException(404, "厅图版本不存在")
        if v.hall_id != hall.id:
            raise HTTPException(400, "厅图版本不属于该影厅")
    else:
        v = _latest_version(db, hall.id)
        if not v:
            raise HTTPException(409, "影厅缺少可用厅图版本")
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


@api_router.get("/seatmap/{showtime_id}", response_model=SeatMapOut)
def seatmap(showtime_id: int, db: Session = Depends(get_db)):
    st = db.get(Showtime, showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    hall = db.get(Hall, st.hall_id)
    assert hall
    version = _resolve_version(db, st)
    aisles = set(_parse_aisles(version.aisle_cols))
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
        layout_version=version.version,
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
    version = _resolve_version(db, st)
    aisles = set(_parse_aisles(version.aisle_cols))
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
