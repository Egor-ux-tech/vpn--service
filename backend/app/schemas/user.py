from datetime import datetime

from pydantic import BaseModel

from app.models.enums import UserStatus
from app.schemas.common import ORMModel


class TelegramAuthRequest(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None


class UserRead(ORMModel):
    id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    status: UserStatus
    created_at: datetime


class UserUpdateStatus(BaseModel):
    status: UserStatus
