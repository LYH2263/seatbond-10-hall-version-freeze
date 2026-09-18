from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine, run_lightweight_migrations
from app.services.layout_versions import backfill_all
from app.services.seed import seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    db = SessionLocal()
    try:
        if settings.seed_on_empty:
            seed_if_empty(db)
        backfill_all(db)  # legacy halls/showtimes get v1 + bindings; no-op when fresh
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
