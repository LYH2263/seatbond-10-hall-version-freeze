from datetime import datetime
from pydantic import BaseModel, Field


class HallOut(BaseModel):
    id: int
    name: str
    rows: int
    cols: int
    aisle_cols: list[int]
    current_version: int | None = None
    current_version_frozen: bool = False
    model_config = {"from_attributes": True}


class LayoutVersionOut(BaseModel):
    id: int
    hall_id: int
    version: int
    rows: int
    cols: int
    aisle_cols: list[int]
    frozen: bool
    bound_showtimes: int
    created_at: datetime
    model_config = {"from_attributes": True}


class LayoutVersionCreate(BaseModel):
    base_version_id: int | None = None  # 缺省取本厅最新版本
    rows: int | None = Field(default=None, ge=1, le=60)
    cols: int | None = Field(default=None, ge=1, le=60)
    aisle_cols: list[int] | None = None


class LayoutVersionUpdate(BaseModel):
    rows: int | None = Field(default=None, ge=1, le=60)
    cols: int | None = Field(default=None, ge=1, le=60)
    aisle_cols: list[int] | None = None


class ShowtimeCreate(BaseModel):
    hall_id: int
    film_title: str = Field(min_length=1, max_length=120)
    start_at: datetime
    layout_version_id: int | None = None  # 缺省绑本厅最新版本


class ShowtimeOut(BaseModel):
    id: int
    hall_id: int
    film_title: str
    start_at: datetime
    hall_name: str | None = None
    layout_version_id: int | None = None
    layout_version: int | None = None
    layout_frozen: bool = False
    model_config = {"from_attributes": True}


class HoldOut(BaseModel):
    id: int
    showtime_id: int
    order_code: str
    row: int
    start_col: int
    end_col: int
    party_size: int
    status: str
    model_config = {"from_attributes": True}


class HoldRequest(BaseModel):
    showtime_id: int
    party_size: int = Field(ge=1, le=12)
    preferred_row: int | None = None


class ConflictOut(BaseModel):
    id: int
    showtime_id: int
    party_size: int
    reason: str
    created_at: datetime
    model_config = {"from_attributes": True}


class SeatMapCell(BaseModel):
    row: int
    col: int
    is_aisle: bool
    occupied: bool
    heat: float


class SeatMapOut(BaseModel):
    showtime_id: int
    hall_name: str
    rows: int
    cols: int
    layout_version: int
    cells: list[SeatMapCell]
