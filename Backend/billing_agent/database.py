from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

DB_PATH      = Path(__file__).resolve().parent / "billing.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables() -> None:
    import billing_agent.models  # noqa: F401
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)