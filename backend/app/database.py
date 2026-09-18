from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

if settings.database_url.startswith("sqlite"):
    # In-memory/file SQLite for tests: share one connection across sessions.
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def run_lightweight_migrations() -> None:
    """Idempotent column additions for databases created before a feature landed.

    create_all only creates missing tables; it never alters existing ones.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        if "showtimes" in tables:
            cols = {c["name"] for c in insp.get_columns("showtimes")}
            if "layout_version_id" not in cols:
                conn.execute(text("ALTER TABLE showtimes ADD COLUMN layout_version_id INTEGER"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
