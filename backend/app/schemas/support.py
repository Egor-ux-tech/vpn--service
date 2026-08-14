from datetime import datetime

from pydantic import BaseModel

from app.models.enums import SupportSender, SupportTicketStatus
from app.schemas.common import ORMModel


class SupportTicketCreate(BaseModel):
    subject: str
    message: str


class SupportMessageCreate(BaseModel):
    text: str


class SupportMessageRead(ORMModel):
    id: int
    sender: SupportSender
    text: str
    created_at: datetime


class SupportTicketRead(ORMModel):
    id: int
    subject: str
    status: SupportTicketStatus
    created_at: datetime
    messages: list[SupportMessageRead] = []
