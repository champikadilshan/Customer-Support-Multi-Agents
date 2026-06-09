from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


# ENUMS
class TicketStatus(str, Enum):
    open        = "open"
    in_progress = "in_progress"
    resolved    = "resolved"
    closed      = "closed"


# DB MODEL
class Ticket(SQLModel, table=True):
    id:          Optional[int]      = Field(default=None, primary_key=True)
    title:       str
    description: str
    customer_id: str                = Field(index=True)
    status:      TicketStatus       = Field(default=TicketStatus.open)

    # Fields added for complaint agent context
    category:    Optional[str]      = Field(default=None)
    priority:    Optional[str]      = Field(default=None)
    assigned_to: Optional[str]      = Field(default=None)

    created_at:  datetime           = Field(default_factory=datetime.utcnow)
    updated_at:  datetime           = Field(default_factory=datetime.utcnow)


# REQUEST / RESPONSE SCHEMAS
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
