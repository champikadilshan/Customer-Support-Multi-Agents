"""
Seed the billing database with sample data for development / testing.

Run once from the project root:
    python -m billing_agent.seed

Or directly:
    python billing_agent/seed.py

WIPE_AND_RESEED = True  → deletes ALL existing rows then inserts fresh data
WIPE_AND_RESEED = False → skips insert if data already exists (safe default)
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, select, delete
from billing_agent.database import create_db_and_tables, engine
from billing_agent.models import AccountBalance, Invoice, PaymentMethod

# ─────────────────────────────────────────────
#  CONTROL FLAG  ← change this to wipe & reseed
# ─────────────────────────────────────────────
WIPE_AND_RESEED: bool = False


# ── SEED DATA ────────────────────────────────────────────────────────────────

ACCOUNT_BALANCES = [
    # ACC-001 — Alice Thompson
    dict(account_id="ACC-001", balance_due="$245.00",  due_date="2024-07-15", payment_status="Pending",  last_payment="$245.00 on 2024-06-15"),
    # ACC-002 — Bob Martinez
    dict(account_id="ACC-002", balance_due="$99.99",   due_date="2024-07-10", payment_status="Overdue",  last_payment="$99.99 on 2024-05-10"),
    # ACC-003 — Carol Singh
    dict(account_id="ACC-003", balance_due="$0.00",    due_date="2024-08-01", payment_status="Paid",     last_payment="$179.99 on 2024-07-01"),
    # ACC-004 — David Chen
    dict(account_id="ACC-004", balance_due="$399.98",  due_date="2024-07-20", payment_status="Overdue",  last_payment="$399.98 on 2024-05-20"),
    # ACC-005 — Emma Wilson
    dict(account_id="ACC-005", balance_due="$54.99",   due_date="2024-07-25", payment_status="Pending",  last_payment="$54.99 on 2024-06-25"),
    # ACC-006 — Frank Okafor
    dict(account_id="ACC-006", balance_due="$120.00",  due_date="2024-07-18", payment_status="Partial",  last_payment="$60.00 on 2024-07-01"),
    # ACC-007 — Grace Kim
    dict(account_id="ACC-007", balance_due="$0.00",    due_date="2024-08-05", payment_status="Paid",     last_payment="$89.99 on 2024-07-05"),
    # ACC-008 — Hassan Ali
    dict(account_id="ACC-008", balance_due="$299.97",  due_date="2024-07-12", payment_status="Overdue",  last_payment="$299.97 on 2024-05-12"),
    # ACC-009 — Isabella Rossi
    dict(account_id="ACC-009", balance_due="$45.00",   due_date="2024-07-30", payment_status="Pending",  last_payment="$45.00 on 2024-06-30"),
    # ACC-010 — James Patel
    dict(account_id="ACC-010", balance_due="$0.00",    due_date="2024-08-10", payment_status="Paid",     last_payment="$134.98 on 2024-07-10"),
]

INVOICES = [
    # ACC-001 — Alice Thompson (Fiber Pro plan ~$59.99 + TV ~$45 = ~$104 but on bundle $99.99)
    dict(account_id="ACC-001", invoice_id="INV-001-06", date="2024-06-01", amount="$245.00", status="Paid"),
    dict(account_id="ACC-001", invoice_id="INV-001-05", date="2024-05-01", amount="$245.00", status="Paid"),
    dict(account_id="ACC-001", invoice_id="INV-001-04", date="2024-04-01", amount="$220.00", status="Paid"),
    dict(account_id="ACC-001", invoice_id="INV-001-03", date="2024-03-01", amount="$220.00", status="Paid"),
    dict(account_id="ACC-001", invoice_id="INV-001-02", date="2024-02-01", amount="$200.00", status="Paid"),
    dict(account_id="ACC-001", invoice_id="INV-001-01", date="2024-01-01", amount="$200.00", status="Paid"),

    # ACC-002 — Bob Martinez (Starter SIM $15 + Basic TV $25 + Fiber Basic $39.99 = ~$79.99)
    dict(account_id="ACC-002", invoice_id="INV-002-06", date="2024-06-01", amount="$99.99",  status="Unpaid"),
    dict(account_id="ACC-002", invoice_id="INV-002-05", date="2024-05-01", amount="$99.99",  status="Unpaid"),
    dict(account_id="ACC-002", invoice_id="INV-002-04", date="2024-04-01", amount="$79.99",  status="Paid"),
    dict(account_id="ACC-002", invoice_id="INV-002-03", date="2024-03-01", amount="$79.99",  status="Paid"),
    dict(account_id="ACC-002", invoice_id="INV-002-02", date="2024-02-01", amount="$79.99",  status="Paid"),
    dict(account_id="ACC-002", invoice_id="INV-002-01", date="2024-01-01", amount="$79.99",  status="Paid"),

    # ACC-003 — Carol Singh (Pro Bundle $99.99 + Smart Home $40 = $139.99 → rounded to $179.99 after add-ons)
    dict(account_id="ACC-003", invoice_id="INV-003-06", date="2024-06-01", amount="$179.99", status="Paid"),
    dict(account_id="ACC-003", invoice_id="INV-003-05", date="2024-05-01", amount="$179.99", status="Paid"),
    dict(account_id="ACC-003", invoice_id="INV-003-04", date="2024-04-01", amount="$159.99", status="Paid"),
    dict(account_id="ACC-003", invoice_id="INV-003-03", date="2024-03-01", amount="$159.99", status="Paid"),
    dict(account_id="ACC-003", invoice_id="INV-003-02", date="2024-02-01", amount="$139.99", status="Paid"),
    dict(account_id="ACC-003", invoice_id="INV-003-01", date="2024-01-01", amount="$139.99", status="Paid"),

    # ACC-004 — David Chen (Fiber Ultra $89.99 + Premium TV $65 + Unlimited SIM $45 = $199.99 x2 months overdue)
    dict(account_id="ACC-004", invoice_id="INV-004-06", date="2024-06-01", amount="$199.99", status="Unpaid"),
    dict(account_id="ACC-004", invoice_id="INV-004-05", date="2024-05-01", amount="$199.99", status="Unpaid"),
    dict(account_id="ACC-004", invoice_id="INV-004-04", date="2024-04-01", amount="$199.99", status="Paid"),
    dict(account_id="ACC-004", invoice_id="INV-004-03", date="2024-03-01", amount="$189.99", status="Paid"),
    dict(account_id="ACC-004", invoice_id="INV-004-02", date="2024-02-01", amount="$189.99", status="Paid"),
    dict(account_id="ACC-004", invoice_id="INV-004-01", date="2024-01-01", amount="$179.99", status="Paid"),

    # ACC-005 — Emma Wilson (Home Bundle $54.99)
    dict(account_id="ACC-005", invoice_id="INV-005-06", date="2024-06-01", amount="$54.99",  status="Paid"),
    dict(account_id="ACC-005", invoice_id="INV-005-05", date="2024-05-01", amount="$54.99",  status="Paid"),
    dict(account_id="ACC-005", invoice_id="INV-005-04", date="2024-04-01", amount="$54.99",  status="Paid"),
    dict(account_id="ACC-005", invoice_id="INV-005-03", date="2024-03-01", amount="$54.99",  status="Paid"),
    dict(account_id="ACC-005", invoice_id="INV-005-02", date="2024-02-01", amount="$44.99",  status="Paid"),
    dict(account_id="ACC-005", invoice_id="INV-005-01", date="2024-01-01", amount="$44.99",  status="Paid"),

    # ACC-006 — Frank Okafor (Standard SIM $29 + Landline $25 + Fiber Basic $39.99 = ~$93.99 → rounded $120)
    dict(account_id="ACC-006", invoice_id="INV-006-06", date="2024-06-01", amount="$120.00", status="Partial"),
    dict(account_id="ACC-006", invoice_id="INV-006-05", date="2024-05-01", amount="$120.00", status="Paid"),
    dict(account_id="ACC-006", invoice_id="INV-006-04", date="2024-04-01", amount="$110.00", status="Paid"),
    dict(account_id="ACC-006", invoice_id="INV-006-03", date="2024-03-01", amount="$110.00", status="Paid"),
    dict(account_id="ACC-006", invoice_id="INV-006-02", date="2024-02-01", amount="$95.00",  status="Paid"),
    dict(account_id="ACC-006", invoice_id="INV-006-01", date="2024-01-01", amount="$95.00",  status="Paid"),

    # ACC-007 — Grace Kim (Fiber Basic $39.99 + Basic TV $25 = $64.99 → $89.99 after smart home addon)
    dict(account_id="ACC-007", invoice_id="INV-007-06", date="2024-06-01", amount="$89.99",  status="Paid"),
    dict(account_id="ACC-007", invoice_id="INV-007-05", date="2024-05-01", amount="$89.99",  status="Paid"),
    dict(account_id="ACC-007", invoice_id="INV-007-04", date="2024-04-01", amount="$74.99",  status="Paid"),
    dict(account_id="ACC-007", invoice_id="INV-007-03", date="2024-03-01", amount="$74.99",  status="Paid"),
    dict(account_id="ACC-007", invoice_id="INV-007-02", date="2024-02-01", amount="$64.99",  status="Paid"),
    dict(account_id="ACC-007", invoice_id="INV-007-01", date="2024-01-01", amount="$64.99",  status="Paid"),

    # ACC-008 — Hassan Ali (Fiber Ultra $89.99 + Unlimited SIM $45 + Premium TV $65 = ~$199.99 x3 months overdue)
    dict(account_id="ACC-008", invoice_id="INV-008-06", date="2024-06-01", amount="$299.97", status="Unpaid"),
    dict(account_id="ACC-008", invoice_id="INV-008-05", date="2024-05-01", amount="$299.97", status="Unpaid"),
    dict(account_id="ACC-008", invoice_id="INV-008-04", date="2024-04-01", amount="$299.97", status="Unpaid"),
    dict(account_id="ACC-008", invoice_id="INV-008-03", date="2024-03-01", amount="$249.97", status="Paid"),
    dict(account_id="ACC-008", invoice_id="INV-008-02", date="2024-02-01", amount="$249.97", status="Paid"),
    dict(account_id="ACC-008", invoice_id="INV-008-01", date="2024-01-01", amount="$199.97", status="Paid"),

    # ACC-009 — Isabella Rossi (Starter SIM $15 + Basic TV $25 = $40 → $45 with landline add-on)
    dict(account_id="ACC-009", invoice_id="INV-009-06", date="2024-06-01", amount="$45.00",  status="Paid"),
    dict(account_id="ACC-009", invoice_id="INV-009-05", date="2024-05-01", amount="$45.00",  status="Paid"),
    dict(account_id="ACC-009", invoice_id="INV-009-04", date="2024-04-01", amount="$40.00",  status="Paid"),
    dict(account_id="ACC-009", invoice_id="INV-009-03", date="2024-03-01", amount="$40.00",  status="Paid"),
    dict(account_id="ACC-009", invoice_id="INV-009-02", date="2024-02-01", amount="$40.00",  status="Paid"),
    dict(account_id="ACC-009", invoice_id="INV-009-01", date="2024-01-01", amount="$29.99",  status="Paid"),

    # ACC-010 — James Patel (Fiber Pro $59.99 + Standard SIM $29 + Entertainment TV $45 = ~$134.98 on bundle)
    dict(account_id="ACC-010", invoice_id="INV-010-06", date="2024-06-01", amount="$134.98", status="Paid"),
    dict(account_id="ACC-010", invoice_id="INV-010-05", date="2024-05-01", amount="$134.98", status="Paid"),
    dict(account_id="ACC-010", invoice_id="INV-010-04", date="2024-04-01", amount="$124.98", status="Paid"),
    dict(account_id="ACC-010", invoice_id="INV-010-03", date="2024-03-01", amount="$124.98", status="Paid"),
    dict(account_id="ACC-010", invoice_id="INV-010-02", date="2024-02-01", amount="$99.99",  status="Paid"),
    dict(account_id="ACC-010", invoice_id="INV-010-01", date="2024-01-01", amount="$99.99",  status="Paid"),
]

PAYMENT_METHODS = [
    # ACC-001 — Alice Thompson
    dict(account_id="ACC-001", type="Visa",         last4="4242", expiry="12/26", bank=None,      is_default=True),
    dict(account_id="ACC-001", type="Bank Account", last4="9876", expiry=None,    bank="Chase",   is_default=False),

    # ACC-002 — Bob Martinez
    dict(account_id="ACC-002", type="Mastercard",   last4="5555", expiry="09/25", bank=None,      is_default=True),

    # ACC-003 — Carol Singh
    dict(account_id="ACC-003", type="Amex",         last4="3714", expiry="03/27", bank=None,      is_default=True),
    dict(account_id="ACC-003", type="Bank Account", last4="1122", expiry=None,    bank="Wells Fargo", is_default=False),

    # ACC-004 — David Chen
    dict(account_id="ACC-004", type="Visa",         last4="1234", expiry="06/26", bank=None,      is_default=True),
    dict(account_id="ACC-004", type="Mastercard",   last4="8765", expiry="11/25", bank=None,      is_default=False),

    # ACC-005 — Emma Wilson
    dict(account_id="ACC-005", type="PayPal",       last4="7890", expiry=None,    bank=None,      is_default=True),

    # ACC-006 — Frank Okafor
    dict(account_id="ACC-006", type="Bank Account", last4="3344", expiry=None,    bank="Bank of America", is_default=True),

    # ACC-007 — Grace Kim
    dict(account_id="ACC-007", type="Visa",         last4="9999", expiry="08/26", bank=None,      is_default=True),
    dict(account_id="ACC-007", type="PayPal",       last4="4321", expiry=None,    bank=None,      is_default=False),

    # ACC-008 — Hassan Ali
    dict(account_id="ACC-008", type="Mastercard",   last4="6011", expiry="04/24", bank=None,      is_default=True),  # expired card — overdue makes sense

    # ACC-009 — Isabella Rossi
    dict(account_id="ACC-009", type="Amex",         last4="0005", expiry="01/28", bank=None,      is_default=True),

    # ACC-010 — James Patel
    dict(account_id="ACC-010", type="Bank Account", last4="5566", expiry=None,    bank="Citibank", is_default=True),
    dict(account_id="ACC-010", type="Visa",         last4="7777", expiry="07/27", bank=None,       is_default=False),
]


# ── SEED FUNCTION ─────────────────────────────────────────────────────────────

def seed() -> None:
    create_db_and_tables()

    with Session(engine) as session:

        if WIPE_AND_RESEED:
            print("WIPE_AND_RESEED=True — deleting all existing billing data...")
            session.exec(delete(PaymentMethod))
            session.exec(delete(Invoice))
            session.exec(delete(AccountBalance))
            session.commit()
            print("  All billing tables cleared.\n")

        # ── Account Balances ──────────────────────────────────────────────────
        inserted_balances = 0
        for data in ACCOUNT_BALANCES:
            existing = session.exec(
                select(AccountBalance).where(AccountBalance.account_id == data["account_id"])
            ).first()

            if existing and not WIPE_AND_RESEED:
                print(f"  AccountBalance for {data['account_id']} already exists — skipping")
                continue

            session.add(AccountBalance(**data))
            inserted_balances += 1

        session.commit()
        print(f"Inserted {inserted_balances} AccountBalance rows")

        # ── Invoices ──────────────────────────────────────────────────────────
        inserted_invoices = 0
        for data in INVOICES:
            existing = session.exec(
                select(Invoice).where(Invoice.invoice_id == data["invoice_id"])
            ).first()

            if existing and not WIPE_AND_RESEED:
                continue

            session.add(Invoice(**data))
            inserted_invoices += 1

        session.commit()
        print(f"Inserted {inserted_invoices} Invoice rows")

        # ── Payment Methods ───────────────────────────────────────────────────
        inserted_methods = 0
        for data in PAYMENT_METHODS:
            existing = session.exec(
                select(PaymentMethod).where(
                    PaymentMethod.account_id == data["account_id"],
                    PaymentMethod.last4 == data["last4"],
                )
            ).first()

            if existing and not WIPE_AND_RESEED:
                continue

            session.add(PaymentMethod(**data))
            inserted_methods += 1

        session.commit()
        print(f"Inserted {inserted_methods} PaymentMethod rows")

    print("\nSeed complete — billing.db is ready")
    print(f"  Accounts : {len(ACCOUNT_BALANCES)}")
    print(f"  Invoices : {len(INVOICES)}")
    print(f"  Pay methods: {len(PAYMENT_METHODS)}")


if __name__ == "__main__":
    seed()