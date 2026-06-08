from typing import Optional
from sqlmodel import Field, SQLModel


class ComplaintTicket(SQLModel, table=True):
    id:          Optional[int] = Field(default=None, primary_key=True)
    ticket_id:   str           = Field(index=True)           # e.g. "TKT-101"
    customer_id: str           = Field(index=True)           # e.g. "CUST-001"
    date:        str                                         # e.g. "2024-06-10"
    subject:     str                                         # short description
    category:    str                                         # billing_dispute | service_outage | etc.
    priority:    str                                         # low | medium | high | critical
    status:      str                                         # Open | In Progress | Resolved | Closed
    assigned_to: str                                         # e.g. "Agent Sarah"
    resolution:  Optional[str] = Field(default=None)        # filled when Resolved / Closed
    last_update: str                                         # e.g. "2024-06-12"


class TicketNote(SQLModel, table=True):
    id:        Optional[int] = Field(default=None, primary_key=True)
    ticket_id: str           = Field(index=True)            # matches ComplaintTicket.ticket_id
    date:      str                                          # e.g. "2024-06-10"
    note:      str                                          # activity description
    added_by:  str                                          # e.g. "Agent Sarah" | "System"