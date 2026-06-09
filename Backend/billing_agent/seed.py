"""
Seed the billing database with sample data for development / testing.

Run once from the project root:
    python -m billing_agent.seed

Or directly:
    python billing_agent/seed.py

Idempotent — skips inserts if data for ACC-001 already exists.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, select
from billing_agent.database import create_db_and_tables, engine
from billing_agent.models import AccountBalance, Invoice, PaymentMethod


def seed() -> None:
    create_db_and_tables()

    with Session(engine) as session:

        existing_balance = session.exec( select(AccountBalance).where(AccountBalance.account_id == "ACC-001")).first()

        if not existing_balance:
            session.add(
                AccountBalance(
                    account_id="ACC-001",
                    balance_due="$245.00",
                    due_date="2024-07-15",
                    payment_status="Pending",
                    last_payment="$245.00 on 2024-06-15",
                )
            )
            print("Inserted AccountBalance for ACC-001")
        else:
            print("AccountBalance for ACC-001 already exists — skipping")

        existing_invoices = session.exec( select(Invoice).where(Invoice.account_id == "ACC-001") ).all()

        if not existing_invoices:
            invoices = [
                Invoice(account_id="ACC-001", invoice_id="INV-001", date="2024-06-01", amount="$245.00", status="Paid"),
                Invoice(account_id="ACC-001", invoice_id="INV-002", date="2024-05-01", amount="$245.00", status="Paid"),
                Invoice(account_id="ACC-001", invoice_id="INV-003", date="2024-04-01", amount="$220.00", status="Paid"),
                Invoice(account_id="ACC-001", invoice_id="INV-004", date="2024-03-01", amount="$220.00", status="Paid"),
                Invoice(account_id="ACC-001", invoice_id="INV-005", date="2024-02-01", amount="$200.00", status="Paid"),
            ]
            for inv in invoices:
                session.add(inv)
            print(f"Inserted {len(invoices)} invoices for ACC-001")
        else:
            print("Invoices for ACC-001 already exist — skipping")

        existing_methods = session.exec( select(PaymentMethod).where(PaymentMethod.account_id == "ACC-001") ).all()

        if not existing_methods:
            methods = [
                PaymentMethod(
                    account_id="ACC-001",
                    type="Visa",
                    last4="4242",
                    expiry="12/26",
                    bank=None,
                    is_default=True,
                ),
                PaymentMethod(
                    account_id="ACC-001",
                    type="Bank Account",
                    last4="9876",
                    expiry=None,
                    bank="Chase",
                    is_default=False,
                ),
            ]
            for method in methods:
                session.add(method)
            print(f"Inserted {len(methods)} payment methods for ACC-001")
        else:
            print("PaymentMethods for ACC-001 already exist — skipping")

        session.commit()
        print("\n Seed complete — billing.db is ready")


if __name__ == "__main__":
    seed()