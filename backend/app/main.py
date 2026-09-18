from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import ensure_layout_versions, seed_if_empty


def _migrate_legacy_schema() -> None:
    """create_all 不会给已存在的表补列；老库在此幂等补齐。"""
    with engine.begin() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("showtimes")}
        if "layout_version_id" not in cols:
            conn.execute(text("ALTER TABLE showtimes ADD COLUMN layout_version_id INTEGER"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _migrate_legacy_schema()
    db = SessionLocal()
    try:
        if settings.seed_on_empty:
            seed_if_empty(db)
        ensure_layout_versions(db)
    finally:
        db.close()
    yield


app = FastAPI(title="SeatBond", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
