from typing import Optional
from sqlmodel import Field, SQLModel


class AccountBalance(SQLModel, table=True):
    id:             Optional[int] = Field(default=None, primary_key=True)
    account_id:     str           = Field(index=True)
    balance_due:    str
    due_date:       str
    payment_status: str
    last_payment:   str


class Invoice(SQLModel, table=True):
    id:         Optional[int] = Field(default=None, primary_key=True)
    account_id: str           = Field(index=True)
    invoice_id: str
    date:       str
    amount:     str
    status:     str


class PaymentMethod(SQLModel, table=True):
    id:         Optional[int] = Field(default=None, primary_key=True)
    account_id: str           = Field(index=True)
    type:       str
    last4:      str
    expiry:     Optional[str] = Field(default=None)
    bank:       Optional[str] = Field(default=None)
    is_default: bool          = Field(default=False)