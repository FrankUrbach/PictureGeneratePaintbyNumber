import os

from sqlalchemy import text
from sqlmodel import SQLModel, create_engine, Session

DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/database.db"
engine = create_engine(DATABASE_URL, echo=False)


def create_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_db()


def _migrate_db() -> None:
    """Add columns introduced after the initial schema without dropping existing data."""
    new_columns = {
        "original_path": "ALTER TABLE template ADD COLUMN original_path TEXT NOT NULL DEFAULT ''",
        "blur": "ALTER TABLE template ADD COLUMN blur INTEGER NOT NULL DEFAULT 4",
        "numberless_regions": "ALTER TABLE template ADD COLUMN numberless_regions TEXT NOT NULL DEFAULT '[]'",
    }
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(template)"))}
        for col, sql in new_columns.items():
            if col not in existing:
                conn.execute(text(sql))
        conn.commit()


def get_session():
    with Session(engine) as session:
        yield session
