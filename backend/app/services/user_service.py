from app.core.errors import NotFoundError, PermissionDeniedError
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import TelegramAuthRequest


class UserService:
    def __init__(self, user_repository: UserRepository) -> None:
        self._users = user_repository

    async def get_or_create_from_telegram(self, payload: TelegramAuthRequest) -> User:
        user = await self._users.get_by_telegram_id(payload.telegram_id)
        if user is not None:
            user.username = payload.username
            user.first_name = payload.first_name
            user.last_name = payload.last_name
            user.language_code = payload.language_code
            return user

        user = User(
            telegram_id=payload.telegram_id,
            username=payload.username,
            first_name=payload.first_name,
            last_name=payload.last_name,
            language_code=payload.language_code,
            status=UserStatus.ACTIVE,
        )
        self._users.add(user)
        await self._users.flush()
        return user

    async def require_active_user(self, telegram_id: int) -> User:
        user = await self._users.get_by_telegram_id(telegram_id)
        if user is None:
            raise NotFoundError("User not found", error_code="user_not_found")
        if user.status is not UserStatus.ACTIVE:
            raise PermissionDeniedError("User is blocked", error_code="user_blocked")
        return user

    async def set_status(self, user: User, status: UserStatus) -> User:
        user.status = status
        return user
