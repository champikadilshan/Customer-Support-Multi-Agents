from typing import Optional
from sqlmodel import Field, SQLModel


class AccountBalance(SQLModel, table=True):
    id:             Optional[int] = Field(default=None, primary_key=True)
    account_id:     str           = Field(index=True)
    balance_due:    str                                  # e.g. "$245.00"
    due_date:       str                                  # e.g. "2024-07-15"
    payment_status: str                                  # "Pending" | "Paid" | "Overdue"
    last_payment:   str                                  # e.g. "$245.00 on 2024-06-15"


class Invoice(SQLModel, table=True):
    id:         Optional[int] = Field(default=None, primary_key=True)
    account_id: str           = Field(index=True)
    invoice_id: str                                      # e.g. "INV-001"
    date:       str                                      # e.g. "2024-06-01"
    amount:     str                                      # e.g. "$245.00"
    status:     str                                      # "Paid" | "Unpaid"


class PaymentMethod(SQLModel, table=True):
    id:         Optional[int] = Field(default=None, primary_key=True)
    account_id: str           = Field(index=True)
    type:       str                                      # "Visa" | "Mastercard" | "Bank Account"
    last4:      str                                      # last 4 digits
    expiry:     Optional[str] = Field(default=None)     # cards only  e.g. "12/26"
    bank:       Optional[str] = Field(default=None)     # bank accounts only e.g. "Chase"
    is_default: bool          = Field(default=False)