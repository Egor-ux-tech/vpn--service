"""CLI to create an admin account — the preferred path when shell/container access is
available (e.g. `make create-admin`), since it needs no HTTP-exposed bootstrap secret at
all. See app/api/v1/auth.py::bootstrap_first_admin for the HTTP alternative used when only
API access is available.

Usage: python -m app.scripts.create_admin --email you@example.com --role superadmin
(prompts for a password; use --password only for non-interactive/CI use, e.g. seeding a
throwaway staging environment — never pass a real password on a shared command line).
"""

import argparse
import asyncio
import getpass

from app.core.logging import configure_logging, get_logger
from app.db.session import AsyncSessionLocal
from app.models.enums import AdminRole
from app.repositories.admin_user_repository import AdminUserRepository
from app.services.admin_auth_service import AdminAuthService

logger = get_logger(__name__)


async def run(email: str, password: str, role: AdminRole) -> None:
    async with AsyncSessionLocal() as session:
        service = AdminAuthService(AdminUserRepository(session))
        admin = await service.create_admin(email=email, password=password, role=role)
        await session.commit()
    logger.info("admin_created", email=email, role=role.value, admin_id=admin.id)
    print(f"Created admin {email} ({role.value})")  # noqa: T201 -- CLI output, not app logging


def main() -> None:
    configure_logging("INFO")
    parser = argparse.ArgumentParser(description="Create an admin panel account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="Omit to be prompted (recommended)")
    parser.add_argument(
        "--role", choices=[r.value for r in AdminRole], default=AdminRole.SUPERADMIN.value
    )
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters")

    asyncio.run(run(args.email, password, AdminRole(args.role)))


if __name__ == "__main__":
    main()
