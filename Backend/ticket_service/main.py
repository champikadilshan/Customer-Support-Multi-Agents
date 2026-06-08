from fastapi import FastAPI, HTTPException, Depends
from sqlmodel import Field, Session, SQLModel, create_engine, select
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional
from pathlib import Path
import uvicorn


# Database Setup
DB_PATH = Path(__file__).resolve().parent / "tickets.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, echo=False)

def get_session():
    with Session(engine) as session:
        yield session


# Enums
class TicketStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


# DB Model
class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str
    customer_id: str
    status: TicketStatus = TicketStatus.open
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Request / Response Schemas
class TicketCreate(BaseModel):
    title: str
    description: str
    customer_id: str

class TicketStatusUpdate(BaseModel):
    status: TicketStatus

class TicketResponse(BaseModel):
    id: int
    title: str
    description: str
    customer_id: str
    status: TicketStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# App
app = FastAPI(
    title="Ticket Service",
    description="Customer Support Ticket Service for Multi-Agent System",
    version="1.0.0",
)

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)


# Routes
@app.post("/tickets/", response_model=TicketResponse, status_code=201)
def create_ticket(payload: TicketCreate, session: Session = Depends(get_session)):
    """Create a new support ticket."""
    ticket = Ticket(**payload.model_dump())
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@app.get("/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket(ticket_id: int, session: Session = Depends(get_session)):
    """Get ticket details and current status."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=TicketResponse)
def update_ticket_status( ticket_id: int, payload: TicketStatusUpdate, session: Session = Depends(get_session),):
    """Update a ticket's status."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    ticket.status = payload.status
    ticket.updated_at = datetime.utcnow()
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


# Entry Point
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)