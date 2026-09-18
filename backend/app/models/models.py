from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Hall(Base):
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    aisle_cols: Mapped[str] = mapped_column(String(80), default="")  # comma-separated
    showtimes: Mapped[list["Showtime"]] = relationship(back_populates="hall")
    layout_versions: Mapped[list["HallLayoutVersion"]] = relationship(back_populates="hall")


class HallLayoutVersion(Base):
    """Immutable-ish snapshot of a hall layout (rows/cols/aisles).

    Every layout change creates a new version row instead of mutating history.
    A version referenced by a showtime that still has active holds is frozen:
    its rows/cols/aisle_cols must not change (enforced in the API layer).
    """

    __tablename__ = "hall_layout_versions"
    __table_args__ = (UniqueConstraint("hall_id", "version_no", name="uq_hall_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    aisle_cols: Mapped[str] = mapped_column(String(80), default="")  # comma-separated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    hall: Mapped[Hall] = relationship(back_populates="layout_versions")


class Showtime(Base):
    __tablename__ = "showtimes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    film_title: Mapped[str] = mapped_column(String(120))
    start_at: Mapped[datetime] = mapped_column(DateTime)
    # Bound at creation to one hall layout version; that version's rows/cols/aisles
    # govern this showtime's seat map and hold placement forever.
    layout_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("hall_layout_versions.id"), nullable=True
    )
    hall: Mapped[Hall] = relationship(back_populates="showtimes")
    layout_version: Mapped[HallLayoutVersion | None] = relationship()
    holds: Mapped[list["SeatHold"]] = relationship(back_populates="showtime")


class SeatHold(Base):
    __tablename__ = "seat_holds"
    __table_args__ = (UniqueConstraint("showtime_id", "row", "start_col", "end_col", name="uq_hold_span"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    showtime_id: Mapped[int] = mapped_column(ForeignKey("showtimes.id"))
    order_code: Mapped[str] = mapped_column(String(40))
    row: Mapped[int] = mapped_column(Integer)
    start_col: Mapped[int] = mapped_column(Integer)
    end_col: Mapped[int] = mapped_column(Integer)
    party_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="held")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    showtime: Mapped[Showtime] = relationship(back_populates="holds")


class ConflictLog(Base):
    __tablename__ = "conflict_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    showtime_id: Mapped[int] = mapped_column(ForeignKey("showtimes.id"))
    party_size: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
