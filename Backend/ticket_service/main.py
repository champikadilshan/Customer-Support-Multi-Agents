from fastapi import FastAPI, HTTPException, Depends
from sqlmodel import Field, Session, SQLModel, create_engine, select
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional
from pathlib import Path
import uvicorn

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.config import TICKET_SERVICE_PORT


# =============================================================================
# DATABASE SETUP
# =============================================================================

DB_PATH      = Path(__file__).resolve().parent / "tickets.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine       = create_engine(DATABASE_URL, echo=False)


def get_session():
    with Session(engine) as session:
        yield session


# =============================================================================
# ENUMS
# =============================================================================

class TicketStatus(str, Enum):
    open        = "open"
    in_progress = "in_progress"
    resolved    = "resolved"
    closed      = "closed"


# =============================================================================
# DB MODEL
# =============================================================================

class Ticket(SQLModel, table=True):
    id:          Optional[int]      = Field(default=None, primary_key=True)
    title:       str
    description: str
    customer_id: str                = Field(index=True)
    status:      TicketStatus       = Field(default=TicketStatus.open)

    # Fields added for complaint agent context
    category:    Optional[str]      = Field(default=None)   # billing_dispute | service_outage | etc.
    priority:    Optional[str]      = Field(default=None)   # low | medium | high | critical
    assigned_to: Optional[str]      = Field(default=None)   # e.g. "Agent Sarah"

    created_at:  datetime           = Field(default_factory=datetime.utcnow)
    updated_at:  datetime           = Field(default_factory=datetime.utcnow)


# =============================================================================
# REQUEST / RESPONSE SCHEMAS
# =============================================================================

class TicketCreate(BaseModel):
    title:       str
    description: str
    customer_id: str
    category:    Optional[str] = None
    priority:    Optional[str] = None
    assigned_to: Optional[str] = None


class TicketUpdate(BaseModel):
    """Used for PATCH — all fields optional, only provided ones are updated."""
    status:      Optional[TicketStatus] = None
    category:    Optional[str]          = None
    priority:    Optional[str]          = None
    assigned_to: Optional[str]          = None


class TicketResponse(BaseModel):
    id:          int
    title:       str
    description: str
    customer_id: str
    status:      TicketStatus
    category:    Optional[str]
    priority:    Optional[str]
    assigned_to: Optional[str]
    created_at:  datetime
    updated_at:  datetime

    class Config:
        from_attributes = True


# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title="Ticket Service",
    description="Customer Support Ticket Service for Multi-Agent System",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup():
    """Create DB tables on first run. Safe to call on every restart."""
    SQLModel.metadata.create_all(engine)


# =============================================================================
# ROUTES
# =============================================================================

@app.post("/tickets", response_model=TicketResponse, status_code=201)
def create_ticket(
    payload: TicketCreate,
    session: Session = Depends(get_session),
):
    """Create a new support ticket."""
    ticket = Ticket(**payload.model_dump())
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@app.get("/tickets/customer/{customer_id}", response_model=list[TicketResponse])
def get_tickets_by_customer(
    customer_id: str,
    session: Session = Depends(get_session),
):
    """
    Get all tickets for a given customer, ordered by most recent first.
    Used by the complaint agent's get_complaint_history tool.
    """
    tickets = session.exec(
        select(Ticket)
        .where(Ticket.customer_id == customer_id)
        .order_by(Ticket.created_at.desc())
    ).all()

    if not tickets:
        raise HTTPException(
            status_code=404,
            detail=f"No tickets found for customer_id '{customer_id}'",
        )

    return tickets


@app.get("/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: int,
    session: Session = Depends(get_session),
):
    """Get a single ticket's details and current status."""
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=404,
            detail=f"Ticket {ticket_id} not found",
        )
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    session: Session = Depends(get_session),
):
    """
    Update a ticket's status, category, priority, or assigned_to.
    Only fields explicitly provided in the request body are updated.
    """
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=404,
            detail=f"Ticket {ticket_id} not found",
        )

    # Only apply fields that were actually provided (not None)
    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(ticket, field, value)

    ticket.updated_at = datetime.utcnow()
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@app.get("/health")
def health():
    return {"status": "ok", "service": "ticket_service"}


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "ticket_service.main:app",
        host="0.0.0.0",
        port=TICKET_SERVICE_PORT,
        reload=True,
    )