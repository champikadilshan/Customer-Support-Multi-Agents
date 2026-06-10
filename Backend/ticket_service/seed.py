"""
Seed the ticket service database with realistic sample data.

Run once from the project root:
    python -m ticket_service.seed

Or directly:
    python ticket_service/seed.py

WIPE_AND_RESEED = True  → deletes ALL existing rows then inserts fresh data
WIPE_AND_RESEED = False → skips insert if tickets already exist (safe default)
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select, delete
from ticket_service.main import engine, on_startup
from ticket_service.models import Ticket, TicketStatus

# ─────────────────────────────────────────────
#  CONTROL FLAG  ← change this to wipe & reseed
# ─────────────────────────────────────────────
WIPE_AND_RESEED: bool = False


# ── SEED DATA ────────────────────────────────────────────────────────────────
# Customers are linked to billing accounts:
#   CUST-001 = ACC-001 = Alice Thompson
#   CUST-002 = ACC-002 = Bob Martinez
#   CUST-003 = ACC-003 = Carol Singh
#   CUST-004 = ACC-004 = David Chen
#   CUST-005 = ACC-005 = Emma Wilson
#   CUST-006 = ACC-006 = Frank Okafor
#   CUST-007 = ACC-007 = Grace Kim
#   CUST-008 = ACC-008 = Hassan Ali
#   CUST-009 = ACC-009 = Isabella Rossi
#   CUST-010 = ACC-010 = James Patel

TICKETS = [

    # ── CUST-001 — Alice Thompson ─────────────────────────────────────────────
    Ticket(
        title="Wrong charge on June invoice",
        description="I was charged $265 on my June invoice but my plan is $245. There is an unexplained $20 charge I did not authorise.",
        customer_id="CUST-001", status=TicketStatus.resolved,
        category="billing_dispute", priority="high", assigned_to="Agent Sarah",
        created_at=datetime(2024, 6, 10, 9, 0), updated_at=datetime(2024, 6, 12, 14, 30),
    ),
    Ticket(
        title="Internet outage not compensated",
        description="My internet was down for 18 hours on 20 April with no warning or proactive communication. I want compensation for the disruption.",
        customer_id="CUST-001", status=TicketStatus.closed,
        category="service_outage", priority="critical", assigned_to="Agent Mike",
        created_at=datetime(2024, 4, 22, 11, 15), updated_at=datetime(2024, 4, 30, 16, 0),
    ),
    Ticket(
        title="Refund not received after plan cancellation",
        description="I cancelled my plan on 20 June and was told I would receive a $45 refund within 10 business days. It has been over 2 weeks and nothing has arrived.",
        customer_id="CUST-001", status=TicketStatus.in_progress,
        category="refund_request", priority="high", assigned_to="Agent David",
        created_at=datetime(2024, 7, 1, 10, 0), updated_at=datetime(2024, 7, 5, 9, 45),
    ),
    Ticket(
        title="Router delivery delayed by 2 weeks",
        description="I ordered a router on 24 June with an expected delivery of 1 July. It still has not arrived and tracking shows no movement.",
        customer_id="CUST-001", status=TicketStatus.open,
        category="delivery_issue", priority="medium", assigned_to="Agent Lisa",
        created_at=datetime(2024, 7, 8, 8, 30), updated_at=datetime(2024, 7, 8, 8, 30),
    ),

    # ── CUST-002 — Bob Martinez ───────────────────────────────────────────────
    Ticket(
        title="Customer service representative was rude",
        description="During my call on 15 May the support agent was dismissive, spoke over me and used an inappropriate tone when I asked about my bill.",
        customer_id="CUST-002", status=TicketStatus.resolved,
        category="rude_staff", priority="medium", assigned_to="Agent Emma",
        created_at=datetime(2024, 5, 15, 14, 0), updated_at=datetime(2024, 5, 18, 11, 0),
    ),
    Ticket(
        title="Modem arrived with cracked casing",
        description="The modem I received on 3 July had a visibly cracked casing. It powers on but cannot establish an internet connection.",
        customer_id="CUST-002", status=TicketStatus.in_progress,
        category="product_defect", priority="medium", assigned_to="Agent James",
        created_at=datetime(2024, 7, 3, 15, 20), updated_at=datetime(2024, 7, 6, 10, 10),
    ),
    Ticket(
        title="Double charged for June and July",
        description="My bank statement shows two identical charges of $99.99 taken on the same day. I only authorised one payment.",
        customer_id="CUST-002", status=TicketStatus.open,
        category="billing_dispute", priority="high", assigned_to=None,
        created_at=datetime(2024, 7, 10, 9, 0), updated_at=datetime(2024, 7, 10, 9, 0),
    ),

    # ── CUST-003 — Carol Singh ────────────────────────────────────────────────
    Ticket(
        title="Smart home hub not pairing with app",
        description="I purchased the Smart Home Starter kit last month. The hub refuses to pair with the mobile app despite following all setup instructions twice.",
        customer_id="CUST-003", status=TicketStatus.open,
        category="product_defect", priority="medium", assigned_to="Agent Priya",
        created_at=datetime(2024, 7, 5, 13, 0), updated_at=datetime(2024, 7, 5, 13, 0),
    ),
    Ticket(
        title="Plan upgrade not applied to bill",
        description="I upgraded to the Pro Bundle on 1 June but my July invoice still shows the old price. The discount has not been applied.",
        customer_id="CUST-003", status=TicketStatus.in_progress,
        category="billing_dispute", priority="high", assigned_to="Agent Sarah",
        created_at=datetime(2024, 7, 2, 10, 30), updated_at=datetime(2024, 7, 4, 15, 0),
    ),
    Ticket(
        title="TV streaming app keeps crashing",
        description="The TV streaming app crashes every time I try to play anything in 4K. Standard definition works fine. This started after the last app update.",
        customer_id="CUST-003", status=TicketStatus.resolved,
        category="product_defect", priority="low", assigned_to="Agent Tom",
        created_at=datetime(2024, 6, 20, 17, 0), updated_at=datetime(2024, 6, 25, 11, 0),
    ),

    # ── CUST-004 — David Chen ─────────────────────────────────────────────────
    Ticket(
        title="Two months of unpaid invoices — disputing charges",
        description="I have been disputing incorrect add-on charges since May. I refuse to pay until the $399.98 overcharge is investigated and corrected.",
        customer_id="CUST-004", status=TicketStatus.in_progress,
        category="billing_dispute", priority="high", assigned_to="Agent David",
        created_at=datetime(2024, 6, 1, 9, 0), updated_at=datetime(2024, 7, 1, 14, 0),
    ),
    Ticket(
        title="Fiber Ultra speed consistently below advertised",
        description="I am paying for 1 Gbps but speed tests consistently show only 200-300 Mbps at all hours of the day. I have rebooted the router and replaced the cables.",
        customer_id="CUST-004", status=TicketStatus.open,
        category="service_outage", priority="critical", assigned_to="Agent Mike",
        created_at=datetime(2024, 7, 7, 10, 0), updated_at=datetime(2024, 7, 7, 10, 0),
    ),
    Ticket(
        title="Requested account cancellation ignored",
        description="I submitted a cancellation request on 15 June via the portal. I have received no confirmation and I am still being billed.",
        customer_id="CUST-004", status=TicketStatus.open,
        category="other", priority="high", assigned_to=None,
        created_at=datetime(2024, 7, 9, 8, 0), updated_at=datetime(2024, 7, 9, 8, 0),
    ),

    # ── CUST-005 — Emma Wilson ────────────────────────────────────────────────
    Ticket(
        title="TV channels missing after bundle upgrade",
        description="After upgrading to the Home Bundle I expected to receive Basic TV channels but several channels listed on the plan page are not appearing in my channel guide.",
        customer_id="CUST-005", status=TicketStatus.resolved,
        category="product_defect", priority="low", assigned_to="Agent Lisa",
        created_at=datetime(2024, 6, 15, 11, 0), updated_at=datetime(2024, 6, 18, 9, 0),
    ),
    Ticket(
        title="Request for paper billing stopped but still receiving",
        description="I opted out of paper billing three months ago but continue to receive physical invoices. I am concerned about my privacy.",
        customer_id="CUST-005", status=TicketStatus.closed,
        category="other", priority="low", assigned_to="Agent Emma",
        created_at=datetime(2024, 5, 10, 14, 0), updated_at=datetime(2024, 5, 20, 10, 0),
    ),
    Ticket(
        title="Wi-Fi signal drops every evening",
        description="Between 7pm and 10pm every evening the Wi-Fi signal drops significantly or disconnects entirely. This has been happening for the last three weeks.",
        customer_id="CUST-005", status=TicketStatus.in_progress,
        category="service_outage", priority="medium", assigned_to="Agent Mike",
        created_at=datetime(2024, 7, 6, 20, 0), updated_at=datetime(2024, 7, 8, 11, 0),
    ),

    # ── CUST-006 — Frank Okafor ───────────────────────────────────────────────
    Ticket(
        title="Partial payment not reflected on account",
        description="I made a partial payment of $60 on 1 July but my online account still shows the full $120 balance as outstanding.",
        customer_id="CUST-006", status=TicketStatus.open,
        category="billing_dispute", priority="medium", assigned_to="Agent Sarah",
        created_at=datetime(2024, 7, 3, 9, 30), updated_at=datetime(2024, 7, 3, 9, 30),
    ),
    Ticket(
        title="Landline number ported incorrectly",
        description="I requested a landline number port from my previous provider. The wrong number was ported and my original number is now unreachable.",
        customer_id="CUST-006", status=TicketStatus.in_progress,
        category="other", priority="high", assigned_to="Agent James",
        created_at=datetime(2024, 6, 28, 10, 0), updated_at=datetime(2024, 7, 2, 15, 0),
    ),
    Ticket(
        title="Late fee charged despite on-time payment",
        description="A $15 late fee appeared on my July invoice even though I paid on time. My bank confirms the payment cleared on the due date.",
        customer_id="CUST-006", status=TicketStatus.resolved,
        category="billing_dispute", priority="medium", assigned_to="Agent David",
        created_at=datetime(2024, 7, 1, 8, 0), updated_at=datetime(2024, 7, 4, 12, 0),
    ),

    # ── CUST-007 — Grace Kim ──────────────────────────────────────────────────
    Ticket(
        title="Smart home sensors showing offline",
        description="Three of my five smart home motion sensors are showing as offline in the app. I have not changed any settings and the hub is powered on.",
        customer_id="CUST-007", status=TicketStatus.open,
        category="product_defect", priority="medium", assigned_to="Agent Priya",
        created_at=datetime(2024, 7, 9, 13, 0), updated_at=datetime(2024, 7, 9, 13, 0),
    ),
    Ticket(
        title="Incorrect plan shown on account portal",
        description="My account portal shows I am on Fiber Basic but I upgraded to Fiber Pro two months ago and have been paying the higher price.",
        customer_id="CUST-007", status=TicketStatus.in_progress,
        category="billing_dispute", priority="medium", assigned_to="Agent Sarah",
        created_at=datetime(2024, 6, 30, 10, 0), updated_at=datetime(2024, 7, 3, 11, 0),
    ),
    Ticket(
        title="Engineer no-show for installation appointment",
        description="An engineer was scheduled to attend on 5 July between 9am and 1pm. No one arrived and I received no communication about the cancellation.",
        customer_id="CUST-007", status=TicketStatus.resolved,
        category="other", priority="high", assigned_to="Agent Lisa",
        created_at=datetime(2024, 7, 5, 14, 0), updated_at=datetime(2024, 7, 7, 10, 0),
    ),

    # ── CUST-008 — Hassan Ali ─────────────────────────────────────────────────
    Ticket(
        title="Three months of unpaid invoices — account at risk",
        description="I have been disputing charges since April. I have not paid the last three invoices totalling $299.97 pending resolution of my dispute.",
        customer_id="CUST-008", status=TicketStatus.in_progress,
        category="billing_dispute", priority="high", assigned_to="Agent David",
        created_at=datetime(2024, 7, 1, 9, 0), updated_at=datetime(2024, 7, 8, 14, 0),
    ),
    Ticket(
        title="Service throttled without notice",
        description="My internet speed was throttled significantly last week. I was not informed and I am not near any data limit. This has impacted my ability to work from home.",
        customer_id="CUST-008", status=TicketStatus.open,
        category="service_outage", priority="critical", assigned_to=None,
        created_at=datetime(2024, 7, 8, 9, 0), updated_at=datetime(2024, 7, 8, 9, 0),
    ),
    Ticket(
        title="Expired card charged without consent",
        description="My Mastercard ending in 6011 expired in April 2024. A charge was still attempted and failed, resulting in a failed payment fee on my account.",
        customer_id="CUST-008", status=TicketStatus.resolved,
        category="billing_dispute", priority="high", assigned_to="Agent Sarah",
        created_at=datetime(2024, 5, 2, 11, 0), updated_at=datetime(2024, 5, 10, 15, 0),
    ),
    Ticket(
        title="Unlimited SIM data not actually unlimited",
        description="I am on the Unlimited SIM plan but I received a notification saying I have used 80% of my data allowance. Unlimited should mean no cap.",
        customer_id="CUST-008", status=TicketStatus.closed,
        category="product_defect", priority="medium", assigned_to="Agent Tom",
        created_at=datetime(2024, 6, 15, 16, 0), updated_at=datetime(2024, 6, 22, 10, 0),
    ),

    # ── CUST-009 — Isabella Rossi ─────────────────────────────────────────────
    Ticket(
        title="Landline line quality is very poor",
        description="Since signing up for the landline add-on last month there is constant crackling and echo on every call. The issue happens on all handsets.",
        customer_id="CUST-009", status=TicketStatus.in_progress,
        category="product_defect", priority="medium", assigned_to="Agent James",
        created_at=datetime(2024, 7, 6, 10, 0), updated_at=datetime(2024, 7, 8, 9, 0),
    ),
    Ticket(
        title="Welcome discount not applied to first invoice",
        description="I was offered a 50% discount on the first month when I signed up. My first invoice shows the full price with no discount applied.",
        customer_id="CUST-009", status=TicketStatus.resolved,
        category="billing_dispute", priority="medium", assigned_to="Agent Sarah",
        created_at=datetime(2024, 6, 5, 9, 0), updated_at=datetime(2024, 6, 9, 11, 0),
    ),
    Ticket(
        title="SIM card not delivered after 2 weeks",
        description="I signed up for the Starter SIM plan on 24 June. The SIM was supposed to arrive within 2-3 days. It is now 8 July and nothing has arrived.",
        customer_id="CUST-009", status=TicketStatus.open,
        category="delivery_issue", priority="medium", assigned_to="Agent Lisa",
        created_at=datetime(2024, 7, 8, 12, 0), updated_at=datetime(2024, 7, 8, 12, 0),
    ),

    # ── CUST-010 — James Patel ────────────────────────────────────────────────
    Ticket(
        title="Pro Bundle promotional discount ended early",
        description="I signed up under the Summer Upgrade Deal which promised 50% off for 3 months. The discount was only applied for 2 months. I want the third month credited.",
        customer_id="CUST-010", status=TicketStatus.in_progress,
        category="billing_dispute", priority="medium", assigned_to="Agent David",
        created_at=datetime(2024, 7, 2, 10, 0), updated_at=datetime(2024, 7, 5, 14, 0),
    ),
    Ticket(
        title="Entertainment TV missing sports channels",
        description="The Entertainment TV plan advertises sports channels but several key sports channels listed on the website are not available in my package.",
        customer_id="CUST-010", status=TicketStatus.resolved,
        category="product_defect", priority="low", assigned_to="Agent Tom",
        created_at=datetime(2024, 6, 18, 15, 0), updated_at=datetime(2024, 6, 22, 10, 0),
    ),
    Ticket(
        title="Standard SIM calls dropping in home area",
        description="I have been experiencing dropped calls at home for the past month. I live in an area that is listed as full coverage on the coverage map.",
        customer_id="CUST-010", status=TicketStatus.closed,
        category="service_outage", priority="medium", assigned_to="Agent Mike",
        created_at=datetime(2024, 6, 10, 11, 0), updated_at=datetime(2024, 6, 20, 16, 0),
    ),
    Ticket(
        title="Requested callback never received",
        description="I requested a callback through the support portal on 5 July at a time I specified. Nobody called and no explanation was given.",
        customer_id="CUST-010", status=TicketStatus.open,
        category="other", priority="low", assigned_to=None,
        created_at=datetime(2024, 7, 7, 9, 0), updated_at=datetime(2024, 7, 7, 9, 0),
    ),
]


# ── SEED FUNCTION ─────────────────────────────────────────────────────────────

def seed() -> None:
    on_startup()

    with Session(engine) as session:

        if WIPE_AND_RESEED:
            print("WIPE_AND_RESEED=True — deleting all existing tickets...")
            session.exec(delete(Ticket))
            session.commit()
            print("  All tickets deleted.\n")

        existing = session.exec(select(Ticket)).all()

        if existing and not WIPE_AND_RESEED:
            print(f"Tickets already exist ({len(existing)} rows) — skipping")
            print("Set WIPE_AND_RESEED = True to replace all data.")
            total_inserted = 0
        else:
            for ticket in TICKETS:
                session.add(ticket)
            session.commit()
            total_inserted = len(TICKETS)
            print(f"Inserted {total_inserted} tickets across 10 customers")

        # Collect summary inside the session while instances are still attached
        all_tickets   = session.exec(select(Ticket)).all()
        unique_custs  = sorted(set(t.customer_id for t in all_tickets))
        total_in_db   = len(all_tickets)

    print("\nSeed complete — tickets.db is ready")
    print(f"  Customers : {', '.join(unique_custs)}")
    print(f"  Tickets   : {total_in_db}")


if __name__ == "__main__":
    seed()