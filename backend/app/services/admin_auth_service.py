from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    constant_time_compare,
    create_token,
    hash_password,
    verify_password,
)
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.repositories.admin_user_repository import AdminUserRepository
from app.schemas.admin import AdminTokenResponse


class AdminAuthService:
    def __init__(self, admin_repository: AdminUserRepository) -> None:
        self._admins = admin_repository

    async def authenticate(self, email: str, password: str) -> AdminUser:
        admin = await self._admins.get_by_email(email)
        if (
            admin is None
            or not admin.is_active
            or not verify_password(password, admin.hashed_password)
        ):
            raise UnauthorizedError("Invalid credentials", error_code="invalid_credentials")
        return admin

    def issue_tokens(self, admin: AdminUser) -> AdminTokenResponse:
        claims = {"role": admin.role.value, "kind": "admin"}
        return AdminTokenResponse(access_token=create_token(str(admin.id), claims))

    async def create_admin(self, *, email: str, password: str, role: AdminRole) -> AdminUser:
        admin = AdminUser(email=email, hashed_password=hash_password(password), role=role)
        self._admins.add(admin)
        await self._admins.flush()
        return admin

    async def bootstrap_first_admin(
        self, *, email: str, password: str, provided_secret: str, expected_secret: str
    ) -> AdminUser:
        """One-time bootstrap for environments without shell/CLI access to run a seed
        script: creates the very first superadmin. Gated two ways — the caller must know
        `ADMIN_SECRET`, *and* this only ever succeeds once, since it refuses if any admin
        already exists. After the first admin exists, this endpoint is permanently a no-op
        regardless of the secret, so a leaked ADMIN_SECRET alone cannot mint new admins."""
        if not constant_time_compare(provided_secret, expected_secret):
            raise UnauthorizedError(
                "Invalid bootstrap secret", error_code="invalid_bootstrap_secret"
            )
        if await self._admins.count_all() > 0:
            raise ConflictError(
                "An admin account already exists; bootstrap is a one-time operation",
                error_code="bootstrap_already_completed",
            )
        return await self.create_admin(email=email, password=password, role=AdminRole.SUPERADMIN)
