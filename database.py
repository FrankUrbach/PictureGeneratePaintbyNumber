import os

from sqlmodel import SQLModel, create_engine, Session

# DATA_DIR points to the Railway volume mount path (e.g. /data).
# Locally it defaults to ./data so the project stays self-contained.
DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/database.db"
engine = create_engine(DATABASE_URL, echo=False)


def create_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
