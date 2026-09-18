from datetime import datetime
from pydantic import BaseModel, Field


class HallOut(BaseModel):
    id: int
    name: str
    rows: int
    cols: int
    aisle_cols: list[int]
    model_config = {"from_attributes": True}


class ShowtimeOut(BaseModel):
    id: int
    hall_id: int
    film_title: str
    start_at: datetime
    hall_name: str | None = None
    layout_version_id: int | None = None
    layout_version_no: int | None = None
    model_config = {"from_attributes": True}


class ShowtimeCreate(BaseModel):
    hall_id: int
    film_title: str = Field(min_length=1, max_length=120)
    start_at: datetime
    layout_version_id: int | None = None  # default: hall's latest version


class ShowtimeBindVersion(BaseModel):
    layout_version_id: int


class LayoutVersionOut(BaseModel):
    id: int
    hall_id: int
    version_no: int
    rows: int
    cols: int
    aisle_cols: list[int]
    frozen: bool
    showtime_count: int
    created_at: datetime


class LayoutVersionUpdate(BaseModel):
    rows: int = Field(ge=1, le=60)
    cols: int = Field(ge=1, le=60)
    aisle_cols: list[int] = []


class LayoutVersionCreate(BaseModel):
    """Copy-as-new-version: unspecified fields are inherited from the source
    (explicit source_version_id, else the hall's latest version)."""

    source_version_id: int | None = None
    rows: int | None = Field(default=None, ge=1, le=60)
    cols: int | None = Field(default=None, ge=1, le=60)
    aisle_cols: list[int] | None = None


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
    layout_version_no: int | None = None
    cells: list[SeatMapCell]
