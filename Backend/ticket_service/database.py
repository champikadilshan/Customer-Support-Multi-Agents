from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

# DB file sits next to this module inside complaint_agent/
DB_PATH      = Path(__file__).resolve().parent / "complaints.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# echo=False keeps SQL out of logs in production;
# set echo=True temporarily if you need to debug queries
engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables() -> None:
    """
    Create all tables registered with SQLModel metadata.
    Safe to call multiple times — skips tables that already exist.
    Called once at FastAPI startup via @app.on_event("startup").
    """
    # models must be imported before this runs so SQLModel sees their metadata
    import complaint_agent.models  # noqa: F401
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """
    Return a plain Session used as a context manager inside each tool:

        with get_session() as session:
            rows = session.exec(select(ComplaintTicket)...).all()

    Each tool opens and closes its own session so tools remain stateless.
    """
    return Session(engine)