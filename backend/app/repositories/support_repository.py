from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.support import SupportMessage, SupportTicket
from app.repositories.base import BaseRepository


class SupportMessageRepository(BaseRepository[SupportMessage]):
    model = SupportMessage


class SupportTicketRepository(BaseRepository[SupportTicket]):
    model = SupportTicket

    async def list_for_user(self, user_id: int) -> list[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, offset: int = 0, limit: int = 50) -> list[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .order_by(SupportTicket.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_messages(self, ticket_id: int) -> SupportTicket | None:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.id == ticket_id)
            .options(selectinload(SupportTicket.messages))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
