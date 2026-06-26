import uvicorn
import sys, os

from fastapi import FastAPI, HTTPException, Depends
from sqlmodel import Session, SQLModel, create_engine, select
from datetime import datetime
from pathlib import Path
from shared.config import TICKET_SERVICE_PORT
from ticket_service.models import (Ticket,TicketCreate, TicketResponse, TicketStatus, TicketUpdate,)

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

DB_PATH      = Path(__file__).resolve().parent / "tickets.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine       = create_engine(DATABASE_URL, echo=False)


def get_session():
    with Session(engine) as session:
        yield session


app = FastAPI(
    title="Ticket Service",
    description="Customer Support Ticket Service for Multi-Agent System",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)


@app.post("/tickets", response_model=TicketResponse, status_code=201)
def create_ticket(payload: TicketCreate,session: Session = Depends(get_session),):
    ticket = Ticket(**payload.model_dump())
    session.add(ticket)
    session.commit()
    session.refresh(ticket)

    return ticket


@app.get("/tickets", response_model=list[TicketResponse])
def list_tickets(session: Session = Depends(get_session)):
    return session.exec( select(Ticket).order_by(Ticket.created_at.desc())).all()


@app.get("/tickets/customer/{customer_id}", response_model=list[TicketResponse])
def get_tickets_by_customer(customer_id: str,session: Session = Depends(get_session),):
    tickets = session.exec( select(Ticket) .where(Ticket.customer_id == customer_id) .order_by(Ticket.created_at.desc())).all()

    if not tickets:
        raise HTTPException(
            status_code=404,
            detail=f"No tickets found for customer_id '{customer_id}'",
        )

    return tickets


@app.get("/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket(ticket_id: int,session: Session = Depends(get_session),):
    ticket = session.get(Ticket, ticket_id)

    if not ticket:
        raise HTTPException(
            status_code=404,
            detail=f"Ticket {ticket_id} not found",
        )

    return ticket


@app.patch("/tickets/{ticket_id}", response_model=TicketResponse)
def update_ticket(ticket_id: int, payload: TicketUpdate, session: Session = Depends(get_session),):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=404,
            detail=f"Ticket {ticket_id} not found",
        )

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


if __name__ == "__main__":
    uvicorn.run(
        "ticket_service.main:app",
        host="0.0.0.0",
        port=TICKET_SERVICE_PORT,
        reload=True,
    )