from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

DB_PATH      = Path(__file__).resolve().parent / "billing.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables() -> None:
    """
    Create all tables that are registered with SQLModel metadata.
    Safe to call multiple times — skips tables that already exist.
    Called once at FastAPI startup via @app.on_event("startup").
    """
    import billing_agent.models  # noqa: F401
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """
    Return a plain Session (not a generator).
    Used directly inside @tool functions:

        with get_session() as session:
            rows = session.exec(select(Invoice)...).all()

    Each tool opens and closes its own session so tools remain stateless.
    """
    return Session(engine)