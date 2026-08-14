from datetime import UTC, datetime

from app.core.errors import NotFoundError
from app.models.enums import SupportSender, SupportTicketStatus
from app.models.support import SupportMessage, SupportTicket
from app.repositories.support_repository import SupportMessageRepository, SupportTicketRepository


class SupportService:
    def __init__(
        self,
        ticket_repository: SupportTicketRepository,
        message_repository: SupportMessageRepository,
    ) -> None:
        self._tickets = ticket_repository
        self._messages = message_repository

    async def create_ticket(self, *, user_id: int, subject: str, message: str) -> SupportTicket:
        ticket = SupportTicket(user_id=user_id, subject=subject, status=SupportTicketStatus.OPEN)
        ticket.messages.append(
            SupportMessage(sender=SupportSender.USER, text=message, created_at=datetime.now(UTC))
        )
        self._tickets.add(ticket)
        await self._tickets.flush()
        return ticket

    async def list_for_user(self, user_id: int) -> list[SupportTicket]:
        return await self._tickets.list_for_user(user_id)

    async def list_all(self, *, offset: int = 0, limit: int = 50) -> list[SupportTicket]:
        return await self._tickets.list_all(offset=offset, limit=limit)

    async def get(self, ticket_id: int) -> SupportTicket:
        ticket = await self._tickets.get_with_messages(ticket_id)
        if ticket is None:
            raise NotFoundError("Support ticket not found", error_code="ticket_not_found")
        return ticket

    async def add_message(
        self, ticket: SupportTicket, *, sender: SupportSender, text: str
    ) -> SupportMessage:
        message = SupportMessage(
            ticket_id=ticket.id, sender=sender, text=text, created_at=datetime.now(UTC)
        )
        if sender is SupportSender.ADMIN and ticket.status is SupportTicketStatus.OPEN:
            ticket.status = SupportTicketStatus.PENDING
        self._messages.add(message)
        await self._messages.flush()
        return message

    async def close(self, ticket: SupportTicket) -> SupportTicket:
        ticket.status = SupportTicketStatus.CLOSED
        return ticket
