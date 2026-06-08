"""
Seed the ticket service database with realistic sample data.

Run once from the project root:
    python -m ticket_service.seed

Or directly:
    python ticket_service/seed.py

Idempotent — skips insert if tickets already exist.
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select
from ticket_service.main import engine, Ticket, TicketStatus, on_startup


# =============================================================================
# SAMPLE TICKETS
# =============================================================================

TICKETS = [
    # CUST-001 — 4 tickets covering different categories
    Ticket(
        title="Wrong charge on invoice",
        description="I was charged $265 on my June invoice but my plan is $245. There is an unexplained $20 charge I did not authorise.",
        customer_id="CUST-001",
        status=TicketStatus.resolved,
        category="billing_dispute",
        priority="high",
        assigned_to="Agent Sarah",
        created_at=datetime(2024, 6, 10, 9, 0, 0),
        updated_at=datetime(2024, 6, 12, 14, 30, 0),
    ),
    Ticket(
        title="Internet service outage not compensated",
        description="My internet was down for 18 hours on 20 April with no warning or proactive communication. I want compensation for the disruption.",
        customer_id="CUST-001",
        status=TicketStatus.closed,
        category="service_outage",
        priority="critical",
        assigned_to="Agent Mike",
        created_at=datetime(2024, 4, 22, 11, 15, 0),
        updated_at=datetime(2024, 4, 30, 16, 0, 0),
    ),
    Ticket(
        title="Refund not received after plan cancellation",
        description="I cancelled my plan on 20 June and was told I would receive a $45 refund within 10 business days. It has now been over 2 weeks and nothing has arrived.",
        customer_id="CUST-001",
        status=TicketStatus.in_progress,
        category="refund_request",
        priority="high",
        assigned_to="Agent David",
        created_at=datetime(2024, 7, 1, 10, 0, 0),
        updated_at=datetime(2024, 7, 5, 9, 45, 0),
    ),
    Ticket(
        title="Router delivery delayed by 2 weeks",
        description="I ordered a router on 24 June with an expected delivery of 1 July. It still has not arrived and tracking shows no movement.",
        customer_id="CUST-001",
        status=TicketStatus.open,
        category="delivery_issue",
        priority="medium",
        assigned_to="Agent Lisa",
        created_at=datetime(2024, 7, 8, 8, 30, 0),
        updated_at=datetime(2024, 7, 8, 8, 30, 0),
    ),

    # CUST-002 — 2 tickets
    Ticket(
        title="Customer service representative was rude",
        description="During my call on 15 May the support agent was dismissive, spoke over me and used an inappropriate tone when I asked about my bill.",
        customer_id="CUST-002",
        status=TicketStatus.resolved,
        category="rude_staff",
        priority="medium",
        assigned_to="Agent Emma",
        created_at=datetime(2024, 5, 15, 14, 0, 0),
        updated_at=datetime(2024, 5, 18, 11, 0, 0),
    ),
    Ticket(
        title="Modem arrived with cracked casing and not working",
        description="The modem I received on 3 July had a visibly cracked casing. It powers on but cannot establish an internet connection.",
        customer_id="CUST-002",
        status=TicketStatus.in_progress,
        category="product_defect",
        priority="medium",
        assigned_to="Agent James",
        created_at=datetime(2024, 7, 3, 15, 20, 0),
        updated_at=datetime(2024, 7, 6, 10, 10, 0),
    ),
]


# =============================================================================
# SEED FUNCTION
# =============================================================================

def seed() -> None:
    # Ensure tables exist before seeding
    on_startup()

    with Session(engine) as session:
        existing = session.exec(select(Ticket)).all()

        if existing:
            print(f"Tickets already exist ({len(existing)} rows) — skipping")
        else:
            for ticket in TICKETS:
                session.add(ticket)
            session.commit()
            print(f"Inserted {len(TICKETS)} tickets")

        print("\nSeed complete — tickets.db is ready")


if __name__ == "__main__":
    seed()